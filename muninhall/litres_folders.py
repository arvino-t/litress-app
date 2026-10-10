"""Окно «Папки» для книги ЛитРес (папки пользователя на ЛитРес)."""
from __future__ import annotations


from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from . import litres_data
from .i18n import tr
from .widgets import BoxedList, exec_dialog, frameless_dialog, label, Switch

class _Bridge(QObject):
    """Передаёт результат из рабочего потока в главный."""
    done = Signal(object, object)


def show_folders_dialog(connector, book):
    """Окно «Папки» книги ЛитРес: переключатели папок и создание новой; изменения уходят на ЛитРес."""
    """Окно выбора папок ЛитРес для книги: переключатель у каждой папки и новая папка."""
    dlg, v = frameless_dialog(connector.app.window, tr("Папки"), 400)

    body = QWidget()
    b = QVBoxLayout(body)
    b.setContentsMargins(18, 18, 18, 18)
    b.setSpacing(6)
    b.addWidget(label(book.get("title") or "", "heading", wrap=True))
    desc = label(tr("Изменения сразу отправляются на ЛитРес"), "dim", wrap=True)
    b.addWidget(desc)
    b.addSpacing(6)
    boxed = BoxedList()
    b.addWidget(boxed)
    switches = []

    def add_row(fid, name):
        sw = Switch(fid in (book.get("folders") or []))
        sw.toggled.connect(lambda on: connector.set_book_folder(book, fid, on))
        boxed.add_row(name, "", sw, padding=(14, 10))
        switches.append(sw)
        boxed.setVisible(True)

    for fid, name in connector.app.library.folders.items():
        add_row(fid, name)
    if not connector.app.library.folders:
        boxed.setVisible(False)
        desc.setText(tr("Папок пока нет — создайте первую ниже"))

    b.addSpacing(12)
    entry = QLineEdit()
    entry.setPlaceholderText(tr("Новая папка — введите название и нажмите Enter"))
    b.addWidget(entry)

    def create():
        title = entry.text().strip()
        if not title:
            return
        if not connector.app.litres.logged_in:
            connector.app.toast(tr("Чтобы создать папку, войдите в ЛитРес"))
            return
        entry.setEnabled(False)

        def done(folders, new_id):
            entry.setEnabled(True)
            if folders is None or new_id is None:
                connector.app.toast(tr("Не удалось создать папку на ЛитРес"))
                return
            entry.clear()
            litres_data.set_folders(connector.app.library, folders, None)
            add_row(new_id, folders[new_id])
            desc.setText(tr("Изменения сразу отправляются на ЛитРес"))
            switches[-1].setChecked(True)   # сразу кладём книгу в новую папку
            connector.app.library_view.refresh_filters(apply=False)
        connector.app.litres.create_folder(title, done)
    entry.returnPressed.connect(create)
    v.addWidget(body)

    exec_dialog(dlg)
