"""Модель библиотеки: книги всех библиотек, порядок, место чтения/прослушивания.

Хранение — LibraryStore (library_store.py), статистика — ReadingStats (reading_stats.py),
свои папки сканирует folder_scan.py, данные ЛитРес обновляет litres_data.py.
"""
from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QTimer

from .core import (COVERS_DIR, FOLDER_DERIVED, SESSION_DIR, STORE_BOOKS, STORE_PROGRESS, books_dir,
                   set_books_dir)
from .i18n import tr
from .library_store import LibraryStore
from .reading_stats import ReadingStats


class Library:
    def __init__(self, store: LibraryStore | None = None):
        self.store = store or LibraryStore()
        self.books, self.order, folders, folder_ops, self.progress = self.store.load()
        # Папки пользователя на ЛитРес: {id: название}; изменения папок, ещё не отправленные на ЛитРес
        self.folders: dict[str, str] = folders
        self.folder_ops: list[dict] = folder_ops
        # Свои библиотеки: {id: {"root", "name", "store"}} — заполняет folder_scan.scan_folders
        self.folder_libs: dict[str, dict] = {}
        # Источники книг, скрытые из библиотеки (например, отключённый ЛитРес) — данные сохраняются
        self.hidden_sources: set[str] = set()
        self.reading = ReadingStats(lambda bid: self.library_key(self.books.get(bid)))
        for d in (books_dir(), COVERS_DIR, SESSION_DIR):
            d.mkdir(parents=True, exist_ok=True)
        # Пишем прогресс на диск не чаще раза в 2 секунды — при листании событий много
        self._progress_timer = QTimer(singleShot=True, interval=2000)
        self._progress_timer.timeout.connect(self.flush)

    # --- статистика (ReadingStats) — для окна статистики и настройки скорости чтения

    @property
    def stats(self) -> dict:
        return self.reading.data

    @property
    def chars_per_min(self) -> int:
        return self.reading.chars_per_min

    @chars_per_min.setter
    def chars_per_min(self, value: int):
        self.reading.chars_per_min = value

    def library_key(self, book) -> str:
        """К какой библиотеке относится книга: "litres", id своей библиотеки или "local" (открытый файл)."""
        if not book:
            return "local"
        return "litres" if book.get("source") == "litres" else book.get("library") or "local"

    # --- сохранение

    def save(self):
        """Книги ЛитРес и открытые файлы — в library.json; свои — в хранилище своей библиотеки."""
        own = {bid for bid, b in self.books.items() if b.get("source") == "folder"}
        self.store.save_main({bid: b for bid, b in self.books.items() if bid not in own},
                             [bid for bid in self.order if bid not in own], self.folders, self.folder_ops)
        for lib_id, lib in self.folder_libs.items():
            data = {b["rel"]: {k: v for k, v in b.items() if k not in FOLDER_DERIVED}
                    for b in self.books.values() if b.get("library") == lib_id and b.get("rel")}
            self.store.write_folder_store(lib["store"], STORE_BOOKS,
                                          {"version": 1, "books": {k: v for k, v in data.items() if v}})

    def flush(self):
        """Место чтения: книги ЛитРес — в progress.json, свои — в хранилище своей библиотеки."""
        self._progress_timer.stop()
        own = {bid: b for bid, b in self.books.items() if b.get("source") == "folder"}
        self.store.save_progress({bid: p for bid, p in self.progress.items() if bid not in own})
        for lib_id, lib in self.folder_libs.items():
            data = {own[bid]["rel"]: p for bid, p in self.progress.items()
                    if bid in own and own[bid].get("library") == lib_id and own[bid].get("rel")}
            self.store.write_folder_store(lib["store"], STORE_PROGRESS, data)

    # --- книги

    def ordered(self):
        return [self.books[i] for i in self.order if i in self.books
                and self.books[i].get("source") not in self.hidden_sources]

    def status(self, book) -> str:
        """finished — прочитано, reading — читаю, unread — не читал."""
        if book.get("finished"):
            return "finished"
        local = self.progress.get(book["id"], {}).get("fraction") or 0
        if book.get("in_progress") or local > 0.005 or (book.get("remote_percent") or 0) > 0:
            return "reading"
        return "unread"

    def percent(self, book) -> int | None:
        """Процент прочитанного: наибольший из своего и с ЛитРес."""
        local = (self.progress.get(book["id"], {}).get("fraction") or 0) * 100
        remote = book.get("remote_percent") or 0
        best = max(local, remote)
        return round(best) if best > 0 else None

    def next_in_series(self, book):
        """Следующая книга той же серии среди ваших книг (или None)."""
        s = book.get("series")
        if not s or s.get("order") is None:
            return None
        candidates = [b for b in self.books.values()
                      if (b.get("series") or {}).get("name") == s["name"]
                      and (b.get("series") or {}).get("order") is not None
                      and b["series"]["order"] > s["order"]]
        return min(candidates, key=lambda b: b["series"]["order"]) if candidates else None

    def recent(self, count=2, last_book=None):
        """Последние читаемые (начатые и не дочитанные) книги — новые первыми.

        У старых записей прогресса нет времени; тогда первой считаем последнюю открытую книгу.
        """
        when: dict[str, float] = {}
        for bid, p in self.progress.items():
            book = self.books.get(bid)
            if not book or book.get("finished") or (p.get("fraction") or 0) >= 0.999:
                continue
            if book.get("source") in self.hidden_sources:
                continue
            if (p.get("fraction") or 0) <= 0.001 and not p.get("cfi") and not p.get("pos"):
                continue
            when[bid] = p.get("ts") or (1 if bid == last_book else 0)
        # Чтение на ЛитРес (телефон, сайт): начатые там книги тоже здесь, по времени чтения
        for bid, book in self.books.items():
            if book.get("source") in self.hidden_sources:
                continue
            remote_at = book.get("remote_read_at")
            if remote_at and not book.get("finished") and 0 < (book.get("remote_percent") or 0) < 100:
                when[bid] = max(when.get(bid, 0), remote_at)
        items = sorted(((ts, bid) for bid, ts in when.items()), reverse=True)
        return [self.books[bid] for _ts, bid in items[:count]]

    # --- место чтения

    def set_progress(self, bid, cfi, fraction, chapter=None):
        # ts — когда книгу читали последний раз (для панели «Продолжить чтение»)
        self.progress[bid] = {"cfi": cfi, "fraction": fraction, "chapter": chapter or "", "ts": time.time()}
        if not self._progress_timer.isActive():
            self._progress_timer.start()

    def set_audio_progress(self, bid, track, position, fraction, chapter=None):
        self.progress[bid] = {"track": track, "pos": position, "fraction": fraction,
                              "chapter": chapter or "", "ts": time.time()}
        if not self._progress_timer.isActive():
            self._progress_timer.start()

    # --- файлы

    def add_local(self, src: Path) -> str:
        name = src.name.lower()
        fmt = "fb2.zip" if name.endswith(".fb2.zip") else src.suffix.lstrip(".").lower()
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:12]
        bid = f"local-{digest}"
        dest = books_dir() / f"{bid}.{fmt}"
        if not dest.exists():
            shutil.copyfile(src, dest)
        title = src.name[: -len(fmt) - 1] if name.endswith("." + fmt) else src.stem
        self.books.setdefault(bid, {"id": bid, "source": "local", "title": title, "authors": []})
        self.books[bid].update(file=dest.name, format=fmt)
        if bid in self.order:
            self.order.remove(bid)
        self.order.insert(0, bid)
        self.save()
        return bid

    def file_path(self, book) -> Path | None:
        if book.get("path"):            # своя книга из папки — открываем на месте
            p = Path(book["path"])
            return p if p.exists() else None
        if book.get("file"):
            p = books_dir() / book["file"]
            if p.exists():
                return p
        return None

    def cover_path(self, book) -> Path | None:
        p = COVERS_DIR / f"{book['id']}.jpg"
        return p if p.exists() and p.stat().st_size > 0 else None

    def move_files(self, new_dir: Path) -> tuple[int, list[str]]:
        """Переносит скачанные книги в другую папку. Возвращает (сколько перенесено, ошибки)."""
        old_dir = books_dir()
        new_dir.mkdir(parents=True, exist_ok=True)
        moved, errors = 0, []
        if old_dir.resolve() != new_dir.resolve():
            for book in self.books.values():
                name = book.get("file")
                if not name or not (old_dir / name).exists():
                    continue
                target = new_dir / name
                if target.exists():
                    errors.append(tr('{0}: в новой папке уже есть файл с таким именем', name))
                    continue
                try:
                    shutil.move(str(old_dir / name), str(target))
                    moved += 1
                except OSError as e:
                    errors.append(f"{name}: {e}")
        set_books_dir(str(new_dir))
        return moved, errors

    def remove_file(self, bid):
        book = self.books.get(bid)
        if not book:
            return
        p = self.file_path(book)
        if p and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p:
            p.unlink(missing_ok=True)
        book.pop("file", None)
        book.pop("format", None)
        self.progress.pop(bid, None)
        if book.get("source") == "local":
            self.books.pop(bid, None)
            self.order = [i for i in self.order if i != bid]
        self.save()
        self.flush()
