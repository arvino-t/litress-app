"""Общая настройка тестов: код из репозитория (а не установленный пакет), данные — во временной папке.

Пути данных приложения вычисляются при импорте core, поэтому окружение задаётся до импорта.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="litreader-tests-"))
for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(_TMP / var.lower())
os.environ["LITREADER_LANG"] = "ru"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

import litres_reader  # noqa: E402

assert Path(litres_reader.__file__).resolve().is_relative_to(ROOT), "тесты должны брать код из репозитория"


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def clean_data():
    """Пустые данные приложения для каждого теста."""
    from litres_reader import core
    for f in (core.LIBRARY_FILE, core.PROGRESS_FILE, core.STATS_FILE, core.CONFIG_FILE):
        f.unlink(missing_ok=True)
    yield core
