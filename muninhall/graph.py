"""Граф книг по тегам (как граф в Obsidian): книги и теги — узлы, связь «книга — тег» — ребро.

Теги: жанры и теги ЛитРес, ваши папки на ЛитРес, серии, авторы, папки своих книг и статей.
Рисует web/graph.html (d3-force + canvas), здесь — данные и страница приложения.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import libraries, style
from .core import SCHEME, STORE_GRAPH, folder_store_dir, load_json, save_json
from .reader import _ReaderWebPage, reader_profile
from .widgets import (HeaderBar, IconButton, LibraryScopeCombo)
from .i18n import tr, web_strings

# (вид тега, название, цвет, включён по умолчанию)
KINDS = (
    ("genre", tr("Жанры"), "#3584e4", True),
    ("folder", tr("Мои папки на ЛитРес"), "#e5a50a", True),
    ("topic", tr("Темы своих книг и статей"), "#c061cb", True),
    ("series", tr("Серии"), "#9141ac", False),
    ("tag", tr("Теги ЛитРес"), "#2ec27e", False),
    ("author", tr("Авторы"), "#e66100", False),
)


def in_scope(book, scope: str) -> bool:
    """scope: "all" — все библиотеки, "litres" — ЛитРес, иначе id своей библиотеки."""
    if scope == "all":
        return True
    if scope == "litres":
        return book.get("source") == "litres"
    return book.get("library") == scope


def build_graph(lib, scope: str = "all") -> dict:
    """Узлы и рёбра для всех видов тегов выбранной библиотеки; фильтрует уже страница."""
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
        if not in_scope(book, scope):
            continue
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
        "single": scope != "all",          # одна библиотека — переключатель «ЛитРес / Мои» не нужен
        "i18n": web_strings(),
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

        self.header = HeaderBar(app.window, tr("Граф книг"))
        back = IconButton("go-previous", tr("Назад"))
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)
        # у каждой библиотеки свой граф; «Все» — общий
        self.scope = "all"
        self.scope_combo = LibraryScopeCombo(app.settings)
        self.scope_combo.scope_changed.connect(self.set_scope)
        self.header.pack_end(self.scope_combo)

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
        return json.dumps(build_graph(self.app.library, self.scope), ensure_ascii=False)

    # --- выбор библиотеки и состояние графа по библиотекам

    def fill_scopes(self, scope=None):
        self.scope_combo.refill(scope if scope else self.scope)
        if self.scope_combo.scope() != self.scope:
            self.set_scope(self.scope_combo.scope())

    def set_scope(self, scope):
        self.scope = scope
        self._layout_done = False
        self._sync_subtitle()
        if self.ready:
            self.page.runJavaScript(f"window.graph.load({self._data_js()}, {json.dumps(self._load_state())})")

    def _state_file(self):
        """Своя библиотека — graph.json в её .library; ЛитРес и «Все» — в настройках."""
        lib = next((l for l in libraries.folder_libraries(self.app.settings) if l["id"] == self.scope), None)
        return folder_store_dir(lib["path"], lib["id"]) / STORE_GRAPH if lib else None

    def _load_state(self) -> dict:
        path = self._state_file()
        if path:
            return load_json(path, {})
        states = self.app.settings.get("graphStates") or {"all": self.app.settings.get("graph") or {}}
        return states.get(self.scope) or {}

    def _save_state(self, state):
        path = self._state_file()
        if path:
            try:
                save_json(path, state)
            except OSError:
                pass
            return
        states = dict(self.app.settings.get("graphStates") or {"all": self.app.settings.get("graph") or {}})
        states[self.scope] = state
        self.app.settings["graphStates"] = states
        self.app.save_settings()

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "ready":
            self.ready = True
            self.page.runJavaScript(f"window.graph.load({self._data_js()}, {json.dumps(self._load_state())})")
        elif t == "open":
            self.app.on_book_activated(msg.get("id"))
        elif t == "state":
            self._save_state(msg.get("state") or {})
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
                text = tr('Загружаю жанры и теги с ЛитРес: {0} из {1}', done, total)
                self.page.runJavaScript(f"window.graph.status({json.dumps(text)}, {done / total:.3f})")
            else:
                self.page.runJavaScript("window.graph.status(null)")
        self._sync_subtitle()

    def _sync_subtitle(self):
        parts = []
        if not self._layout_done:
            parts.append(tr("строю граф…"))
        if self._fetch:
            parts.append(tr('жанры с ЛитРес: {0} из {1}', self._fetch[0], self._fetch[1]))
        text = " · ".join(parts)
        self.header.set_title(tr("Граф книг"), text[:1].upper() + text[1:])

    def refresh(self):
        """Данные поменялись (подгрузились жанры, обновилась библиотека)."""
        self._layout_done = False
        self._sync_subtitle()
        if self.ready:
            self.page.runJavaScript(f"window.graph.update({self._data_js()})")
