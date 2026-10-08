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
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import __version__
from .core import CONFIG_DIR, CONFIG_FILE, DATA_DIR, LIBRARY_FILE, PROGRESS_FILE, STATS_FILE, load_json, save_json
from .i18n import tr

SINGULARITY_FILE = CONFIG_DIR / "singularity.json"
FILES = {
    "settings.json": CONFIG_FILE,
    "library.json": LIBRARY_FILE,
    "progress.json": PROGRESS_FILE,
    "stats.json": STATS_FILE,
    "singularity.json": SINGULARITY_FILE,
}
PREFIX = "litres-reader-backup-"
PENDING_DIR = DATA_DIR / "restore-pending"
MAX_FILE = 50 * 1024 * 1024
INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
# Настройки, которые не берутся из копии: они про этот компьютер и про сами копии
LOCAL_SETTINGS = ("booksDir", "localFolders", "backupDir", "backupLast")


def default_dir() -> Path:
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(docs or Path.home()) / "Backups" / "litres-reader"


def backup_dir(settings) -> Path:
    return Path(settings.get("backupDir") or default_dir())


def create(settings, reason: str = "") -> Path:
    """Создаёт копию и удаляет лишние старые. Возвращает путь к архиву."""
    folder = backup_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stem = PREFIX + now.strftime("%Y-%m-%d_%H%M%S") + (f"-{reason}" if reason else "")
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
            if arc == "settings.json":
                data = json.dumps(settings, ensure_ascii=False, indent=1).encode()   # текущие, даже не сохранённые
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
        z.writestr("manifest.json", json.dumps({
            "app": "litres-reader", "version": __version__, "created": now.isoformat(timespec="seconds"),
            "files": stored, "token": include_token, "reason": reason,
        }, ensure_ascii=False, indent=1))
    if sys.platform != "win32":
        tmp.chmod(0o600)      # история чтения, пути к книгам, возможно токен — только для владельца
    tmp.replace(dest)
    prune(folder, int(settings.get("backupKeep") or 10))
    return dest


def list_backups(folder: Path) -> list[tuple[Path, datetime]]:
    """Копии в папке, новые первыми."""
    out = []
    try:
        for p in folder.glob(PREFIX + "*.zip"):
            try:
                when = datetime.strptime(p.stem[len(PREFIX):len(PREFIX) + 17], "%Y-%m-%d_%H%M%S")
            except ValueError:
                when = datetime.fromtimestamp(p.stat().st_mtime)
            out.append((p, when))
    except OSError:
        return []
    return sorted(out, key=lambda x: x[1], reverse=True)


def prune(folder: Path, keep: int):
    for p, _when in list_backups(folder)[max(1, keep):]:
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
        raise ValueError(tr('это не копия Читалки ЛитРес ({0})', e)) from None
    if manifest.get("app") != "litres-reader":
        raise ValueError(tr("это не копия Читалки ЛитРес"))
    return manifest


def stage_restore(path: Path) -> dict:
    """Проверяет копию и складывает её файлы в restore-pending. Возвращает манифест."""
    manifest = read_manifest(path)
    staged = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename not in FILES:       # только известные имена — никаких путей из архива
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
        (PENDING_DIR / name).write_bytes(data)
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
    shutil.rmtree(PENDING_DIR, ignore_errors=True)
    return applied
