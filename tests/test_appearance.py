"""Внешний вид: значки приложения на выбор, тема и акцент, горячие клавиши по умолчанию."""
from muninhall import core, style


def test_all_app_icons_exist_and_are_svg():
    for name in core.APP_ICON_NAMES:
        p = core.app_icon_path(name)
        assert p.parent == core.APP_ICONS_DIR and p.read_text().lstrip().startswith("<svg"), name
    assert core.app_icon_path("nonexistent") == core.APP_ICON


def test_theme_and_accent_overrides():
    style.set_overrides("dark", "#e62d42")
    assert style.is_dark() and style.ACCENT == "#e62d42"
    style.set_overrides("light", None)
    assert not style.is_dark() and style.ACCENT != "#e62d42"
    style.set_overrides("auto", "auto")
    assert style.FORCED_SCHEME is None and style.FORCED_ACCENT is None


def test_default_shortcuts_unique():
    from muninhall.app import SHORTCUTS
    keys = [k for _a, _t, ks, _s in SHORTCUTS for k in ks]
    assert len(keys) == len(set(keys))
    assert len({a for a, *_ in SHORTCUTS}) == len(SHORTCUTS)
