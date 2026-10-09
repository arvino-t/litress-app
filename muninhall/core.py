"""Общая часть без интерфейса: пути, настройки, библиотека и прогресс чтения."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


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
# Значки приложения на выбор («Настройки → Внешний вид»); по умолчанию — крылья-«М»
APP_ICONS_DIR = PKG_DIR / "data" / "icons"
APP_ICON_NAMES = ("wings", "raven-hall", "moon", "flight", "twins", "runestone", "hall", "quill", "eye")


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
    if os.environ.get("FLATPAK_ID"):
        # во Flatpak — те же каталоги, что у обычной установки (доступ к домашней папке дан в манифесте),
        # а не ~/.var/app/…: данные общие, переход между установками ничего не теряет
        data, config, cache = home / ".local" / "share", home / ".config", home / ".cache"
    else:
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
    "appIcon": "wings",
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
STATUS_FILTERS = (("all", tr("Все")), ("reading", tr("Читаю")), ("unread", tr("Не читал")),
                  ("finished", tr("Прочитано")))
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
