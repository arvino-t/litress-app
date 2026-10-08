"""Оформление в стиле GNOME/libadwaita: палитры, таблица стилей и символьные значки.

Цвета взяты из libadwaita, чтобы приложение выглядело одинаково на Linux и Windows.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .core import CACHE_DIR, ICONS_DIR

ACCENT = "#3584e4"

PALETTES = {
    "dark": {
        "window": "#222226", "view": "#1d1d20", "header": "#2e2e32", "card": "#2e2e32",
        "fg": "#ffffff", "dim": "rgba(255,255,255,0.55)", "border": "rgba(255,255,255,0.1)",
        "button": "rgba(255,255,255,0.1)", "button_hover": "rgba(255,255,255,0.15)",
        "button_active": "rgba(255,255,255,0.3)", "flat_hover": "rgba(255,255,255,0.07)",
        "accent_fg": "#78aeed", "placeholder": "rgba(53,132,228,0.18)",
        "popover": "#36363a", "toast": "#3a3a3e", "success": "#26a269",
        "slider_track": "rgba(255,255,255,0.15)", "entry": "rgba(255,255,255,0.1)",
    },
    "light": {
        "window": "#fafafb", "view": "#ffffff", "header": "#ffffff", "card": "#ffffff",
        "fg": "rgba(0,0,6,0.8)", "dim": "rgba(0,0,6,0.5)", "border": "rgba(0,0,6,0.15)",
        "button": "rgba(0,0,6,0.1)", "button_hover": "rgba(0,0,6,0.15)",
        "button_active": "rgba(0,0,6,0.3)", "flat_hover": "rgba(0,0,6,0.07)",
        "accent_fg": "#1c71d8", "placeholder": "rgba(53,132,228,0.18)",
        "popover": "#ffffff", "toast": "#3a3a3e", "success": "#2ec27e",
        "slider_track": "rgba(0,0,6,0.15)", "entry": "rgba(0,0,6,0.06)",
    },
}


_portal_scheme: int | None = None   # 0 — нет предпочтения, 1 — тёмная, 2 — светлая


def read_portal_scheme() -> int | None:
    """Тема GNOME/KDE через портал org.freedesktop.appearance (так её узнаёт и GTK).

    Qt из pip на GNOME тёмную тему сам не определяет, поэтому спрашиваем портал.
    """
    global _portal_scheme
    if not sys.platform.startswith("linux"):
        return None
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        iface = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                               "org.freedesktop.portal.Settings", QDBusConnection.sessionBus())
        args = iface.call("ReadOne", "org.freedesktop.appearance", "color-scheme").arguments()
        value = args[0].variant() if args and hasattr(args[0], "variant") else None
        _portal_scheme = int(value) if value is not None else None
    except Exception:  # noqa: BLE001 — нет D-Bus или портала: остаётся мнение Qt
        _portal_scheme = None
    return _portal_scheme


# Именованные акценты GNOME (libadwaita) → цвет
GNOME_ACCENTS = {
    "blue": "#3584e4", "teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800",
    "orange": "#ed5b00", "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac", "slate": "#6f8396",
}


def read_accent() -> str:
    """Цвет акцента системы: на GNOME — из настроек, на Windows — из палитры Qt."""
    global ACCENT
    accent = None
    if sys.platform.startswith("linux"):
        try:
            import subprocess
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "accent-color"],
                                 capture_output=True, text=True, timeout=2).stdout.strip().strip("'")
            accent = GNOME_ACCENTS.get(out)
        except (OSError, subprocess.SubprocessError):
            accent = None
    if accent is None:
        c = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
        if c.isValid() and c.alpha() and hasattr(QPalette.ColorRole, "Accent"):
            accent = c.name()
    ACCENT = accent or "#3584e4"
    return ACCENT


def accent_rgba(alpha: float) -> str:
    c = QColor(ACCENT)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def is_dark() -> bool:
    if _portal_scheme in (1, 2):
        return _portal_scheme == 1
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def colors() -> dict:
    return PALETTES["dark" if is_dark() else "light"]


def solid_fg() -> QColor:
    """Цвет значков: в тёмной теме белый, в светлой — почти чёрный."""
    return QColor("#ffffff") if is_dark() else QColor(0, 0, 6, 204)


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    return (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")


def icon(name: str, color: QColor | str | None = None, size: int = 16) -> QIcon:
    """Символьный значок Adwaita, перекрашенный в нужный цвет (как делает GTK)."""
    c = QColor(color) if color is not None else solid_fg()
    hex_color = c.name(QColor.NameFormat.HexRgb)
    svg = re.sub(r'fill="#[0-9a-fA-F]{3,6}"', f'fill="{hex_color}"', _svg(name))
    svg = svg.replace("currentColor", hex_color)
    svg = re.sub(r"fill:#[0-9a-fA-F]{3,6}", f"fill:{hex_color}", svg)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2, 3):
        img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setOpacity(c.alphaF())
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(scale)
        result.addPixmap(pix)
    return result


def icon_file(name: str, color: str) -> str:
    """Перекрашенный значок в файле — для таблицы стилей (стрелки списков и т.п.)."""
    out = CACHE_DIR / "icons" / f"{name}-{color.strip('#')}.svg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        svg = re.sub(r'fill="#[0-9a-fA-F]{3,6}"', f'fill="{color}"', _svg(name))
        out.write_text(svg, encoding="utf-8")
    return out.as_posix()


def icon_size(px: int = 16) -> QSize:
    return QSize(px, px)


def apply_palette(app):
    """Базовая палитра Qt (для стандартных виджетов) под текущую тему."""
    c = colors()
    pal = QPalette()
    dark = is_dark()
    fg = QColor("#ffffff") if dark else QColor(0, 0, 6, 204)
    pal.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["view"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["header"]))
    pal.setColor(QPalette.ColorRole.WindowText, fg)
    pal.setColor(QPalette.ColorRole.Text, fg)
    pal.setColor(QPalette.ColorRole.ButtonText, fg)
    pal.setColor(QPalette.ColorRole.Button, QColor(c["header"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["popover"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, fg)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(128, 128, 128))
    link = QColor(ACCENT).lighter(135) if dark else QColor(ACCENT).darker(115)
    pal.setColor(QPalette.ColorRole.Link, link)
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())


def app_font() -> QFont:
    f = QFont()
    f.setFamilies(["Adwaita Sans", "Inter Variable", "Inter", "Cantarell", "Segoe UI Variable",
                   "Segoe UI", "sans-serif"])
    f.setPointSizeF(10.5)
    return f


def stylesheet() -> str:
    c = colors()
    acc_hover = QColor(ACCENT).lighter(112).name()
    acc_pressed = QColor(ACCENT).darker(118).name()
    return f"""
    QMainWindow, QDialog, #page {{ background: {c['window']}; color: {c['fg']}; }}
    QWidget {{ color: {c['fg']}; }}
    QToolTip {{ background: {c['popover']}; color: {c['fg']}; border: 1px solid {c['border']};
               border-radius: 6px; padding: 4px 8px; }}

    /* Заголовок окна (как Adw.HeaderBar) */
    #headerbar {{ background: {c['header']}; border-bottom: 1px solid {c['border']}; }}
    #title {{ font-weight: bold; font-size: 11pt; }}
    #subtitle {{ color: {c['dim']}; font-size: 9pt; }}

    /* Кнопки */
    QPushButton, QToolButton {{
        background: {c['button']}; border: none; border-radius: 6px;
        padding: 6px 12px; min-height: 22px; font-weight: bold;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {c['button_hover']}; }}
    QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{ background: {c['button_active']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {c['dim']}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    *[cls~="flat"] {{ background: transparent; }}
    *[cls~="flat"]:hover {{ background: {c['flat_hover']}; }}
    *[cls~="flat"]:pressed, *[cls~="flat"]:checked {{ background: {c['button']}; }}
    *[cls~="circular"] {{ border-radius: 17px; min-width: 22px; padding: 6px; }}
    *[cls~="suggested"] {{ background: {ACCENT}; color: white; }}
    *[cls~="suggested"]:hover {{ background: {acc_hover}; }}
    *[cls~="suggested"]:pressed {{ background: {acc_pressed}; }}
    *[cls~="destructive"] {{ background: #c01c28; color: white; }}
    *[cls~="pill"] {{ border-radius: 20px; padding: 10px 32px; }}
    *[cls~="play"] {{ background: {ACCENT}; border-radius: 32px; min-width: 64px; min-height: 64px;
             max-width: 64px; max-height: 64px; padding: 0; }}
    *[cls~="play"]:hover {{ background: {acc_hover}; }}

    /* Кнопки окна: свернуть/развернуть/закрыть */
    *[cls~="wincontrol"] {{ background: {c['button']}; border-radius: 12px; padding: 0;
                   min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }}
    *[cls~="wincontrol"]:hover {{ background: {c['button_hover']}; }}

    /* Сегментированные кнопки (linked) */
    *[cls~="linked"] {{ border-radius: 0; }}
    *[cls~="linked-first"] {{ border-top-right-radius: 0; border-bottom-right-radius: 0;
                     border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    *[cls~="linked-last"] {{ border-top-left-radius: 0; border-bottom-left-radius: 0;
                    border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    *[cls~="linked"]:checked, *[cls~="linked-first"]:checked, *[cls~="linked-last"]:checked {{
        background: {c['button_active']}; }}

    /* Выпадающие списки */
    QComboBox {{ background: {c['button']}; border: none; border-radius: 6px;
                 padding: 6px 12px; min-height: 22px; font-weight: bold; }}
    QComboBox:hover {{ background: {c['button_hover']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{icon_file('pan-down', '#ffffff' if is_dark() else '#1e1e20')}");
                             width: 16px; height: 16px; }}
    QComboBox QAbstractItemView {{ background: {c['popover']}; border: 1px solid {c['border']};
        border-radius: 8px; padding: 4px; outline: none; selection-background-color: {c['button']}; }}

    /* Поля ввода */
    QLineEdit {{ background: {c['entry']}; border: 2px solid transparent; border-radius: 6px;
                 padding: 6px 8px; selection-background-color: {ACCENT}; }}
    QLineEdit:focus {{ border: 2px solid {accent_rgba(0.5)}; }}

    /* Прокрутка */
    QScrollArea, #grid {{ background: {c['window']}; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['button_hover']}; border-radius: 3px; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['button_active']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* Ползунки */
    QSlider::groove:horizontal {{ height: 4px; background: {c['slider_track']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #ffffff; width: 20px; height: 20px; margin: -8px 0;
                                  border-radius: 10px; border: 1px solid rgba(0,0,0,0.15); }}

    /* Карточки книг */
    #bookcard {{ background: transparent; border-radius: 12px; }}
    #bookcard:hover {{ background: {c['flat_hover']}; }}
    #booktitle {{ font-weight: bold; }}
    *[cls~="dim"] {{ color: {c['dim']}; }}
    *[cls~="caption"] {{ font-size: 9pt; }}
    *[cls~="title1"] {{ font-size: 20pt; font-weight: 800; }}
    *[cls~="title2"] {{ font-size: 15pt; font-weight: 800; }}
    *[cls~="heading"] {{ font-weight: bold; }}

    /* Всплывающие панели и меню (как Gtk.Popover) */
    #popover {{ background: {c['popover']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    QMenu {{ background: {c['popover']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['flat_hover']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 6px 4px; }}
    QMenu::indicator {{ width: 0; }}

    /* Списки в стиле boxed-list */
    *[cls~="boxed"] {{ background: {c['card']}; border-radius: 12px; border: 1px solid {c['border']}; }}
    *[cls~="row"] {{ border-bottom: 1px solid {c['border']}; }}
    *[cls~="separator-line"] {{ background: {c['border']}; border: none; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
    QListWidget::item:hover, QListWidget::item:selected {{ background: {c['flat_hover']}; color: {c['fg']}; }}

    /* Уведомления внизу окна (Adw.Toast) */
    #toast {{ background: {c['toast']}; color: white; border-radius: 22px; }}
    #toast QLabel {{ color: white; }}
    #toast QPushButton {{ background: transparent; color: #99c1f1; padding: 4px 10px; }}
    #toast QPushButton:hover {{ background: rgba(255,255,255,0.1); }}

    /* Панель «Продолжить чтение» справа в библиотеке */
    #sidepanel {{ background: {c['header']}; border-left: 1px solid {c['border']}; }}
    *[cls~="recentcard"] {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    *[cls~="recentcard"]:hover {{ background: {c['flat_hover']}; }}
    QProgressBar {{ background: {c['slider_track']}; border: none; border-radius: 3px; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

    /* Панели читалки */
    #readerbar {{ background: {c['header']}; }}
    """
