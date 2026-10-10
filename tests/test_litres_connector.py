"""Коннектор ЛитРес на поддельном сервере: выбор файла, синхронизация, скачивание."""
from types import SimpleNamespace

from muninhall import core, litres_connector
from muninhall.litres_connector import _Download, _SyncRun, pick_download
from muninhall.model import Library


def test_pick_download_prefers_epub_and_audio_m4b():
    files = [{"id": 1, "extension": "fb2.zip"}, {"id": 2, "extension": "ios.epub"}, {"id": 9, "extension": "epub",
                                                                                     "is_additional": True}]
    (urls, fmt, local), err = pick_download({}, files, "7")
    assert err is None and fmt == "ios.epub" and local == "epub" and urls[0].endswith("/download_book/7/2/7.ios.epub")
    (urls, fmt, local), _ = pick_download({"is_audio": True}, [{"id": 5, "file_type": "zip_with_mp3"},
                                                               {"id": 6, "file_type": "mobile_version_mp4"}], "8")
    assert (fmt, local) == ("m4b", "m4b") and "/8/6/8.m4b" in urls[0]
    assert pick_download({}, [{"id": 1, "extension": "html"}], "7")[0] is None
    assert pick_download({"is_audio": True}, [{"id": 1, "file_type": "chapter"}], "7")[0] is None


class FakeLitres:
    logged_in = True

    def __init__(self, arts, folders=None, members=None, fail_first=False):
        self.arts, self.folders, self.members, self.fail_first = arts, folders or {}, members or {}, fail_first
        self.urls = []

    def fetch_library(self, cb):
        cb(self.arts, 200)

    def fetch_list(self, path, cb):
        if path.startswith("/folders/"):
            cb([{"id": i} for i in self.members[path.split("/")[2]]], 200)
        else:
            cb([{"id": 2}], 200)

    def fetch_folders(self, cb):
        cb(self.folders, 200)

    def fetch_files(self, bid, cb):
        cb([{"id": 11, "extension": "epub"}], 200)

    def download(self, url, dest, progress, done):
        self.urls.append(url)
        progress(0.5)
        # ЛитРес на отказ отвечает HTML-страницей вместо книги
        dest.write_bytes(b"<html>" if self.fail_first and len(self.urls) == 1 else b"PK\x03\x04epub")
        done(True, None)


def fake_app(lib, litres):
    toasts, flags = [], []
    app = SimpleNamespace(
        library=lib, litres=litres, toasts=toasts, reader=None, player=SimpleNamespace(book_id=None),
        library_view=SimpleNamespace(cards={}, refresh_library=lambda: None, refresh_card=lambda bid: None),
        singularity=SimpleNamespace(schedule=lambda soon: None), toast=toasts.append,
        set_syncing=flags.append, set_finished=lambda book, value: book.update(finished=value))
    connector = SimpleNamespace(app=app, downloading=set(), flush_folder_ops=lambda then: then(),
                                _fetch_details=lambda: None, apply_remote_position=lambda book: None)
    return app, connector, flags


def test_sync_run_merges_books_progress_and_folders(clean_data):
    lib = Library()
    arts = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
    app, connector, flags = fake_app(lib, FakeLitres(arts, {"f1": "Любимое"}, {"f1": [1]}))
    _SyncRun(connector, quiet=False).start()
    assert flags == [True, False]
    assert set(lib.books) == {"1", "2"} and lib.books["2"].get("in_progress")
    assert lib.books["1"].get("folders") == ["f1"] and lib.folders == {"f1": "Любимое"}
    assert app.toasts == ["Книг в аккаунте: 2"]


def test_download_retries_and_saves(clean_data, tmp_path, monkeypatch):
    monkeypatch.setattr(litres_connector, "books_dir", lambda: tmp_path)
    lib = Library()
    lib.books["7"] = {"id": "7", "title": "C", "source": "litres"}
    litres = FakeLitres([], fail_first=True)
    app, connector, _ = fake_app(lib, litres)
    results = []
    _Download(connector, lib.books["7"], False, lambda ok, err: results.append((ok, err))).start()
    assert results == [(True, None)] and len(litres.urls) == 2 and "download_book_subscr" in litres.urls[1]
    assert lib.books["7"]["file"] == "7.epub" and lib.books["7"]["format"] == "epub"
    assert (tmp_path / "7.epub").read_bytes().startswith(b"PK") and not connector.downloading
    assert core.looks_like_book(tmp_path / "7.epub", "epub")
