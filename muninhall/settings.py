"""Страница «Настройки» — в духе Adw.PreferencesWindow: вкладки, на них группы со строками.

Вкладки: «Общие» (язык, запуск, статистика), «Библиотеки» (свои папки и ЛитРес), «Чтение» (вид текста, чтение
вслух, автолистание, аудиокниги), «Интеграции» (ЛитРес, Singularity — со значками сервисов),
«Резервные копии» (создание, расписание, восстановление) и «Дополнительно» (обновление
с ЛитРес, оценка чтения на телефоне, журнал, данные, сброс).
Изменения применяются сразу.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QKeySequenceEdit,
                               QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, backup, core, i18n, libraries, style
from .i18n import tr
from .core import CACHE_DIR, CONFIG_DIR, DATA_DIR, DEFAULT_SETTINGS, SITE, books_dir
from .player import SPEEDS
from .reader import FONTS, TEXT_THEMES
from .widgets import (BoxedList, cls, confirm, HeaderBar, IconButton, label, LibraryScopeCombo, Switch)


TABS = (("general", tr("Общие")), ("libraries", tr("Библиотеки")), ("appearance", tr("Внешний вид")),
        ("reading", tr("Чтение")),
        ("integrations", tr("Интеграции")), ("backup", tr("Резервные копии")), ("advanced", tr("Дополнительно")))
UI_THEMES = (("auto", tr("Как в системе")), ("light", tr("Светлая")), ("dark", tr("Тёмная")))
# цвета акцента — палитра GNOME; "auto" — системный
ACCENTS = (("auto", tr("Системный")), ("#3584e4", tr("Синий")), ("#2190a4", tr("Бирюзовый")),
           ("#3a944a", tr("Зелёный")), ("#c88800", tr("Жёлтый")), ("#ed5b00", tr("Оранжевый")),
           ("#e62d42", tr("Красный")), ("#d56199", tr("Розовый")), ("#9141ac", tr("Фиолетовый")),
           ("#6f8396", tr("Сланцевый")))
APP_ICON_TITLES = {"raven-hall": tr("Ворон в чертоге"), "moon": tr("Ворон на луне"), "flight": tr("Полёт на закате"),
                   "twins": tr("Хугин и Мунин"), "runestone": tr("Рунный камень"), "hall": tr("Чертог"),
                   "quill": tr("Перо ворона"), "eye": tr("Глаз ворона"), "wings": tr("Крылья-«М»")}
BACKUP_AUTO = (("off", tr("Выключено")), ("daily", tr("Раз в день")), ("weekly", tr("Раз в неделю")))
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
SHOWN_BACKUPS = 5


MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")


def human_time(when: datetime) -> str:
    today = datetime.now().date()
    if when.date() == today:
        day = tr("сегодня")
    elif i18n.LANG == "en":
        day = f"{MONTHS_EN[when.month - 1]} {when.day}" + ("" if when.year == today.year else f", {when.year}")
    else:
        day = f"{when.day} {MONTHS[when.month - 1]}" + ("" if when.year == today.year else f" {when.year}")
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
KEEP_ON_RESET = {"booksDir", "libraries", "appIcon", "shortcuts", "lastBook", "graph", "settingsTab",
                 "libraryStatus", "libraryFolder", "librarySubdir", "libraryType", "librarySort",
                 "backupDir", "backupAuto", "backupKeep", "backupLast", "backupToken", "language"}

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

        header = HeaderBar(app.window, tr("Настройки"))
        back = IconButton("go-previous", tr("Назад"))
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
        box = BoxedList()
        rows = box.lay
        self.col.addSpacing(4)
        self.col.addWidget(box)
        return rows

    def row(self, rows, title, widget=None, hint="", service=None, icon=None, icon_path=None):
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
        elif icon_path:
            ic = QLabel()
            ic.setFixedSize(ICON_SIZE, ICON_SIZE)
            ic.setPixmap(QIcon(icon_path).pixmap(QSize(ICON_SIZE, ICON_SIZE), ic.devicePixelRatioF() or 1.0))
            h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        elif icon:
            ic = QLabel()
            ic.setFixedSize(ICON_SIZE, ICON_SIZE)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setPixmap(style.icon(icon, size=24).pixmap(24, 24))
            h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
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
        g = self.group(tr("Язык"))
        self.combo(g, tr("Язык интерфейса"), "language",
                   (("auto", tr("Как в системе")), ("ru", "Русский"), ("en", "English")),
                   tr("Применяется после перезапуска"), on_change=self._language_changed)
        g = self.group(tr("Запуск и библиотека"))
        self.switch(g, tr("Открывать последнюю текстовую книгу при запуске"), "openLastBook",
                    tr("Самую свежую из начатых и скачанных — с учётом чтения на телефоне"))
        only = Switch(app.only_downloaded)
        only.toggled.connect(app.only_action.setChecked)
        self.row(g, tr("Показывать только скачанные книги"), only)
        if app.has_litres():
            self.button(g, tr("Скачать все книги"), tr("Скачать…"), app.download_all,
                        tr("Все купленные книги ЛитРес — в папку для скачанных книг"))

        g = self.group(tr("Статистика"))
        self.button(g, tr("Статистика чтения"), tr("Открыть"), app.show_stats_dialog,
                    tr("Минуты по дням, серия дней подряд, дочитанные книги"))
        self.col.addStretch()

        # --- Библиотеки
        self.page("libraries")
        self.account_btn = None
        self.libraries_group = self.group(
            tr("Библиотеки"), tr("Своя библиотека — папка на диске: её подпапки видны в фильтре «Подкаталог», "
                                 "данные (отметки, место чтения) хранятся в ней же, в скрытой папке .library. "
                                 "Файлы открываются на месте, приложение их не копирует и не удаляет. "
                                 "ЛитРес — подключаемая библиотека купленных книг."))
        self._library_rows = []
        self._fill_libraries()
        self.col.addStretch()

        # --- Внешний вид
        self.page("appearance")
        g = self.group(tr("Оформление"))
        self.combo(g, tr("Тема интерфейса"), "uiTheme", UI_THEMES, tr("Светлая или тёмная — независимо от системы"),
                   on_change=lambda _v: app.apply_appearance())
        self.row(g, tr("Цвет акцента"), self._accent_picker())

        g = self.group(tr("Значок приложения"), tr("Значок окна и ярлыка в меню приложений."))
        self.row(g, tr("Значок"), self._icon_picker())

        self.shortcuts_group = self.group(tr("Горячие клавиши"),
                                          tr("Щёлкните поле и нажмите новое сочетание; Backspace — убрать."))
        self._shortcut_rows = []
        self._fill_shortcuts()
        self.col.addStretch()

        # --- Чтение
        self.page("reading")
        g = self.group(tr("Вид текста"))
        self.spin(g, tr("Размер шрифта"), "fontSize", 12, 40)
        self.combo(g, tr("Тема"), "theme", TEXT_THEMES)
        self.combo(g, tr("Шрифт"), "font", FONTS)
        self.slider(g, tr("Межстрочный интервал"), "lineHeight", 1.1, 2.2, 10)
        self.slider(g, tr("Поля"), "margin", 0, 20, fmt=lambda v: f"{v:g} %")
        self.slider(g, tr("Ширина строки"), "lineWidth", 400, 1400, fmt=lambda v: f"{v:g} px")
        self.switch(g, tr("Две страницы в горизонтальном положении"), "twoColumns")
        self.switch(g, tr("Выравнивать по ширине"), "justify")
        self.switch(g, tr("Переносы слов"), "hyphenate")

        g = self.group(tr("Чтение вслух и автолистание"))
        self.slider(g, tr("Скорость чтения вслух"), "ttsRate", -0.5, 0.8, 10,
                    fmt=lambda v: tr("обычная") if v == 0 else f"{v:+g}")
        self.slider(g, tr("Автолистание — страница каждые"), "autoFlipSec", 5, 120, fmt=lambda v: tr('{0:g} с', v))

        g = self.group(tr("Аудиокниги"))
        rate = QComboBox()
        rate.addItems([f"{s:g}×" for s in SPEEDS])
        cur = st.get("audioRate", 1.0)
        rate.setCurrentIndex(SPEEDS.index(cur) if cur in SPEEDS else SPEEDS.index(1.0))

        def rate_changed(i):
            st["audioRate"] = SPEEDS[i]
            app.save_settings()
            app.player.set_rate(SPEEDS[i])
        rate.currentIndexChanged.connect(rate_changed)
        self.row(g, tr("Скорость воспроизведения"), rate, tr("Без изменения высоты голоса"))
        self.col.addStretch()

        # --- Интеграции
        self.page("integrations")
        g = self.group(tr("Сервисы"), tr("Сторонние сервисы, с которыми работает приложение."))
        self.button(g, "Singularity", tr("Настроить…"), app.show_singularity_dialog,
                    tr("Задачи «Читаю», прогресс в заметках, привычка ежедневного чтения"), service="singularity")
        self.col.addStretch()

        # --- Резервные копии
        self.page("backup")
        g = self.group(tr("Резервные копии"), tr("Копия «Все библиотеки» — настройки, статистика, Singularity и данные "
                       "всех библиотек; копия одной библиотеки — её отметки, место чтения и граф. Книги и обложки "
                       "в копию не входят, вход в ЛитРес — тоже. Папку с копиями удобно держать в облаке."))
        scope_combo = LibraryScopeCombo(st, getattr(self, "backup_scope", "all"))
        scope_combo.setVisible(True)                 # копия «Все библиотеки» есть даже при одной библиотеке
        self.backup_scope = scope_combo.scope()
        self._backup_scopes = scope_combo.scopes()
        scope_combo.scope_changed.connect(self._on_backup_scope)
        self.row(g, tr("Библиотека"), scope_combo, tr("К ней относятся «Создать» и список копий ниже"))
        self.backup_now = self.button(g, tr("Создать копию сейчас"), tr("Создать"), self._backup_now)
        self.combo(g, tr("Создавать автоматически"), "backupAuto", BACKUP_AUTO,
                   tr("Копию всех библиотек — при запуске и пока приложение открыто"))
        self.spin(g, tr("Хранить копий"), "backupKeep", 1, 100, hint=tr("У каждой библиотеки; более старые удаляются"),
                  on_change=lambda v: [backup.prune(backup.backup_dir(st), v, sc) for sc in self._backup_scopes])
        dir_box = QWidget()
        dh = QHBoxLayout(dir_box)
        dh.setContentsMargins(0, 0, 0, 0)
        open_dir = QPushButton(tr("Открыть"))
        open_dir.clicked.connect(self._open_backup_dir)
        change_dir = QPushButton(tr("Изменить…"))
        change_dir.clicked.connect(self._choose_backup_dir)
        dh.addWidget(open_dir)
        dh.addWidget(change_dir)
        self.backup_dir_row = self.row(g, tr("Папка для копий"), dir_box, str(backup.backup_dir(st)))
        self.switch(g, tr("Сохранять токен Singularity"), "backupToken",
                    tr("Без него после восстановления на другом компьютере Singularity придётся подключить "
                    "заново. Токен даёт доступ к вашим задачам — храните такие копии бережно"))

        self.restore_group = self.group(
            tr("Восстановление"), tr("Перед восстановлением текущие данные тоже сохраняются "
                                        "в копию. Папки книг и копий остаются как на этом компьютере. "
                                        "Приложение перезапустится."))
        self._restore_rows = []
        self._fill_backups()
        self.col.addStretch()

        # --- Дополнительно
        self.page("advanced")
        g = self.group(tr("Синхронизация с ЛитРес"))
        self.spin(g, tr("Обновлять библиотеку с ЛитРес каждые"), "remoteSyncMin", 0, 120, 5, tr(" мин"),
                  tr("Пока окно открыто; 0 — только при запуске и по F5"), on_change=lambda v: app.apply_remote_sync())
        self.button(g, tr("Обновить сейчас"), tr("Обновить"), app.sync, tr("То же, что F5"))
        self.spin(g, tr("Скорость чтения для оценки чтения на телефоне"), "readingCharsPerMin", 500, 4000, 100,
                  tr(" зн/мин"), tr("По ней прирост процента на ЛитРес переводится в минуты (аудио — по длительности)"),
                  on_change=lambda v: setattr(app.library, "chars_per_min", v))

        g = self.group(tr("Журнал"))
        self.switch(g, tr("Подробный журнал"), "debugLog",
                    tr("Запросы к ЛитРес, скачивания, сообщения страниц — в поток ошибок (терминал, журнал системы). "
                    "Инструменты разработчика в читалке — по правой кнопке мыши."),
                    on_change=core.set_debug)

        g = self.group(tr("Данные приложения"))
        for title, path, hint in ((tr("Данные"), DATA_DIR, tr("Библиотека, прогресс, статистика, обложки")),
                                  (tr("Настройки"), CONFIG_DIR, "settings.json"),
                                  (tr("Кэш"), CACHE_DIR, tr("Можно удалить — приложение создаст заново"))):
            self.button(g, title, tr("Открыть папку"),
                        lambda _=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),
                        f"{hint}\n{path}")
        self.button(g, tr("Сбросить настройки"), tr("Сбросить…"), self._reset,
                    tr("Вид текста, чтение, обновление, журнал. "
                    "Папки, вход и библиотека не меняются"), style="destructive")

        g = self.group(tr("О приложении"))
        about = QPushButton(tr("Подробнее…"))
        about.clicked.connect(app.on_about)
        self.row(g, core.APP_NAME, about, tr("версия {0} · своя библиотека книг и статей; ЛитРес — подключаемая "
                                             "библиотека", __version__), icon_path=str(core.APP_ICON))
        self.button(g, tr("Документация и исходный код"), tr("Открыть"),
                    lambda: QDesktopServices.openUrl(QUrl("https://github.com/arvino-t/muninhall")),
                    "github.com/arvino-t/muninhall")
        self.col.addStretch()

        self.show_tab(st.get("settingsTab") or "general")

    # --- обработчики

    def _choose_books_dir(self):
        self.app.choose_books_dir()
        self._sync_account()

    def _fill_libraries(self):
        g = self.libraries_group
        for w in self._library_rows:
            g.removeWidget(w)
            w.deleteLater()
        before = g.count()
        app = self.app
        self.account_btn = None
        for lib in libraries.all_libraries(app.settings):
            box = QWidget()
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0, 0, 0, 0)
            if lib["kind"] == "litres":
                self.account_btn = QPushButton()
                self.account_btn.clicked.connect(self._account)
                folder = QPushButton(tr("Папка для книг…"))
                folder.setToolTip(str(books_dir()))
                folder.clicked.connect(self._choose_books_dir)
                off = QPushButton(tr("Отключить"))
                off.clicked.connect(app.disconnect_litres)
                for b in (self.account_btn, folder, off):
                    bh.addWidget(b)
                self.litres_row = self.row(g, lib["name"], box, "", service="litres")
                self._sync_account()
            else:
                path = lib["path"]
                rename = QPushButton(tr("Переименовать…"))
                rename.clicked.connect(lambda _=False, p=path: (app.rename_local_folder(p), self._fill_libraries()))
                remove = QPushButton(tr("Убрать"))
                remove.setToolTip(tr("Убрать из программы — файлы и данные в папке останутся"))
                remove.clicked.connect(lambda _=False, p=path: (app.remove_local_folder(p), self._fill_libraries()))
                bh.addWidget(rename)
                bh.addWidget(remove)
                count = sum(1 for b in app.library.books.values() if b.get("library") == lib["id"])
                self.row(g, lib["name"], box, f"{path} · {tr('книг: {0}', count)}", icon="accessories-dictionary")
        add = QPushButton(tr("Добавить библиотеку…"))
        add.clicked.connect(lambda: self._add_library(add))
        rescan = QPushButton(tr("Обновить список"))
        rescan.clicked.connect(lambda: (app.rescan_local(report=True), self._fill_libraries()))
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(rescan)
        h.addWidget(add)
        self.row(g, tr("Книг во всех библиотеках"), box, str(len(app.library.ordered())))
        self._library_rows = [g.itemAt(i).widget() for i in range(before, g.count())]

    def _add_library(self, button):
        menu = QMenu(button)
        menu.addAction(tr("Своя библиотека — папка на диске…"),
                       lambda: (self.app.add_local_folder(), self._fill_libraries()))
        if not self.app.has_litres():
            menu.addAction(tr("ЛитРес — купленные книги"), self.app.connect_litres)
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

    # --- резервные копии

    def _on_backup_scope(self, scope):
        if scope in self._backup_scopes:
            self.backup_scope = scope
            self._fill_backups()

    def _sync_backup_hint(self):
        items = backup.list_backups(backup.backup_dir(self.app.settings), self.backup_scope)
        text = tr("Последняя: ") + human_time(items[0][1]) if items else tr("Копий ещё не было")
        self._set_hint(self.backup_now, text)

    def _fill_backups(self):
        g = self.restore_group
        for w in self._restore_rows:
            g.removeWidget(w)
            w.deleteLater()
        before = g.count()
        items = backup.list_backups(backup.backup_dir(self.app.settings), self.backup_scope)
        for path, when in items[:SHOWN_BACKUPS]:
            b = QPushButton(tr("Восстановить"))
            b.clicked.connect(lambda _=False, p=path: self._restore(p))
            try:
                size = tr('{0:.0f} КБ', path.stat().st_size / 1024)
            except OSError:
                size = ""
            note = tr(" · перед восстановлением") if "before-restore" in path.name else ""
            self.row(g, human_time(when).capitalize(), b, f"{size}{note}")
        if len(items) > SHOWN_BACKUPS:
            self.row(g, tr('И ещё {0} — в папке для копий', len(items) - SHOWN_BACKUPS))
        elif not items:
            self.row(g, tr("В папке пока нет копий"))
        self.button(g, tr("Восстановить из файла"), tr("Выбрать…"), self._restore_from_file,
                    tr("Например, копия с другого компьютера"))
        self._restore_rows = [g.itemAt(i).widget() for i in range(before, g.count())]
        self._sync_backup_hint()

    def _backup_now(self):
        path = self.app.make_backup(scope=self.backup_scope)
        if path:
            self.app.toast(tr('Копия создана: {0}', path.name))
        else:
            self.app.toast(tr("Не удалось создать копию — подробности в журнале"))
        self._fill_backups()

    def _open_backup_dir(self):
        folder = backup.backup_dir(self.app.settings)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _choose_backup_dir(self):
        cur = backup.backup_dir(self.app.settings)
        folder = QFileDialog.getExistingDirectory(self.app.window, tr("Папка для резервных копий"),
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
        path, _f = QFileDialog.getOpenFileName(self.app.window, tr("Резервная копия"),
                                               str(backup.backup_dir(self.app.settings)),
                                               tr("Резервные копии (*.zip)"))
        if path:
            self._restore(Path(path))

    def _restore(self, path: Path):
        try:
            manifest = backup.read_manifest(path)
        except ValueError as e:
            QMessageBox.warning(self.app.window, tr("Не удалось восстановить"), str(e).capitalize())
            return
        try:
            when = human_time(datetime.fromisoformat(manifest.get("created", "")))
        except ValueError:
            when = path.name
        scope = manifest.get("scope") or backup.scope_of(path)
        names = {lib["id"]: lib["name"] for lib in libraries.all_libraries(self.app.settings)}
        if scope != "all" and scope not in names:
            QMessageBox.warning(self.app.window, tr("Не удалось восстановить"),
                                tr("Это копия библиотеки, которой нет в программе. Добавьте библиотеку и повторите."))
            return
        if scope == "all":
            info = tr('Копия версии {0}. Библиотека, место чтения, статистика и настройки заменятся данными '
                      'из копии; текущие сначала сохранятся в отдельную копию. Приложение перезапустится.',
                      manifest.get('version', '?'))
        else:
            info = tr("Отметки, место чтения и граф библиотеки «{0}» заменятся данными из копии; "
                      "текущие сначала сохранятся в отдельную копию. Приложение перезапустится.", names[scope])
        if not confirm(self.app.window, tr("Восстановить из копии?"),
                       tr('<b>Восстановить данные из копии ({0})?</b>', when), info,
                       tr("Восстановить и перезапустить")):
            return
        # сначала читаем копию (старые копии может удалить очистка при новой копии), потом страхуемся
        try:
            backup.stage_restore(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self.app.window, tr("Не удалось восстановить"), str(e).capitalize())
            return
        if not self.app.make_backup("before-restore", scope):
            backup.cancel_pending()
            QMessageBox.warning(self.app.window, tr("Восстановление отменено"),
                                tr("Не удалось сохранить текущие данные в копию — подробности в журнале."))
            return
        self.app.restart()

    # --- внешний вид

    def _accent_picker(self) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        group = QButtonGroup(box)
        current = self.app.settings.get("accent") or "auto"
        for value, title in ACCENTS:
            b = QPushButton()
            b.setCheckable(True)
            b.setToolTip(title)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if value == "auto":
                b.setText("A")
                b.setStyleSheet("QPushButton { border-radius: 13px; padding: 0; }"
                                "QPushButton:checked { border: 2px solid palette(text); }")
            else:
                b.setStyleSheet(f"QPushButton {{ background: {value}; border-radius: 13px; padding: 0; }}"
                                f"QPushButton:checked {{ border: 3px solid palette(text); }}")
            b.setChecked(value == current)
            b.clicked.connect(lambda _=False, v=value: self._set_accent(v))
            group.addButton(b)
            h.addWidget(b)
        return box

    def _set_accent(self, value):
        self.app.settings["accent"] = value
        self.app.save_settings()
        self.app.apply_appearance()

    def _icon_picker(self) -> QWidget:
        box = QWidget()
        grid = QHBoxLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        group = QButtonGroup(box)
        current = self.app.settings.get("appIcon") or core.APP_ICON_NAMES[0]
        for name in core.APP_ICON_NAMES:
            b = QPushButton()
            b.setCheckable(True)
            cls(b, "flat")
            b.setIcon(QIcon(str(core.app_icon_path(name))))
            b.setIconSize(QSize(36, 36))
            b.setFixedSize(46, 46)
            b.setToolTip(APP_ICON_TITLES.get(name, name))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(name == current)
            b.clicked.connect(lambda _=False, n=name: self._set_icon(n))
            group.addButton(b)
            grid.addWidget(b)
        return box

    def _set_icon(self, name):
        self.app.settings["appIcon"] = name
        self.app.save_settings()
        self.app.apply_app_icon(name)

    def _fill_shortcuts(self):
        from .appearance import SHORTCUTS
        g = self.shortcuts_group
        for w in self._shortcut_rows:
            g.removeWidget(w)
            w.deleteLater()
        before = g.count()
        keys = {a: self.app.shortcut_keys(a) for a, *_ in SHORTCUTS}
        taken: dict[str, list[str]] = {}
        for a, ks in keys.items():
            for k in ks:
                taken.setdefault(QKeySequence(k).toString(), []).append(a)
        titles = {a: t for a, t, *_ in SHORTCUTS}
        for action, title, default, _slot in SHORTCUTS:
            edit = QKeySequenceEdit(QKeySequence(keys[action][0]) if keys[action] else QKeySequence())
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            edit.setFixedWidth(150)
            inner = edit.findChild(QLineEdit)
            if inner is not None:
                inner.setPlaceholderText(tr("Нажмите сочетание"))
            edit.editingFinished.connect(lambda a=action, e=edit: self._set_shortcut(a, e.keySequence()))
            edit.keySequenceChanged.connect(lambda seq, a=action: (not seq.isEmpty()) or self._set_shortcut(a, seq))
            extra = [k for k in keys[action][1:]]
            conflicts = sorted({titles[o] for k in keys[action] for o in taken.get(QKeySequence(k).toString(), [])
                                if o != action})
            hint = []
            if extra:
                hint.append(tr("Также: {0}", ", ".join(QKeySequence(k).toString(QKeySequence.SequenceFormat.NativeText)
                                                       for k in extra)))
            if conflicts:
                hint.append(tr("Совпадает с: {0}", ", ".join(conflicts)))
            if keys[action] != default:
                hint.append(tr("По умолчанию: {0}", ", ".join(default) or "—"))
            self.row(g, title, edit, " · ".join(hint))
        reset = QPushButton(tr("Сбросить клавиши"))
        reset.clicked.connect(self._reset_shortcuts)
        self.row(g, tr("Все сочетания по умолчанию"), reset)
        self._shortcut_rows = [g.itemAt(i).widget() for i in range(before, g.count())]

    def _set_shortcut(self, action, seq: QKeySequence):
        custom = dict(self.app.settings.get("shortcuts") or {})
        new = [seq.toString()] if not seq.isEmpty() else []
        if custom.get(action) == new or (action not in custom and self.app.shortcut_keys(action) == new):
            return
        custom[action] = new
        self.app.settings["shortcuts"] = custom
        self.app.save_settings()
        self.app.apply_shortcuts()
        QTimer.singleShot(0, self._fill_shortcuts)    # подсказки о совпадениях

    def _reset_shortcuts(self):
        self.app.settings["shortcuts"] = None
        self.app.save_settings()
        self.app.apply_shortcuts()
        self._fill_shortcuts()

    def _language_changed(self, lang):
        effective = lang if lang in ("ru", "en") else i18n.system_language()
        if effective == i18n.LANG:
            return
        self.app.save_settings()
        # Подпись — сразу на выбранном языке: человек может не читать текущий
        text = "Language changes after restart" if effective == "en" else "Язык сменится после перезапуска"
        button = "Restart" if effective == "en" else "Перезапустить"
        self.app.toast(text, button=button, on_button=self.app.restart, timeout=10000)

    def _reset(self):
        if not confirm(self.app.window, tr("Сбросить настройки?"), tr("<b>Сбросить настройки?</b>"),
                       tr("Вид текста, чтение вслух, аудио, обновление с ЛитРес и журнал вернутся "
                          "к исходным. Папки, вход в ЛитРес и библиотека не изменятся."), tr("Сбросить")):
            return
        st = self.app.settings
        for k, v in DEFAULT_SETTINGS.items():
            if k not in KEEP_ON_RESET:
                st[k] = v
        core.set_debug(st.get("debugLog"))
        self.app.library.chars_per_min = st["readingCharsPerMin"]
        self.app.apply_remote_sync()
        self.app.player.set_rate(st["audioRate"])
        self.app.apply_appearance()
        self.app.save_settings()
        self._rebuild()
        self.app.toast(tr("Настройки сброшены"))

    def _rebuild(self):
        """Заново строит вкладки, чтобы переключатели показали новые значения."""
        for w in list(self.pages.values()):
            self.stack.removeWidget(w)
            w.deleteLater()
        self.pages = {}
        self.build()

    def _account(self):
        self.app.toggle_account()

    def _sync_account(self):
        if getattr(self, "account_btn", None) is None:
            return
        lit = self.app.litres
        self.account_btn.setText(tr("Выйти") if lit.logged_in else tr("Войти"))
        state = (tr('Вход выполнен: {0}', lit.user_name) if lit.logged_in and lit.user_name
                 else tr("Вход выполнен") if lit.logged_in else tr("Вход не выполнен"))
        hint = self.litres_row.findChild(QLabel, "row-hint")
        hint.setText(f"{state}\n{tr('Книги: {0}', books_dir())}")
        hint.setVisible(True)

    def rebuild_later(self):
        """Перестроить вкладки после смены библиотек (не из обработчика удаляемой кнопки)."""
        QTimer.singleShot(0, self._rebuild)

    @staticmethod
    def _set_hint(widget, text):
        """Подпись под заголовком строки, в которой стоит widget."""
        sub = widget.parentWidget().findChild(QLabel, "row-hint")
        if sub is not None:
            sub.setText(text)
            sub.setVisible(bool(text))
