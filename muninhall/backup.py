"""Резервные копии данных приложения.

Копия — zip-архив с настройками, библиотекой (папки, отметки, пути к скачанным книгам),
местом чтения и закладками, статистикой и настройками Singularity. Книги и обложки в копию
не входят (книги скачиваются заново, обложки подгружаются сами), вход в ЛитРес — тоже.
Токен Singularity кладётся в копию, только если это включено.

Восстановление в два шага: файлы из копии проверяются и складываются в restore-pending,
приложение перезапускается и при запуске, до чтения данных, переносит их на место.
Так открытое приложение не затрёт восстановленные файлы своими при закрытии.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import __version__
from .core import (CONFIG_DIR, CONFIG_FILE, DATA_DIR, LIBRARY_FILE, PROGRESS_FILE, STATS_FILE, STORE_BOOKS,
                   STORE_GRAPH, STORE_PROGRESS, folder_store_dir, load_json, save_json)
from .i18n import tr

SINGULARITY_FILE = CONFIG_DIR / "singularity.json"
FILES = {
    "settings.json": CONFIG_FILE,
    "library.json": LIBRARY_FILE,
    "progress.json": PROGRESS_FILE,
    "stats.json": STATS_FILE,
    "singularity.json": SINGULARITY_FILE,
}
PREFIX = "muninhall-backup-"
# копии прежних версий (Shelfwise, «Читалка ЛитРес») тоже видны и восстанавливаются
OLD_PREFIXES = ("shelfwise-backup-", "litres-reader-backup-")
APP_TAGS = ("muninhall", "shelfwise", "litres-reader")
PENDING_DIR = DATA_DIR / "restore-pending"
MAX_FILE = 50 * 1024 * 1024
INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
# Настройки, которые не берутся из копии: они про этот компьютер и про сами копии
# Данные своих библиотек (их хранилища `.library/`) — в архиве как libraries/<id>/<файл>
STORE_FILES = (STORE_BOOKS, STORE_PROGRESS, STORE_GRAPH)
STORE_ENTRY = re.compile(r"^libraries/(folder-[0-9a-f]{10})/(%s)$" % "|".join(map(re.escape, STORE_FILES)))
LOCAL_SETTINGS = ("booksDir", "libraries", "localFolders", "backupDir", "backupLast")


def _folder_stores(settings) -> dict[str, Path]:
    """{id библиотеки: папка хранилища} для своих библиотек из реестра настроек."""
    out = {}
    for lib in settings.get("libraries") or []:
        if isinstance(lib, dict) and lib.get("kind") == "folder" and lib.get("id") and lib.get("path"):
            out[lib["id"]] = folder_store_dir(Path(lib["path"]), lib["id"])
    return out


def default_dir() -> Path:
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(docs or Path.home()) / "Backups" / "muninhall"


def migrate_default_dir():
    """Папка копий по умолчанию переименована: Backups/shelfwise или Backups/litres-reader → Backups/muninhall."""
    new = default_dir()
    for name in ("shelfwise", "litres-reader"):
        old = new.parent / name
        if not old.is_dir():
            continue
        try:
            if not new.exists():
                old.rename(new)
            else:                        # уже есть — переносим копии по одной
                for f in old.iterdir():
                    if not (new / f.name).exists():
                        f.rename(new / f.name)
                old.rmdir()
        except OSError:
            pass


def backup_dir(settings) -> Path:
    return Path(settings.get("backupDir") or default_dir())


def scope_tag(scope: str) -> str:
    """Часть имени файла по библиотеке: «Все» — без пометки (как раньше)."""
    return "" if scope == "all" else "-litres" if scope == "litres" else f"-lib-{scope}"


def scope_of(path: Path) -> str:
    m = re.search(r"-lib-(folder-[0-9a-f]{10})", path.name)
    return m.group(1) if m else "litres" if "-litres" in path.name else "all"


# Что входит в копию ЛитРес: её книги и место чтения (свои книги лежат в .library своих библиотек)
LITRES_FILES = ("library.json", "progress.json")


def create(settings, reason: str = "", scope: str = "all") -> Path:
    """Создаёт копию библиотеки (scope: "all", "litres" или id своей) и удаляет лишние старые."""
    folder = backup_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stem = PREFIX + now.strftime("%Y-%m-%d_%H%M%S") + scope_tag(scope) + (f"-{reason}" if reason else "")
    dest = folder / f"{stem}.zip"
    n = 2
    while dest.exists():                    # две копии в одну секунду
        dest = folder / f"{stem}-{n}.zip"
        n += 1
    tmp = dest.with_suffix(".zip.tmp")
    include_token = bool(settings.get("backupToken"))
    stored = []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in FILES.items():
            if scope != "all" and not (scope == "litres" and arc in LITRES_FILES):
                continue
            if arc == "settings.json":
                data = json.dumps(dict(settings), ensure_ascii=False, indent=1).encode()   # текущие, даже не сохранённые
            elif path.exists():
                data = path.read_bytes()
                if arc == "singularity.json" and not include_token:
                    state = json.loads(data or b"{}")
                    state.pop("token", None)
                    data = json.dumps(state, ensure_ascii=False, indent=1).encode()
            else:
                continue
            z.writestr(arc, data)
            stored.append(arc)
        for lib_id, store in _folder_stores(settings).items():
            if scope not in ("all", lib_id):
                continue
            for name in STORE_FILES:
                if (store / name).exists():
                    arc = f"libraries/{lib_id}/{name}"
                    z.writestr(arc, (store / name).read_bytes())
                    stored.append(arc)
        z.writestr("manifest.json", json.dumps({
            "app": "muninhall", "version": __version__, "created": now.isoformat(timespec="seconds"),
            "files": stored, "token": include_token and scope == "all", "reason": reason, "scope": scope,
        }, ensure_ascii=False, indent=1))
    if sys.platform != "win32":
        tmp.chmod(0o600)      # история чтения, пути к книгам, возможно токен — только для владельца
    tmp.replace(dest)
    prune(folder, int(settings.get("backupKeep") or 10), scope)
    return dest


def list_backups(folder: Path, scope: str | None = None) -> list[tuple[Path, datetime]]:
    """Копии в папке (scope — только этой библиотеки), новые первыми; в одну секунду — по времени записи."""
    out = []
    try:
        for p in [p for prefix in (PREFIX, *OLD_PREFIXES) for p in folder.glob(prefix + "*.zip")]:
            if scope is not None and scope_of(p) != scope:
                continue
            st = p.stat()
            try:
                start = next(len(x) for x in (PREFIX, *OLD_PREFIXES) if p.name.startswith(x))
                when = datetime.strptime(p.stem[start:start + 17], "%Y-%m-%d_%H%M%S")
            except ValueError:
                when = datetime.fromtimestamp(st.st_mtime)
            out.append((p, when, st.st_mtime_ns))
    except OSError:
        return []
    out.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [(p, when) for p, when, _ns in out]


def prune(folder: Path, keep: int, scope: str = "all"):
    """Оставляет keep последних копий этой библиотеки (у каждой библиотеки — свой счёт)."""
    for p, _when in list_backups(folder, scope)[max(1, keep):]:
        p.unlink(missing_ok=True)


def due(settings) -> bool:
    interval = INTERVALS.get(settings.get("backupAuto"))
    if not interval:
        return False
    try:
        last = datetime.fromisoformat(settings.get("backupLast") or "")
    except ValueError:
        return True
    return datetime.now() - last >= interval


def read_manifest(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ValueError(tr('это не резервная копия Muninhall ({0})', e)) from None
    if manifest.get("app") not in APP_TAGS:
        raise ValueError(tr("это не резервная копия Muninhall"))
    return manifest


def stage_restore(path: Path) -> dict:
    """Проверяет копию и складывает её файлы в restore-pending. Возвращает манифест."""
    manifest = read_manifest(path)
    staged = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            # только известные имена — никаких путей из архива
            if info.filename not in FILES and not STORE_ENTRY.match(info.filename):
                continue
            if info.file_size > MAX_FILE:
                raise ValueError(tr('{0}: слишком большой файл', info.filename))
            data = z.read(info)
            try:
                json.loads(data)
            except ValueError:
                raise ValueError(tr('{0}: повреждён', info.filename)) from None
            staged[info.filename] = data
    if not staged:
        raise ValueError(tr("в копии нет данных"))
    shutil.rmtree(PENDING_DIR, ignore_errors=True)
    PENDING_DIR.mkdir(parents=True)
    for name, data in staged.items():
        target = PENDING_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest


def cancel_pending():
    shutil.rmtree(PENDING_DIR, ignore_errors=True)


def apply_pending() -> bool:
    """При запуске: переносит восстановленные файлы на место. True — если что-то восстановлено."""
    if not PENDING_DIR.is_dir():
        return False
    applied = False
    for name, target in FILES.items():
        src = PENDING_DIR / name
        if not src.exists():
            continue
        data = load_json(src, None)
        if data is None:
            continue
        current = load_json(target, {})
        if name == "singularity.json" and not data.get("token") and current.get("token"):
            data["token"] = current["token"]          # в копии без токена — оставляем свой
        if name == "settings.json":
            for key in LOCAL_SETTINGS:
                if key in current:
                    data[key] = current[key]
                else:
                    data.pop(key, None)
        save_json(target, data)
        applied = True
    # хранилища своих библиотек — в те библиотеки этого компьютера, что есть в его реестре
    stores = _folder_stores(load_json(CONFIG_FILE, {}))
    pending_libs = PENDING_DIR / "libraries"
    if pending_libs.is_dir():
        for src in pending_libs.glob("*/*.json"):
            lib_id = src.parent.name
            data = load_json(src, None)
            if lib_id in stores and data is not None and STORE_ENTRY.match(f"libraries/{lib_id}/{src.name}"):
                save_json(stores[lib_id] / src.name, data)
                applied = True
    shutil.rmtree(PENDING_DIR, ignore_errors=True)
    return applied
