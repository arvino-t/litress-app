"""Главное окно и логика приложения: библиотека, вход в ЛитРес, синхронизация, скачивание."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, backup, core, folder_scan, libraries, singularity, style, widgets
from .i18n import tr
from .core import (APP_ICON, APP_ID, APP_NAME, APP_SLUG, OLD_APP_IDS, AUDIO_FORMATS, CONFIG_FILE,
                   DEFAULT_SETTINGS, READABLE, books_dir, load_json, log, save_json, set_books_dir)
from .graph import GraphPage
from .settings import SettingsPage
from .litres import LitresSession
from .player import AudioPlayer, PlayerPage, audio_tracks
from .reader import ReaderPage
from .litres_connector import LitresConnector
from .singularity import SingularitySync
from .appearance import SHORTCUTS, Appearance
from .library import LibraryPage
from .model import Library
from .widgets import BookCard, cls, HeaderBar, IconButton, Toast

EBOOK_PATTERNS = "*.epub *.fb2 *.fb2.zip *.fbz *.mobi *.azw3"


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


class App(QObject, LibraryPage, Appearance):
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
        folder_scan.scan_folders(self.library, self.local_folders())
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

    # --- сетка книг

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
            self.lib_header.set_title(tr("Библиотека"),
                                      tr('Скачиваю книги: {0} из {1}', b['done'] + b['failed'], b['total']))
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
            self.library.reading.mark_finished(book["id"])
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
        n = folder_scan.scan_folders(self.library, self.local_folders())
        self._fill_type_combo()
        self.refresh_library()
        QTimer.singleShot(500, self._make_pdf_covers)
        if report:
            self.toast(tr('Своих книг и статей: {0}', n))

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
            self.library.reading.add_reading_time(bid, 30)
            self.singularity.add_reading_time(30)
            if self.player.playing:
                self.singularity.schedule()

    def show_stats_dialog(self):
        from .stats import show_stats
        show_stats(self)

    def show_singularity_dialog(self):
        singularity.show_dialog(self)

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
        if getattr(sys, "frozen", False):          # собранная программа (Windows): сама себя
            QProcess.startDetached(sys.executable, ["--restarted"])
        else:
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
        QMessageBox.information(None, APP_NAME, tr("Закройте прежнюю версию приложения («Читалка ЛитРес» "
                                                   "или Shelfwise) и запустите Muninhall снова: её данные "
                                                   "перенесутся."))
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
    if os.environ.get("MUNINHALL_SMOKE_TEST"):
        # проверка сборки (CI): окно поднялось, библиотека построена — выходим с кодом 0
        def smoke():
            line = f"MUNINHALL_SMOKE_TEST ok: {APP_NAME} {__version__}, books: {len(app.library.ordered())}"
            print(line, flush=True)
            if os.environ.get("MUNINHALL_SMOKE_TEST_FILE"):    # у оконной сборки Windows нет консоли
                Path(os.environ["MUNINHALL_SMOKE_TEST_FILE"]).write_text(line + "\n", encoding="utf-8")
            app.window.close()
            qapp.quit()
        QTimer.singleShot(int(os.environ.get("MUNINHALL_SMOKE_TEST_MS", "4000")), smoke)
    return qapp.exec()
