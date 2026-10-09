"""Общая часть без интерфейса: пути, настройки, библиотека и прогресс чтения."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer

from .i18n import tr

APP_ID = "io.github.arvino_t.Muninhall"
APP_NAME = "Muninhall"
APP_SLUG = "muninhall"          # каталоги данных, команда, имя приложения для Qt
# прежние имена: «Читалка ЛитРес» (до 0.16) и Shelfwise (0.16) — новые первыми
OLD_SLUGS = ("shelfwise", "litres-reader")
OLD_APP_IDS = ("io.github.arvino_t.Shelfwise", "ru.local.LitresReader")
SCHEME = "litreader"

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"
ICONS_DIR = PKG_DIR / "data" / "sym"
APP_ICON = PKG_DIR / "data" / f"{APP_ID}.svg"
# Значки приложения на выбор («Настройки → Внешний вид»); по умолчанию — ворон в чертоге
APP_ICONS_DIR = PKG_DIR / "data" / "icons"
APP_ICON_NAMES = ("raven-hall", "moon", "flight", "twins", "runestone", "hall", "quill", "eye", "wings")


def app_icon_path(name: str | None) -> Path:
    p = APP_ICONS_DIR / f"{name}.svg"
    return p if name in APP_ICON_NAMES and p.exists() else APP_ICON


def _dirs(slug=APP_SLUG):
    """Каталоги данных по правилам системы: XDG на Linux, AppData на Windows."""
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return local / slug, roaming / slug, local / slug / "cache"
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return data / slug, config / slug, cache / slug


DATA_DIR, CONFIG_DIR, CACHE_DIR = _dirs()


def migration_needed() -> bool:
    """Есть данные прежней версии (Shelfwise или «Читалки ЛитРес»), а у Muninhall их ещё нет."""
    for slug in OLD_SLUGS:
        old_data, old_config, _ = _dirs(slug)
        if ((old_data / "library.json").exists() and not (DATA_DIR / "library.json").exists()) or \
                ((old_config / "settings.json").exists() and not CONFIG_FILE.exists()):
            return True
    return False


def migrate_old_dirs() -> list[str]:
    """Переносит данные прежней версии в каталоги Muninhall (один раз, при запуске).

    Сначала Shelfwise, потом «Читалка ЛитРес»: что уже перенесено, второй раз не переносится.
    Возвращает список перенесённых каталогов. Если новый каталог уже полон — старый не трогается.
    """
    moved = []
    pairs = []
    for slug in OLD_SLUGS:
        old_dirs = _dirs(slug)
        if sys.platform == "win32":     # на Windows кэш лежит внутри каталога данных — переносится вместе с ним
            pairs += list(zip(old_dirs[:2], (DATA_DIR, CONFIG_DIR)))
        else:
            pairs += list(zip(old_dirs, (DATA_DIR, CONFIG_DIR, CACHE_DIR)))
    # главный файл каталога: если его нет в новом, а в старом есть — новый пуст (например, его уже создал Qt)
    markers = {DATA_DIR: "library.json", CONFIG_DIR: "settings.json", CACHE_DIR: None}
    for old, new in pairs:
        if not old.is_dir():
            continue
        if not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            try:
                old.rename(new)                  # тот же диск — мгновенно, со ссылками и правами
            except OSError:
                shutil.copytree(old, new, symlinks=True)
            moved.append(str(new))
        elif markers.get(new) and not (new / markers[new]).exists() and (old / markers[new]).exists():
            _merge_move(old, new)
            moved.append(str(new))
    return moved


def _merge_move(src: Path, dst: Path):
    """Переносит содержимое src в существующую dst, не затирая уже имеющиеся файлы (рекурсивно)."""
    for item in list(src.iterdir()):
        target = dst / item.name
        if not target.exists() and not target.is_symlink():
            shutil.move(str(item), str(target))
        elif item.is_dir() and not item.is_symlink() and target.is_dir():
            _merge_move(item, target)
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
# Данные своей библиотеки лежат в её корневой папке — едут вместе с книгами (облако, другой компьютер)
LIBRARY_STORE = ".library"
STORE_BOOKS = "books.json"
STORE_PROGRESS = "progress.json"
STORE_GRAPH = "graph.json"
# Поля книги из папки, которые получаются сканированием (в хранилище библиотеки не пишутся)
FOLDER_DERIVED = {"id", "source", "format", "path", "title", "authors", "section", "collection", "library", "rel"}


def folder_library_id(path) -> str:
    return "folder-" + hashlib.sha1(str(Path(path).expanduser()).encode()).hexdigest()[:10]


def folder_store_dir(root: Path, lib_id: str, create=False) -> Path:
    """`<корень>/.library`; если папка только для чтения — запасное место в данных приложения."""
    store = Path(root).expanduser() / LIBRARY_STORE
    if store.is_dir() and os.access(store, os.W_OK):
        return store
    if create:
        try:
            store.mkdir()
            return store
        except OSError:
            pass
    elif not store.exists() and os.access(Path(root).expanduser(), os.W_OK):
        return store
    return DATA_DIR / "libraries" / lib_id
HEADERS_FILE = SESSION_DIR / "api-headers.json"

API = "https://api.litres.ru/foundation/api"
SITE = "https://www.litres.ru"
COVERS_BASE = "https://static.litres.ru"
LOGIN_URL = f"{SITE}/auth/login/"

# Форматы в порядке предпочтения: первые открывает встроенная читалка
FORMAT_ORDER = ("epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "a4.pdf", "a6.pdf")
READABLE = {"epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "fbz", "mobi", "azw3", "pdf"}
# Форматы, которые ищутся в папках со своими книгами и статьями
FOLDER_FORMATS = ("fb2.zip", "epub", "fb2", "fbz", "mobi", "azw3", "pdf")
LOCAL_SUFFIX = {"ios.epub": "epub", "mobi.prc": "mobi", "a4.pdf": "pdf", "a6.pdf": "pdf"}
AUDIO_FORMATS = {"m4b", "mp3dir"}
# Аудио: сначала один файл M4B, иначе архив с MP3
AUDIO_FILE_TYPES = (("mobile_version_mp4", "m4b"), ("zip_with_mp3", "zip"))
# Эти заголовки браузер выставляет сам — копировать их в fetch нельзя
DROP_HEADERS = {"cookie", "host", "content-length", "content-type", "connection",
                "accept-encoding", "user-agent", "origin", "referer",
                # одноразовые заголовки трассировки запросов
                "sentry-trace", "baggage", "x-request-id"}

def _env_debug() -> bool:
    """MUNINHALL_DEBUG=1 (прежние SHELFWISE_DEBUG и LITREADER_DEBUG тоже понимаются)."""
    return any(os.environ.get(v) for v in ("MUNINHALL_DEBUG", "SHELFWISE_DEBUG", "LITREADER_DEBUG"))


DEBUG = _env_debug()


def set_debug(on: bool):
    """Подробный журнал: переменная MUNINHALL_DEBUG или настройка «Дополнительно → Подробный журнал»."""
    global DEBUG
    DEBUG = bool(on) or _env_debug()

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
    # Подкаталог своих книг (путь «Раздел / папка» из collection); None — все
    "librarySubdir": None,
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
    # Библиотеки, внесённые в программу (см. libraries.py); None — создаётся из прежних настроек
    "libraries": None,
    # Как часто подтягивать библиотеку с ЛитРес, пока окно открыто (минуты; 0 — не обновлять)
    "remoteSyncMin": 15,
    # Скорость чтения для оценки чтения на телефоне (знаков в минуту)
    "readingCharsPerMin": 1300,
    # Подробный журнал (то же, что MUNINHALL_DEBUG=1)
    "debugLog": False,
    # Последняя открытая вкладка настроек
    "settingsTab": "general",
    # Язык интерфейса: auto (как в системе) / ru / en — применяется после перезапуска
    "language": "auto",
    # Внешний вид: тема интерфейса (auto / light / dark), цвет акцента (auto или #rrggbb), значок приложения
    "uiTheme": "auto",
    "accent": "auto",
    "appIcon": "raven-hall",
    # Горячие клавиши, изменённые пользователем: {действие: [клавиши]}; None — все по умолчанию
    "shortcuts": None,
    # Резервные копии: папка (None — Документы/Backups/muninhall), off / daily / weekly,
    # сколько хранить, время последней копии, класть ли в копию токен Singularity
    "backupDir": None,
    "backupAuto": "weekly",
    "backupKeep": 10,
    "backupLast": None,
    "backupToken": False,
}

# Особое значение фильтра по папкам: книги, не лежащие ни в одной папке
NO_FOLDER = "__none__"
STATUS_FILTERS = (("all", tr("Все")), ("reading", tr("Читаю")), ("unread", tr("Не читал")), ("finished", tr("Прочитано")))
SORT_MODES = (("recent", tr("Недавние")), ("litres", tr("Как на ЛитРес")), ("title", tr("По названию")),
              ("author", tr("По автору")), ("series", tr("По сериям")), ("progress", tr("По прогрессу")),
              ("purchased", tr("По дате покупки")))


# Какие ссылки из книг можно отдавать системе. Остальные схемы (file:, smb:, \\сервер\…,
# ms-msdt:, search-ms: и т. п.) из книги не открываем — через них возможны атаки.
SAFE_LINK_SCHEMES = {"http", "https", "mailto"}

# Оценка времени чтения на телефоне/сайте ЛитРес по приросту процента:
# текст — объём в знаках (symbols_count) при средней скорости чтения, аудио — длительность
# (у аудиокниг ЛитРес отдаёт её в том же поле, в секундах)
READING_CHARS_PER_MIN = 1300
REMOTE_MAX_PER_SYNC = 4 * 3600   # большой скачок (перелистали к концу) — не больше 4 часов


def parse_time(value) -> float | None:
    """Время из API ЛитРес («2026-10-04T15:28:01», без пояса — московское, как и у пользователя)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def log(*args):
    if DEBUG:
        print("[litreader]", *args, file=sys.stderr, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data, private=True):
    """Атомарная запись JSON. Файлы данных (история чтения, пути к книгам, токены) —
    только для владельца (0600)."""
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
        # Свои библиотеки: {id: {"root", "name", "store"}}; последнее записанное — чтобы не писать зря
        self.folder_libs: dict[str, dict] = {}
        self._written: dict[Path, str] = {}
        # Источники книг, скрытые из библиотеки (например, отключённый ЛитРес) — данные сохраняются
        self.hidden_sources: set[str] = set()
        # Статистика: секунды чтения по дням и по книгам, даты дочитывания
        self.stats: dict = {"days": {}, "books": {}, "finished": {}, **load_json(STATS_FILE, {})}
        if "lib_days" not in self.stats:
            # по библиотекам время пишется с версии 0.15; раньше в приложении читали только книги ЛитРес —
            # если в статистике нет других книг, прошлое время целиком относим к ЛитРес
            only_litres = all(str(b).isdigit() for b in self.stats["books"])
            self.stats["lib_days"] = {"litres": dict(self.stats["days"])} if only_litres and self.stats["days"] else {}
            self.stats["lib_remote_days"] = ({"litres": dict(self.stats.get("remote_days", {}))}
                                             if only_litres and self.stats.get("remote_days") else {})
        for d in (books_dir(), COVERS_DIR, SESSION_DIR):
            d.mkdir(parents=True, exist_ok=True)
        # Пишем прогресс на диск не чаще раза в 2 секунды — при листании событий много
        self._progress_timer = QTimer(singleShot=True, interval=2000)
        self._progress_timer.timeout.connect(self.flush)

    def save(self):
        """Книги ЛитРес и открытые файлы — в library.json; свои — в хранилище своей библиотеки."""
        own = {bid for bid, b in self.books.items() if b.get("source") == "folder"}
        save_json(LIBRARY_FILE, {"books": {bid: b for bid, b in self.books.items() if bid not in own},
                                 "order": [bid for bid in self.order if bid not in own],
                                 "folders": self.folders, "folder_ops": self.folder_ops})
        for lib_id, lib in self.folder_libs.items():
            data = {b["rel"]: {k: v for k, v in b.items() if k not in FOLDER_DERIVED}
                    for b in self.books.values() if b.get("library") == lib_id and b.get("rel")}
            self._write_store(lib, STORE_BOOKS, {"version": 1, "books": {k: v for k, v in data.items() if v}})

    def _write_store(self, lib, name, data):
        """Пишет файл хранилища, только если он изменился (меньше лишних синхронизаций с облаком)."""
        path = lib["store"] / name
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if self._written.get(path) == text and path.exists():
            return
        try:
            save_json(path, data)
            self._written[path] = text
        except OSError as e:
            log("хранилище библиотеки недоступно:", path, e)

    def ordered(self):
        return [self.books[i] for i in self.order if i in self.books
                and self.books[i].get("source") not in self.hidden_sources]

    def merge_litres(self, arts: list[dict]):
        """Добавляет/обновляет книги из аккаунта, не трогая скачанные файлы."""
        ids = []
        for art in arts:
            bid = str(art.get("id"))
            if not bid.isdigit():
                log("пропущена книга с некорректным id:", repr(bid)[:40])
                continue
            prev = self.books.get(bid, {})
            prev_percent, prev_at, was_finished = (prev.get("remote_percent"), prev.get("remote_read_at"),
                                                   prev.get("finished"))
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
            # Когда и где читали на ЛитРес (телефон, сайт) — для панели «Продолжить чтение»
            read_at = parse_time(art.get("read_at"))
            if read_at:
                book["remote_read_at"] = read_at
            else:
                book.pop("remote_read_at", None)
            chapter = art.get("last_read_chapter_number")
            if chapter:
                book["remote_chapter"] = tr('Глава {0}', chapter)
            else:
                book.pop("remote_chapter", None)
            if art.get("symbols_count"):
                book["symbols"] = int(art["symbols_count"])
            # Прочитанное на телефоне/сайте — в статистику (только прирост с прошлой синхронизации)
            new_percent = book.get("remote_percent")
            if (prev_percent is not None and new_percent is not None and new_percent > prev_percent
                    and read_at and read_at > (prev_at or 0)):
                self.add_remote_reading(book, new_percent - prev_percent, read_at)
            if book["finished"] and was_finished is False:
                self.mark_finished_stat(bid)
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

    def scan_folders(self, folders: list[dict]) -> int:
        """Находит свои книги и статьи в папках [{"path", "name"}]; name — раздел (подпись и фильтр).
        Файлы не копируются и не меняются: в библиотеке хранится только путь.
        Возвращает число найденных файлов."""
        if self.folder_libs:
            # повторное сканирование: сначала дописываем несохранённое, иначе хранилище его затрёт
            self.save()
            self.flush()
        downloads = books_dir().resolve()
        seen: set[str] = set()
        self.folder_libs = {}
        for folder in folders:
            root = Path(folder["path"]).expanduser()
            section = folder.get("name") or root.name
            if not root.is_dir():
                continue
            lib_id = folder.get("id") or folder_library_id(root)
            store = folder_store_dir(root, lib_id, create=True)
            self.folder_libs[lib_id] = {"root": root, "name": section, "store": store}
            # хранилища ещё нет — первый запуск этой версии: данные берутся из общих файлов (миграция)
            saved_books = load_json(store / STORE_BOOKS, None)
            saved_progress = load_json(store / STORE_PROGRESS, None)
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
                            self.progress[bid] = saved_progress[file_rel]
                    if bid in self.books:
                        book = self.books[bid]
                        if any(book.get(k) != v for k, v in derived.items()):
                            book.update(derived)                   # раздел переименовали / новая версия
                        if not migrate and saved_books.get(file_rel):
                            book.update(saved_books[file_rel])
                        continue
                    self.books[bid] = {
                        "id": bid, "source": "folder", "format": fmt, "path": str(path),
                        "title": name[: -len(fmt) - 1].replace("_", " ").strip() or name,
                        "authors": [], **derived, **saved_books.get(file_rel, {}),
                    }
                    self.order.append(bid)
        for bid in [b for b, v in self.books.items() if v.get("source") == "folder" and b not in seen]:
            del self.books[bid]              # файл удалён или папку убрали из списка
            self.progress.pop(bid, None)     # место чтения осталось в хранилище библиотеки
            if bid in self.order:
                self.order.remove(bid)
        # сохраняем всегда: при первом запуске так создаются хранилища (миграция), дальше — только изменения
        self.save()
        self.flush()
        return len(seen)

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

    def library_key(self, book) -> str:
        """К какой библиотеке относится книга: "litres", id своей библиотеки или "local" (открытый файл)."""
        if not book:
            return "local"
        return "litres" if book.get("source") == "litres" else book.get("library") or "local"

    def _add_lib_day(self, key, bid, day, seconds):
        lib = self.library_key(self.books.get(bid))
        days = self.stats.setdefault(key, {}).setdefault(lib, {})
        days[day] = days.get(day, 0) + seconds

    def add_reading_time(self, bid, seconds):
        day = time.strftime("%Y-%m-%d")
        self.stats["days"][day] = self.stats["days"].get(day, 0) + seconds
        if bid:
            self.stats["books"][bid] = self.stats["books"].get(bid, 0) + seconds
            self._add_lib_day("lib_days", bid, day, seconds)
        save_json(STATS_FILE, self.stats)

    def add_remote_reading(self, book, percent_delta: float, when: float):
        """Время, прочитанное или прослушанное вне приложения (оценка по приросту процента)."""
        size = book.get("symbols") or 0
        if size <= 0 or percent_delta <= 0:
            return
        part = size * percent_delta / 100
        speed = getattr(self, "chars_per_min", READING_CHARS_PER_MIN) or READING_CHARS_PER_MIN
        seconds = part if book.get("is_audio") else part / speed * 60
        seconds = int(min(seconds, REMOTE_MAX_PER_SYNC))
        if seconds < 30:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(when))
        for key, k in (("days", day), ("books", book["id"])):
            self.stats[key][k] = self.stats[key].get(k, 0) + seconds
        remote = self.stats.setdefault("remote_days", {})
        remote[day] = remote.get(day, 0) + seconds
        self._add_lib_day("lib_days", book["id"], day, seconds)
        self._add_lib_day("lib_remote_days", book["id"], day, seconds)
        save_json(STATS_FILE, self.stats)
        log(f"чтение вне приложения: {book.get('title')} +{percent_delta:g}% ≈ {seconds // 60} мин ({day})")

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

    def flush(self):
        """Место чтения: книги ЛитРес — в progress.json, свои — в хранилище своей библиотеки."""
        self._progress_timer.stop()
        own = {bid: b for bid, b in self.books.items() if b.get("source") == "folder"}
        save_json(PROGRESS_FILE, {bid: p for bid, p in self.progress.items() if bid not in own})
        for lib_id, lib in self.folder_libs.items():
            data = {own[bid]["rel"]: p for bid, p in self.progress.items()
                    if bid in own and own[bid].get("library") == lib_id and own[bid].get("rel")}
            self._write_store(lib, STORE_PROGRESS, data)
