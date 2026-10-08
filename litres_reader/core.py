"""Общая часть без интерфейса: пути, настройки, библиотека и прогресс чтения."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer

APP_ID = "ru.local.LitresReader"
APP_NAME = "Читалка ЛитРес"
SCHEME = "litreader"

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"
ICONS_DIR = PKG_DIR / "data" / "sym"
APP_ICON = PKG_DIR / "data" / f"{APP_ID}.svg"


def _dirs():
    """Каталоги данных по правилам системы: XDG на Linux, AppData на Windows."""
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return local / "litres-reader", roaming / "litres-reader", local / "litres-reader" / "cache"
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return data / "litres-reader", config / "litres-reader", cache / "litres-reader"


DATA_DIR, CONFIG_DIR, CACHE_DIR = _dirs()
# Папка со скачанными книгами: по умолчанию внутри данных приложения,
# пользователь может выбрать свою (настройка booksDir)
BOOKS_DIR = DATA_DIR / "books"
_books_dir = BOOKS_DIR


def books_dir() -> Path:
    return _books_dir


def set_books_dir(path: str | None) -> Path:
    global _books_dir
    _books_dir = Path(path).expanduser() if path else BOOKS_DIR
    _books_dir.mkdir(parents=True, exist_ok=True)
    return _books_dir
COVERS_DIR = DATA_DIR / "covers"
SESSION_DIR = DATA_DIR / "webengine"
CONFIG_FILE = CONFIG_DIR / "settings.json"
LIBRARY_FILE = DATA_DIR / "library.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
STATS_FILE = DATA_DIR / "stats.json"
HEADERS_FILE = SESSION_DIR / "api-headers.json"

API = "https://api.litres.ru/foundation/api"
SITE = "https://www.litres.ru"
COVERS_BASE = "https://static.litres.ru"
LOGIN_URL = f"{SITE}/auth/login/"

# Форматы в порядке предпочтения: первые открывает встроенная читалка
FORMAT_ORDER = ("epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "a4.pdf", "a6.pdf")
READABLE = {"epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "fbz", "mobi", "azw3"}
LOCAL_SUFFIX = {"ios.epub": "epub", "mobi.prc": "mobi", "a4.pdf": "pdf", "a6.pdf": "pdf"}
AUDIO_FORMATS = {"m4b", "mp3dir"}
# Аудио: сначала один файл M4B, иначе архив с MP3
AUDIO_FILE_TYPES = (("mobile_version_mp4", "m4b"), ("zip_with_mp3", "zip"))
# Эти заголовки браузер выставляет сам — копировать их в fetch нельзя
DROP_HEADERS = {"cookie", "host", "content-length", "content-type", "connection",
                "accept-encoding", "user-agent", "origin", "referer",
                # одноразовые заголовки трассировки запросов
                "sentry-trace", "baggage", "x-request-id"}

DEBUG = bool(os.environ.get("LITREADER_DEBUG"))

DEFAULT_SETTINGS = {
    "fontSize": 19,
    "lineHeight": 1.5,
    "margin": 6,
    "lineWidth": 720,
    "twoColumns": True,
    "justify": True,
    "hyphenate": True,
    "font": "book",
    "theme": "auto",
    # фильтры библиотеки
    "libraryStatus": "all",
    "libraryFolder": None,
    "libraryType": "all",   # all / text / audio
    "librarySort": "recent",
    "ttsRate": 0.0,        # скорость чтения вслух, -0.5…0.8
    "autoFlipSec": 30,     # интервал автолистания
    "audioRate": 1.0,
    # Автопереход: при запуске открыть последнюю книгу на месте, где остановились
    "openLastBook": True,
    "lastBook": None,
    # Папка для скачанных книг; None — папка внутри данных приложения
    "booksDir": None,
}

# Особое значение фильтра по папкам: книги, не лежащие ни в одной папке
NO_FOLDER = "__none__"
STATUS_FILTERS = (("all", "Все"), ("reading", "Читаю"), ("unread", "Не читал"), ("finished", "Прочитано"))
SORT_MODES = (("recent", "Недавние"), ("litres", "Как на ЛитРес"), ("title", "По названию"),
              ("author", "По автору"), ("series", "По сериям"), ("progress", "По прогрессу"),
              ("purchased", "По дате покупки"))
TYPE_FILTERS = (("all", "Книги и аудио"), ("text", "Книги"), ("audio", "Аудиокниги"))


def log(*args):
    if DEBUG:
        print("[litreader]", *args, file=sys.stderr, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if private and sys.platform != "win32":
        tmp.chmod(0o600)
    tmp.replace(path)


def absolute(url: str | None, base: str) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base + url
    return url


def looks_like_book(path: Path, fmt: str) -> bool:
    """ЛитРес на отказ отвечает HTML-страницей — отличаем её от настоящего файла."""
    try:
        with path.open("rb") as f:
            head = f.read(96)
    except OSError:
        return False
    if head[:2] == b"PK":
        return True
    if fmt == "m4b":
        return head[4:8] == b"ftyp"
    if fmt.endswith("pdf"):
        return head.startswith(b"%PDF")
    if fmt.startswith("mobi"):
        return head[60:68] in (b"BOOKMOBI", b"TEXtREAd")
    if fmt == "fb2":
        text = head.lstrip(b"\xef\xbb\xbf").lstrip()
        return text.startswith(b"<?xml") or text.startswith(b"<FictionBook")
    return False


class Library:
    """Список книг (library.json) и позиции чтения/прослушивания (progress.json)."""

    def __init__(self):
        data = load_json(LIBRARY_FILE, {})
        self.books: dict[str, dict] = data.get("books", {})
        self.order: list[str] = data.get("order", list(self.books))
        # Папки пользователя на ЛитРес: {id: название}
        self.folders: dict[str, str] = data.get("folders", {})
        # Изменения папок, ещё не отправленные на ЛитРес: [{op, folder, art}]
        self.folder_ops: list[dict] = data.get("folder_ops", [])
        self.progress: dict[str, dict] = load_json(PROGRESS_FILE, {})
        # Статистика: секунды чтения по дням и по книгам, даты дочитывания
        self.stats: dict = {"days": {}, "books": {}, "finished": {}, **load_json(STATS_FILE, {})}
        for d in (books_dir(), COVERS_DIR, SESSION_DIR):
            d.mkdir(parents=True, exist_ok=True)
        # Пишем прогресс на диск не чаще раза в 2 секунды — при листании событий много
        self._progress_timer = QTimer(singleShot=True, interval=2000)
        self._progress_timer.timeout.connect(self.flush)

    def save(self):
        save_json(LIBRARY_FILE, {"books": self.books, "order": self.order,
                                 "folders": self.folders, "folder_ops": self.folder_ops})

    def ordered(self):
        return [self.books[i] for i in self.order if i in self.books]

    def merge_litres(self, arts: list[dict]):
        """Добавляет/обновляет книги из аккаунта, не трогая скачанные файлы."""
        ids = []
        for art in arts:
            bid = str(art.get("id"))
            authors = [p.get("full_name") for p in art.get("persons") or []
                       if p.get("role") == "author" and p.get("full_name")]
            book = self.books.setdefault(bid, {"id": bid, "source": "litres"})
            book.update(
                title=art.get("title") or bid,
                authors=authors,
                cover_url=absolute(art.get("cover_url"), COVERS_BASE),
                is_drm=bool(art.get("is_drm")),
                url=absolute(art.get("url"), SITE),
                finished=bool(art.get("is_finished")),
                is_audio=art.get("art_type") == 1,
            )
            if art.get("read_percent") is not None:
                book["remote_percent"] = float(art["read_percent"] or 0)
            if art.get("in_folders") is not None:
                book["folders"] = [str(f.get("folder_id")) for f in art["in_folders"]
                                   if f.get("folder_id") is not None]
            if art.get("purchased_at"):
                book["purchased_at"] = art["purchased_at"]
            # Серия: первая из списка — название и номер книги в ней
            series = [s for s in art.get("series") or [] if isinstance(s, dict) and s.get("name")]
            if series:
                order = series[0].get("art_order")
                book["series"] = {"name": series[0]["name"],
                                  "order": float(order) if order is not None else None}
            else:
                book.pop("series", None)
            ids.append(bid)
        local = [i for i in self.order if i in self.books and i not in ids]
        self.order = ids + local
        self.apply_pending_folder_ops()
        self.save()

    def set_in_progress(self, ids):
        """Книги из списка ЛитРес «Читаю сейчас»."""
        ids = {str(i) for i in ids}
        for bid, book in self.books.items():
            if book.get("source") == "litres":
                book["in_progress"] = bid in ids
        self.save()

    def set_in_folder(self, bid, fid, inside: bool):
        """Локально кладёт книгу в папку (или убирает) и ставит изменение в очередь."""
        book = self.books[bid]
        folders = [f for f in book.get("folders") or [] if f != fid]
        if inside:
            folders.append(fid)
        book["folders"] = folders
        op = "add" if inside else "remove"
        # Противоположное неотправленное изменение просто отменяем
        opposite = {"op": "remove" if inside else "add", "folder": fid, "art": bid}
        if opposite in self.folder_ops:
            self.folder_ops.remove(opposite)
        else:
            self.folder_ops.append({"op": op, "folder": fid, "art": bid})
        self.save()

    def apply_pending_folder_ops(self):
        """Неотправленные изменения папок важнее ответа сервера — накладываем их поверх."""
        for op in self.folder_ops:
            book = self.books.get(op["art"])
            if not book:
                continue
            folders = [f for f in book.get("folders") or [] if f != op["folder"]]
            if op["op"] == "add":
                folders.append(op["folder"])
            book["folders"] = folders

    def set_folders(self, folders: dict[str, str], members: dict[str, list[str]] | None):
        """folders — {id: название}; members — {id папки: [id книг]} (если известно)."""
        self.folders = folders
        if members is not None:
            for book in self.books.values():
                if book.get("source") == "litres":
                    book["folders"] = [fid for fid, ids in members.items() if book["id"] in ids]
        self.apply_pending_folder_ops()
        self.save()

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
                    errors.append(f"{name}: в новой папке уже есть файл с таким именем")
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
        save_json(PROGRESS_FILE, self.progress)

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

    # --- статистика чтения

    def add_reading_time(self, bid, seconds):
        day = time.strftime("%Y-%m-%d")
        self.stats["days"][day] = self.stats["days"].get(day, 0) + seconds
        if bid:
            self.stats["books"][bid] = self.stats["books"].get(bid, 0) + seconds
        save_json(STATS_FILE, self.stats)

    def mark_finished_stat(self, bid):
        if bid not in self.stats["finished"]:
            self.stats["finished"][bid] = time.strftime("%Y-%m-%d")
            save_json(STATS_FILE, self.stats)

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
        items = []
        for bid, p in self.progress.items():
            book = self.books.get(bid)
            if not book or book.get("finished") or (p.get("fraction") or 0) >= 0.999:
                continue
            if (p.get("fraction") or 0) <= 0.001 and not p.get("cfi") and not p.get("pos"):
                continue
            ts = p.get("ts") or (1 if bid == last_book else 0)
            items.append((ts, bid))
        items.sort(reverse=True)
        return [self.books[bid] for _ts, bid in items[:count]]

    def flush(self):
        self._progress_timer.stop()
        save_json(PROGRESS_FILE, self.progress)
