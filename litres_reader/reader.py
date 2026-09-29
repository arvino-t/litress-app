"""Экран чтения: книга рендерится foliate-js во встроенном Chromium."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from PySide6.QtCore import QByteArray, QFile, QIODevice, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestJob,
                                     QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QSlider, QWidget)

from . import style
from .core import BOOKS_DIR, DEBUG, SCHEME, WEB_DIR, log
from .litres import PREFIX
from .widgets import HeaderBar, IconButton, Popover, Switch, attach_popover, cls, label


def register_scheme():
    """Схема litreader:// для страницы читалки и файлов книг (до создания QApplication)."""
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

        self.web = QWebEngineView(self)
        self.page = _ReaderWebPage(reader_profile(), self._on_message, self)
        self.web.setPage(self.page)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu if DEBUG
                                      else Qt.ContextMenuPolicy.NoContextMenu)

        # Верхняя панель — заголовок окна, лежит поверх текста
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
        self.header.setParent(self)

        # Нижняя панель: ползунок по книге и процент
        self.bottom = QFrame(self)
        self.bottom.setObjectName("headerbar")
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(12)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self._on_seek)
        self.percent = label("0%")
        self.percent.setMinimumWidth(44)
        bl.addWidget(self.slider, 1)
        bl.addWidget(self.percent)

        self.page.load(QUrl(f"{SCHEME}://app/reader.html"))
        QTimer.singleShot(3000, lambda: self.set_ui_visible(False))

    # --- раскладка: панели поверх текста, показ/скрытие не перестраивает страницы

    def resizeEvent(self, e):
        w, h = self.width(), self.height()
        self.web.setGeometry(0, 0, w, h)
        self.header.setGeometry(0, 0, w, self.header.height())
        bh = self.bottom.sizeHint().height()
        self.bottom.setGeometry(0, h - bh, w, bh)
        super().resizeEvent(e)

    def set_ui_visible(self, visible):
        self.ui_visible = visible
        self.header.setVisible(visible)
        self.bottom.setVisible(visible)

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
            self._fill_toc(msg.get("toc") or [])
            self.app.on_book_metadata(self.book["id"], msg.get("title"), msg.get("author"))
            self._offer_remote_position()
        elif t == "relocate":
            if msg.get("fraction") is None:
                return
            frac = float(msg["fraction"])
            if not self.slider.isSliderDown():
                self.slider.setValue(int(frac * 1000))
            self.percent.setText(f"{round(frac * 100)}%")
            self.header.set_title(self.book.get("title") or "", msg.get("chapter") or "")
            if msg.get("cfi"):
                self.app.library.set_progress(self.book["id"], msg["cfi"], frac)
            if msg.get("atEnd") and not self.book.get("finished"):
                self.app.set_finished(self.book, True, auto=True)
        elif t == "toggle-ui":
            self.set_ui_visible(not self.ui_visible)
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

    def _offer_remote_position(self):
        """Если на ЛитРес книга прочитана дальше, предлагаем перейти туда."""
        remote = self.book.get("remote_percent") or 0
        local = (self.app.library.progress.get(self.book["id"], {}).get("fraction") or 0) * 100
        if remote < 1 or remote - local < 1:
            return
        self.app.toast(f"На ЛитРес прочитано {round(remote)}%", button="Перейти", timeout=10000,
                       on_button=lambda: self.js(f"window.reader.goToFraction({min(remote, 100) / 100})"))

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

    def close_page(self):
        self.app.library.flush()
        self.page.deleteLater()
