"""Внешний вид: тема и цвет акцента, значок приложения, горячие клавиши.
Примесь к App (app.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QKeySequence

from . import core, style
from .i18n import tr
from .core import APP_ID, log
from .widgets import HeaderBar

EBOOK_PATTERNS = "*.epub *.fb2 *.fb2.zip *.fbz *.mobi *.azw3"


# Горячие клавиши: действие, подпись, клавиши по умолчанию, метод App
SHORTCUTS = (
    ("sync", tr("Обновить библиотеку"), ["F5", "Ctrl+R"], "sync"),
    ("search", tr("Поиск"), ["Ctrl+F"], "_toggle_search"),
    ("open", tr("Открыть файл"), ["Ctrl+O"], "on_open_file"),
    ("graph", tr("Граф книг"), ["Ctrl+G"], "show_graph"),
    ("stats", tr("Статистика чтения"), [], "show_stats_dialog"),
    ("settings", tr("Настройки"), ["Ctrl+,"], "show_settings"),
    ("fullscreen", tr("Во весь экран"), ["F11"], "toggle_fullscreen"),
    ("back", tr("Назад"), ["Alt+Left"], "go_back"),
)


class Appearance:
    def shortcut_keys(self, action) -> list[str]:
        custom = (self.settings.get("shortcuts") or {}).get(action)
        if custom is not None:
            return [k for k in custom if k]
        return next(keys for a, _t, keys, _s in SHORTCUTS if a == action)

    def apply_shortcuts(self):
        for action, sc in self.shortcuts.items():
            sc.setKeys([QKeySequence(k) for k in self.shortcut_keys(action)])

    def apply_appearance(self):
        """Тема и цвет акцента из настроек (или системные) — сразу, без перезапуска."""
        style.set_overrides(self.settings.get("uiTheme"), self.settings.get("accent"))
        style.read_portal_scheme()
        self._on_theme_changed()

    def apply_app_icon(self, name):
        """Значок окна и — если приложение установлено — ярлыка в меню (тема значков пользователя)."""
        path = core.app_icon_path(name)
        icon = QIcon(str(path))
        self.qapp.setWindowIcon(icon)
        if getattr(self, "window", None) is not None:
            self.window.setWindowIcon(icon)
        if sys.platform.startswith("linux"):
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
            if not (base / "applications" / f"{APP_ID}.desktop").exists():
                return                      # не установлено (запуск из исходников) — ярлыка нет
            target = base / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
            try:
                data = path.read_bytes()
                if not target.exists() or target.read_bytes() != data:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    subprocess.Popen(["gtk-update-icon-cache", "-q", "-f", "-t", str(base / "icons" / "hicolor")],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                log("значок ярлыка не обновлён:", e)

    def _poll_theme(self):
        style.read_portal_scheme()
        style.read_accent()
        if (style.is_dark(), style.ACCENT) != self._scheme:
            self._on_theme_changed()

    def _on_theme_changed(self, *_):
        self._scheme = (style.is_dark(), style.ACCENT)
        style.apply_palette(self.qapp)
        for w in self.window.findChildren(HeaderBar):
            w.refresh_icons()
        for card in self.cards.values():
            card.refresh_icons()
            card.cover.update()
        self.sync_btn.refresh_icon()
        if self.reader:
            self.reader.refresh_style()
        if self.player_page:
            self.player_page.refresh_style()
        self._on_player_state()
