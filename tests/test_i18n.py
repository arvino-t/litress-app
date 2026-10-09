"""Перевод: у каждой строки tr() есть английский вариант с теми же подстановками."""
import ast
import re
from pathlib import Path

from muninhall import i18n_en, i18n

PKG = Path(__file__).resolve().parent.parent / "muninhall"
PLACEHOLDER = re.compile(r"\{[^}]*\}")


def tr_keys():
    keys = set()
    for f in PKG.glob("*.py"):
        if f.name.startswith("i18n"):
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args):
                arg = node.args[0]
                assert isinstance(arg, ast.Constant), f"{f.name}:{node.lineno}: tr() — только с текстом-строкой"
                keys.add(arg.value)
    return keys | set(i18n.WEB_KEYS)


def test_every_string_translated():
    missing = sorted(tr_keys() - set(i18n_en.EN))
    assert not missing, f"нет перевода: {missing}"


def test_no_stale_translations():
    stale = sorted(set(i18n_en.EN) - tr_keys())
    assert not stale, f"перевод больше не используется: {stale}"


def test_placeholders_match():
    bad = [k for k in tr_keys() if sorted(PLACEHOLDER.findall(k)) != sorted(PLACEHOLDER.findall(i18n_en.EN[k]))]
    assert not bad, f"подстановки не совпадают: {bad}"


def test_plural_forms():
    assert [i18n.plural(n, "книга", "книги", "книг") for n in (1, 3, 5, 11, 21, 22)] == \
        ["книга", "книги", "книг", "книг", "книга", "книги"]
    assert set(i18n_en.EN_PLURAL) == {"книга", "аудиокнига", "минута", "день"}
