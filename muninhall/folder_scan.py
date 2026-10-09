"""Сканирование своих библиотек: книги и статьи в папках, отметки и место чтения — из `.library/`.

Файлы не копируются и не меняются: в библиотеке хранится только путь. ID книги считается от полного
пути, а данные в `.library/` — по пути внутри библиотеки, чтобы переезжать на другой компьютер.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .core import FOLDER_FORMATS, STORE_BOOKS, STORE_PROGRESS, books_dir, folder_library_id, folder_store_dir


def scan_folders(lib, folders: list[dict]) -> int:
    """Находит свои книги и статьи в папках [{"id", "path", "name"}] и обновляет lib (model.Library).
    Возвращает число найденных файлов."""
    if lib.folder_libs:
        # повторное сканирование: сначала дописываем несохранённое, иначе хранилище его затрёт
        lib.save()
        lib.flush()
    downloads = books_dir().resolve()
    seen: set[str] = set()
    lib.folder_libs = {}
    for folder in folders:
        root = Path(folder["path"]).expanduser()
        section = folder.get("name") or root.name
        if not root.is_dir():
            continue
        lib_id = folder.get("id") or folder_library_id(root)
        store = folder_store_dir(root, lib_id, create=True)
        lib.folder_libs[lib_id] = {"root": root, "name": section, "store": store}
        # хранилища ещё нет — первый запуск этой версии: данные берутся из общих файлов (миграция)
        saved_books = lib.store.read_folder_store(store, STORE_BOOKS)
        saved_progress = lib.store.read_folder_store(store, STORE_PROGRESS)
        migrate = saved_books is None
        saved_books = (saved_books or {}).get("books", {})
        saved_progress = saved_progress or {}
        for dirpath, dirnames, files in os.walk(root):
            here = Path(dirpath)
            # книги ЛитРес (если их папка внутри) уже есть в библиотеке
            if here.resolve() == downloads:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(files):
                low = name.lower()
                fmt = next((e for e in FOLDER_FORMATS if low.endswith("." + e)), None)
                if not fmt or name.startswith("."):
                    continue
                path = here / name
                bid = "file-" + hashlib.sha1(str(path).encode()).hexdigest()[:12]
                seen.add(bid)
                rel = here.relative_to(root)
                file_rel = path.relative_to(root).as_posix()
                # подпись на карточке: раздел и вложенная папка
                collection = section + ("" if str(rel) == "." else f" / {rel.as_posix()}")
                derived = {"section": section, "collection": collection, "library": lib_id, "rel": file_rel}
                if not migrate:
                    # отметки и место чтения — из хранилища библиотеки (оно главнее общих файлов)
                    if file_rel in saved_progress:
                        lib.progress[bid] = saved_progress[file_rel]
                if bid in lib.books:
                    book = lib.books[bid]
                    if any(book.get(k) != v for k, v in derived.items()):
                        book.update(derived)                   # раздел переименовали / новая версия
                    if not migrate and saved_books.get(file_rel):
                        book.update(saved_books[file_rel])
                    continue
                lib.books[bid] = {
                    "id": bid, "source": "folder", "format": fmt, "path": str(path),
                    "title": name[: -len(fmt) - 1].replace("_", " ").strip() or name,
                    "authors": [], **derived, **saved_books.get(file_rel, {}),
                }
                lib.order.append(bid)
    for bid in [b for b, v in lib.books.items() if v.get("source") == "folder" and b not in seen]:
        del lib.books[bid]              # файл удалён или папку убрали из списка
        lib.progress.pop(bid, None)     # место чтения осталось в хранилище библиотеки
        if bid in lib.order:
            lib.order.remove(bid)
    # сохраняем всегда: при первом запуске так создаются хранилища (миграция), дальше — только изменения
    lib.save()
    lib.flush()
    return len(seen)
