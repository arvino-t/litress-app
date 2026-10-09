"""Файлы библиотеки: library.json и progress.json (книги ЛитРес и открытые файлы) и хранилища
своих библиотек `<корень>/.library/` (books.json, progress.json). Пишет только то, что изменилось —
меньше лишних синхронизаций с облаком."""
from __future__ import annotations

import json
from pathlib import Path

from .core import LIBRARY_FILE, PROGRESS_FILE, load_json, log, save_json


class LibraryStore:
    def __init__(self, library_file=LIBRARY_FILE, progress_file=PROGRESS_FILE):
        self.library_file = library_file
        self.progress_file = progress_file
        self._written: dict[Path, str] = {}

    def load(self) -> tuple[dict, list, dict, list, dict]:
        """(книги, порядок, папки ЛитРес, очередь изменений папок, место чтения)."""
        data = load_json(self.library_file, {})
        books = data.get("books", {})
        return (books, data.get("order", list(books)), data.get("folders", {}), data.get("folder_ops", []),
                load_json(self.progress_file, {}))

    def save_main(self, books: dict, order: list, folders: dict, folder_ops: list):
        save_json(self.library_file, {"books": books, "order": order, "folders": folders, "folder_ops": folder_ops})

    def save_progress(self, progress: dict):
        save_json(self.progress_file, progress)

    @staticmethod
    def read_folder_store(store: Path, name: str):
        """Содержимое файла хранилища своей библиотеки или None, если его ещё нет."""
        return load_json(store / name, None)

    def write_folder_store(self, store: Path, name: str, data):
        path = store / name
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if self._written.get(path) == text and path.exists():
            return
        try:
            save_json(path, data)
            self._written[path] = text
        except OSError as e:
            log("хранилище библиотеки недоступно:", path, e)
