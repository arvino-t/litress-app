"""Страница «Настройки» — в духе Adw.PreferencesWindow: вкладки, на них группы со строками.

Вкладки: «Общие» (запуск, библиотека, папки, статистика), «Чтение» (вид текста, чтение
вслух, автолистание, аудиокниги), «Интеграции» (ЛитРес, Singularity — со значками сервисов),
«Резервные копии» (создание, расписание, восстановление) и «Дополнительно» (обновление
с ЛитРес, оценка чтения на телефоне, журнал, данные, сброс).
Изменения применяются сразу.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, backup, core, style
from .core import CACHE_DIR, CONFIG_DIR, DATA_DIR, DEFAULT_SETTINGS, SITE, books_dir
from .player import SPEEDS
from .widgets import HeaderBar, IconButton, Switch, cls, label

THEMES = (("auto", "Как в системе"), ("light", "Светлая"), ("sepia", "Сепия"),
          ("dark", "Тёмная"), ("black", "Чёрная"))
FONTS = (("book", "Как в книге"), ("serif", "С засечками"), ("sans", "Без засечек"))

TABS = (("general", "Общие"), ("reading", "Чтение"), ("integrations", "Интеграции"),
        ("backup", "Резервные копии"), ("advanced", "Дополнительно"))
BACKUP_AUTO = (("off", "Выключено"), ("daily", "Раз в день"), ("weekly", "Раз в неделю"))
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
SHOWN_BACKUPS = 5


def human_time(when: datetime) -> str:
    today = datetime.now().date()
    day = ("сегодня" if when.date() == today else
           f"{when.day} {MONTHS[when.month - 1]}" + ("" if when.year == today.year else f" {when.year}"))
    return f"{day}, {when:%H:%M}"

# Значки сторонних сервисов: значок из темы системы (если приложение установлено),
# иначе favicon сайта — один раз скачивается и хранится в данных приложения.
SERVICES = {
    "litres": {"theme": (), "favicon": SITE + "/favicon.ico", "fallback": "accessories-dictionary"},
    "singularity": {"theme": ("singularityapp", "singularity"), "favicon": "https://singularity-app.com/favicon.ico",
                    "fallback": "object-select"},
}
ICONS_DIR = CACHE_DIR / "service-icons"
ICON_SIZE = 32
# Настройки, которые «Сбросить» не трогает: где лежат книги, что открыто, состояние графа
KEEP_ON_RESET = {"booksDir", "localFolders", "lastBook", "graph", "settingsTab",
                 "libraryStatus", "libraryFolder", "libraryType", "librarySort",
                 "backupDir", "backupAuto", "backupKeep", "backupLast", "backupToken"}

_net = None


def service_icon(target: QLabel, key: str):
    """Ставит значок сервиса в target (сразу из кэша или темы, иначе — когда скачается)."""
    info = SERVICES[key]
    dpr = target.devicePixelRatioF() or 1.0

    def show(icon: QIcon):
        target.setPixmap(icon.pixmap(QSize(ICON_SIZE, ICON_SIZE), dpr))

    for name in info["theme"]:
        if QIcon.hasThemeIcon(name):
            show(QIcon.fromTheme(name))
            return
    cached = ICONS_DIR / f"{key}.png"
    if cached.exists() and not QPixmap(str(cached)).isNull():
        show(QIcon(str(cached)))
        return
    show(style.icon(info["fallback"], size=ICON_SIZE))     # пока не скачался
    global _net
    if _net is None:
        _net = QNetworkAccessManager()
    reply = _net.get(QNetworkRequest(QUrl(info["favicon"])))

    def done():
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return
        pm = QPixmap()
        if not pm.loadFromData(bytes(reply.readAll())) or pm.isNull():
            return
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        pm.save(str(cached), "PNG")
        try:
            show(QIcon(pm))
        except RuntimeError:        # страницу настроек уже закрыли
            pass
    reply.finished.connect(done)


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app

        header = HeaderBar(app.window, "Настройки")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        header.pack_start(back)

        # Переключатель вкладок (как Adw.ViewSwitcher) под заголовком
        bar = QWidget()
        bar.setObjectName("headerbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 12, 8)
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.tab_group = QButtonGroup(self)
        self.tab_buttons = {}
        for i, (key, text) in enumerate(TABS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            cls(b, "linked-first" if i == 0 else "linked-last" if i == len(TABS) - 1 else "linked")
            b.toggled.connect(lambda on, k=key: on and self.show_tab(k))
            self.tab_group.addButton(b)
            self.tab_buttons[key] = b
            sl.addWidget(b)
        bl.addStretch()
        bl.addWidget(seg)
        bl.addStretch()

        self.stack = QStackedWidget()
        self.pages = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(bar)
        lay.addWidget(self.stack, 1)
        app.litres.state_changed.connect(self._sync_account)
        self.build()

    def show_tab(self, key):
        if key not in self.pages:
            key = TABS[0][0]
        self.stack.setCurrentWidget(self.pages[key])
        if key == "backup":
            self._fill_backups()      # копии могли появиться сами (автоматически)
        btn = self.tab_buttons[key]
        if not btn.isChecked():
            btn.setChecked(True)
        if self.app.settings.get("settingsTab") != key:
            self.app.settings["settingsTab"] = key
            self.app.save_settings()

    def page(self, key):
        """Новая вкладка: прокручиваемая колонка по центру не шире 640 px (как Adw.Clamp)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        outer = QHBoxLayout(holder)
        outer.setContentsMargins(16, 16, 16, 28)
        self.col = QVBoxLayout()
        self.col.setSpacing(6)
        column = QWidget()
        column.setLayout(self.col)
        column.setMaximumWidth(640)
        outer.addStretch()
        outer.addWidget(column, 1)
        outer.addStretch()
        scroll.setWidget(holder)
        self.stack.addWidget(scroll)
        self.pages[key] = scroll

    # --- строительные блоки

    def group(self, title, description=""):
        if self.col.count():
            self.col.addSpacing(18)
        self.col.addWidget(label(title, "heading"))
        if description:
            self.col.addWidget(label(description, "dim", "caption", wrap=True))
        box = QFrame()
        cls(box, "boxed")
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.col.addSpacing(4)
        self.col.addWidget(box)
        return rows

    def row(self, rows, title, widget=None, hint="", service=None):
        r = QWidget()
        if rows.count():
            cls(r, "row-top")
        h = QHBoxLayout(r)
        h.setContentsMargins(14, 9, 12, 9)
        h.setSpacing(12)
        if service:
            ic = QLabel()
            ic.setFixedSize(ICON_SIZE, ICON_SIZE)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
            service_icon(ic, service)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(label(title, wrap=True))
        sub = label(hint, "dim", "caption", wrap=True)   # подпись есть всегда — её можно обновлять
        sub.setObjectName("row-hint")
        sub.setVisible(bool(hint))
        texts.addWidget(sub)
        h.addLayout(texts, 1)
        if widget is not None:
            h.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        if rows.count():
            line = QFrame()
            line.setFixedHeight(1)
            cls(line, "separator-line")
            rows.addWidget(line)
        rows.addWidget(r)
        return r

    def switch(self, rows, title, key, hint="", on_change=None):
        sw = Switch(bool(self.app.settings.get(key)))

        def changed(on):
            self.app.settings[key] = on
            self.app.save_settings()
            if on_change:
                on_change(on)
        sw.toggled.connect(changed)
        self.row(rows, title, sw, hint)
        return sw

    def combo(self, rows, title, key, options, hint="", on_change=None):
        c = QComboBox()
        keys = [k for k, _t in options]
        c.addItems([t for _k, t in options])
        cur = self.app.settings.get(key)
        c.setCurrentIndex(keys.index(cur) if cur in keys else 0)

        def changed(i):
            self.app.settings[key] = keys[i]
            self.app.save_settings()
            if on_change:
                on_change(keys[i])
        c.currentIndexChanged.connect(changed)
        self.row(rows, title, c, hint)
        return c

    def slider(self, rows, title, key, lo, hi, scale=1, fmt=lambda v: f"{v:g}", hint=""):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(int(lo * scale), int(hi * scale))
        s.setValue(int(round(float(self.app.settings.get(key, lo)) * scale)))
        s.setMinimumWidth(170)
        value = label(fmt(s.value() / scale), "dim")
        value.setMinimumWidth(52)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def changed(v):
            self.app.settings[key] = round(v / scale, 2)
            value.setText(fmt(v / scale))
            self.app.save_settings()
        s.valueChanged.connect(changed)
        h.addWidget(s)
        h.addWidget(value)
        self.row(rows, title, box, hint)
        return s

    def spin(self, rows, title, key, lo, hi, step=1, suffix="", hint="", on_change=None):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(int(self.app.settings.get(key) or 0))
        if suffix:
            s.setSuffix(suffix)

        def changed(v):
            self.app.settings[key] = v
            self.app.save_settings()
            if on_change:
                on_change(v)
        s.valueChanged.connect(changed)
        self.row(rows, title, s, hint)
        return s

    def button(self, rows, title, text, slot, hint="", style=None, service=None):
        b = QPushButton(text)
        if style:
            cls(b, style)
        b.clicked.connect(slot)
        self.row(rows, title, b, hint, service=service)
        return b

    # --- содержимое

    def build(self):
        app = self.app
        st = app.settings

        # --- Общие
        self.page("general")
        g = self.group("Запуск и библиотека")
        self.switch(g, "Открывать последнюю текстовую книгу при запуске", "openLastBook",
                    "Самую свежую из начатых и скачанных — с учётом чтения на телефоне")
        only = Switch(app.only_downloaded)
        only.toggled.connect(app.only_action.setChecked)
        self.row(g, "Показывать только скачанные книги", only)
        self.button(g, "Скачать все книги", "Скачать…", app._download_all_action,
                    "Все купленные книги ЛитРес — в папку для скачанных книг")

        g = self.group("Папки", "Где хранятся скачанные книги и где искать свои книги и статьи. "
                                "Свои файлы открываются на месте, приложение их не копирует и не удаляет.")
        self.books_row = self.button(g, "Скачанные книги ЛитРес", "Изменить…", self._choose_books_dir,
                                     hint=str(books_dir()))
        self.folders_group = g
        self._folder_rows = []
        self._fill_folders()

        g = self.group("Статистика")
        self.button(g, "Статистика чтения", "Открыть", app.show_stats_dialog,
                    "Минуты по дням, серия дней подряд, дочитанные книги")
        self.col.addStretch()

        # --- Чтение
        self.page("reading")
        g = self.group("Вид текста")
        self.spin(g, "Размер шрифта", "fontSize", 12, 40)
        self.combo(g, "Тема", "theme", THEMES)
        self.combo(g, "Шрифт", "font", FONTS)
        self.slider(g, "Межстрочный интервал", "lineHeight", 1.1, 2.2, 10)
        self.slider(g, "Поля", "margin", 0, 20, fmt=lambda v: f"{v:g} %")
        self.slider(g, "Ширина строки", "lineWidth", 400, 1400, fmt=lambda v: f"{v:g} px")
        self.switch(g, "Две страницы в горизонтальном положении", "twoColumns")
        self.switch(g, "Выравнивать по ширине", "justify")
        self.switch(g, "Переносы слов", "hyphenate")

        g = self.group("Чтение вслух и автолистание")
        self.slider(g, "Скорость чтения вслух", "ttsRate", -0.5, 0.8, 10,
                    fmt=lambda v: "обычная" if v == 0 else f"{v:+g}")
        self.slider(g, "Автолистание — страница каждые", "autoFlipSec", 5, 120, fmt=lambda v: f"{v:g} с")

        g = self.group("Аудиокниги")
        rate = QComboBox()
        rate.addItems([f"{s:g}×" for s in SPEEDS])
        cur = st.get("audioRate", 1.0)
        rate.setCurrentIndex(SPEEDS.index(cur) if cur in SPEEDS else SPEEDS.index(1.0))

        def rate_changed(i):
            st["audioRate"] = SPEEDS[i]
            app.save_settings()
            app.player.set_rate(SPEEDS[i])
        rate.currentIndexChanged.connect(rate_changed)
        self.row(g, "Скорость воспроизведения", rate, "Без изменения высоты голоса")
        self.col.addStretch()

        # --- Интеграции
        self.page("integrations")
        g = self.group("Сервисы", "Сторонние сервисы, с которыми работает приложение.")
        self.account_btn = self.button(g, "ЛитРес", "", self._account, hint="", service="litres")
        self._sync_account()
        self.button(g, "Singularity", "Настроить…", app.show_singularity_dialog,
                    "Задачи «Читаю», прогресс в заметках, привычка ежедневного чтения", service="singularity")
        self.col.addStretch()

        # --- Резервные копии
        self.page("backup")
        g = self.group("Резервные копии", "Настройки, библиотека (папки, отметки, пути к скачанным книгам), "
                       "место чтения и закладки, статистика, настройки Singularity. Книги и обложки в копию "
                       "не входят, вход в ЛитРес — тоже. Папку с копиями удобно держать в облаке.")
        self.backup_now = self.button(g, "Создать копию сейчас", "Создать", self._backup_now)
        self.combo(g, "Создавать автоматически", "backupAuto", BACKUP_AUTO,
                   "При запуске и пока приложение открыто")
        self.spin(g, "Хранить копий", "backupKeep", 1, 100, hint="Более старые удаляются",
                  on_change=lambda v: backup.prune(backup.backup_dir(st), v))
        dir_box = QWidget()
        dh = QHBoxLayout(dir_box)
        dh.setContentsMargins(0, 0, 0, 0)
        open_dir = QPushButton("Открыть")
        open_dir.clicked.connect(self._open_backup_dir)
        change_dir = QPushButton("Изменить…")
        change_dir.clicked.connect(self._choose_backup_dir)
        dh.addWidget(open_dir)
        dh.addWidget(change_dir)
        self.backup_dir_row = self.row(g, "Папка для копий", dir_box, str(backup.backup_dir(st)))
        self.switch(g, "Сохранять токен Singularity", "backupToken",
                    "Без него после восстановления на другом компьютере Singularity придётся подключить "
                    "заново. Токен даёт доступ к вашим задачам — храните такие копии бережно")

        self.restore_group = self.group("Восстановление", "Перед восстановлением текущие данные тоже сохраняются "
                                        "в копию. Папки книг и копий остаются как на этом компьютере. "
                                        "Приложение перезапустится.")
        self._restore_rows = []
        self._fill_backups()
        self.col.addStretch()

        # --- Дополнительно
        self.page("advanced")
        g = self.group("Синхронизация с ЛитРес")
        self.spin(g, "Обновлять библиотеку с ЛитРес каждые", "remoteSyncMin", 0, 120, 5, " мин",
                  "Пока окно открыто; 0 — только при запуске и по F5", on_change=lambda v: app.apply_remote_sync())
        self.button(g, "Обновить сейчас", "Обновить", app.sync, "То же, что F5")
        self.spin(g, "Скорость чтения для оценки чтения на телефоне", "readingCharsPerMin", 500, 4000, 100,
                  " зн/мин", "По ней прирост процента на ЛитРес переводится в минуты (аудио — по длительности)",
                  on_change=lambda v: setattr(app.library, "chars_per_min", v))

        g = self.group("Журнал")
        self.switch(g, "Подробный журнал", "debugLog",
                    "Запросы к ЛитРес, скачивания, сообщения страниц — в поток ошибок (терминал, журнал системы). "
                    "Инструменты разработчика в читалке — по правой кнопке мыши.",
                    on_change=core.set_debug)

        g = self.group("Данные приложения")
        for title, path, hint in (("Данные", DATA_DIR, "Библиотека, прогресс, статистика, обложки"),
                                  ("Настройки", CONFIG_DIR, "settings.json"),
                                  ("Кэш", CACHE_DIR, "Можно удалить — приложение создаст заново")):
            self.button(g, title, "Открыть папку",
                        lambda _=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),
                        f"{hint}\n{path}")
        self.button(g, "Сбросить настройки", "Сбросить…", self._reset, "Вид текста, чтение, обновление, журнал. "
                    "Папки, вход и библиотека не меняются", style="destructive")

        g = self.group("О приложении")
        self.row(g, "Читалка ЛитРес", label(f"версия {__version__}", "dim"))
        self.col.addStretch()

        self.show_tab(st.get("settingsTab") or "general")

    # --- обработчики

    def _choose_books_dir(self):
        self.app.choose_books_dir()
        self._set_hint(self.books_row, str(books_dir()))

    def _fill_folders(self):
        g = self.folders_group
        for w in self._folder_rows:
            g.removeWidget(w)
            w.deleteLater()
        self._folder_rows = []
        before = g.count()
        for folder in self.app.local_folders():
            b = QPushButton("Убрать")
            b.clicked.connect(lambda _=False, f=folder: (self.app._remove_local_folder(f), self._fill_folders()))
            self.row(g, "Мои книги и статьи", b, folder)
        add = QPushButton("Добавить папку…")
        add.clicked.connect(lambda: (self.app._add_local_folder(), self._fill_folders()))
        rescan = QPushButton("Обновить список")
        rescan.clicked.connect(lambda: self.app.rescan_local(report=True))
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(rescan)
        h.addWidget(add)
        mine = sum(1 for b in self.app.library.books.values() if b.get("source") == "folder")
        self.row(g, "Найдено своих книг и статей", box, str(mine))
        self._folder_rows = [g.itemAt(i).widget() for i in range(before, g.count())]

    # --- резервные копии

    def _sync_backup_hint(self):
        last = self.app.settings.get("backupLast")
        try:
            text = "Последняя: " + human_time(datetime.fromisoformat(last))
        except (TypeError, ValueError):
            text = "Копий ещё не было"
        self._set_hint(self.backup_now, text)

    def _fill_backups(self):
        g = self.restore_group
        for w in self._restore_rows:
            g.removeWidget(w)
            w.deleteLater()
        before = g.count()
        items = backup.list_backups(backup.backup_dir(self.app.settings))
        for path, when in items[:SHOWN_BACKUPS]:
            b = QPushButton("Восстановить")
            b.clicked.connect(lambda _=False, p=path: self._restore(p))
            try:
                size = f"{path.stat().st_size / 1024:.0f} КБ"
            except OSError:
                size = ""
            note = " · перед восстановлением" if "before-restore" in path.name else ""
            self.row(g, human_time(when).capitalize(), b, f"{size}{note}")
        if len(items) > SHOWN_BACKUPS:
            self.row(g, f"И ещё {len(items) - SHOWN_BACKUPS} — в папке для копий")
        elif not items:
            self.row(g, "В папке пока нет копий")
        self.button(g, "Восстановить из файла", "Выбрать…", self._restore_from_file,
                    "Например, копия с другого компьютера")
        self._restore_rows = [g.itemAt(i).widget() for i in range(before, g.count())]
        self._sync_backup_hint()

    def _backup_now(self):
        path = self.app.make_backup()
        if path:
            self.app.toast(f"Копия создана: {path.name}")
        else:
            self.app.toast("Не удалось создать копию — подробности в журнале")
        self._fill_backups()

    def _open_backup_dir(self):
        folder = backup.backup_dir(self.app.settings)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _choose_backup_dir(self):
        cur = backup.backup_dir(self.app.settings)
        folder = QFileDialog.getExistingDirectory(self.app.window, "Папка для резервных копий",
                                                  str(cur if cur.exists() else Path.home()))
        if not folder:
            return
        self.app.settings["backupDir"] = None if Path(folder) == backup.default_dir() else folder
        self.app.save_settings()
        hint = self.backup_dir_row.findChild(QLabel, "row-hint")
        hint.setText(folder)
        hint.setVisible(True)
        self._fill_backups()

    def _restore_from_file(self):
        path, _f = QFileDialog.getOpenFileName(self.app.window, "Резервная копия",
                                               str(backup.backup_dir(self.app.settings)),
                                               "Резервные копии (*.zip)")
        if path:
            self._restore(Path(path))

    def _restore(self, path: Path):
        try:
            manifest = backup.read_manifest(path)
        except ValueError as e:
            QMessageBox.warning(self.app.window, "Не удалось восстановить", str(e).capitalize())
            return
        try:
            when = human_time(datetime.fromisoformat(manifest.get("created", "")))
        except ValueError:
            when = path.name
        box = QMessageBox(self.app.window)
        box.setWindowTitle("Восстановить из копии?")
        box.setText(f"<b>Восстановить данные из копии ({when})?</b>")
        box.setInformativeText(
            f"Копия версии {manifest.get('version', '?')}. Библиотека, место чтения, статистика и настройки "
            "заменятся данными из копии; текущие сначала сохранятся в отдельную копию. "
            "Приложение перезапустится.")
        cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton("Восстановить и перезапустить", QMessageBox.ButtonRole.DestructiveRole)
        cls(ok, "destructive")
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return
        # сначала читаем копию (старые копии может удалить очистка при новой копии), потом страхуемся
        try:
            backup.stage_restore(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self.app.window, "Не удалось восстановить", str(e).capitalize())
            return
        if not self.app.make_backup("before-restore"):
            backup.cancel_pending()
            QMessageBox.warning(self.app.window, "Восстановление отменено",
                                "Не удалось сохранить текущие данные в копию — подробности в журнале.")
            return
        self.app.restart()

    def _reset(self):
        box = QMessageBox(self.app.window)
        box.setWindowTitle("Сбросить настройки?")
        box.setText("<b>Сбросить настройки?</b>")
        box.setInformativeText("Вид текста, чтение вслух, аудио, обновление с ЛитРес и журнал вернутся "
                               "к исходным. Папки, вход в ЛитРес и библиотека не изменятся.")
        cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        ok = box.addButton("Сбросить", QMessageBox.ButtonRole.DestructiveRole)
        cls(ok, "destructive")
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return
        st = self.app.settings
        for k, v in DEFAULT_SETTINGS.items():
            if k not in KEEP_ON_RESET:
                st[k] = v
        core.set_debug(st.get("debugLog"))
        self.app.library.chars_per_min = st["readingCharsPerMin"]
        self.app.apply_remote_sync()
        self.app.player.set_rate(st["audioRate"])
        self.app.save_settings()
        self._rebuild()
        self.app.toast("Настройки сброшены")

    def _rebuild(self):
        """Заново строит вкладки, чтобы переключатели показали новые значения."""
        for w in list(self.pages.values()):
            self.stack.removeWidget(w)
            w.deleteLater()
        self.pages = {}
        self.build()

    def _account(self):
        self.app._account_action()

    def _sync_account(self):
        if not hasattr(self, "account_btn"):
            return
        lit = self.app.litres
        self.account_btn.setText("Выйти" if lit.logged_in else "Войти")
        self._set_hint(self.account_btn, f"Вход выполнен: {lit.user_name}" if lit.logged_in and lit.user_name
                       else "Вход выполнен" if lit.logged_in else "Вход не выполнен")

    @staticmethod
    def _set_hint(widget, text):
        """Подпись под заголовком строки, в которой стоит widget."""
        sub = widget.parentWidget().findChild(QLabel, "row-hint")
        if sub is not None:
            sub.setText(text)
            sub.setVisible(bool(text))
