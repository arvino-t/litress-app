"""Страница «Настройки» — в духе Adw.PreferencesPage: группы со строками.

Всё, что раньше было разбросано по меню и всплывающим панелям: запуск и библиотека,
папки, вид текста, чтение вслух и автолистание, аудио, синхронизация, статистика,
интеграции и сведения о приложении. Изменения применяются сразу.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from . import __version__
from .core import DATA_DIR, books_dir
from .player import SPEEDS
from .widgets import HeaderBar, IconButton, Switch, cls, label

THEMES = (("auto", "Как в системе"), ("light", "Светлая"), ("sepia", "Сепия"),
          ("dark", "Тёмная"), ("black", "Чёрная"))
FONTS = (("book", "Как в книге"), ("serif", "С засечками"), ("sans", "Без засечек"))


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app

        header = HeaderBar(app.window, "Настройки")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        header.pack_start(back)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        outer = QHBoxLayout(holder)
        outer.setContentsMargins(16, 20, 16, 28)
        # колонка по центру не шире 640 px (как Adw.Clamp)
        self.col = QVBoxLayout()
        self.col.setSpacing(6)
        column = QWidget()
        column.setLayout(self.col)
        column.setMaximumWidth(640)
        outer.addStretch()
        outer.addWidget(column, 1)
        outer.addStretch()
        scroll.setWidget(holder)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(scroll, 1)
        self.build()

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

    def row(self, rows, title, widget=None, hint=""):
        r = QWidget()
        if rows.count():
            cls(r, "row-top")
        h = QHBoxLayout(r)
        h.setContentsMargins(14, 9, 12, 9)
        h.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(label(title, wrap=True))
        sub = label(hint, "dim", "caption", wrap=True)   # подпись есть всегда — её можно обновлять
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

    def button(self, rows, title, text, slot, hint="", style=None):
        b = QPushButton(text)
        if style:
            cls(b, style)
        b.clicked.connect(slot)
        self.row(rows, title, b, hint)
        return b

    # --- содержимое

    def build(self):
        app = self.app
        st = app.settings

        g = self.group("Запуск и библиотека")
        self.switch(g, "Открывать последнюю текстовую книгу при запуске", "openLastBook",
                    "Самую свежую из начатых и скачанных — с учётом чтения на телефоне")
        only = Switch(app.only_downloaded)
        only.toggled.connect(app.only_action.setChecked)
        self.row(g, "Показывать только скачанные книги", only)
        self.spin(g, "Обновлять библиотеку с ЛитРес каждые", "remoteSyncMin", 0, 120, 5, " мин",
                  "Пока окно открыто; 0 — только при запуске и по F5", on_change=lambda v: app.apply_remote_sync())

        g = self.group("Папки", "Где хранятся скачанные книги и где искать свои книги и статьи. "
                                "Свои файлы открываются на месте, приложение их не копирует и не удаляет.")
        self.books_row = self.button(g, "Скачанные книги ЛитРес", "Изменить…", self._choose_books_dir,
                                     hint=str(books_dir()))
        self.folders_group = g
        self._folder_rows = []
        self._fill_folders()

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

        g = self.group("Статистика")
        self.spin(g, "Скорость чтения для оценки чтения на телефоне", "readingCharsPerMin", 500, 4000, 100,
                  " зн/мин", "По ней прирост процента на ЛитРес переводится в минуты (аудио — по длительности)",
                  on_change=lambda v: setattr(app.library, "chars_per_min", v))
        self.button(g, "Статистика чтения", "Открыть", app.show_stats_dialog)

        g = self.group("Аккаунт и интеграции")
        self.account_btn = self.button(g, "ЛитРес", "", self._account, hint="")
        self._sync_account()
        app.litres.state_changed.connect(self._sync_account)
        self.button(g, "Singularity", "Настроить…", app.show_singularity_dialog,
                    "Задачи «Читаю», прогресс в заметках, привычка ежедневного чтения")

        g = self.group("О приложении")
        self.row(g, "Читалка ЛитРес", label(f"версия {__version__}", "dim"))
        self.button(g, "Данные приложения", "Открыть папку",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))),
                    "Библиотека, прогресс, статистика, обложки")
        self.col.addStretch()

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

    def _account(self):
        self.app._account_action()

    def _sync_account(self):
        lit = self.app.litres
        self.account_btn.setText("Выйти" if lit.logged_in else "Войти")
        self._set_hint(self.account_btn, f"Вход выполнен: {lit.user_name}" if lit.logged_in and lit.user_name
                       else "Вход выполнен" if lit.logged_in else "Вход не выполнен")

    @staticmethod
    def _set_hint(widget, text):
        """Подпись под заголовком строки, в которой стоит widget."""
        row = widget.parentWidget()
        labels = row.findChildren(QLabel)
        if len(labels) >= 2:
            labels[1].setText(text)
            labels[1].setVisible(bool(text))
