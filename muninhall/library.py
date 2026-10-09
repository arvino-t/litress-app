"""Страница библиотеки: фильтры, сетка карточек (создаются порциями), обложки,
«Продолжить чтение», меню книги. Примесь к App (app.py): методы работают с его состоянием.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from . import libraries, style
from .i18n import tr
from .core import COVERS_DIR, NO_FOLDER, SORT_MODES, STATUS_FILTERS, log
from .widgets import (BookCard, cls, FlowLayout, HeaderBar, IconButton, label, RecentPanel, Spinner)

EBOOK_PATTERNS = "*.epub *.fb2 *.fb2.zip *.fbz *.mobi *.azw3"


class LibraryPage:
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
            menu.addAction(tr("Скачать заново") if downloaded else tr("Скачать"),
                           lambda: self.litres_lib.download_book(book))
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

    def _set_type_filter(self, key):
        if key in self._type_keys:
            self.type_combo.setCurrentIndex(self._type_keys.index(key))

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
        except (OSError, RuntimeError, ValueError) as e:
            log("обложка PDF:", book["path"], e)
        if not target.exists():
            target.touch()                           # пустой файл: больше не пытаться
        self.refresh_card(book["id"])
        QTimer.singleShot(30, self._make_pdf_covers)
