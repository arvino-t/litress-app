"""Прогон основных сценариев на установленной сборке (запускать через tools/flow_check.sh).

Окна и меню не показываются (exec подменён), данные библиотек (`.library`) пишутся в STORES —
реальные папки книг не меняются. Печатает ok/FAIL по шагам и число неперехваченных исключений.
"""
import sys
import traceback
from pathlib import Path

STORES = Path(sys.argv[1])
import muninhall.core as core  # noqa: E402

core.folder_store_dir = lambda root, lib_id, create=False: (STORES / lib_id)
from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

import muninhall.app as A  # noqa: E402

errors = []
sys.excepthook = lambda *e: (errors.append(1), print("EXC", "".join(traceback.format_exception(*e))))
QMessageBox.exec = lambda self: 0
QMenu.exec = lambda self, *a, **k: None
QMenu.popup = lambda self, *a, **k: None
QDialog.exec = lambda self: (QTimer.singleShot(0, self.accept), 0)[1]
holder = {}
steps = []


class P(A.App):
    def __init__(self, q):
        super().__init__(q)
        holder["a"] = self
        QTimer.singleShot(5000, run)


def step(name, fn):
    try:
        fn()
        steps.append(f"ok   {name}")
    except Exception:
        steps.append(f"FAIL {name}\n{traceback.format_exc()}")


def run():
    a = holder["a"]
    v = a.library_view
    books = a.library.ordered()
    lit = next((b for b in books if b.get("source") == "litres"), None)
    own = next((b for b in books if b.get("source") == "folder"), None)

    def reader_page():
        book = next(b for b in books if str(a.library.file_path(b) or "").endswith((".epub", ".fb2", ".pdf")))
        a.open_book(book, a.library.file_path(book))
        r = a.reader
        r._on_message({"type": "relocate", "fraction": 0.3, "chapter": "Глава"})
        before = a.settings["fontSize"]
        r._on_message({"type": "pinch", "scale": 1.2})
        r.change_font_size(-2)
        for t in ("toggle-ui", "toggle-ui", "unknown"):
            r._on_message({"type": t})
        print("  читалка:", book.get("title", "")[:30], "· процент", r.percent.text(),
              "· шрифт", before, "→", a.settings["fontSize"], "· метка", r.size_label.text())
        a.go_back()

    def player_page():
        from muninhall.player import PlayerPage
        audio = next(b for b in books if b.get("is_audio"))
        page = PlayerPage(a, audio)
        page._set_sleep(-1)
        page._set_sleep(0)
        print("  плеер:", audio.get("title", "")[:30], "· скорость", page.speed.currentText())
        page.deleteLater()

    def singularity_class():
        from muninhall.singularity import SingularityDialog
        d = SingularityDialog(a)
        d.apply()
        print("  singularity: переключателей", len(d.switches), "+", len(d.lib_switches))
        d.dlg.deleteLater()

    def recent_resize():
        """Изменение размера окна пересчитывает панель «Продолжить чтение» (прячется уже 900 px)."""
        calls = []
        orig = v.update_recent_panel
        v.update_recent_panel = lambda: (calls.append(1), orig())
        a.window.resize(a.window.width() + 50, a.window.height())
        QApplication.processEvents()
        v.update_recent_panel = orig
        print("  панель «Продолжить»: пересчётов при изменении размера", len(calls),
              "· минимальная ширина окна", a.window.minimumSizeHint().width())
        assert calls

    def graph_signals():
        a.show_graph()
        a.litres_lib.details_progress.emit(3, 10)
        f = a.graph_page._fetch
        a.litres_lib.details_progress.emit(10, 10)
        a.litres_lib.details_changed.emit()
        print("  граф: прогресс", f, "→", a.graph_page._fetch)
        assert f == (3, 10) and a.graph_page._fetch is None
        a.go_back()
        a.litres_lib.details_changed.emit()          # страница графа закрыта — сигнал никуда не падает

    step("cards", lambda: print("  карточек:", len(v.cards), "из", len(books)))
    for k in list(v._type_keys):
        step(f"filter {k[:16]}", lambda k=k: (v._set_type_filter(k), print(
            f"  {k[:22]:22} видно {sum(1 for c in v.cards.values() if not c.isHidden())}")))
    step("search", lambda: (v._toggle_search(), v.search.setText("a"), v._apply_filter(), v.search.setText("")))
    step("sort", lambda: [v._on_sort_selected(i) for i in range(3)])
    step("book menu", lambda: [v.show_book_menu(b["id"], QPoint(1, 1)) for b in (lit, own) if b])
    if lit:
        step("folders dialog", lambda: a.litres_lib.show_folders_dialog(lit))
    step("reader page", reader_page)
    step("player page", player_page)
    step("recent panel resize", recent_resize)
    step("stats dialog", a.show_stats_dialog)
    step("singularity dialog", a.show_singularity_dialog)
    step("singularity dialog class", singularity_class)
    step("graph", lambda: (a.show_graph(), a.go_back()))
    step("graph signals", graph_signals)
    step("settings tabs", lambda: [(a.show_settings(), a.settings_page.show_tab(k)) for k in (
        "general", "libraries", "appearance", "reading", "integrations", "backup", "advanced")])
    step("appearance", lambda: (a.settings.__setitem__("uiTheme", "light"), a.apply_appearance(),
                                a.settings.__setitem__("uiTheme", "dark"), a.apply_appearance(),
                                a.apply_app_icon("moon")))
    step("shortcuts", lambda: (a.shortcuts["graph"].activated.emit(), a.go_back(), a.apply_shortcuts()))
    step("sync (no login)", lambda: a.sync())
    step("download all", a.download_all)
    a.pop_to_library()
    step("disconnect/connect litres", lambda: (
        setattr(QMessageBox, "clickedButton",
                lambda self: [b for b in self.buttons() if b.text() in ("Отключить", "Disconnect")][0]),
        a.disconnect_litres(), a.connect_litres()))
    step("about", a.on_about)
    if own:
        step("set finished own", lambda: a.set_finished(own, True))
    QTimer.singleShot(2500, finish)


def finish():
    print("\n".join(steps))
    print("uncaught:", len(errors))
    QApplication.instance().quit()


A.App = P
A.main(["muninhall"])
