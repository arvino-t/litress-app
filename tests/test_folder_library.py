"""Свои библиотеки: данные в `<корень>/.library/`, перенос со старых версий, переносимость."""
import json
import shutil

from litres_reader import backup, core, libraries
from litres_reader.core import Library, folder_library_id


def make_lib(root):
    for rel in ("a.epub", "sub/b.pdf"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return {"id": folder_library_id(root), "path": str(root), "name": "Статьи"}


def bid_of(lib, rel):
    return next(b["id"] for b in lib.books.values() if b.get("rel") == rel)


def test_progress_and_marks_go_to_library_store(clean_data, tmp_path):
    folder = make_lib(tmp_path / "articles")
    lib = Library()
    lib.scan_folders([folder])
    b = bid_of(lib, "sub/b.pdf")
    lib.books[b]["finished"] = True
    lib.set_progress(b, None, 0.4)
    lib.save()
    lib.flush()
    store = tmp_path / "articles" / ".library"
    assert json.loads((store / "progress.json").read_text())["sub/b.pdf"]["fraction"] == 0.4
    assert json.loads((store / "books.json").read_text())["books"] == {"sub/b.pdf": {"finished": True}}
    # в общих файлах приложения своих книг больше нет
    assert b not in core.load_json(core.PROGRESS_FILE, {})
    assert b not in core.load_json(core.LIBRARY_FILE, {})["books"]


def test_migration_from_old_version(clean_data, tmp_path):
    folder = make_lib(tmp_path / "articles")
    path = tmp_path / "articles" / "a.epub"
    old_bid = "file-" + __import__("hashlib").sha1(str(path).encode()).hexdigest()[:12]
    # как писала прошлая версия: свои книги и их место чтения — в общих файлах
    core.save_json(core.LIBRARY_FILE, {"books": {old_bid: {"id": old_bid, "source": "folder", "path": str(path),
                                                           "title": "a", "finished": True}}, "order": [old_bid]})
    core.save_json(core.PROGRESS_FILE, {old_bid: {"cfi": "epubcfi(/6/4)", "fraction": 0.7}})
    lib = Library()
    lib.scan_folders([folder])
    assert lib.progress[old_bid]["fraction"] == 0.7 and lib.books[old_bid]["finished"] is True
    store = tmp_path / "articles" / ".library"
    assert json.loads((store / "progress.json").read_text())["a.epub"]["cfi"] == "epubcfi(/6/4)"
    assert json.loads((store / "books.json").read_text())["books"]["a.epub"] == {"finished": True}


def test_store_travels_with_folder(clean_data, tmp_path):
    """На другом компьютере путь другой — данные находятся по пути внутри библиотеки."""
    lib = Library()
    lib.scan_folders([make_lib(tmp_path / "pc1" / "articles")])
    lib.set_progress(bid_of(lib, "a.epub"), "cfi", 0.55)
    lib.flush()
    shutil.copytree(tmp_path / "pc1" / "articles", tmp_path / "pc2" / "docs" / "articles")
    other = Library()
    other.progress.clear()
    other.scan_folders([{"path": str(tmp_path / "pc2" / "docs" / "articles"), "name": "Статьи"}])
    assert other.progress[bid_of(other, "a.epub")]["fraction"] == 0.55


def test_rescan_keeps_unsaved_progress(clean_data, tmp_path):
    folder = make_lib(tmp_path / "articles")
    lib = Library()
    lib.scan_folders([folder])
    b = bid_of(lib, "a.epub")
    lib.set_progress(b, "cfi", 0.9)          # ещё не записано (таймер 2 с)
    lib.scan_folders([folder])
    assert lib.progress[b]["fraction"] == 0.9


def test_registry_from_legacy_settings(tmp_path):
    s = {"localFolders": [str(tmp_path / "a"), {"path": str(tmp_path / "b"), "name": "Лекции"}]}
    assert libraries.ensure_registry(s) is True
    assert "localFolders" not in s
    kinds = [(l["kind"], l.get("name")) for l in s["libraries"]]
    assert kinds == [("litres", None), ("folder", "a"), ("folder", "Лекции")]
    assert libraries.ensure_registry(s) is False                 # второй раз ничего не меняет
    libraries.set_folder_libraries(s, [{"path": str(tmp_path / "c"), "name": "Новая"}])
    assert [l["name"] for l in libraries.all_libraries(s)] == ["ЛитРес", "Новая"]


def test_backup_includes_library_store(clean_data, tmp_path):
    folder = make_lib(tmp_path / "articles")
    settings = {"backupDir": str(tmp_path / "bk"), "libraries": [{"kind": "folder", **folder}]}
    core.save_json(core.CONFIG_FILE, settings)
    lib = Library()
    lib.scan_folders([folder])
    lib.set_progress(bid_of(lib, "a.epub"), "cfi", 0.3)
    lib.flush()
    path = backup.create(settings)
    store = tmp_path / "articles" / ".library" / "progress.json"
    store.write_text(json.dumps({"a.epub": {"fraction": 0.99}}))
    backup.stage_restore(path)
    assert backup.apply_pending() is True
    assert json.loads(store.read_text())["a.epub"]["fraction"] == 0.3
