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
    from muninhall.appearance import SHORTCUTS
    keys = [k for _a, _t, ks, _s in SHORTCUTS for k in ks]
    assert len(keys) == len(set(keys))
    assert len({a for a, *_ in SHORTCUTS}) == len(SHORTCUTS)


def test_cover_thumb_downscales_and_caches(tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QColor
    from muninhall import widgets
    src = tmp_path / "cover.jpg"
    img = QImage(900, 1300, QImage.Format.Format_RGB32)
    img.fill(QColor("#3584e4"))
    img.save(str(src), "JPG")
    widgets.THUMBS_DIR = tmp_path / "thumbs"
    widgets._THUMBS.clear()
    pm = widgets.cover_thumb(src, QSize(132, 192), 1.0)
    assert pm is not None and pm.width() <= 140 and pm.height() >= 192        # декодирована уменьшенной
    assert widgets.cover_thumb(src, QSize(132, 192), 1.0) is pm               # из памяти
    widgets._THUMBS.clear()
    assert len(list((tmp_path / "thumbs").iterdir())) == 1                    # и на диске
    assert widgets.cover_thumb(src, QSize(132, 192), 1.0).height() == pm.height()


def test_elide_lines():
    from PySide6.QtGui import QFont, QFontMetrics
    from muninhall.widgets import elide_lines
    fm = QFontMetrics(QFont())
    assert elide_lines(fm, "Короткое", 132, 2) == "Короткое"
    long = "Очень длинное название книги " * 10
    out = elide_lines(fm, long, 132, 2)
    assert out.endswith("…") and len(out) < len(long)


def test_scope_from_filter():
    from muninhall.libraries import scope_from_filter
    assert [scope_from_filter(k) for k in ("all", "litres", "text", "audio", "lib:folder-0123456789")] == \
        ["all", "litres", "litres", "litres", "folder-0123456789"]


def test_library_scope_combo(tmp_path):
    from muninhall.widgets import LibraryScopeCombo
    settings = {"libraries": [{"id": "litres", "kind": "litres"},
                              {"id": "folder-0123456789", "kind": "folder", "name": "Статьи", "path": str(tmp_path)}]}
    combo = LibraryScopeCombo(settings, "folder-0123456789")
    assert combo.scopes() == ["all", "litres", "folder-0123456789"] and combo.scope() == "folder-0123456789"
    seen = []
    combo.scope_changed.connect(seen.append)
    combo.setCurrentIndex(1)
    assert seen == ["litres"]
    combo.refill("missing")                         # неизвестная — остаётся текущая
    assert combo.scope() == "litres"


def test_settings_autosave_and_signal(tmp_path):
    import json
    from PySide6.QtCore import QCoreApplication
    from muninhall.config import Settings
    path = tmp_path / "settings.json"
    st = Settings(path, defaults={"fontSize": 19})
    seen = []
    st.changed.connect(seen.append)
    st["fontSize"] = 24
    assert seen == ["fontSize"] and st.get("fontSize") == 24 and dict(st) == {"fontSize": 24}
    assert not path.exists()                         # запись — пачкой, через полсекунды
    st.save_now()
    assert json.loads(path.read_text()) == {"fontSize": 24}
    assert Settings(path, defaults={"fontSize": 19, "theme": "auto"}).as_dict() == {"fontSize": 24, "theme": "auto"}
    st.pop("fontSize")
    assert "fontSize" not in st and seen[-1] == "fontSize"
    QCoreApplication.processEvents()
