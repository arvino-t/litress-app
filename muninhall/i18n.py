"""Язык интерфейса: русский (исходный) или английский.

Строки интерфейса пишутся по-русски и проходят через tr(): tr("Скачано {0} из {1}", done, total).
Для английского русский текст — ключ словаря EN (i18n_en.py); нет перевода — остаётся русский.
Язык выбирается в настройках (language: auto / ru / en) и применяется после перезапуска:
модули строят подписи при импорте, поэтому язык определяется здесь же, при первом импорте.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LANGUAGES = ("auto", "ru", "en")
# Языки системы, при которых «Как в системе» означает русский
_RU_LIKE = {"ru", "uk", "be", "kk"}


def _config_file() -> Path:
    """Тот же путь, что CONFIG_FILE в core (без импорта core — он сам использует tr)."""
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    # до переноса данных прежней версии настройки ещё в её каталоге
    for slug in ("muninhall", "shelfwise", "litres-reader"):
        if (base / slug / "settings.json").exists():
            return base / slug / "settings.json"
    return base / "muninhall" / "settings.json"


def system_language() -> str:
    from PySide6.QtCore import QLocale
    name = QLocale.system().name().split("_")[0].lower()
    return "ru" if name in _RU_LIKE else "en"


def _detect() -> str:
    forced = (os.environ.get("MUNINHALL_LANG") or os.environ.get("SHELFWISE_LANG")
              or os.environ.get("LITREADER_LANG", ""))
    if forced in ("ru", "en"):
        return forced
    try:
        lang = json.loads(_config_file().read_text(encoding="utf-8")).get("language", "auto")
    except (OSError, ValueError, AttributeError):
        lang = "auto"
    return lang if lang in ("ru", "en") else system_language()


LANG = _detect()
EN: dict[str, str] = {}
EN_PLURAL: dict[str, tuple[str, str]] = {}
if LANG == "en":
    from .i18n_en import EN, EN_PLURAL   # noqa: F811


def tr(text: str, *args, **kwargs) -> str:
    s = EN.get(text, text) if LANG == "en" else text
    return s.format(*args, **kwargs) if args or kwargs else s


# Строки веб-страниц (читалка, граф): отдаются странице словарём {русский: перевод}
WEB_KEYS = (
    "Открываю книгу…", "Не удалось прочитать файл ({0})", "Не удалось открыть книгу: {0}",
    "{0} книг · {1} тегов", "прочитано {0}%", "{0} · книг: {1}", "Раскладка графа — {0}%", "Строю граф…",
    "Найти книгу или тег", "Книги", "Все", "ЛитРес", "Мои", "Связи", "Тег — от", "книг", "Книги без связей",
    "Показать всё", "Нет связей для выбранных фильтров",
)


def web_strings() -> dict[str, str]:
    return {k: EN[k] for k in WEB_KEYS if k in EN} if LANG == "en" else {}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: plural(5, "книга", "книги", "книг") → «книг» / «books»."""
    if LANG == "en":
        sg, pl = EN_PLURAL.get(one, (one, one))
        return sg if n == 1 else pl
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many
