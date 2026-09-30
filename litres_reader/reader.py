"""Экран чтения: книга рендерится foliate-js во встроенном Chromium."""
from __future__ import annotations

import json
import mimetypes
import os
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QFile, QIODevice, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestJob,
                                     QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QSlider, QVBoxLayout, QWidget)

from . import style
from .core import BOOKS_DIR, DEBUG, SCHEME, WEB_DIR, log
from .litres import PREFIX
from .widgets import HeaderBar, IconButton, Popover, SeekSlider, Switch, attach_popover, cls, label


def register_scheme():
    """Схема litreader:// для страницы читалки и файлов книг (до создания QApplication).

    Заодно отключаем масштабирование страницы щипком в Chromium — щипок в читалке
    меняет размер шрифта.
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-pinch" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-pinch").strip()
    s = QWebEngineUrlScheme(SCHEME.encode())
    s.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    s.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
               | QWebEngineUrlScheme.Flag.LocalAccessAllowed
               | QWebEngineUrlScheme.Flag.CorsEnabled
               | QWebEngineUrlScheme.Flag.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(s)


class SchemeHandler(QWebEngineUrlSchemeHandler):
    """litreader://app/… — файлы читалки, litreader://app/book/… — сами книги."""

    def requestStarted(self, job: QWebEngineUrlRequestJob):
        path = job.requestUrl().path().lstrip("/")
        base, rel = (BOOKS_DIR, path[5:]) if path.startswith("book/") else (WEB_DIR, path)
        target = (base / rel).resolve()
        if not target.is_file() or base.resolve() not in target.parents:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = "text/javascript" if target.suffix in (".js", ".mjs") else \
            (mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        f = QFile(str(target), job)   # файл живёт, пока жив запрос
        if not f.open(QIODevice.OpenModeFlag.ReadOnly):
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        job.reply(QByteArray(mime.encode()), f)


_profile = None


def reader_profile():
    """Отдельный профиль без сохранения данных, с обработчиком схемы litreader://."""
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile()
        _profile._handler = SchemeHandler(_profile)
        _profile.installUrlSchemeHandler(SCHEME.encode(), _profile._handler)
    return _profile


class _ReaderWebPage(QWebEnginePage):
    def __init__(self, profile, on_message, parent):
        super().__init__(profile, parent)
        self._on_message = on_message

    def javaScriptConsoleMessage(self, level, text, line, source):
        if text.startswith(PREFIX):
            try:
                self._on_message(json.loads(text[len(PREFIX):]))
            except ValueError:
                pass
        elif DEBUG:
            log("reader console:", text)

    def acceptNavigationRequest(self, url, nav_type, is_main):
        if url.scheme() in (SCHEME, "blob", "data", "about"):
            return True
        QDesktopServices.openUrl(url)   # внешние ссылки — в браузере
        return False


class ReaderPage(QWidget):
    def __init__(self, app, book, path: Path):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        self.book = book
        self.path = path
        self.toc: list[dict] = []
        self.ui_visible = True
        self._remote_checked = False

        self.web = QWebEngineView(self)
        self.page = _ReaderWebPage(reader_profile(), self._on_message, self)
        self.web.setPage(self.page)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu if DEBUG
                                      else Qt.ContextMenuPolicy.NoContextMenu)

        # Верхняя панель — заголовок окна
        self.header = HeaderBar(app.window, book.get("title") or "")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)
        full = IconButton("view-fullscreen", "Во весь экран (F11)")
        full.clicked.connect(app.toggle_fullscreen)
        self.header.pack_end(full)
        settings_btn = IconButton("font-select", "Вид текста")
        attach_popover(settings_btn, Popover(self._build_settings()))
        self.header.pack_end(settings_btn)
        self.toc_btn = IconButton("view-list", "Оглавление")
        self.toc_list = QListWidget()
        self.toc_list.setMinimumWidth(320)
        self.toc_list.setMinimumHeight(360)
        self.toc_list.itemActivated.connect(self._on_toc)
        self.toc_list.itemClicked.connect(self._on_toc)
        self.toc_popover = Popover(self.toc_list)
        attach_popover(self.toc_btn, self.toc_popover)
        self.header.pack_end(self.toc_btn)
        self.flip_btn = IconButton("media-playlist-repeat", "Автолистание")
        self.flip_btn.setCheckable(True)
        self.flip_btn.toggled.connect(self._toggle_autoflip)
        self.header.pack_end(self.flip_btn)
        self.tts_btn = IconButton("audio-volume-high", "Читать вслух")
        self.tts_btn.setCheckable(True)
        self.tts_btn.toggled.connect(self._toggle_tts)
        self.header.pack_end(self.tts_btn)

        # Чтение вслух: очередь предложений текущего абзаца
        self._tts = None
        self.tts_active = False
        self._tts_queue: list[dict] = []
        # Автолистание: таймер; ручное листание его сбрасывает
        self._flip_timer = QTimer(self)
        self._flip_timer.timeout.connect(self._autoflip_turn)
        self._auto_turn = False

        # Нижняя панель: ползунок по книге и процент
        self.bottom = QFrame()
        self.bottom.setObjectName("headerbar")
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(12)
        self.slider = SeekSlider()
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(lambda v: self.percent.setText(f"{round(v / 10)}%"))
        self.slider.sliderReleased.connect(self._on_seek)
        self.percent = label("0%")
        self.percent.setMinimumWidth(44)
        bl.addWidget(self.slider, 1)
        bl.addWidget(self.percent)

        # Обычная раскладка без наложения: поверх встроенного Chromium панели
        # при фокусе на странице могут оказаться под ней и «исчезнуть»
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.web, 1)
        lay.addWidget(self.bottom)

        self.page.load(QUrl(f"{SCHEME}://app/reader.html"))

    # --- панели видны всегда; касание середины страницы прячет их для чтения без отвлечений

    def set_ui_visible(self, visible):
        self.ui_visible = visible
        self.header.setVisible(visible)
        self.bottom.setVisible(visible)
        # Строка «глава · %» внутри страницы нужна, только когда панели спрятаны
        self.js(f"document.getElementById('footer').style.display = '{'none' if visible else ''}'")

    # --- настройки вида

    def _build_settings(self):
        st = self.app.settings
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        row = 0

        def add(text, widget):
            nonlocal row
            grid.addWidget(label(text), row, 0)
            grid.addWidget(widget, row, 1, Qt.AlignmentFlag.AlignRight)
            row += 1

        size_box = QWidget()
        sl = QHBoxLayout(size_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        minus = IconButton("zoom-out", "Меньше", flat=False)
        plus = IconButton("zoom-in", "Больше", flat=False)
        cls(minus, "linked-first")
        cls(plus, "linked-last")
        size_label = QLabel(str(st["fontSize"]))
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_label.setMinimumWidth(40)
        cls(size_label, "heading")

        def change_size(delta):
            st["fontSize"] = max(12, min(40, st["fontSize"] + delta))
            size_label.setText(str(st["fontSize"]))
            self.app.save_settings()
        minus.clicked.connect(lambda: change_size(-1))
        plus.clicked.connect(lambda: change_size(+1))
        sl.addWidget(minus)
        sl.addWidget(size_label)
        sl.addWidget(plus)
        add("Размер шрифта", size_box)

        grid.addWidget(label("Тема"), row, 0, 1, 2)
        row += 1
        themes = QWidget()
        tl = QHBoxLayout(themes)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        group = QButtonGroup(themes)
        options = (("auto", "Авто"), ("light", "Светлая"), ("sepia", "Сепия"),
                   ("dark", "Тёмная"), ("black", "Чёрная"))
        from PySide6.QtWidgets import QPushButton
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(st["theme"] == key)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            cls(b, "linked-first" if i == 0 else "linked-last" if i == len(options) - 1 else "linked")
            b.toggled.connect(lambda on, k=key: on and self._set("theme", k))
            group.addButton(b)
            tl.addWidget(b)
        grid.addWidget(themes, row, 0, 1, 2)
        row += 1

        fonts = QComboBox()
        font_keys = ["book", "serif", "sans"]
        fonts.addItems(["Как в книге", "С засечками", "Без засечек"])
        fonts.setCurrentIndex(font_keys.index(st["font"]) if st["font"] in font_keys else 0)
        fonts.currentIndexChanged.connect(lambda i: self._set("font", font_keys[i]))
        add("Шрифт", fonts)

        def slider(text, key, lo, hi, scale=1):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(int(lo * scale), int(hi * scale))
            s.setValue(int(round(st[key] * scale)))
            s.setMinimumWidth(180)
            s.valueChanged.connect(lambda v: self._set(key, round(v / scale, 2)))
            add(text, s)

        slider("Межстрочный интервал", "lineHeight", 1.1, 2.2, 10)
        slider("Поля, %", "margin", 0, 20)
        slider("Ширина строки", "lineWidth", 400, 1400)
        slider("Скорость чтения вслух", "ttsRate", -0.5, 0.8, 10)
        slider("Автолистание, секунд", "autoFlipSec", 5, 120)

        for key, text in (("twoColumns", "Две страницы в горизонтальном положении"),
                          ("justify", "Выравнивать по ширине"),
                          ("hyphenate", "Переносы слов")):
            sw = Switch(st[key])
            sw.toggled.connect(lambda on, k=key: self._set(k, on))
            add(text, sw)
        return box

    def _set(self, key, value):
        self.app.settings[key] = value
        self.app.save_settings()

    def resolved_settings(self):
        s = dict(self.app.settings)
        if s["theme"] == "auto":
            s["theme"] = "dark" if style.is_dark() else "light"
        return s

    def apply_settings(self):
        self.js(f"window.reader?.applySettings({json.dumps(self.resolved_settings())})")

    def refresh_style(self):
        self.header.refresh_icons()
        self.apply_settings()

    # --- связь с JS

    def js(self, code):
        self.page.runJavaScript(code)

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "ready":
            ext = self.path.name.split(".", 1)[1] if "." in self.path.name else ""
            params = {
                "url": f"{SCHEME}://app/book/{self.path.name}",
                "name": f"book.{ext}",
                "cfi": self.app.library.progress.get(self.book["id"], {}).get("cfi"),
                "settings": self.resolved_settings(),
            }
            self.js(f"window.reader.open({json.dumps(params)})")
        elif t == "opened":
            self.set_ui_visible(self.ui_visible)
            self._fill_toc(msg.get("toc") or [])
            self.app.on_book_metadata(self.book["id"], msg.get("title"), msg.get("author"))
        elif t == "relocate":
            if msg.get("fraction") is None:
                return
            frac = float(msg["fraction"])
            if not self.slider.isSliderDown():
                self.slider.setValue(int(frac * 1000))
            self.percent.setText(f"{round(frac * 100)}%")
            self.header.set_title(self.book.get("title") or "", msg.get("chapter") or "")
            if msg.get("cfi"):
                self.app.library.set_progress(self.book["id"], msg["cfi"], frac, msg.get("chapter"))
                self.app.note_activity()
            if msg.get("atEnd") and not self.book.get("finished"):
                self.app.set_finished(self.book, True, auto=True)
            if self._flip_timer.isActive():
                if msg.get("atEnd"):
                    self.flip_btn.setChecked(False)   # книга кончилась — автолистание выключаем
                elif not self._auto_turn:
                    self._flip_timer.start()           # листнули вручную — отсчёт заново
                self._auto_turn = False
            if not self._remote_checked:
                # Книга встала на своё место — теперь можно подтянуть место с ЛитРес
                self._remote_checked = True
                self.app.apply_remote_position(self.book)
        elif t == "toggle-ui" or t == "swipe-down":
            self.set_ui_visible(not self.ui_visible)
        elif t == "swipe-up":
            if self.toc:
                self.set_ui_visible(True)
                self.toc_popover.popup_under(self.toc_btn)
        elif t == "pinch":
            step = 2 if float(msg.get("scale") or 1) > 1 else -2
            st = self.app.settings
            st["fontSize"] = max(12, min(40, st["fontSize"] + step))
            self.app.save_settings()
            self.app.toast(f"Размер шрифта: {st['fontSize']}", timeout=1200)
        elif t == "tts":
            self._tts_queue = [x for x in msg.get("segments") or [] if x.get("text")]
            self._tts_speak_next()
        elif t == "tts-end":
            self.tts_btn.setChecked(False)
            self.app.toast("Чтение вслух: книга дочитана до конца")
        elif t == "escape":
            if self.app.window.isFullScreen():
                self.app.toggle_fullscreen()
            else:
                self.app.go_back()
        elif t == "external-link":
            QDesktopServices.openUrl(QUrl(msg["href"]))
        elif t == "error":
            self.app.toast(f"Не удалось открыть книгу: {msg.get('message')}")
        log("reader:", t)

    def _fill_toc(self, toc):
        self.toc = toc
        self.toc_list.clear()
        for entry in toc:
            it = QListWidgetItem("    " * entry["depth"] + (entry["label"] or "—"))
            self.toc_list.addItem(it)
        self.toc_btn.setVisible(bool(toc))

    def _on_toc(self, item):
        href = self.toc[self.toc_list.row(item)]["href"]
        self.js(f"window.reader.goTo({json.dumps(href)})")
        self.toc_popover.hide()

    def _on_seek(self):
        self.js(f"window.reader.goToFraction({self.slider.value() / 1000})")

    # --- чтение вслух

    def _tts_engine(self, sample_text=""):
        from PySide6.QtCore import QLocale
        from PySide6.QtTextToSpeech import QTextToSpeech
        if self._tts is None:
            engines = [e for e in QTextToSpeech.availableEngines() if e != "mock"]
            self._tts = QTextToSpeech(engines[0]) if engines else QTextToSpeech()
            self._tts.stateChanged.connect(self._on_tts_state)
            self._tts_lang = None
        # Голос по языку текста: кириллица — русский, иначе английский
        lang = QLocale.Language.Russian if re.search("[а-яё]", sample_text, re.I) else QLocale.Language.English
        if lang != self._tts_lang:
            self._tts.setLocale(QLocale(lang))
            self._tts_lang = lang
        self._tts.setRate(float(self.app.settings.get("ttsRate", 0.0)))
        return self._tts

    def _toggle_tts(self, on):
        if on:
            if self.flip_btn.isChecked():
                self.flip_btn.setChecked(False)   # чтение вслух само листает страницы
            self.tts_active = True
            self._tts_queue = []
            self.js("window.reader.ttsStart()")
        else:
            self.tts_active = False
            self._tts_queue = []
            if self._tts is not None:
                self._tts.stop()
            self.js("window.reader.ttsStop()")

    def _tts_speak_next(self):
        if not self.tts_active:
            return
        if not self._tts_queue:
            self.js("window.reader.ttsNext()")   # абзац прочитан — следующий
            return
        seg = self._tts_queue.pop(0)
        if seg.get("mark") is not None:
            self.js(f"window.reader.ttsMark({json.dumps(seg['mark'])})")
        self._tts_engine(seg["text"]).say(seg["text"])

    def _on_tts_state(self, state):
        from PySide6.QtTextToSpeech import QTextToSpeech
        if state == QTextToSpeech.State.Ready and self.tts_active:
            self._tts_speak_next()
        elif state == QTextToSpeech.State.Error:
            self.tts_btn.setChecked(False)
            self.app.toast(f"Чтение вслух недоступно: {self._tts.errorString()}")

    # --- автолистание

    def _toggle_autoflip(self, on):
        if on:
            if self.tts_btn.isChecked():
                self.tts_btn.setChecked(False)
            sec = int(self.app.settings.get("autoFlipSec", 30))
            self._flip_timer.start(sec * 1000)
            self.app.toast(f"Автолистание: страница каждые {sec} с")
        else:
            self._flip_timer.stop()

    def _autoflip_turn(self):
        self._auto_turn = True
        self.js("window.reader.next()")

    def close_page(self):
        self._flip_timer.stop()
        if self.tts_active:
            self.tts_active = False
            if self._tts is not None:
                self._tts.stop()
        self.app.library.flush()
        self.page.deleteLater()
