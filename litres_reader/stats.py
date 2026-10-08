"""Окно «Статистика чтения»: минуты по дням, серия дней подряд, дочитанные книги."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from . import style
from .i18n import plural, tr
from .widgets import HeaderBar, IconButton, cls, label


def minutes_word(n: int) -> str:
    return plural(n, "минута", "минуты", "минут")


def days_word(n: int) -> str:
    return plural(n, "день", "дня", "дней")


def streak(days: dict) -> int:
    """Сколько дней подряд (до сегодня или вчера включительно) было чтение."""
    day = dt.date.today()
    if days.get(day.isoformat(), 0) < 60:
        day -= dt.timedelta(days=1)   # сегодня ещё не читали — серия не прервана
    n = 0
    while days.get(day.isoformat(), 0) >= 60:
        n += 1
        day -= dt.timedelta(days=1)
    return n


class BarChart(QWidget):
    """Минуты чтения за последние N дней — столбики в цвете акцента."""

    def __init__(self, days: dict, remote: dict | None = None, count=14):
        super().__init__()
        today = dt.date.today()
        self.items = [(today - dt.timedelta(days=i)) for i in range(count - 1, -1, -1)]
        self.values = [days.get(d.isoformat(), 0) / 60 for d in self.items]
        # часть дня, прочитанная на телефоне/сайте ЛитРес (оценка)
        remote = remote or {}
        self.remote = [min(remote.get(d.isoformat(), 0) / 60, v) for d, v in zip(self.items, self.values)]
        self.setMinimumHeight(180)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = style.colors()
        w, h = self.width(), self.height()
        n = len(self.values)
        top = max(self.values + [10])
        base = h - 22
        slot = w / n
        bar = slot * 0.62
        dim = QColor(c["dim"]) if c["dim"].startswith("#") else style.solid_fg()
        for i, (d, v) in enumerate(zip(self.items, self.values)):
            x = i * slot + (slot - bar) / 2
            bh = (base - 18) * (v / top)
            color = QColor(style.ACCENT)
            if v == 0:
                color = QColor(style.solid_fg())
                color.setAlpha(40)
                bh = 3
            p.setPen(Qt.PenStyle.NoPen)
            r = self.remote[i]
            if v > 0 and r > 0:
                # низ столбика — чтение в приложении, верх (светлее) — на телефоне/сайте ЛитРес
                rh = bh * r / v
                light = QColor(style.ACCENT)
                light.setAlpha(105)
                p.setBrush(light)
                p.drawRoundedRect(QRectF(x, base - bh, bar, rh), 4, 4)
                if bh - rh > 0.5:
                    p.setBrush(color)
                    p.drawRoundedRect(QRectF(x, base - bh + rh, bar, bh - rh), 4, 4)
            else:
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x, base - bh, bar, bh), 4, 4)
            p.setPen(dim)
            f = p.font()
            f.setPointSizeF(8)
            p.setFont(f)
            p.drawText(QRectF(i * slot, base + 4, slot, 16), Qt.AlignmentFlag.AlignCenter, f"{d.day}")
            if v >= 1:
                p.drawText(QRectF(i * slot, base - bh - 16, slot, 14), Qt.AlignmentFlag.AlignCenter, f"{round(v)}")
        p.end()


def tile(value: str, caption: str) -> QFrame:
    f = QFrame()
    cls(f, "recentcard")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 10, 14, 10)
    v.setSpacing(0)
    v.addWidget(label(value, "title2"))
    v.addWidget(label(caption, "dim", "caption"))
    return f


def show_stats(app):
    lib = app.library
    days = lib.stats.get("days", {})
    remote = lib.stats.get("remote_days", {})
    week_remote = sum(remote.get((dt.date.today() - dt.timedelta(days=i)).isoformat(), 0) for i in range(7)) // 60
    today_remote = remote.get(dt.date.today().isoformat(), 0) // 60
    today = dt.date.today()
    week = sum(days.get((today - dt.timedelta(days=i)).isoformat(), 0) for i in range(7)) // 60
    today_min = days.get(today.isoformat(), 0) // 60
    month = today.strftime("%Y-%m")
    finished_month = sum(1 for d in lib.stats.get("finished", {}).values() if d.startswith(month))
    total_finished = len(lib.stats.get("finished", {}))
    st = streak(days)

    dlg = QDialog(app.window, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dlg.setMinimumWidth(620)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    header = HeaderBar(dlg, tr("Статистика чтения"), show_controls=False)
    close = IconButton("window-close", tr("Закрыть"), flat=False)
    cls(close, "wincontrol")
    close.clicked.connect(dlg.accept)
    header.pack_end(close)
    outer.addWidget(header)

    body = QWidget()
    b = QVBoxLayout(body)
    b.setContentsMargins(18, 18, 18, 18)
    b.setSpacing(14)
    tiles = QGridLayout()
    tiles.setSpacing(10)
    phone = lambda m: tr('\nиз них на телефоне ~{0}', m) if m else ""
    tiles.addWidget(tile(f"{today_min}", tr('{0} сегодня{1}', minutes_word(today_min), phone(today_remote))), 0, 0)
    tiles.addWidget(tile(f"{week}", tr('{0} за неделю{1}', minutes_word(week), phone(week_remote))), 0, 1)
    tiles.addWidget(tile(f"{st}", tr('{0} подряд', days_word(st))), 0, 2)
    tiles.addWidget(tile(f"{finished_month}", tr('дочитано в этом месяце · всего {0}', total_finished)), 0, 3)
    b.addLayout(tiles)

    b.addWidget(label(tr("Последние две недели, минут в день"), "heading"))
    b.addWidget(BarChart(days, remote))
    if any(remote.values()):
        b.addWidget(label(tr("Светлая часть столбика — чтение на телефоне или сайте ЛитРес. "
                          "Оценка по приросту процента: текст — ~1300 знаков в минуту, аудио — по длительности."),
                          "dim", "caption", wrap=True))

    top = sorted(lib.stats.get("books", {}).items(), key=lambda kv: -kv[1])[:5]
    top = [(lib.books[bid], sec) for bid, sec in top if bid in lib.books]
    if top:
        b.addWidget(label(tr("Больше всего времени"), "heading"))
        box = QFrame()
        cls(box, "boxed")
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for book, sec in top:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 8, 14, 8)
            h.addWidget(label(book.get("title") or "", wrap=True), 1)
            if book.get("is_audio"):
                h.addWidget(label(tr("аудио"), "dim", "caption"))
            hours, mins = divmod(int(sec) // 60, 60)
            h.addWidget(label(tr('{0} ч {1} мин', hours, mins) if hours else tr('{0} мин', mins), "dim"))
            rows.addWidget(row)
        b.addWidget(box)
    else:
        b.addWidget(label(tr("Пока пусто — статистика копится, пока вы читаете и слушаете."), "dim", wrap=True))
    outer.addWidget(body)

    frame = QFrame(dlg)
    frame.setObjectName("popover")
    frame.lower()
    dlg.resizeEvent = lambda e: frame.setGeometry(dlg.rect())
    dlg.exec()
