"""Реестр библиотек, внесённых в программу.

Своя библиотека (kind="folder") — корневая папка на диске, её подпапки — подкаталоги; данные
(отметки, место чтения) хранятся в `<корень>/.library/`. Подключаемая библиотека ЛитРес
(kind="litres") — купленные книги аккаунта; её данные — в данных приложения.
Реестр — настройка `libraries`: [{"id", "kind", "name", "path"}].
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from .core import folder_library_id
from .i18n import tr

LITRES_ID = "litres"


def _default_folders() -> list[dict]:
    """Без настроек — три папки из «Документов», если они есть."""
    docs = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    defaults = (("Books/others", tr("Другие книги")), ("articles", tr("Статьи")),
                ("trainings", tr("Тренинги и презентации")))
    return [{"path": str(docs / d), "name": name} for d, name in defaults if (docs / d).is_dir()]


def _legacy_folders(raw) -> list[dict]:
    """Старая настройка localFolders: просто пути или {"path", "name"}."""
    out = []
    for f in raw:
        if isinstance(f, str):
            f = {"path": f}
        if isinstance(f, dict) and f.get("path"):
            out.append({"path": f["path"], "name": (f.get("name") or "").strip() or Path(f["path"]).name})
    return out


def ensure_registry(settings) -> bool:
    """Создаёт реестр из прежних настроек (один раз). True — если настройки изменились."""
    if isinstance(settings.get("libraries"), list):
        return False
    legacy = settings.get("localFolders")
    folders = _legacy_folders(legacy) if legacy is not None else _default_folders()
    settings["libraries"] = [{"id": LITRES_ID, "kind": "litres"}] + [
        {"id": folder_library_id(f["path"]), "kind": "folder", "name": f["name"], "path": f["path"]}
        for f in folders]
    settings.pop("localFolders", None)
    return True


def all_libraries(settings) -> list[dict]:
    ensure_registry(settings)
    out = []
    for lib in settings["libraries"]:
        if not isinstance(lib, dict) or lib.get("kind") not in ("folder", "litres"):
            continue
        if lib["kind"] == "folder":
            if not lib.get("path"):
                continue
            lib = {**lib, "id": lib.get("id") or folder_library_id(lib["path"]),
                   "name": (lib.get("name") or "").strip() or Path(lib["path"]).name}
        else:
            lib = {**lib, "name": lib.get("name") or tr("ЛитРес")}
        out.append(lib)
    return out


def folder_libraries(settings) -> list[dict]:
    return [lib for lib in all_libraries(settings) if lib["kind"] == "folder"]


def set_litres(settings, on: bool):
    """Подключить или отключить библиотеку ЛитРес (данные и вход при отключении не стираются)."""
    ensure_registry(settings)
    rest = [lib for lib in settings["libraries"] if not (isinstance(lib, dict) and lib.get("kind") == "litres")]
    settings["libraries"] = ([{"id": LITRES_ID, "kind": "litres"}] if on else []) + rest


def set_folder_libraries(settings, folders: list[dict]):
    """Заменяет свои библиотеки, сохраняя подключаемые и их порядок впереди."""
    others = [lib for lib in settings.get("libraries") or [] if isinstance(lib, dict) and lib.get("kind") != "folder"]
    settings["libraries"] = others + [
        {"id": f.get("id") or folder_library_id(f["path"]), "kind": "folder", "name": f["name"], "path": f["path"]}
        for f in folders]
