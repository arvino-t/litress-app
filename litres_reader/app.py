"""Главное окно и логика приложения: библиотека, вход в ЛитРес, синхронизация, скачивание."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, style
from .core import (APP_ICON, APP_ID, APP_NAME, AUDIO_FILE_TYPES, AUDIO_FORMATS, CONFIG_FILE,
                   COVERS_DIR, DEFAULT_SETTINGS, FORMAT_ORDER, LOCAL_SUFFIX, LOGIN_URL, NO_FOLDER,
                   READABLE, SITE, SORT_MODES, STATUS_FILTERS, TYPE_FILTERS, Library, books_dir,
                   load_json, log, looks_like_book, save_json, set_books_dir)
from .litres import LitresSession
from .player import AudioPlayer, PlayerPage, audio_tracks
from .reader import ReaderPage
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


class _Bridge(QObject):
    """Передаёт результат из рабочего потока в главный."""
    done = Signal(object, object)


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


class App(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = {**DEFAULT_SETTINGS, **load_json(CONFIG_FILE, {})}
        try:
            set_books_dir(self.settings.get("booksDir"))
        except OSError:
            # выбранная папка недоступна (например, отключён диск) — берём папку по умолчанию
            set_books_dir(None)
        self.library = Library()
        self._settings_timer = QTimer(self, singleShot=True, interval=500)
        self._settings_timer.timeout.connect(lambda: save_json(CONFIG_FILE, self.settings))
        self.cards: dict[str, BookCard] = {}
        self.downloading: set[str] = set()
        self.syncing = False
        self.only_downloaded = False
        self.reader: ReaderPage | None = None
        self.player_page: PlayerPage | None = None
        self.net = QNetworkAccessManager(self)
        self._covers_running = 0
        self._cover_queue: list[str] = []

        style.read_portal_scheme()
        style.read_accent()
        style.apply_palette(qapp)
        qapp.styleHints().colorSchemeChanged.connect(self._on_theme_changed)
        # Портал не шлёт сигнал в Qt — проверяем смену темы и акцента раз в 2 секунды
        self._scheme = (style.is_dark(), style.ACCENT)
        self._theme_timer = QTimer(self, interval=2000)
        self._theme_timer.timeout.connect(self._poll_theme)
        self._theme_timer.start()

        self.player = AudioPlayer(self)
        self.player.finished.connect(self._on_audio_finished)
        self.player.error.connect(lambda msg: self.toast(f"Ошибка воспроизведения: {msg}"))
        self.player.state_changed.connect(self._on_player_state)
        # Место прослушивания сохраняем раз в 5 секунд
        self._audio_timer = QTimer(self, interval=5000)
        self._audio_timer.timeout.connect(self.save_audio_progress)
        self._audio_timer.start()

        self.litres = LitresSession(self)
        self.litres.state_changed.connect(self.on_login_state)

        # Singularity: задачи книг, прогресс, «Хочу прочитать», привычка «Чтение N минут»
        self.singularity = SingularitySync(self)
        self._last_activity = 0.0
        self._activity_timer = QTimer(self, interval=30_000)
        self._activity_timer.timeout.connect(self._count_reading_time)
        self._activity_timer.start()
        QTimer.singleShot(10_000, self.singularity.sync)

        self.window = MainWindow(self)
        self.window.setWindowIcon(QIcon(str(APP_ICON)))
        self.stack = QStackedWidget()
        self.window.setCentralWidget(self.stack)
        self.history: list[QWidget] = []

        self.library_page = self._build_library_page()
        self.login_page = self._build_login_page()
        self.push(self.library_page)

        for keys, slot in (("F11", self.toggle_fullscreen), ("F5", self.sync), ("Ctrl+R", self.sync),
                           ("Ctrl+O", self.on_open_file), ("Ctrl+F", self._toggle_search),
                           ("Alt+Left", self.go_back)):
            QShortcut(QKeySequence(keys), self.window, activated=slot)

        self.library.scan_folders(self.local_folders())
        self.refresh_library()
        QTimer.singleShot(0, self._open_last_book)
        QTimer.singleShot(1500, self._make_pdf_covers)

    def _open_last_book(self):
        """Автопереход: открыть последнюю книгу на месте, где остановились (аудио — на паузе)."""
        if not self.settings.get("openLastBook", True):
            return
        book = self.library.books.get(self.settings.get("lastBook") or "")
        path = self.library.file_path(book) if book else None
        if not path:
            return
        if (self.library.progress.get(book["id"], {}).get("fraction") or 0) >= 0.999:
            return   # дочитанную книгу сами не открываем
        if book.get("format") in AUDIO_FORMATS:
            self.open_player(book, path)
        else:
            self.open_book(book, path)

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

        self.lib_header = HeaderBar(self.window, "Библиотека", "Вход в ЛитРес не выполнен")
        self.sync_btn = IconButton("view-refresh", "Обновить список книг с ЛитРес (F5)")
        self.sync_btn.clicked.connect(self.sync)
        self.lib_header.pack_start(self.sync_btn)
        self.sync_spinner = Spinner()
        self.sync_spinner.setVisible(False)
        self.lib_header.pack_start(self.sync_spinner)
        self.now_playing_btn = QPushButton()
        cls(self.now_playing_btn, "flat")
        self.now_playing_btn.setToolTip("Вернуться к плееру")
        self.now_playing_btn.setVisible(False)
        self.now_playing_btn.clicked.connect(self.show_player)
        self.lib_header.pack_start(self.now_playing_btn)

        menu_btn = IconButton("open-menu", "Меню")
        self.menu = QMenu(menu_btn)
        self.menu.addAction("Открыть файл…", self.on_open_file)
        self.only_action = QAction("Только скачанные", self.menu, checkable=True)
        self.only_action.toggled.connect(self._on_only_downloaded)
        self.menu.addAction(self.only_action)
        self.last_action = QAction("Открывать последнюю книгу при запуске", self.menu, checkable=True)
        self.last_action.setChecked(bool(self.settings.get("openLastBook", True)))
        self.last_action.toggled.connect(lambda on: (self.settings.__setitem__("openLastBook", on),
                                                     self.save_settings()))
        self.menu.addAction(self.last_action)
        self.menu.addAction("Папка для книг…", self.choose_books_dir)
        self.mine_menu = self.menu.addMenu("Мои книги и статьи")
        self.mine_menu.aboutToShow.connect(self._fill_mine_menu)
        self.menu.addSeparator()
        self.account_action = self.menu.addAction("Войти в ЛитРес", self._account_action)
        self.menu.addAction("Singularity…", self.show_singularity_dialog)
        self.menu.addAction("Статистика чтения", self.show_stats_dialog)
        self.menu.addSeparator()
        self.menu.addAction("О приложении", self.on_about)
        menu_btn.clicked.connect(lambda: self.menu.popup(menu_btn.mapToGlobal(QPoint(0, menu_btn.height() + 4))))
        self.lib_header.pack_end(menu_btn)
        self.search_btn = IconButton("system-search", "Поиск (Ctrl+F)")
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
        self.search.setPlaceholderText("Название или автор")
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
        v.addWidget(label("Книг пока нет", "title1", align=Qt.AlignmentFlag.AlignCenter))
        v.addWidget(label("Войдите в аккаунт ЛитРес, чтобы увидеть купленные книги,\n"
                          "или откройте файл EPUB/FB2.", align=Qt.AlignmentFlag.AlignCenter))
        v.addSpacing(18)
        for text, slot, suggested in (("Войти в ЛитРес", self.show_login, True),
                                      ("Открыть файл с компьютера", self.on_open_file, False)):
            b = QPushButton(text)
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

    def _build_filter_bar(self):
        """Статус чтения, папки пользователя и тип книг."""
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
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
        h.addWidget(seg)

        self._folder_ids: list = [None]
        self.folder_combo = QComboBox()
        self.folder_combo.setToolTip("Папка на ЛитРес")
        self.folder_combo.currentIndexChanged.connect(self._on_folder_selected)
        h.addWidget(self.folder_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItems([text for _k, text in TYPE_FILTERS])
        keys = [k for k, _t in TYPE_FILTERS]
        cur = self.settings.get("libraryType", "all")
        self.type_combo.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        self.type_combo.currentIndexChanged.connect(self._on_type_selected)
        h.addWidget(self.type_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.setToolTip("Сортировка")
        self.sort_combo.addItems([text for _k, text in SORT_MODES])
        keys = [k for k, _t in SORT_MODES]
        cur = self.settings.get("librarySort", "recent")
        self.sort_combo.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_selected)
        h.addWidget(self.sort_combo)
        h.addStretch()
        return bar

    def _build_login_page(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.login_header = HeaderBar(self.window, "Вход в ЛитРес", "Пароль вводится на сайте ЛитРес")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(self.go_back)
        self.login_header.pack_start(back)
        reload_btn = IconButton("view-refresh", "Обновить страницу")
        reload_btn.clicked.connect(lambda: self.litres.view.reload())
        self.login_header.pack_end(reload_btn)
        lay.addWidget(self.login_header)
        lay.addWidget(self.litres.view, 1)
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

    def _on_folder_selected(self, idx):
        if getattr(self, "_filling_folders", False) or idx < 0:
            return
        self.settings["libraryFolder"] = self._folder_ids[idx] if idx < len(self._folder_ids) else None
        self.save_settings()
        self._apply_filter()

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

    def _on_type_selected(self, idx):
        self.settings["libraryType"] = TYPE_FILTERS[idx][0]
        self.save_settings()
        self._apply_filter()

    def _on_only_downloaded(self, on):
        self.only_downloaded = on
        self._apply_filter()

    def _visible(self, book) -> bool:
        if self.only_downloaded and not self.library.file_path(book):
            return False
        status = self.settings.get("libraryStatus", "all")
        if status != "all" and self.library.status(book) != status:
            return False
        kind = self.settings.get("libraryType", "all")
        mine = book.get("source") == "folder"
        if kind == "mine" and not mine:
            return False
        if kind in ("text", "audio") and (mine or bool(book.get("is_audio")) != (kind == "audio")):
            return False
        folder = self.settings.get("libraryFolder")
        if folder == NO_FOLDER:
            if book.get("folders"):
                return False
        elif folder and folder not in (book.get("folders") or []):
            return False
        q = self.search.text().strip().lower()
        if q:
            hay = " ".join([book.get("title") or ""] + (book.get("authors") or [])).lower()
            return q in hay
        return True

    def _apply_filter(self):
        for bid, card in self.cards.items():
            book = self.library.books.get(bid)
            card.setVisible(bool(book) and self._visible(book))
        self.grid.invalidate()
        self.grid_widget.adjustSize()

    def _update_filter_bar(self):
        books = self.library.ordered()
        counts = {"all": len(books), "reading": 0, "unread": 0, "finished": 0}
        for b in books:
            counts[self.library.status(b)] += 1
        for key, text in STATUS_FILTERS:
            self.status_buttons[key].setText(f"{text} · {counts[key]}")

        folders = self.library.folders
        self._filling_folders = True
        self._folder_ids = [None, NO_FOLDER] + list(folders)
        self.folder_combo.clear()
        self.folder_combo.addItems(["Все папки", "Без папки"] + [folders[f] for f in folders])
        current = self.settings.get("libraryFolder")
        self.folder_combo.setCurrentIndex(self._folder_ids.index(current) if current in self._folder_ids else 0)
        self._filling_folders = False
        if current not in self._folder_ids:
            self.settings["libraryFolder"] = None
        self.folder_combo.setVisible(bool(folders))
        self.type_combo.setVisible(any(b.get("is_audio") or b.get("source") == "folder" for b in books))

    # --- сетка книг

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
        for book in ordered:
            card = self.cards.get(book["id"])
            if card is None:
                card = BookCard(book["id"])
                card.activated.connect(self.on_book_activated)
                card.menu_requested.connect(self.show_book_menu)
                self.cards[book["id"]] = card
            card.setParent(self.grid_widget)
            self.grid.addWidget(card)
            card.update_book(book, self.library)
            if book.get("cover_url") and not self.library.cover_path(book):
                self._queue_cover(book["id"])
        self.content.setCurrentIndex(1 if self.cards else 0)
        self._update_filter_bar()
        self._apply_filter()
        self._update_recent_panel()

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

    def on_login_state(self):
        self._update_account_ui()
        if self.litres.logged_in:
            if self.current() is self.login_page:
                self.go_back()
                self.toast("Вы вошли в ЛитРес")
                self.sync()
            elif not getattr(self, "_startup_synced", False):
                # При запуске тихо забираем свежие данные (в том числе место чтения на ЛитРес)
                self._startup_synced = True
                self.sync(quiet=bool(self.library.books))

    def _update_account_ui(self):
        if self.litres.logged_in:
            self.account_action.setText("Выйти из ЛитРес")
            self.lib_header.set_title("Библиотека", f"ЛитРес: {self.litres.user_name}"
                                      if self.litres.user_name else "ЛитРес: вход выполнен")
        else:
            self.account_action.setText("Войти в ЛитРес")
            self.lib_header.set_title("Библиотека", "Вход в ЛитРес не выполнен")

    def _account_action(self):
        self.on_logout() if self.litres.logged_in else self.show_login()

    def show_login(self):
        self.push(self.login_page)
        if not self.litres.logged_in:
            self.litres.page.load(QUrl(LOGIN_URL))

    def on_logout(self):
        box = QMessageBox(self.window)
        box.setWindowTitle("Выйти из ЛитРес?")
        box.setText("<b>Выйти из ЛитРес?</b>")
        box.setInformativeText("Скачанные книги и закладки останутся на этом компьютере.")
        cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        out = box.addButton("Выйти", QMessageBox.ButtonRole.DestructiveRole)
        cls(out, "destructive")
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is out:
            self.litres.logout(lambda: (self._update_account_ui(), self.toast("Вы вышли из ЛитРес")))

    # --- синхронизация

    def flush_folder_ops(self, then=None):
        """Отправляет накопленные изменения папок на ЛитРес по одному."""
        ops = self.library.folder_ops
        if not ops or not self.litres.logged_in:
            if then:
                then()
            return
        op = ops[0]

        def done(ok):
            if ok:
                if op in self.library.folder_ops:
                    self.library.folder_ops.remove(op)
                self.library.save()
                self.flush_folder_ops(then)
            else:
                self.toast("Не удалось изменить папку на ЛитРес — повторю при синхронизации")
                if then:
                    then()
        self.litres.folder_change(op["folder"], [op["art"]], op["op"] == "add", done)

    def _set_syncing(self, on):
        self.syncing = on
        self.sync_btn.setVisible(not on)
        self.sync_spinner.setVisible(on)

    def sync(self, quiet=False):
        if self.syncing:
            return
        self.rescan_local()
        if not self.litres.logged_in:
            self.show_login()
            return
        self._set_syncing(True)
        problems = []
        state = {}

        def finish(text):
            self._set_syncing(False)
            self.refresh_library()
            # Открытая книга могла уйти дальше на ЛитРес — подтягиваем место
            for bid in {self.reader.book["id"] if self.reader else None, self.player.book_id} - {None}:
                if bid in self.library.books:
                    self.apply_remote_position(self.library.books[bid])
            if problems:
                text += ". Не получено: " + ", ".join(problems)
            if not quiet or problems:
                self.toast(text)
            self.singularity.schedule(soon=True)

        def got_arts(arts, status):
            if arts is None:
                self._set_syncing(False)
                if status in (401, 403):
                    self.litres.logged_in = False
                    self._update_account_ui()
                    self.toast("Сессия ЛитРес истекла — войдите снова")
                else:
                    self.toast(f"Не удалось получить список книг (код {status})")
                return
            # Отметки «прочитано», которые не успели уйти на ЛитРес, важнее ответа сервера
            pending = {bid: b["finished_pending"] for bid, b in self.library.books.items()
                       if "finished_pending" in b}
            self.library.merge_litres(arts)
            for bid, value in pending.items():
                if bid in self.library.books:
                    self.set_finished(self.library.books[bid], value)
            state["count"] = len(arts)
            state["has_folders_field"] = any("in_folders" in a for a in arts)
            self.litres.fetch_list("/users/me/arts/in-progress", got_progress)

        def got_progress(arts, _status):
            if arts is None:
                problems.append("«Читаю сейчас»")
            else:
                self.library.set_in_progress(a.get("id") for a in arts)
            self.litres.fetch_folders(got_folders)

        def got_folders(folders, _status):
            if folders is None:
                problems.append("папки")
                finish(f"Книг в аккаунте: {state['count']}")
                return
            if state["has_folders_field"] or not folders:
                self.library.set_folders(folders, None)
                finish(f"Книг в аккаунте: {state['count']}")
                return
            members: dict[str, list[str]] = {}
            queue = list(folders)

            def next_folder():
                if not queue:
                    self.library.set_folders(folders, members)
                    finish(f"Книг в аккаунте: {state['count']}")
                    return
                fid = queue.pop(0)

                def got(arts, _st):
                    if arts is None:
                        problems.append(f"папка «{folders[fid]}»")
                    else:
                        members[fid] = [str(a.get("id")) for a in arts]
                    next_folder()
                self.litres.fetch_list(f"/folders/{fid}/arts", got)
            next_folder()

        # Сначала отправляем свои изменения папок, потом забираем состояние с сервера
        self.flush_folder_ops(lambda: self.litres.fetch_library(got_arts))

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
            self._toast_finished(book, "Книга дочитана — отмечена прочитанной")
        if book.get("source") != "litres" or not self.litres.logged_in:
            return

        def done(ok):
            if ok:
                book.pop("finished_pending", None)
                self.library.save()
            else:
                self.toast("Не удалось обновить отметку на ЛитРес — повторю при синхронизации")
        self.litres.set_finished(book["id"], finished, done)

    def _toast_finished(self, book, text):
        """Уведомление о дочитанной книге; если есть следующая в серии — кнопка «Дальше»."""
        nxt = self.library.next_in_series(book)
        if nxt:
            self.toast(f"{text}. Следующая в серии: «{nxt.get('title')}»", button="Открыть",
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
            self.download_book(book, open_after=True)

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

    def download_book(self, book, open_after=False):
        bid = book["id"]
        if bid in self.downloading:
            return
        if not self.litres.logged_in:
            self.toast("Сначала войдите в ЛитРес")
            self.show_login()
            return
        self.downloading.add(bid)
        card = self.cards.get(bid)
        if card:
            card.set_download_progress(0)

        def fail(text):
            self.downloading.discard(bid)
            if card:
                card.set_download_progress(None)
            self.toast(text)

        def got_files(files, status):
            if files is None:
                fail(f"Не удалось получить файлы книги (код {status})")
                return
            main = [f for f in files if not f.get("is_additional")] or files
            if book.get("is_audio"):
                by_type = {f.get("file_type"): f for f in main if f.get("file_type")}
                choice = next(((t, ext) for t, ext in AUDIO_FILE_TYPES if t in by_type), None)
                if not choice:
                    fail("Для этой аудиокниги доступны только отдельные главы — пока не поддерживается")
                    return
                ftype, local = choice
                f = by_type[ftype]
                remote_ext = f.get("extension") or local
                dest = books_dir() / f"{bid}.{local}"
                try_next([f"{SITE}/download_book/{bid}/{f['id']}/{bid}.{remote_ext}",
                          f"{SITE}/download_book_subscr/{bid}/{f['id']}/{bid}.{remote_ext}"], dest, local, local)
                return
            by_ext = {f.get("extension"): f for f in main if f.get("extension")}
            fmt = next((e for e in FORMAT_ORDER if e in by_ext), None)
            if not fmt:
                fail("У этой книги нет формата для чтения (возможно, только онлайн-чтение)")
                return
            file_id = by_ext[fmt]["id"]
            local_ext = LOCAL_SUFFIX.get(fmt, fmt)
            dest = books_dir() / f"{bid}.{local_ext}"
            try_next([f"{SITE}/download_book/{bid}/{file_id}/{bid}.{fmt}",
                      f"{SITE}/download_book_subscr/{bid}/{file_id}/{bid}.{fmt}"], dest, fmt, local_ext)

        def finished_ok(file_name, fmt_saved, path):
            self.downloading.discard(bid)
            if card:
                card.set_download_progress(None)
            book.update(file=file_name, format=fmt_saved)
            self.library.save()
            self.refresh_card(bid)
            if book.get("is_drm"):
                self.toast("Книга защищена DRM — она может не открыться")
            if open_after:
                self.open_book(book, path)

        def try_next(attempts, dest, fmt, local_ext):
            url = attempts.pop(0)

            def done(ok, err):
                if ok and looks_like_book(dest, fmt) and book.get("is_audio") and fmt == "zip":
                    folder = books_dir() / bid   # MP3-архив распаковываем в папку книги

                    def extracted(error):
                        if error:
                            fail(f"Не удалось распаковать аудиокнигу: {error}")
                        else:
                            finished_ok(folder.name, "mp3dir", folder)
                    self._extract_zip(dest, folder, extracted)
                    return
                if ok and looks_like_book(dest, fmt):
                    finished_ok(dest.name, local_ext if local_ext in READABLE | AUDIO_FORMATS else fmt, dest)
                    return
                dest.unlink(missing_ok=True)
                if attempts:
                    try_next(attempts, dest, fmt, local_ext)
                else:
                    fail(f"ЛитРес не отдал файл книги ({err or 'неверный ответ'})")

            self.litres.download(url, dest, lambda f: card and card.set_download_progress(f), done)

        self.litres.fetch_files(bid, got_files)

    def _extract_zip(self, zip_path: Path, dest_dir: Path, on_done):
        """Распаковка MP3-архива в отдельном потоке (архивы бывают большими)."""
        bridge = _Bridge(self)
        bridge.done.connect(lambda err, _x: (on_done(err), bridge.deleteLater()))

        def work():
            try:
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(dest_dir)
                zip_path.unlink(missing_ok=True)
                bridge.done.emit(None, None)
            except (OSError, zipfile.BadZipFile) as e:
                shutil.rmtree(dest_dir, ignore_errors=True)
                bridge.done.emit(str(e), None)
        threading.Thread(target=work, daemon=True).start()

    def show_book_menu(self, bid, pos):
        book = self.library.books.get(bid)
        if not book:
            return
        menu = QMenu(self.window)
        downloaded = self.library.file_path(book) is not None
        if downloaded:
            menu.addAction("Слушать" if book.get("is_audio") else "Читать",
                           lambda: self.on_book_activated(bid))
        if book.get("finished"):
            menu.addAction("Снять отметку «Прочитано»", lambda: self.set_finished(book, False))
        else:
            menu.addAction("Отметить прочитанной", lambda: self.set_finished(book, True))
        if book.get("source") == "litres":
            menu.addAction("Папки…", lambda: self.show_folders_dialog(book))
            menu.addAction("Скачать заново" if downloaded else "Скачать", lambda: self.download_book(book))
            if book.get("url"):
                menu.addAction("Открыть на сайте ЛитРес", lambda: QDesktopServices.openUrl(QUrl(book["url"])))
        nxt = self.library.next_in_series(book)
        if nxt:
            menu.addAction(f"Следующая в серии: {nxt.get('title')}", lambda: self.on_book_activated(nxt["id"]))
        if book.get("source") == "folder":
            # своя книга: файл остаётся на месте, удалять его из читалки не даём
            menu.addAction("Показать файл в папке", lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(book["path"]).parent))))
        elif downloaded or book.get("source") == "local":
            menu.addSeparator()
            menu.addAction("Удалить с устройства", lambda: self.remove_book_file(bid))
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

    def show_folders_dialog(self, book):
        """Окно выбора папок ЛитРес для книги: переключатель у каждой папки и новая папка."""
        dlg = QDialog(self.window, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dlg.setMinimumWidth(400)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        header = HeaderBar(dlg, "Папки", show_controls=False)
        close = IconButton("window-close", "Закрыть", flat=False)
        cls(close, "wincontrol")
        close.clicked.connect(dlg.accept)
        header.pack_end(close)
        v.addWidget(header)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 18, 18, 18)
        b.setSpacing(6)
        b.addWidget(label(book.get("title") or "", "heading", wrap=True))
        desc = label("Изменения сразу отправляются на ЛитРес", "dim", wrap=True)
        b.addWidget(desc)
        b.addSpacing(6)
        boxed = QFrame()
        cls(boxed, "boxed")
        rows = QVBoxLayout(boxed)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        b.addWidget(boxed)
        switches = []

        def add_row(fid, name):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 10, 14, 10)
            h.addWidget(label(name), 1)
            sw = Switch(fid in (book.get("folders") or []))
            sw.toggled.connect(lambda on: self.set_book_folder(book, fid, on))
            h.addWidget(sw)
            rows.addWidget(row)
            switches.append(sw)
            boxed.setVisible(True)

        for fid, name in self.library.folders.items():
            add_row(fid, name)
        if not self.library.folders:
            boxed.setVisible(False)
            desc.setText("Папок пока нет — создайте первую ниже")

        b.addSpacing(12)
        entry = QLineEdit()
        entry.setPlaceholderText("Новая папка — введите название и нажмите Enter")
        b.addWidget(entry)

        def create():
            title = entry.text().strip()
            if not title:
                return
            if not self.litres.logged_in:
                self.toast("Чтобы создать папку, войдите в ЛитРес")
                return
            entry.setEnabled(False)

            def done(folders, new_id):
                entry.setEnabled(True)
                if folders is None or new_id is None:
                    self.toast("Не удалось создать папку на ЛитРес")
                    return
                entry.clear()
                self.library.set_folders(folders, None)
                add_row(new_id, folders[new_id])
                desc.setText("Изменения сразу отправляются на ЛитРес")
                switches[-1].setChecked(True)   # сразу кладём книгу в новую папку
                self._update_filter_bar()
            self.litres.create_folder(title, done)
        entry.returnPressed.connect(create)
        v.addWidget(body)

        frame = QFrame(dlg)
        frame.setObjectName("popover")
        frame.lower()
        dlg.resizeEvent = lambda e: frame.setGeometry(dlg.rect())
        dlg.exec()

    def set_book_folder(self, book, fid, inside: bool):
        if inside == (fid in (book.get("folders") or [])):
            return
        self.library.set_in_folder(book["id"], fid, inside)
        self._update_filter_bar()
        self._apply_filter()
        self.flush_folder_ops()

    # --- аудиокниги

    def open_player(self, book, path: Path, autoplay=True):
        self.settings["lastBook"] = book["id"]
        self.save_settings()
        if self.player.book_id != book["id"]:
            tracks = audio_tracks(path)
            if not tracks:
                self.toast("В аудиокниге не найдено звуковых файлов")
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
            QTimer.singleShot(1500, lambda: self.apply_remote_position(book))
        elif not self.player.playing and autoplay:
            self.player.play()
        self.show_player()

    def apply_remote_position(self, book, _attempt=0):
        """Синхронизация места: если на ЛитРес ушли дальше — переходим туда сами.

        В уведомлении есть «Вернуть»; после него это место с ЛитРес больше не применяется.
        """
        remote = book.get("remote_percent") or 0
        if remote < 1 or book.get("remote_ignored") == remote:
            return
        bid = book["id"]
        target = min(remote, 99.9) / 100

        def ignore():
            book["remote_ignored"] = remote
            self.library.save()

        if self.reader and self.reader.book["id"] == bid:
            local = (self.library.progress.get(bid, {}).get("fraction") or 0) * 100
            if remote - local < 1:
                return
            back_cfi = self.library.progress.get(bid, {}).get("cfi")
            self.reader.js(f"window.reader.goToFraction({target})")

            def undo():
                ignore()
                if back_cfi and self.reader and self.reader.book["id"] == bid:
                    self.reader.js(f"window.reader.goTo({json.dumps(back_cfi)})")
            self.toast(f"Продолжаю с места на ЛитРес — {round(remote)}%", button="Вернуть",
                       on_button=undo, timeout=8000)
        elif self.player.book_id == bid:
            if not self.player.duration():
                # Файл ещё загружается — попробуем чуть позже
                if _attempt < 10:
                    QTimer.singleShot(1000, lambda: self.apply_remote_position(book, _attempt + 1))
                return
            if remote - self.player.fraction() * 100 < 1:
                return
            index, pos = self.player.index, self.player.position()
            self.player.go_to_fraction(target)

            def undo():
                ignore()
                if self.player.book_id == bid:
                    self.player.go_to(index, pos)
            self.toast(f"Продолжаю с места на ЛитРес — {round(remote)}%", button="Вернуть",
                       on_button=undo, timeout=8000)

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
            self._toast_finished(book, "Аудиокнига прослушана — отмечена прочитанной")

    # --- открытие своих файлов

    def import_and_open(self, path: Path):
        try:
            bid = self.library.add_local(path)
        except OSError as e:
            self.toast(f"Не удалось открыть файл: {e.strerror}")
            return
        self.refresh_library()
        book = self.library.books[bid]
        self.open_book(book, self.library.file_path(book))

    def choose_books_dir(self):
        """Выбор папки для скачанных книг; уже скачанные переносятся туда же."""
        current = books_dir()
        path = QFileDialog.getExistingDirectory(self.window, f"Папка для книг (сейчас: {current})", str(current))
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
            self.toast(f"Книги теперь в {new_dir}. Перенесено: {moved}, не удалось: {len(errors)} — "
                       + errors[0], timeout=10000)
        else:
            self.toast(f"Книги теперь в {new_dir}" + (f" — перенесено файлов: {moved}" if moved else ""))

    # --- свои книги и статьи

    def local_folders(self) -> list[str]:
        """Папки со своими книгами и статьями; по умолчанию — из «Документов»."""
        folders = self.settings.get("localFolders")
        if folders is None:
            docs = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
            folders = [str(docs / d) for d in ("Books/others", "articles", "trainings") if (docs / d).is_dir()]
        return folders

    def rescan_local(self, report=False):
        n = self.library.scan_folders(self.local_folders())
        self.refresh_library()
        QTimer.singleShot(500, self._make_pdf_covers)
        if report:
            self.toast(f"Своих книг и статей: {n}")

    def _fill_mine_menu(self):
        m = self.mine_menu
        m.clear()
        show = m.addAction("Показать в библиотеке", lambda: self._set_type_filter("mine"))
        show.setEnabled(any(b.get("source") == "folder" for b in self.library.books.values()))
        m.addAction("Обновить список", lambda: self.rescan_local(report=True))
        m.addSeparator()
        for folder in self.local_folders():
            m.addAction(f"Убрать папку: {folder}", lambda f=folder: self._remove_local_folder(f))
        m.addAction("Добавить папку…", self._add_local_folder)

    def _set_type_filter(self, key):
        keys = [k for k, _t in TYPE_FILTERS]
        self.type_combo.setCurrentIndex(keys.index(key))

    def _add_local_folder(self):
        start = self.local_folders()[0] if self.local_folders() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self.window, "Папка со своими книгами и статьями", start)
        if path and path not in self.local_folders():
            self.settings["localFolders"] = self.local_folders() + [path]
            self.save_settings()
            self.rescan_local(report=True)

    def _remove_local_folder(self, folder):
        self.settings["localFolders"] = [f for f in self.local_folders() if f != folder]
        self.save_settings()
        self.rescan_local(report=True)

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
        path, _ = QFileDialog.getOpenFileName(self.window, "Открыть книгу", str(Path.home()),
                                              f"Электронные книги ({EBOOK_PATTERNS})")
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
        close = IconButton("window-close", "Закрыть", flat=False)
        cls(close, "wincontrol")
        close.clicked.connect(dlg.accept)
        header.pack_end(close)
        v.addWidget(header)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 18, 18, 18)
        b.setSpacing(8)
        intro = label("Книги, прогресс и ежедневное чтение — в планировщике SingularityApp.<br>"
                      "Токен создаётся в <a href='https://me.singularity-app.com'>личном кабинете</a> → "
                      "«Доступ к API» (нужен доступ к задачам, проектам и привычкам).", wrap=True)
        intro.setOpenExternalLinks(True)
        b.addWidget(intro)
        token = QLineEdit(s.state.get("token", ""))
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setPlaceholderText("API-токен Singularity")
        b.addWidget(token)
        b.addSpacing(6)

        boxed = QFrame()
        cls(boxed, "boxed")
        rows = QVBoxLayout(boxed)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        switches = {}
        for key, title, hint in (
                ("reading", "Задачи «Читаю»", "Начатые книги — задачи в проекте «Книги», дочитанные закрываются"),
                ("progress", "Прогресс в задаче", "Процент и текущая глава в заметке задачи"),
                ("wishlist", "«Хочу прочитать»", "Непрочитанные книги — задачи в отдельном проекте"),
                ("daily", "Ежедневное чтение", "Привычка отмечается сама, когда за день набралось N минут")):
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

        goal_row = QHBoxLayout()
        goal_row.addWidget(label("Цель чтения в день, минут"), 1)
        goal = QSpinBox()
        goal.setRange(5, 240)
        goal.setSingleStep(5)
        goal.setValue(int(s.state.get("dailyMinutes") or 20))
        goal_row.addWidget(goal)
        b.addLayout(goal_row)
        b.addWidget(label(f"Сегодня прочитано и прослушано: {s.today_minutes()} мин", "dim", "caption"))

        status = label("", "dim", wrap=True)
        b.addWidget(status)
        s.status.connect(status.setText)
        buttons = QHBoxLayout()
        disconnect = QPushButton("Отключить")
        run = QPushButton("Проверить и синхронизировать")
        cls(run, "suggested")
        buttons.addWidget(disconnect)
        buttons.addStretch()
        buttons.addWidget(run)
        b.addSpacing(6)
        b.addLayout(buttons)
        v.addWidget(body)

        def apply():
            s.configure(token=token.text().strip(), dailyMinutes=goal.value(),
                        **{k: sw.isChecked() for k, sw in switches.items()})

        def check_and_sync():
            apply()
            if not s.enabled:
                status.setText("Вставьте токен")
                return
            status.setText("Проверяю токен…")
            run.setEnabled(False)

            def checked(ok, text):
                run.setEnabled(True)
                status.setText(text + ("; синхронизирую…" if ok else ""))
                if ok:
                    s.sync()
            s.check_token(checked)

        def off():
            s.configure(token="")
            token.clear()
            status.setText("Синхронизация с Singularity отключена")
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

    def save_settings(self):
        if self.reader:
            self.reader.apply_settings()
        self._settings_timer.start()

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
        box.setWindowTitle("О приложении")
        box.setIconPixmap(QIcon(str(APP_ICON)).pixmap(96, 96))
        box.setText(f"<h3>{APP_NAME}</h3><p>Версия {__version__}</p>")
        box.setInformativeText("Чтение и прослушивание книг, купленных на ЛитРес.<br>"
                               "Вход выполняется на сайте ЛитРес; приложение не хранит пароль.<br><br>"
                               "Лицензия MIT. Движок чтения — foliate-js (MIT).")
        box.exec()

    def on_close(self):
        self.save_audio_progress()
        self.player.unload()
        self.library.flush()
        save_json(CONFIG_FILE, self.settings)
        if self.reader:
            self.reader.close_page()
        self.litres.shutdown()


# ─────────────────────────────────────────────────────────────── запуск

def _server_name():
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return f"{APP_ID}-{user}"


def main(argv=None):
    argv = sys.argv if argv is None else argv
    files = [Path(a).resolve() for a in argv[1:] if not a.startswith("-") and Path(a).exists()]

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
    QApplication.setApplicationName("litres-reader")
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    qapp = QApplication(argv)
    qapp.setStyle("Fusion")
    qapp.setFont(style.app_font())
    qapp.setWindowIcon(QIcon(str(APP_ICON)))

    app = App(qapp)
    app.window.show()

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
