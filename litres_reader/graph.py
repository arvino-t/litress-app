"""Граф книг по тегам (как граф в Obsidian): книги и теги — узлы, связь «книга — тег» — ребро.

Теги: жанры и теги ЛитРес, ваши папки на ЛитРес, серии, авторы, папки своих книг и статей.
Рисует web/graph.html (d3-force + canvas), здесь — данные и страница приложения.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import style
from .core import SCHEME
from .reader import _ReaderWebPage, reader_profile
from .widgets import HeaderBar, IconButton

# (вид тега, название, цвет, включён по умолчанию)
KINDS = (
    ("genre", "Жанры", "#3584e4", True),
    ("folder", "Мои папки на ЛитРес", "#e5a50a", True),
    ("topic", "Темы своих книг и статей", "#c061cb", True),
    ("series", "Серии", "#9141ac", False),
    ("tag", "Теги ЛитРес", "#2ec27e", False),
    ("author", "Авторы", "#e66100", False),
)


def build_graph(lib) -> dict:
    """Узлы и рёбра для всех видов тегов; фильтрует уже страница."""
    dark = style.is_dark()
    status_color = {
        "reading": style.ACCENT,
        "finished": "#57e389" if dark else "#26a269",
        "unread": "#8f8d96" if dark else "#9a98a3",
    }
    nodes, links, tags = [], [], {}

    def tag(kind, name, bid):
        name = (name or "").strip()
        if not name:
            return
        tid = f"{kind}:{name.lower()}"
        tags.setdefault(tid, {"id": tid, "kind": kind, "label": name})
        links.append({"source": bid, "target": tid})

    for book in lib.ordered():
        bid = book["id"]
        authors = book.get("authors") or []
        status = lib.status(book)
        nodes.append({
            "id": bid, "kind": "book", "label": book.get("title") or bid,
            "sub": ", ".join(authors[:2]) or book.get("collection", ""),
            "src": "mine" if book.get("source") in ("folder", "local") else "litres",
            "pct": lib.percent(book) or 0,
            "color": status_color.get(status, status_color["unread"]),
        })
        for g in book.get("genres") or []:
            tag("genre", g, bid)
        for t in book.get("tags") or []:
            tag("tag", t, bid)
        for fid in book.get("folders") or []:
            tag("folder", lib.folders.get(fid), bid)
        if book.get("series"):
            tag("series", book["series"].get("name"), bid)
        for a in authors:
            tag("author", a, bid)
        if book.get("collection"):
            # «articles / security» → тема «security»; «others / cpp» → «cpp»
            parts = [p.strip() for p in book["collection"].split("/") if p.strip()]
            tag("topic", parts[1] if len(parts) > 1 else parts[0], bid)

    return {
        "nodes": nodes + list(tags.values()),
        "links": links,
        "kinds": [{"id": k, "label": label, "color": color, "on": on} for k, label, color, on in KINDS],
        "theme": {
            "dark": dark,
            "accent": style.ACCENT,
            "bg": "#1d1d20" if dark else "#fafafb",
            "text": "#f0eff3" if dark else "#241f31",
            "link": "#7d7a86" if dark else "#a8a5b0",
        },
    }


class GraphPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        self.ready = False
        self._layout_done = False
        self._fetch = None      # (готово, всего) — подгрузка жанров с ЛитРес

        self.header = HeaderBar(app.window, "Граф книг")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)

        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.web = QWebEngineView(self)
        self.page = _ReaderWebPage(reader_profile(), self._on_message, self)
        self.web.setPage(self.page)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.web, 1)
        self.page.load(QUrl(f"{SCHEME}://app/graph.html"))
        self._sync_subtitle()

    def _data_js(self) -> str:
        return json.dumps(build_graph(self.app.library), ensure_ascii=False)

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "ready":
            self.ready = True
            saved = self.app.settings.get("graph") or {}
            self.page.runJavaScript(f"window.graph.load({self._data_js()}, {json.dumps(saved)})")
        elif t == "open":
            self.app.on_book_activated(msg.get("id"))
        elif t == "state":
            self.app.settings["graph"] = msg.get("state") or {}
            self.app.save_settings()
        elif t == "escape":
            self.app.go_back()
        elif t == "layout-done":
            self._layout_done = True
            self._sync_subtitle()

    def set_fetch_progress(self, done: int, total: int):
        """Подгрузка жанров и тегов с ЛитРес: показываем в странице и в заголовке."""
        self._fetch = (done, total) if done < total else None
        if self.ready:
            if self._fetch:
                text = f"Загружаю жанры и теги с ЛитРес: {done} из {total}"
                self.page.runJavaScript(f"window.graph.status({json.dumps(text)}, {done / total:.3f})")
            else:
                self.page.runJavaScript("window.graph.status(null)")
        self._sync_subtitle()

    def _sync_subtitle(self):
        parts = []
        if not self._layout_done:
            parts.append("строю граф…")
        if self._fetch:
            parts.append(f"жанры с ЛитРес: {self._fetch[0]} из {self._fetch[1]}")
        text = " · ".join(parts)
        self.header.set_title("Граф книг", text[:1].upper() + text[1:])

    def refresh(self):
        """Данные поменялись (подгрузились жанры, обновилась библиотека)."""
        self._layout_done = False
        self._sync_subtitle()
        if self.ready:
            self.page.runJavaScript(f"window.graph.update({self._data_js()})")
