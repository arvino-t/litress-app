"""Главное окно и логика приложения: библиотека, вход в ЛитРес, синхронизация, скачивание."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QProcess, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, backup, core, libraries, style, widgets
from .i18n import tr
from .core import (APP_ICON, APP_ID, APP_NAME, APP_SLUG, OLD_APP_IDS, AUDIO_FORMATS, CONFIG_FILE, COVERS_DIR, DEFAULT_SETTINGS,
                   NO_FOLDER, READABLE, SORT_MODES, STATUS_FILTERS, Library, books_dir, load_json, log,
                   save_json, set_books_dir)
from .graph import GraphPage
from .settings import SettingsPage
from .litres import LitresSession
from .player import AudioPlayer, PlayerPage, audio_tracks
from .reader import ReaderPage
from .litres_connector import LitresConnector
from .singularity import SingularitySync
from .widgets import (BookCard, FlowLayout, HeaderBar, IconButton, RecentPanel, Switch, Toast, cls,
                      label)

EBOOK_PATTERNS = "*.epub *.fb2 *.fb2.zip *.fbz *.mobi *.azw3"


class Spinner(QWidget):
    """Крутящийся индикатор (Adw.Spinner)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(34, 34)
        self._angle = 0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def setVisible(self, v):
        super().setVisible(v)
        self._timer.start() if v else self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(style.solid_fg(), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        r = QRectF(9, 9, 16, 16)
        p.drawArc(r, -self._angle * 16, 270 * 16)
        p.end()


class EdgeGrip(QWidget):
    """Невидимая полоска у края окна без рамки: тянет окно системным растягиванием."""

    CURSORS = {
        Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
        Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, window, edges):
        super().__init__(window)
        self.edges = edges
        self.setCursor(self.CURSORS[edges])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemResize(self.edges)


class MainWindow(QMainWindow):
    """Окно без системной рамки: заголовок рисуем сами, края тянутся за невидимые полоски."""

    BORDER = 6

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(1100, 760)
        E = Qt.Edge
        self._grips = [EdgeGrip(self, e) for e in (
            E.LeftEdge, E.RightEdge, E.TopEdge, E.BottomEdge,
            E.LeftEdge | E.TopEdge, E.RightEdge | E.TopEdge,
            E.LeftEdge | E.BottomEdge, E.RightEdge | E.BottomEdge)]

    def _place_grips(self):
        b, w, h = self.BORDER, self.width(), self.height()
        E = Qt.Edge
        rects = {
            E.LeftEdge: (0, b, b, h - 2 * b), E.RightEdge: (w - b, b, b, h - 2 * b),
            E.TopEdge: (b, 0, w - 2 * b, b), E.BottomEdge: (b, h - b, w - 2 * b, b),
            E.LeftEdge | E.TopEdge: (0, 0, b, b), E.RightEdge | E.TopEdge: (w - b, 0, b, b),
            E.LeftEdge | E.BottomEdge: (0, h - b, b, b), E.RightEdge | E.BottomEdge: (w - b, h - b, b, b),
        }
        resizable = not (self.isMaximized() or self.isFullScreen())
        for g in self._grips:
            g.setGeometry(*rects[g.edges])
            g.setVisible(resizable)
            g.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_grips()
        if hasattr(self.app, "recent_panel"):
            self.app._update_recent_panel()
        for t in self.findChildren(Toast):
            t.reposition()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._place_grips()

    def closeEvent(self, e):
        self.app.on_close()
        super().closeEvent(e)


# Горячие клавиши: действие, подпись, клавиши по умолчанию, метод App
SHORTCUTS = (
    ("sync", tr("Обновить библиотеку"), ["F5", "Ctrl+R"], "sync"),
    ("search", tr("Поиск"), ["Ctrl+F"], "_toggle_search"),
    ("open", tr("Открыть файл"), ["Ctrl+O"], "on_open_file"),
    ("graph", tr("Граф книг"), ["Ctrl+G"], "show_graph"),
    ("stats", tr("Статистика чтения"), [], "show_stats_dialog"),
    ("settings", tr("Настройки"), ["Ctrl+,"], "show_settings"),
    ("fullscreen", tr("Во весь экран"), ["F11"], "toggle_fullscreen"),
    ("back", tr("Назад"), ["Alt+Left"], "go_back"),
)

class App(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = {**DEFAULT_SETTINGS, **load_json(CONFIG_FILE, {})}
        core.set_debug(self.settings.get("debugLog"))
        if libraries.ensure_registry(self.settings):      # первый запуск с библиотеками — перенос настроек
            save_json(CONFIG_FILE, self.settings)
        try:
            set_books_dir(self.settings.get("booksDir"))
        except OSError:
            # выбранная папка недоступна (например, отключён диск) — берём папку по умолчанию
            set_books_dir(None)
        self.library = Library()
        self.library.chars_per_min = int(self.settings.get("readingCharsPerMin") or 1300)
        self._settings_timer = QTimer(self, singleShot=True, interval=500)
        self._settings_timer.timeout.connect(lambda: save_json(CONFIG_FILE, self.settings))
        # Автоматические резервные копии: проверка через минуту после запуска и раз в час
        self._backup_timer = QTimer(self, interval=3600_000)
        self._backup_timer.timeout.connect(self.auto_backup)
        self._backup_timer.start()
        QTimer.singleShot(60_000, self.auto_backup)
        self.cards: dict[str, BookCard] = {}
        self.litres_lib = LitresConnector(self)   # подключаемая библиотека ЛитРес
        self.only_downloaded = False
        self.reader: ReaderPage | None = None
        self.graph_page: GraphPage | None = None
        self.settings_page: SettingsPage | None = None
        self._details_running = False
        self.player_page: PlayerPage | None = None
        widgets.THUMBS_DIR = core.CACHE_DIR / "thumbs"      # миниатюры обложек
        self.net = QNetworkAccessManager(self)
        self._covers_running = 0
        self._cover_queue: list[str] = []

        style.read_portal_scheme()
        style.set_overrides(self.settings.get("uiTheme"), self.settings.get("accent"))
        style.apply_palette(qapp)
        qapp.styleHints().colorSchemeChanged.connect(self._on_theme_changed)
        # Портал не шлёт сигнал в Qt — проверяем смену темы и акцента раз в 2 секунды
        self._scheme = (style.is_dark(), style.ACCENT)
        self._theme_timer = QTimer(self, interval=2000)
        self._theme_timer.timeout.connect(self._poll_theme)
        self._theme_timer.start()

        self.player = AudioPlayer(self)
        self.player.finished.connect(self._on_audio_finished)
        self.player.error.connect(lambda msg: self.toast(tr('Ошибка воспроизведения: {0}', msg)))
        self.player.state_changed.connect(self._on_player_state)
        # Место прослушивания сохраняем раз в 5 секунд
        self._audio_timer = QTimer(self, interval=5000)
        self._audio_timer.timeout.connect(self.save_audio_progress)
        self._audio_timer.start()

        self.litres = LitresSession(self)
        self.litres.state_changed.connect(self.litres_lib.on_login_state)

        # Singularity: задачи книг, прогресс, «Хочу прочитать», привычка «Чтение N минут»
        self.singularity = SingularitySync(self)
        self._last_activity = 0.0
        self._activity_timer = QTimer(self, interval=30_000)
        self._activity_timer.timeout.connect(self._count_reading_time)
        self._activity_timer.start()
        QTimer.singleShot(10_000, self.singularity.sync)

        self.window = MainWindow(self)
        self.apply_app_icon(self.settings.get("appIcon"))
        self.stack = QStackedWidget()
        self.window.setCentralWidget(self.stack)
        self.history: list[QWidget] = []

        self.library_page = self._build_library_page()
        self.login_page = self._build_login_page()
        self.push(self.library_page)

        # горячие клавиши — настраиваются в «Настройки → Внешний вид»
        self.shortcuts: dict[str, QShortcut] = {}
        for action, _title, _keys, slot in SHORTCUTS:
            sc = QShortcut(self.window)
            sc.activated.connect(getattr(self, slot))
            self.shortcuts[action] = sc
        self.apply_shortcuts()

        self._apply_litres_ui()
        if self.has_litres():
            # встроенный Chromium для ЛитРес — когда окно уже на экране
            QTimer.singleShot(400, self.litres.start)
        self.library.scan_folders(self.local_folders())
        self.refresh_library()
        QTimer.singleShot(0, self._open_last_book)
        QTimer.singleShot(1500, self._make_pdf_covers)
        # Пока окно открыто — тихо подтягиваем с ЛитРес прочитанное на других устройствах
        self._remote_timer = QTimer(self)
        self._remote_timer.timeout.connect(self.litres_lib._periodic_sync)
        self.litres_lib.apply_remote_sync()

    def show_settings(self):
        if self.settings_page is None:
            self.settings_page = SettingsPage(self)
        self.push(self.settings_page)

    def _open_last_book(self):
        """Автопереход: открыть последнюю текстовую книгу на месте, где остановились.

        Берётся самая свежая из начатых и не дочитанных — с учётом чтения на ЛитРес —
        среди скачанных; аудиокниги при запуске сами не открываются.
        """
        if not self.settings.get("openLastBook", True):
            return
        for book in self.library.recent(len(self.library.books), self.settings.get("lastBook")):
            if book.get("is_audio") or book.get("format") in AUDIO_FORMATS:
                continue
            path = self.library.file_path(book)
            if path:
                self.open_book(book, path)
                return

    # --- навигация между экранами (как Adw.NavigationView)

    def push(self, page):
        if self.stack.indexOf(page) < 0:
            self.stack.addWidget(page)
        if page in self.history:
            self.history.remove(page)
        self.history.append(page)
        self.stack.setCurrentWidget(page)
        page.setFocus()

    def go_back(self):
        if len(self.history) <= 1:
            return
        page = self.history.pop()
        self.stack.setCurrentWidget(self.history[-1])
        self._on_page_left(page)

    def pop_to_library(self):
        while len(self.history) > 1:
            self.go_back()

    def current(self):
        return self.history[-1] if self.history else None

    def _on_page_left(self, page):
        if page is self.reader:
            self.reader.close_page()
            self.stack.removeWidget(page)
            page.deleteLater()
            self.reader = None
            self.library.flush()
        elif page is self.settings_page:
            self.stack.removeWidget(page)
            page.deleteLater()
            self.settings_page = None
        elif page is self.graph_page:
            self.stack.removeWidget(page)
            page.deleteLater()
            self.graph_page = None
        elif page is self.login_page:
            pass
        self.refresh_library()

    def toggle_fullscreen(self):
        w = self.window
        w.showNormal() if w.isFullScreen() else w.showFullScreen()

    def toast(self, text, button=None, on_button=None, timeout=4000):
        t = Toast(self.window, text, button, on_button, timeout)
        t.show_in()

    # --- экран библиотеки

    def _build_library_page(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.lib_header = HeaderBar(self.window, tr("Библиотека"), tr("Вход в ЛитРес не выполнен"))
        self.sync_btn = IconButton("view-refresh", tr("Обновить список книг с ЛитРес (F5)"))
        self.sync_btn.clicked.connect(self.litres_lib.sync)
        self.lib_header.pack_start(self.sync_btn)
        self.sync_spinner = Spinner()
        self.sync_spinner.setVisible(False)
        self.lib_header.pack_start(self.sync_spinner)
        self.now_playing_btn = QPushButton()
        cls(self.now_playing_btn, "flat")
        self.now_playing_btn.setToolTip(tr("Вернуться к плееру"))
        self.now_playing_btn.setVisible(False)
        self.now_playing_btn.clicked.connect(self.show_player)
        self.lib_header.pack_start(self.now_playing_btn)

        menu_btn = IconButton("open-menu", tr("Меню"))
        self.menu = QMenu(menu_btn)
        self.menu.addAction(tr("Открыть файл…"), self.on_open_file)
        self.download_all_action = self.menu.addAction(tr("Скачать все книги…"), self.litres_lib.download_all)
        self.only_action = QAction(tr("Только скачанные"), self.menu, checkable=True)
        self.only_action.toggled.connect(self._on_only_downloaded)
        self.menu.addAction(self.only_action)
        self.last_action = QAction(tr("Открывать последнюю текстовую книгу при запуске"), self.menu, checkable=True)
        self.last_action.setChecked(bool(self.settings.get("openLastBook", True)))
        self.last_action.toggled.connect(lambda on: (self.settings.__setitem__("openLastBook", on),
                                                     self.save_settings()))
        self.menu.addSeparator()
        self.account_action = self.menu.addAction(tr("Войти в ЛитРес"), self.litres_lib.toggle_account)
        self.menu.addAction(tr("Настройки… (Ctrl+,)"), self.show_settings)
        self.menu.addAction(tr("Статистика чтения"), self.show_stats_dialog)
        self.menu.addAction(tr("Граф книг (Ctrl+G)"), self.show_graph)
        self.menu.addSeparator()
        self.menu.addAction(tr("О приложении"), self.on_about)
        menu_btn.clicked.connect(lambda: self.menu.popup(menu_btn.mapToGlobal(QPoint(0, menu_btn.height() + 4))))
        self.lib_header.pack_end(menu_btn)
        self.search_btn = IconButton("system-search", tr("Поиск (Ctrl+F)"))
        self.search_btn.setCheckable(True)
        self.search_btn.toggled.connect(self._on_search_toggled)
        self.lib_header.pack_end(self.search_btn)
        lay.addWidget(self.lib_header)

        # Строка поиска (Gtk.SearchBar)
        self.search_bar = QFrame()
        self.search_bar.setObjectName("headerbar")
        sl = QHBoxLayout(self.search_bar)
        sl.setContentsMargins(12, 6, 12, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Название или автор"))
        self.search.setMaximumWidth(480)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        sl.addStretch()
        sl.addWidget(self.search, 10)
        sl.addStretch()
        self.search_bar.setVisible(False)
        lay.addWidget(self.search_bar)

        lay.addWidget(self._build_filter_bar())

        self.content = QStackedWidget()
        self.empty = self._build_empty_page()
        self.content.addWidget(self.empty)
        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("grid")
        self.grid = FlowLayout(self.grid_widget, spacing=12, margin=12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_widget)
        self.content.addWidget(scroll)

        # Справа — «Продолжить чтение»: две последние читаемые книги
        self.recent_panel = RecentPanel(count=2)
        self.recent_panel.activated.connect(self.on_book_activated)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.content, 1)
        body.addWidget(self.recent_panel)
        lay.addLayout(body, 1)
        return page

    def _update_recent_panel(self):
        books = self.library.recent(2, self.settings.get("lastBook"))
        self.recent_panel.update_books(books, self.library)
        # На узком окне (портрет на планшете) панель прячем — книгам нужнее место
        self.recent_panel.setVisible(bool(books) and self.window.width() >= 900)

    def _build_empty_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch()
        icon = label()
        icon.setPixmap(style.icon("accessories-dictionary", "#9a9a9e", 128).pixmap(128, 128))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon)
        v.addSpacing(12)
        v.addWidget(label(tr("Книг пока нет"), "title1", align=Qt.AlignmentFlag.AlignCenter))
        v.addWidget(label(tr("Добавьте папку со своими книгами, подключите ЛитРес\n"
                          "или откройте файл EPUB/FB2."), align=Qt.AlignmentFlag.AlignCenter))
        v.addSpacing(18)
        for text, slot, suggested in ((tr("Войти в ЛитРес"), self.litres_lib.show_login, True),
                                      (tr("Добавить папку с книгами…"), self.add_local_folder, False),
                                      (tr("Открыть файл с компьютера"), self.on_open_file, False)):
            b = QPushButton(text)
            if slot == self.litres_lib.show_login:
                self.empty_login_btn = b
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            cls(b, "pill", *(("suggested",) if suggested else ()))
            b.clicked.connect(slot)
            h = QHBoxLayout()
            h.addStretch()
            h.addWidget(b)
            h.addStretch()
            v.addLayout(h)
            v.addSpacing(6)
        v.addStretch()
        return w

    @staticmethod
    def _compact(combo, chars=11):
        """Ширина списка не растёт от длинных пунктов; раскрытый список — по самому длинному."""
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(chars)

    @staticmethod
    def _fit_popup(combo):
        view = combo.view()
        view.setMinimumWidth(max(combo.width(), view.sizeHintForColumn(0) + 40))

    @staticmethod
    def _captioned(widget, caption):
        """Фильтр с подписью сверху — чтобы было ясно, что выбирается в списке."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        cap = label(caption or " ", "dim", "caption")
        v.addWidget(cap)
        v.addWidget(widget)
        return box

    def _build_filter_bar(self):
        """Статус чтения, папки пользователя, источник и сортировка — каждый с подписью."""
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 4, 12, 6)
        h.setSpacing(12)
        h.addStretch()
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.status_group = QButtonGroup(bar)
        self.status_buttons = {}
        for i, (key, _text) in enumerate(STATUS_FILTERS):
            b = QPushButton()
            b.setCheckable(True)
            b.setChecked(self.settings["libraryStatus"] == key)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            cls(b, "linked-first" if i == 0 else "linked-last" if i == len(STATUS_FILTERS) - 1 else "linked")
            b.toggled.connect(lambda on, k=key: on and self._set_status_filter(k))
            self.status_group.addButton(b)
            self.status_buttons[key] = b
            sl.addWidget(b)
        # статус — без подписи, но вровень с выпадающими списками
        status_box = self._captioned(seg, "")
        h.addWidget(status_box, 0, Qt.AlignmentFlag.AlignBottom)

        self.type_combo = QComboBox()
        self._compact(self.type_combo)
        self.type_combo.setToolTip(tr("Источник"))
        self._type_keys: list[str] = []
        self.type_box = self._captioned(self.type_combo, tr("Источник"))
        h.addWidget(self.type_box)

        # подкаталог: для ЛитРес — папки ЛитРес, для своих книг — папки на диске
        self._folder_ids: list = [None]
        self.folder_combo = QComboBox()
        self._compact(self.folder_combo)
        self.folder_combo.currentIndexChanged.connect(self._on_folder_selected)
        self.folder_box = self._captioned(self.folder_combo, tr("Подкаталог"))
        h.addWidget(self.folder_box)
        self._fill_type_combo()
        self.type_combo.currentIndexChanged.connect(self._on_type_selected)

        self.sort_combo = QComboBox()
        self.sort_combo.setToolTip(tr("Сортировка"))
        self.sort_combo.addItems([text for _k, text in SORT_MODES])
        keys = [k for k, _t in SORT_MODES]
        cur = self.settings.get("librarySort", "recent")
        self.sort_combo.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_selected)
        h.addWidget(self._captioned(self.sort_combo, tr("Сортировка")))
        h.addStretch()
        return bar

    def _build_login_page(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.login_header = HeaderBar(self.window, tr("Вход в ЛитРес"), tr("Пароль вводится на сайте ЛитРес"))
        back = IconButton("go-previous", tr("Назад"))
        back.clicked.connect(self.go_back)
        self.login_header.pack_start(back)
        reload_btn = IconButton("view-refresh", tr("Обновить страницу"))
        reload_btn.clicked.connect(lambda: self.litres.view and self.litres.view.reload())
        self.login_header.pack_end(reload_btn)
        lay.addWidget(self.login_header)
        # браузер ЛитРес создаётся по требованию — страница входа получит его, когда он появится
        self.litres.view_holder.append(lambda view: lay.addWidget(view, 1))
        return page

    # --- фильтры

    def _toggle_search(self):
        self.search_btn.setChecked(not self.search_btn.isChecked())

    def _on_search_toggled(self, on):
        self.search_bar.setVisible(on)
        if on:
            self.search.setFocus()
        else:
            self.search.clear()

    def _set_status_filter(self, key):
        self.settings["libraryStatus"] = key
        self.save_settings()
        self._apply_filter()

    def _fs_mode(self) -> bool:
        """Выбрана своя библиотека — подкаталоги берутся с диска."""
        return self.settings.get("libraryType", "all").startswith("lib:")

    def _on_folder_selected(self, idx):
        if getattr(self, "_filling_folders", False) or idx < 0:
            return
        value = self._folder_ids[idx] if idx < len(self._folder_ids) else None
        self.settings["librarySubdir" if self._fs_mode() else "libraryFolder"] = value
        self._sync_folder_tip()
        self.save_settings()
        self._apply_filter()

    def _fill_folder_combo(self):
        """Список подкаталогов под выбранный источник."""
        if self._fs_mode():
            lib_id = self.settings["libraryType"][len("lib:"):]
            dirs = set()
            for b in self.library.books.values():
                if b.get("library") != lib_id or not b.get("rel"):
                    continue
                parts = b["rel"].split("/")[:-1]
                for i in range(1, len(parts) + 1):          # и родительские папки тоже
                    dirs.add("/".join(parts[:i]))
            dirs = sorted(dirs, key=str.lower)
            ids = [None] + [f"{lib_id}:{d}" for d in dirs]
            texts = [tr("Все подкаталоги")] + dirs
            key, tip, visible = "librarySubdir", tr("Папка на диске"), bool(dirs)
        else:
            folders = self.library.folders
            ids = [None, NO_FOLDER] + list(folders)
            texts = [tr("Все папки"), tr("Без папки")] + [folders[f] for f in folders]
            key, tip, visible = "libraryFolder", tr("Папка на ЛитРес"), bool(folders)
        self._filling_folders = True
        self._folder_ids = ids
        self.folder_combo.clear()
        self.folder_combo.addItems(texts)
        current = self.settings.get(key)
        if current not in ids:
            current = None
            self.settings[key] = None
        self.folder_combo.setCurrentIndex(ids.index(current))
        self._fit_popup(self.folder_combo)
        self._filling_folders = False
        self._folder_tip = tip
        self._sync_folder_tip()
        self.folder_box.setVisible(visible)

    def _sync_folder_tip(self):
        """Подсказка — с полным названием: в узком списке длинное обрезается."""
        self.folder_combo.setToolTip(f"{self._folder_tip}: {self.folder_combo.currentText()}")

    def _on_sort_selected(self, idx):
        self.settings["librarySort"] = SORT_MODES[idx][0]
        self.save_settings()
        self.refresh_library()

    def _sorted(self, books):
        """Порядок книг в сетке по выбранной сортировке."""
        mode = self.settings.get("librarySort", "recent")
        lib = self.library
        if mode == "litres":
            return books
        if mode == "title":
            return sorted(books, key=lambda b: (b.get("title") or "").lower())
        if mode == "author":
            return sorted(books, key=lambda b: (", ".join(b.get("authors") or []).lower() or "я",
                                                (b.get("title") or "").lower()))
        if mode == "series":
            # Книги одной серии рядом и по порядку; без серии — в конце по названию
            return sorted(books, key=lambda b: (
                0 if b.get("series") else 1,
                ((b.get("series") or {}).get("name") or "").lower(),
                (b.get("series") or {}).get("order") or 0,
                (b.get("title") or "").lower()))
        if mode == "progress":
            return sorted(books, key=lambda b: -(lib.percent(b) or 0))
        if mode == "purchased":
            return sorted(books, key=lambda b: b.get("purchased_at") or "", reverse=True)
        # «Недавние»: сначала то, что читали/слушали последним, потом остальное как на ЛитРес
        last = self.settings.get("lastBook")
        return sorted(books, key=lambda b: -(lib.progress.get(b["id"], {}).get("ts")
                                             or (1 if b["id"] == last else 0)))

    def _fill_type_combo(self):
        """«Все» и библиотеки по реестру; у ЛитРес — ещё «Книги» и «Аудиокниги»."""
        options = [("all", tr("Все"))]
        for lib in libraries.all_libraries(self.settings):
            if lib["kind"] == "litres":
                options += [("litres", lib["name"]), ("text", "— " + tr("Книги")), ("audio", "— " + tr("Аудиокниги"))]
            else:
                options.append(("lib:" + lib["id"], lib["name"]))
        self._type_keys = [k for k, _t in options]
        cur = self.settings.get("libraryType", "all")
        if cur not in self._type_keys:
            cur = "all"
            self.settings["libraryType"] = cur
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems([text for _k, text in options])
        self.type_combo.setCurrentIndex(self._type_keys.index(cur))
        self._fit_popup(self.type_combo)
        self.type_combo.blockSignals(False)
        self.type_box.setVisible(len(self._type_keys) > 2)
        self._fill_folder_combo()

    def _on_type_selected(self, idx):
        if 0 <= idx < len(self._type_keys):
            self.settings["libraryType"] = self._type_keys[idx]
            self.save_settings()
            self._fill_folder_combo()
            self._apply_filter()

    def _on_only_downloaded(self, on):
        self.only_downloaded = on
        self._apply_filter()

    def _visible(self, book) -> bool:
        status = self.settings.get("libraryStatus", "all")
        if status != "all" and self.library.status(book) != status:
            return False
        if not self._in_scope(book):
            return False
        q = self.search.text().strip().lower()
        if q:
            hay = " ".join([book.get("title") or ""] + (book.get("authors") or [])).lower()
            return q in hay
        return True

    def _in_scope(self, book) -> bool:
        """Источник, подкаталог и «только скачанные» — то, к чему относятся счётчики статусов."""
        if self.only_downloaded and not self.library.file_path(book):
            return False
        kind = self.settings.get("libraryType", "all")
        source = book.get("source")
        if kind in ("litres", "text", "audio") and source != "litres":
            return False
        if kind in ("text", "audio") and bool(book.get("is_audio")) != (kind == "audio"):
            return False
        if kind.startswith("lib:") and book.get("library") != kind[len("lib:"):]:
            return False
        if self._fs_mode():
            sub = self.settings.get("librarySubdir")
            if sub:
                _lib, _sep, folder = sub.partition(":")
                if not (book.get("rel") or "").startswith(folder + "/"):
                    return False
        else:
            folder = self.settings.get("libraryFolder")
            if folder == NO_FOLDER:
                if book.get("folders"):
                    return False
            elif folder and folder not in (book.get("folders") or []):
                return False
        return True

    def _update_status_counts(self):
        """Счётчики на кнопках статуса — по выбранному источнику и подкаталогу."""
        counts = {"all": 0, "reading": 0, "unread": 0, "finished": 0}
        for b in self.library.ordered():
            if self._in_scope(b):
                counts["all"] += 1
                counts[self.library.status(b)] += 1
        for key, text in STATUS_FILTERS:
            self.status_buttons[key].setText(f"{text} · {counts[key]}")

    def _apply_filter(self):
        self._update_status_counts()
        for bid, card in self.cards.items():
            book = self.library.books.get(bid)
            card.setVisible(bool(book) and self._visible(book))
        self.grid.invalidate()
        self.grid_widget.adjustSize()

    def _update_filter_bar(self):
        self._fill_folder_combo()
        self._update_status_counts()
        self.type_box.setVisible(len(self._type_keys) > 2)

    # --- сетка книг

    CARDS_FIRST = 60          # столько карточек — сразу, остальные — порциями, пока приложение простаивает
    CARDS_BATCH = 40

    def _make_card(self, book):
        card = BookCard(book["id"])
        card.activated.connect(self.on_book_activated)
        card.menu_requested.connect(self.show_book_menu)
        self.cards[book["id"]] = card
        return card

    def _place_card(self, card, book):
        card.setParent(self.grid_widget)
        self.grid.addWidget(card)
        card.update_book(book, self.library)
        if book.get("cover_url") and not self.library.cover_path(book):
            self._queue_cover(book["id"])

    def refresh_library(self):
        ordered = self._sorted(self.library.ordered())
        ids = [b["id"] for b in ordered]
        for bid in list(self.cards):
            if bid not in ids:
                card = self.cards.pop(bid)
                self.grid.removeWidget(card)
                card.deleteLater()
        # Пересобираем порядок: FlowLayout раскладывает в порядке добавления
        while self.grid.count():
            self.grid.takeAt(0)
        created, pending, reorder = 0, [], False
        for book in ordered:
            card = self.cards.get(book["id"])
            if card is None:
                if created >= self.CARDS_FIRST:
                    pending.append(book)            # создадим позже, по порциям
                    continue
                card = self._make_card(book)
                created += 1
            elif pending:
                reorder = True                      # готовая карточка стоит после отложенных
            self._place_card(card, book)
        self._card_queue = pending
        self._card_reorder = reorder
        if pending:
            QTimer.singleShot(0, self._create_more_cards)
        self.content.setCurrentIndex(1 if self.cards or pending else 0)
        self._update_filter_bar()
        self._apply_filter()
        self._update_recent_panel()

    def _create_more_cards(self):
        """Следующая порция отложенных карточек; в конце — порядок, если он нарушился."""
        queue = getattr(self, "_card_queue", [])
        if not queue:
            return
        batch, self._card_queue = queue[:self.CARDS_BATCH], queue[self.CARDS_BATCH:]
        for book in batch:
            if book["id"] in self.cards or book["id"] not in self.library.books:
                continue
            card = self._make_card(book)
            self._place_card(card, book)
            card.setVisible(self._visible(book))
        self.grid.invalidate()
        self.grid_widget.adjustSize()
        if self._card_queue:
            QTimer.singleShot(0, self._create_more_cards)
        elif self._card_reorder:
            self.refresh_library()

    def refresh_card(self, bid):
        card = self.cards.get(bid)
        book = self.library.books.get(bid)
        if card and book:
            card.update_book(book, self.library)
            self._update_filter_bar()
            self._apply_filter()
            self._update_recent_panel()

    def on_book_metadata(self, bid, title, author):
        book = self.library.books.get(bid)
        if book and book.get("source") == "local":
            if title:
                book["title"] = title
            if author:
                book["authors"] = [author]
            self.library.save()
            self.refresh_card(bid)

    def _queue_cover(self, bid):
        if bid not in self._cover_queue:
            self._cover_queue.append(bid)
        self._next_cover()

    def _next_cover(self):
        while self._cover_queue and self._covers_running < 4:
            bid = self._cover_queue.pop(0)
            book = self.library.books.get(bid)
            if not book or not book.get("cover_url"):
                continue
            self._covers_running += 1
            req = QNetworkRequest(QUrl(book["cover_url"]))
            req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            reply = self.net.get(req)

            def done(reply=reply, bid=bid):
                self._covers_running -= 1
                data = bytes(reply.readAll())
                if reply.error() == reply.NetworkError.NoError and data[:4] != b"<!DO" and data:
                    (COVERS_DIR / f"{bid}.jpg").write_bytes(data)
                    self.refresh_card(bid)
                reply.deleteLater()
                self._next_cover()
            reply.finished.connect(done)

    # --- аккаунт

    def has_litres(self) -> bool:
        return any(lib["kind"] == "litres" for lib in libraries.all_libraries(self.settings))

    def connect_litres(self):
        if self.has_litres():
            return
        libraries.set_litres(self.settings, True)
        self.save_settings()
        self.litres.start()
        self.apply_libraries()
        if self.litres.logged_in:
            self.litres_lib.sync()
        else:
            self.litres_lib.show_login()

    def disconnect_litres(self):
        box = QMessageBox(self.window)
        box.setWindowTitle(tr("Отключить ЛитРес?"))
        box.setText(tr("<b>Отключить библиотеку ЛитРес?</b>"))
        box.setInformativeText(tr("Книги ЛитРес пропадут из программы. Скачанные файлы, отметки и вход "
                                  "сохранятся — библиотеку можно подключить снова."))
        cancel = box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
        off = box.addButton(tr("Отключить"), QMessageBox.ButtonRole.DestructiveRole)
        cls(off, "destructive")
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not off:
            return
        libraries.set_litres(self.settings, False)
        self.save_settings()
        self.apply_libraries()

    def apply_libraries(self):
        """Реестр библиотек изменился: что показывать про ЛитРес, фильтры, сетка, настройки."""
        self._apply_litres_ui()
        self.rescan_local()
        if self.settings_page is not None:
            self.settings_page.rebuild_later()

    def _apply_litres_ui(self):
        """ЛитРес отключён — в интерфейсе нет ничего про него (данные и вход сохраняются)."""
        on = self.has_litres()
        self.library.hidden_sources = set() if on else {"litres"}
        self.account_action.setVisible(on)
        self.download_all_action.setVisible(on)
        self.sync_btn.setToolTip(tr("Обновить список книг с ЛитРес (F5)") if on else tr("Обновить список книг (F5)"))
        self.empty_login_btn.setVisible(on)
        self._update_account_ui()

    def _update_account_ui(self):
        if not self.has_litres():
            libs = libraries.all_libraries(self.settings)
            self.lib_header.set_title(tr("Библиотека"), tr("Библиотек: {0} · книг: {1}", len(libs),
                                                           len(self.library.ordered())))
        elif self.litres_lib.bulk:
            b = self.litres_lib.bulk
            self.lib_header.set_title(tr("Библиотека"), tr('Скачиваю книги: {0} из {1}', b['done'] + b['failed'], b['total']))
        elif self.litres.logged_in:
            self.account_action.setText(tr("Выйти из ЛитРес"))
            self.lib_header.set_title(tr("Библиотека"), tr('ЛитРес: {0}', self.litres.user_name)
                                      if self.litres.user_name else tr("ЛитРес: вход выполнен"))
        else:
            self.account_action.setText(tr("Войти в ЛитРес"))
            self.lib_header.set_title(tr("Библиотека"), tr("Вход в ЛитРес не выполнен"))

    # --- синхронизация

    def _set_syncing(self, on):
        self.litres_lib.syncing = on
        self.sync_btn.setVisible(not on)
        self.sync_spinner.setVisible(on)

    def set_finished(self, book, finished: bool, auto=False):
        """Отметка «прочитано»: локально и на ЛитРес (сразу или при следующей синхронизации)."""
        book["finished"] = finished
        self.singularity.schedule(soon=True)
        if book.get("source") == "litres":
            book["finished_pending"] = finished
        self.library.save()
        self.refresh_card(book["id"])
        if finished:
            self.library.mark_finished_stat(book["id"])
        if auto:
            self._toast_finished(book, tr("Книга дочитана — отмечена прочитанной"))
        if book.get("source") != "litres" or not self.litres.logged_in:
            return

        def done(ok):
            if ok:
                book.pop("finished_pending", None)
                self.library.save()
            else:
                self.toast(tr("Не удалось обновить отметку на ЛитРес — повторю при синхронизации"))
        self.litres.set_finished(book["id"], finished, done)

    def _toast_finished(self, book, text):
        """Уведомление о дочитанной книге; если есть следующая в серии — кнопка «Дальше»."""
        nxt = self.library.next_in_series(book)
        if nxt:
            self.toast(tr('{0}. Следующая в серии: «{1}»', text, nxt.get('title')), button=tr("Открыть"),
                       on_button=lambda: self.on_book_activated(nxt["id"]), timeout=10000)
        else:
            self.toast(text)

    # --- книги

    def on_book_activated(self, bid):
        book = self.library.books.get(bid)
        if not book:
            return
        path = self.library.file_path(book)
        if path:
            self.open_book(book, path)
        elif book.get("source") == "litres":
            self.litres_lib.download_book(book, open_after=True)

    def open_book(self, book, path: Path):
        fmt = book.get("format") or ""
        if fmt in AUDIO_FORMATS or fmt in READABLE:
            self.settings["lastBook"] = book["id"]
            self.save_settings()
        if fmt in AUDIO_FORMATS:
            self.open_player(book, path)
            return
        if fmt not in READABLE:
            # PDF и прочее — в приложении по умолчанию
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        self.pop_to_library()
        self.reader = ReaderPage(self, book, path)
        self.push(self.reader)

    # --- скачивание всех книг разом

    def show_book_menu(self, bid, pos):
        book = self.library.books.get(bid)
        if not book:
            return
        menu = QMenu(self.window)
        downloaded = self.library.file_path(book) is not None
        if downloaded:
            menu.addAction(tr("Слушать") if book.get("is_audio") else tr("Читать"),
                           lambda: self.on_book_activated(bid))
        if book.get("finished"):
            menu.addAction(tr("Снять отметку «Прочитано»"), lambda: self.set_finished(book, False))
        else:
            menu.addAction(tr("Отметить прочитанной"), lambda: self.set_finished(book, True))
        if book.get("source") == "litres":
            menu.addAction(tr("Папки…"), lambda: self.litres_lib.show_folders_dialog(book))
            menu.addAction(tr("Скачать заново") if downloaded else tr("Скачать"), lambda: self.litres_lib.download_book(book))
            if book.get("url"):
                menu.addAction(tr("Открыть на сайте ЛитРес"), lambda: QDesktopServices.openUrl(QUrl(book["url"])))
        nxt = self.library.next_in_series(book)
        if nxt:
            menu.addAction(tr('Следующая в серии: {0}', nxt.get('title')), lambda: self.on_book_activated(nxt["id"]))
        if book.get("source") == "folder":
            # своя книга: файл остаётся на месте, удалять его из читалки не даём
            menu.addAction(tr("Показать файл в папке"), lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(book["path"]).parent))))
        elif downloaded or book.get("source") == "local":
            menu.addSeparator()
            menu.addAction(tr("Удалить с устройства"), lambda: self.remove_book_file(bid))
        menu.popup(pos)

    def remove_book_file(self, bid):
        if self.player.book_id == bid:
            # Удаляем то, что сейчас звучит — сначала останавливаем плеер
            if self.player_page:
                if self.player_page in self.history:
                    self.pop_to_library()
                self.player_page.close_page()
                self.stack.removeWidget(self.player_page)
                self.player_page.deleteLater()
                self.player_page = None
            self.player.unload()
            self.now_playing_btn.setVisible(False)
        self.library.remove_file(bid)
        self.refresh_library()

    # --- папки

    # --- аудиокниги

    def open_player(self, book, path: Path, autoplay=True):
        self.settings["lastBook"] = book["id"]
        self.save_settings()
        if self.player.book_id != book["id"]:
            tracks = audio_tracks(path)
            if not tracks:
                self.toast(tr("В аудиокниге не найдено звуковых файлов"))
                return
            self.save_audio_progress()
            saved = self.library.progress.get(book["id"], {})
            if (saved.get("fraction") or 0) >= 0.999:
                saved = {}   # прослушанную книгу начинаем сначала
            self.player.rate = self.settings.get("audioRate", 1.0)
            self.player.load(book["id"], tracks, saved.get("track", 0), saved.get("pos", 0.0), play=autoplay)
            if self.player_page:
                self.player_page.close_page()
                self.stack.removeWidget(self.player_page)
                self.player_page.deleteLater()
            self.player_page = PlayerPage(self, book)
            QTimer.singleShot(1500, lambda: self.litres_lib.apply_remote_position(book))
        elif not self.player.playing and autoplay:
            self.player.play()
        self.show_player()

    def show_player(self):
        if not self.player_page:
            return
        if self.current() is not self.player_page:
            self.pop_to_library()
            self.push(self.player_page)

    def save_audio_progress(self):
        bid = self.player.book_id
        if not bid or not self.player.tracks:
            return
        ch = self.player.chapters[self.player.current_chapter()]["title"] if self.player.chapters else ""
        self.library.set_audio_progress(bid, self.player.index, self.player.position(),
                                        self.player.fraction(), ch)
        if bid in self.cards and not self.player.playing:
            self.refresh_card(bid)

    def _on_player_state(self):
        book = self.library.books.get(self.player.book_id or "")
        if not book:
            return
        name = "media-playback-start" if self.player.playing else "media-playback-pause"
        self.now_playing_btn.setIcon(style.icon(name))
        title = book.get("title") or ""
        self.now_playing_btn.setText(" " + self.now_playing_btn.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, 200))
        self.now_playing_btn.setVisible(True)
        self.save_audio_progress()

    def _on_audio_finished(self):
        book = self.library.books.get(self.player.book_id or "")
        if not book:
            return
        self.library.set_audio_progress(book["id"], len(self.player.tracks) - 1, 0.0, 1.0)
        if not book.get("finished"):
            self.set_finished(book, True)
            self._toast_finished(book, tr("Аудиокнига прослушана — отмечена прочитанной"))

    # --- открытие своих файлов

    def import_and_open(self, path: Path):
        try:
            bid = self.library.add_local(path)
        except OSError as e:
            self.toast(tr('Не удалось открыть файл: {0}', e.strerror))
            return
        self.refresh_library()
        book = self.library.books[bid]
        self.open_book(book, self.library.file_path(book))

    def choose_books_dir(self):
        """Выбор папки для скачанных книг; уже скачанные переносятся туда же."""
        current = books_dir()
        path = QFileDialog.getExistingDirectory(self.window, tr('Папка для книг (сейчас: {0})', current), str(current))
        if not path:
            return
        new_dir = Path(path)
        if new_dir.resolve() == current.resolve():
            return
        moved, errors = self.library.move_files(new_dir)
        self.library.save()
        self.settings["booksDir"] = str(new_dir)
        self.save_settings()
        self.refresh_library()
        if errors:
            self.toast(tr('Книги теперь в {0}. Перенесено: {1}, не удалось: {2} — ', new_dir, moved, len(errors))
                       + errors[0], timeout=10000)
        else:
            self.toast(tr('Книги теперь в {0}', new_dir) + (tr(' — перенесено файлов: {0}', moved) if moved else ""))

    # --- граф книг

    def show_graph(self):
        """Граф библиотеки, выбранной в фильтре «Источник» (или всех)."""
        kind = self.settings.get("libraryType", "all")
        scope = ("litres" if kind in ("litres", "text", "audio") else
                 kind[len("lib:"):] if kind.startswith("lib:") else "all")
        if self.graph_page is None:
            self.graph_page = GraphPage(self)
        self.graph_page.fill_scopes(scope)
        self.push(self.graph_page)
        if self.has_litres():
            self.litres_lib._fetch_details()

    # --- свои книги и статьи

    def local_folders(self) -> list[dict]:
        """Свои библиотеки: [{"id", "path", "name"}] — корневые папки из реестра библиотек."""
        return libraries.folder_libraries(self.settings)

    def rescan_local(self, report=False):
        n = self.library.scan_folders(self.local_folders())
        self._fill_type_combo()
        self.refresh_library()
        QTimer.singleShot(500, self._make_pdf_covers)
        if report:
            self.toast(tr('Своих книг и статей: {0}', n))

    def _set_type_filter(self, key):
        if key in self._type_keys:
            self.type_combo.setCurrentIndex(self._type_keys.index(key))

    def _ask_section(self, path, current=""):
        """Название раздела для папки; None — отменили."""
        name, ok = QInputDialog.getText(self.window, tr("Раздел"),
                                        tr("Название раздела для папки\n{0}", path),
                                        text=current or Path(path).name.capitalize())
        name = name.strip()
        return name if ok and name else None

    def _save_local_folders(self, folders):
        libraries.set_folder_libraries(self.settings, folders)
        self.save_settings()
        self.rescan_local(report=True)

    def add_local_folder(self):
        folders = self.local_folders()
        start = folders[0]["path"] if folders else str(Path.home())
        path = QFileDialog.getExistingDirectory(self.window, tr("Папка со своими книгами и статьями"), start)
        if not path:
            return
        if any(Path(f["path"]) == Path(path) for f in folders):
            self.toast(tr("Эта папка уже добавлена"))
            return
        name = self._ask_section(path)
        if name:
            self._save_local_folders(folders + [{"path": path, "name": name}])

    def rename_local_folder(self, path):
        folders = self.local_folders()
        current = next((f["name"] for f in folders if f["path"] == path), "")
        name = self._ask_section(path, current)
        if name and name != current:
            self._save_local_folders([{**f, "name": name} if f["path"] == path else f for f in folders])

    def remove_local_folder(self, path):
        self._save_local_folders([f for f in self.local_folders() if f["path"] != path])

    def _make_pdf_covers(self):
        """Обложки своих PDF — первая страница; по одной за раз, чтобы не подвешивать окно."""
        todo = [b for b in self.library.ordered()
                if b.get("source") == "folder" and b.get("format") == "pdf"
                and not (COVERS_DIR / f"{b['id']}.jpg").exists()]
        if not todo:
            return
        book = todo[0]
        target = COVERS_DIR / f"{book['id']}.jpg"
        try:
            from PySide6.QtGui import QColor, QImage, QPainter
            from PySide6.QtPdf import QPdfDocument
            doc = QPdfDocument()
            doc.load(book["path"])
            if doc.status() == QPdfDocument.Status.Ready and doc.pageCount() > 0:
                pt = doc.pagePointSize(0)
                h = 360
                w = max(1, int(h * pt.width() / pt.height())) if pt.height() > 0 else 255
                page = doc.render(0, QSize(w, h))
                img = QImage(page.size(), QImage.Format.Format_RGB32)
                img.fill(QColor("white"))            # у PDF прозрачный фон
                p = QPainter(img)
                p.drawImage(0, 0, page)
                p.end()
                img.save(str(target), "JPG", 85)
            doc.close()
        except Exception as e:
            log("обложка PDF:", book["path"], e)
        if not target.exists():
            target.touch()                           # пустой файл: больше не пытаться
        self.refresh_card(book["id"])
        QTimer.singleShot(30, self._make_pdf_covers)

    def on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window, tr("Открыть книгу"), str(Path.home()),
                                              tr('Электронные книги ({0})', EBOOK_PATTERNS))
        if path:
            self.import_and_open(Path(path))

    # --- Singularity

    def note_activity(self):
        """Читатель листает книгу — для учёта времени чтения и отправки прогресса."""
        self._last_activity = time.monotonic()
        self.singularity.schedule()

    def _count_reading_time(self):
        reading = (self.reader is not None and self.current() is self.reader
                   and self.window.isActiveWindow() and time.monotonic() - self._last_activity < 180)
        tts = self.reader is not None and getattr(self.reader, "tts_active", False)
        if reading or tts or self.player.playing:
            bid = self.reader.book["id"] if (reading or tts) else self.player.book_id
            self.library.add_reading_time(bid, 30)
            self.singularity.add_reading_time(30)
            if self.player.playing:
                self.singularity.schedule()

    def show_stats_dialog(self):
        from .stats import show_stats
        show_stats(self)

    def show_singularity_dialog(self):
        s = self.singularity
        dlg = QDialog(self.window, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dlg.setMinimumWidth(460)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        header = HeaderBar(dlg, "Singularity", show_controls=False)
        close = IconButton("window-close", tr("Закрыть"), flat=False)
        cls(close, "wincontrol")
        close.clicked.connect(dlg.accept)
        header.pack_end(close)
        v.addWidget(header)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 18, 18, 18)
        b.setSpacing(8)
        intro = label(tr("Книги, прогресс и ежедневное чтение — в планировщике SingularityApp.<br>"
                      "Токен создаётся в <a href='https://me.singularity-app.com'>личном кабинете</a> → "
                      "«Доступ к API» (нужен доступ к задачам, проектам и привычкам)."), wrap=True, rich=True)
        intro.setOpenExternalLinks(True)
        b.addWidget(intro)
        token = QLineEdit(s.state.get("token", ""))
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setPlaceholderText(tr("API-токен Singularity"))
        b.addWidget(token)
        b.addSpacing(6)

        boxed = QFrame()
        cls(boxed, "boxed")
        rows = QVBoxLayout(boxed)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        switches = {}
        for key, title, hint in (
                ("reading", tr("Задачи «Читаю»"), tr("Начатые книги — задачи в проекте «Книги», дочитанные закрываются")),
                ("progress", tr("Прогресс в задаче"), tr("Процент и текущая глава в заметке задачи")),
                ("wishlist", tr("«Хочу прочитать»"), tr("Непрочитанные книги — задачи в отдельном проекте")),
                ("daily", tr("Ежедневное чтение"), tr("Привычка отмечается сама, когда за день набралось N минут"))):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 8, 14, 8)
            texts = QVBoxLayout()
            texts.setSpacing(0)
            texts.addWidget(label(title))
            texts.addWidget(label(hint, "dim", "caption", wrap=True))
            h.addLayout(texts, 1)
            sw = Switch(bool(s.state.get(key)))
            h.addWidget(sw)
            rows.addWidget(row)
            switches[key] = sw
        b.addWidget(boxed)

        # книги каких библиотек ведутся задачами («Хочу прочитать» — только ЛитРес)
        libs = libraries.all_libraries(self.settings)
        allowed = s.state.get("libraries")
        lib_switches = {}
        if len(libs) > 1:
            b.addWidget(label(tr("Библиотеки"), "heading"))
            lib_box = QFrame()
            cls(lib_box, "boxed")
            lrows = QVBoxLayout(lib_box)
            lrows.setContentsMargins(0, 0, 0, 0)
            lrows.setSpacing(0)
            for lib in libs:
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(14, 6, 14, 6)
                h.addWidget(label(lib["name"]), 1)
                sw = Switch(allowed is None or lib["id"] in allowed)
                h.addWidget(sw)
                lrows.addWidget(row)
                lib_switches[lib["id"]] = sw
            b.addWidget(lib_box)

        goal_row = QHBoxLayout()
        goal_row.addWidget(label(tr("Цель чтения в день, минут")), 1)
        goal = QSpinBox()
        goal.setRange(5, 240)
        goal.setSingleStep(5)
        goal.setValue(int(s.state.get("dailyMinutes") or 20))
        goal_row.addWidget(goal)
        b.addLayout(goal_row)
        b.addWidget(label(tr('Сегодня прочитано и прослушано: {0} мин', s.today_minutes()), "dim", "caption"))

        status = label("", "dim", wrap=True)
        b.addWidget(status)
        s.status.connect(status.setText)
        buttons = QHBoxLayout()
        disconnect = QPushButton(tr("Отключить"))
        run = QPushButton(tr("Проверить и синхронизировать"))
        cls(run, "suggested")
        buttons.addWidget(disconnect)
        buttons.addStretch()
        buttons.addWidget(run)
        b.addSpacing(6)
        b.addLayout(buttons)
        v.addWidget(body)

        def apply():
            chosen = [lid for lid, sw in lib_switches.items() if sw.isChecked()]
            s.configure(token=token.text().strip(), dailyMinutes=goal.value(),
                        libraries=None if len(chosen) == len(lib_switches) else chosen,
                        **{k: sw.isChecked() for k, sw in switches.items()})

        def check_and_sync():
            apply()
            if not s.enabled:
                status.setText(tr("Вставьте токен"))
                return
            status.setText(tr("Проверяю токен…"))
            run.setEnabled(False)

            def checked(ok, text):
                run.setEnabled(True)
                status.setText(text + (tr("; синхронизирую…") if ok else ""))
                if ok:
                    s.sync()
            s.check_token(checked)

        def off():
            s.configure(token="")
            token.clear()
            status.setText(tr("Синхронизация с Singularity отключена"))
        run.clicked.connect(check_and_sync)
        disconnect.clicked.connect(off)

        frame = QFrame(dlg)
        frame.setObjectName("popover")
        frame.lower()
        dlg.resizeEvent = lambda e: frame.setGeometry(dlg.rect())
        dlg.exec()
        apply()
        s.status.disconnect(status.setText)

    # --- прочее

    # --- ЛитРес: подключаемая библиотека (litres_connector.py); делегаты для других модулей

    def sync(self, *args, **kwargs):
        if not self.has_litres():
            return self.rescan_local(report=not kwargs.get("quiet"))
        return self.litres_lib.sync(*args, **kwargs)

    def download_book(self, *args, **kwargs):
        return self.litres_lib.download_book(*args, **kwargs)

    def show_login(self, *args, **kwargs):
        return self.litres_lib.show_login(*args, **kwargs)

    def apply_remote_position(self, *args, **kwargs):
        return self.litres_lib.apply_remote_position(*args, **kwargs)

    def apply_remote_sync(self, *args, **kwargs):
        return self.litres_lib.apply_remote_sync(*args, **kwargs)

    def download_all(self, *args, **kwargs):
        return self.litres_lib.download_all(*args, **kwargs)

    def toggle_account(self, *args, **kwargs):
        return self.litres_lib.toggle_account(*args, **kwargs)

    def save_settings(self):
        if self.reader:
            self.reader.apply_settings()
        self._settings_timer.start()

    # --- внешний вид: тема, акцент, значок, горячие клавиши

    def shortcut_keys(self, action) -> list[str]:
        custom = (self.settings.get("shortcuts") or {}).get(action)
        if custom is not None:
            return [k for k in custom if k]
        return next(keys for a, _t, keys, _s in SHORTCUTS if a == action)

    def apply_shortcuts(self):
        for action, sc in self.shortcuts.items():
            sc.setKeys([QKeySequence(k) for k in self.shortcut_keys(action)])

    def apply_appearance(self):
        """Тема и цвет акцента из настроек (или системные) — сразу, без перезапуска."""
        style.set_overrides(self.settings.get("uiTheme"), self.settings.get("accent"))
        style.read_portal_scheme()
        self._on_theme_changed()

    def apply_app_icon(self, name):
        """Значок окна и — если приложение установлено — ярлыка в меню (тема значков пользователя)."""
        path = core.app_icon_path(name)
        icon = QIcon(str(path))
        self.qapp.setWindowIcon(icon)
        if getattr(self, "window", None) is not None:
            self.window.setWindowIcon(icon)
        if sys.platform.startswith("linux"):
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
            if not (base / "applications" / f"{APP_ID}.desktop").exists():
                return                      # не установлено (запуск из исходников) — ярлыка нет
            target = base / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
            try:
                data = path.read_bytes()
                if not target.exists() or target.read_bytes() != data:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    subprocess.Popen(["gtk-update-icon-cache", "-q", "-f", "-t", str(base / "icons" / "hicolor")],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                log("значок ярлыка не обновлён:", e)

    def _poll_theme(self):
        style.read_portal_scheme()
        style.read_accent()
        if (style.is_dark(), style.ACCENT) != self._scheme:
            self._on_theme_changed()

    def _on_theme_changed(self, *_):
        self._scheme = (style.is_dark(), style.ACCENT)
        style.apply_palette(self.qapp)
        for w in self.window.findChildren(HeaderBar):
            w.refresh_icons()
        for card in self.cards.values():
            card.refresh_icons()
            card.cover.update()
        self.sync_btn.refresh_icon()
        if self.reader:
            self.reader.refresh_style()
        if self.player_page:
            self.player_page.refresh_style()
        self._on_player_state()

    def on_about(self):
        box = QMessageBox(self.window)
        box.setWindowTitle(tr("О приложении"))
        box.setIconPixmap(QIcon(str(core.app_icon_path(self.settings.get("appIcon")))).pixmap(96, 96))
        box.setText(tr('<h3>{0}</h3><p>Версия {1}</p>', APP_NAME, __version__))
        libs = libraries.all_libraries(self.settings)
        box.setInformativeText(
            tr("Своя библиотека книг и статей: создавайте, читайте, организуйте и обслуживайте её. "
               "Библиотеки — папки на диске; у каждой свой граф и свои резервные копии, а все вместе "
               "они просматриваются как одна большая.<br><br>"
               "ЛитРес — подключаемая библиотека купленных книг и аудиокниг; вход выполняется на сайте "
               "ЛитРес, приложение не хранит пароль.")
            + "<br><br>" + tr("Библиотек: {0} · книг: {1}", len(libs), len(self.library.ordered()))
            + "<br><br>" + tr("Лицензия MIT. Движок чтения — foliate-js (MIT), PDF — pdf.js (Apache 2.0), "
                              "граф — d3-force (ISC), значки — Adwaita.")
            + "<br>" + tr("Документация и исходный код: {0}", "github.com/arvino-t/muninhall"))
        site = box.addButton(tr("Открыть на GitHub"), QMessageBox.ButtonRole.ActionRole)
        site.clicked.disconnect()          # кнопка не закрывает окно
        site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/arvino-t/muninhall")))
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()

    # --- резервные копии

    def make_backup(self, reason="", scope="all") -> Path | None:
        """Копия всех библиотек (scope="all") или одной: "litres" / id своей."""
        self.library.save()
        self.library.flush()
        try:
            path = backup.create(self.settings, reason, scope)
        except (OSError, ValueError) as e:
            print(f"muninhall: резервная копия не создана: {e}", file=sys.stderr, flush=True)
            return None
        if scope == "all":
            self.settings["backupLast"] = datetime.now().isoformat(timespec="seconds")
            self.save_settings()
        log("backup", path)
        return path

    def auto_backup(self):
        if backup.due(self.settings):
            self.make_backup()

    def restart(self):
        """Перезапуск приложения (после восстановления из копии)."""
        QProcess.startDetached(sys.executable, ["-m", "muninhall", "--restarted"])
        self.window.close()
        self.qapp.quit()

    def on_close(self):
        self.save_audio_progress()
        self.player.unload()
        self.library.flush()
        save_json(CONFIG_FILE, self.settings)
        if self.reader:
            self.reader.close_page()
        self.litres.shutdown()


# ─────────────────────────────────────────────────────────────── запуск

def _server_name(app_id=APP_ID):
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return f"{app_id}-{user}"


def _old_version_running() -> bool:
    """Открыта прежняя версия — данные переносить нельзя, она пишет в старые каталоги."""
    for app_id in OLD_APP_IDS:
        sock = QLocalSocket()
        sock.connectToServer(_server_name(app_id))
        running = sock.waitForConnected(300)
        sock.abort()
        if running:
            return True
    return False


def main(argv=None):
    argv = sys.argv if argv is None else argv
    files = [Path(a).resolve() for a in argv[1:] if not a.startswith("-") and Path(a).exists()]

    if "--restarted" in argv:
        # Перезапуск: ждём, пока прежний экземпляр закроется (до 15 с)
        for _ in range(50):
            probe = QLocalSocket()
            probe.connectToServer(_server_name())
            if not probe.waitForConnected(100):
                break
            probe.abort()
            time.sleep(0.3)

    # Уже запущено — передаём файлы открытому окну и выходим
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if sock.waitForConnected(300):
        sock.write(("\n".join(map(str, files)) or "\n").encode())
        sock.flush()
        sock.waitForBytesWritten(1000)
        return 0

    from .reader import register_scheme
    register_scheme()
    QApplication.setApplicationName(APP_SLUG)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    qapp = QApplication(argv)
    qapp.setStyle("Fusion")
    qapp.setFont(style.app_font())
    qapp.setWindowIcon(QIcon(str(APP_ICON)))

    # Переименование «Читалка ЛитРес» → Muninhall: данные переезжают в новые каталоги (один раз)
    if core.migration_needed() and _old_version_running():
        QMessageBox.information(None, APP_NAME, tr("Закройте прежнюю версию приложения («Читалка ЛитРес» или Shelfwise) "
                                                   "и запустите Muninhall снова: её данные перенесутся."))
        return 0
    moved = core.migrate_old_dirs()
    backup.migrate_default_dir()
    if moved:
        log("данные прежней версии перенесены:", moved)
    restored = backup.apply_pending()     # восстановление из копии — до чтения данных
    app = App(qapp)
    app.window.show()
    if restored:
        QTimer.singleShot(800, lambda: app.toast(tr("Данные восстановлены из резервной копии"), timeout=6000))

    server = QLocalServer()
    QLocalServer.removeServer(_server_name())
    server.listen(_server_name())

    def on_connection():
        conn = server.nextPendingConnection()

        def read():
            for line in bytes(conn.readAll()).decode().splitlines():
                if line.strip():
                    app.import_and_open(Path(line.strip()))
            app.window.showNormal() if app.window.isMinimized() else None
            app.window.raise_()
            app.window.activateWindow()
        conn.readyRead.connect(read)
    server.newConnection.connect(on_connection)

    for f in files:
        QTimer.singleShot(0, lambda f=f: app.import_and_open(f))
    return qapp.exec()
