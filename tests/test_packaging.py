"""Все файлы страниц и данных попадают в пакет (в 0.11.0 из-за этого не работали граф и PDF)."""
import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "shelfwise"


def test_package_data_covers_assets():
    globs = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["shelfwise"]
    missing = []
    for folder in ("web", "data"):
        for f in (PKG / folder).rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                rel = f.relative_to(PKG).as_posix()
                if not any(fnmatch.fnmatchcase(rel, g) and rel.count("/") == g.count("/") for g in globs):
                    missing.append(rel)
    assert not missing, f"не попадут в пакет: {missing[:10]} (всего {len(missing)})"
