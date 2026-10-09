"""Модель библиотеки: книги ЛитРес, свои папки, статусы и проценты."""
from pathlib import Path

from muninhall.core import Library


def art(id_, **kw):
    return {"id": id_, "title": f"Книга {id_}", "persons": [{"role": "author", "full_name": "Автор"}], **kw}


def test_merge_litres_adds_books_and_keeps_order(clean_data):
    lib = Library()
    lib.merge_litres([art(1), art(2, art_type=1, read_percent=40), art("bad/../id")])
    assert [b["id"] for b in lib.ordered()] == ["1", "2"]       # некорректный id отброшен
    assert lib.books["1"]["authors"] == ["Автор"]
    assert lib.books["2"]["is_audio"] is True
    assert lib.percent(lib.books["2"]) == 40


def test_status_and_percent(clean_data):
    lib = Library()
    lib.merge_litres([art(1), art(2, is_finished=True), art(3)])
    lib.progress["3"] = {"fraction": 0.25}
    assert lib.status(lib.books["1"]) == "unread"
    assert lib.status(lib.books["2"]) == "finished"
    assert lib.status(lib.books["3"]) == "reading"
    assert lib.percent(lib.books["3"]) == 25
    assert lib.percent(lib.books["1"]) is None


def test_remote_reading_goes_to_stats(clean_data):
    lib = Library()
    lib.merge_litres([art(1, read_percent=10, symbols_count=130_000, read_at="2026-10-01T10:00:00+03:00")])
    lib.merge_litres([art(1, read_percent=20, symbols_count=130_000, read_at="2026-10-02T10:00:00+03:00")])
    # 10% от 130 000 знаков при 1300 зн/мин = 10 минут
    assert lib.stats["books"]["1"] == 600
    assert sum(lib.stats["remote_days"].values()) == 600


def make_tree(root: Path):
    for rel in ("a.epub", "sub/b.pdf", "sub/deep/c.fb2", "sub/skip.txt", ".hidden/d.epub"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_scan_folders_sections_and_subfolders(clean_data, tmp_path):
    make_tree(tmp_path / "articles")
    lib = Library()
    n = lib.scan_folders([{"path": str(tmp_path / "articles"), "name": "Статьи"}])
    assert n == 3                                               # txt и скрытая папка пропущены
    by_title = {b["title"]: b for b in lib.books.values()}
    assert by_title["a"]["collection"] == "Статьи"
    assert by_title["b"]["collection"] == "Статьи / sub"
    assert by_title["c"]["collection"] == "Статьи / sub/deep"
    assert all(b["source"] == "folder" and b["section"] == "Статьи" for b in by_title.values())


def test_scan_folders_rename_and_remove(clean_data, tmp_path):
    make_tree(tmp_path / "articles")
    lib = Library()
    folder = {"path": str(tmp_path / "articles"), "name": "Статьи"}
    lib.scan_folders([folder])
    lib.scan_folders([{**folder, "name": "Papers"}])            # переименовали раздел
    assert {b["section"] for b in lib.books.values()} == {"Papers"}
    lib.scan_folders([])                                        # папку убрали
    assert not lib.books
    assert (tmp_path / "articles" / "a.epub").exists()          # файлы не тронуты


def test_library_persists(clean_data):
    lib = Library()
    lib.merge_litres([art(7)])
    lib.set_progress("7", "epubcfi(/6/2)", 0.5, "Глава 1")
    lib.flush()
    again = Library()
    assert again.books["7"]["title"] == "Книга 7"
    assert again.progress["7"]["fraction"] == 0.5


def test_graph_scope(clean_data, tmp_path):
    from muninhall.graph import build_graph
    make_tree(tmp_path / "articles")
    lib = Library()
    lib.merge_litres([art(1, persons=[{"role": "author", "full_name": "Автор"}])])
    lib.scan_folders([{"id": "folder-0123456789", "path": str(tmp_path / "articles"), "name": "Статьи"}])
    books = lambda scope: {n["id"] for n in build_graph(lib, scope)["nodes"] if n["kind"] == "book"}
    assert len(books("all")) == 4
    assert books("litres") == {"1"}
    assert len(books("folder-0123456789")) == 3 and "1" not in books("folder-0123456789")
    assert build_graph(lib, "all")["single"] is False and build_graph(lib, "litres")["single"] is True


def test_stats_per_library(clean_data, tmp_path):
    make_tree(tmp_path / "articles")
    lib = Library()
    lib.merge_litres([art(1)])
    lib.scan_folders([{"id": "folder-0123456789", "path": str(tmp_path / "articles"), "name": "Статьи"}])
    own = next(b["id"] for b in lib.books.values() if b.get("source") == "folder")
    lib.add_reading_time("1", 120)
    lib.add_reading_time(own, 60)
    day = next(iter(lib.stats["days"]))
    assert lib.stats["days"][day] == 180
    assert lib.stats["lib_days"]["litres"][day] == 120
    assert lib.stats["lib_days"]["folder-0123456789"][day] == 60


def test_old_stats_attributed_to_litres(clean_data):
    from muninhall import core
    core.save_json(core.STATS_FILE, {"days": {"2026-10-01": 600}, "books": {"5": 600}, "finished": {}})
    assert Library().stats["lib_days"] == {"litres": {"2026-10-01": 600}}


def test_singularity_library_filter(clean_data, tmp_path):
    from muninhall.singularity import SingularitySync
    make_tree(tmp_path / "articles")
    lib = Library()
    lib.merge_litres([art(1, read_percent=30)])
    lib.scan_folders([{"id": "folder-0123456789", "path": str(tmp_path / "articles"), "name": "Статьи"}])
    own = next(b["id"] for b in lib.books.values() if b.get("source") == "folder")
    lib.progress[own] = {"fraction": 0.4}
    sync = SingularitySync.__new__(SingularitySync)
    sync.state = {"reading": True, "progress": False, "wishlist": False, "sent": {}, "libraries": None}
    planned = lambda: {op[3] for op in sync._plan(lib, {}, "P", None)}
    assert planned() == {"1", own}
    sync.state["libraries"] = ["litres"]
    assert planned() == {"1"}
