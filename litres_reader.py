#!/usr/bin/env python3
"""Читалка для книг, купленных на ЛитРес.

Вход выполняется на самом сайте litres.ru во встроенном браузере (WebKit):
приложение не видит и не хранит пароль. После входа оно пользуется той же
сессией браузера, чтобы получить список купленных книг и скачать файлы
(EPUB/FB2/MOBI). Книги читаются встроенной читалкой на foliate-js.

Неофициальные адреса API ЛитРес взяты из проекта bookvault
(https://github.com/mavrovde/bookvault) и могут измениться без предупреждения.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango, WebKit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio import AUDIO_FORMATS, AudioPlayer, PlayerPage, audio_tracks  # noqa: E402

APP_ID = "ru.local.LitresReader"
APP_NAME = "Читалка ЛитРес"
SCHEME = "litreader"

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
DATA_DIR = Path(GLib.get_user_data_dir()) / "litres-reader"
BOOKS_DIR = DATA_DIR / "books"
COVERS_DIR = DATA_DIR / "covers"
SESSION_DIR = DATA_DIR / "session"
CACHE_DIR = Path(GLib.get_user_cache_dir()) / "litres-reader"
CONFIG_FILE = Path(GLib.get_user_config_dir()) / "litres-reader" / "settings.json"
LIBRARY_FILE = DATA_DIR / "library.json"
PROGRESS_FILE = DATA_DIR / "progress.json"
HEADERS_FILE = SESSION_DIR / "api-headers.json"

API = "https://api.litres.ru/foundation/api"
SITE = "https://www.litres.ru"
COVERS_BASE = "https://static.litres.ru"
LOGIN_URL = f"{SITE}/auth/login/"

# Форматы в порядке предпочтения: первые четыре открывает встроенная читалка
FORMAT_ORDER = ("epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "a4.pdf", "a6.pdf")
READABLE = {"epub", "ios.epub", "fb2.zip", "fb2", "mobi.prc", "fbz", "mobi", "azw3"}
# Имена файлов, по которым foliate-js определяет формат
LOCAL_SUFFIX = {"ios.epub": "epub", "mobi.prc": "mobi", "a4.pdf": "pdf", "a6.pdf": "pdf"}
# Эти заголовки браузер выставляет сам — копировать их в fetch нельзя
DROP_HEADERS = {"cookie", "host", "content-length", "content-type", "connection",
                "accept-encoding", "user-agent", "origin", "referer",
                # одноразовые заголовки трассировки запросов
                "sentry-trace", "baggage", "x-request-id"}

DEBUG = bool(os.environ.get("LITREADER_DEBUG"))

DEFAULT_SETTINGS = {
    "fontSize": 19,
    "lineHeight": 1.5,
    "margin": 6,
    "lineWidth": 720,
    "twoColumns": True,
    "justify": True,
    "hyphenate": True,
    "font": "book",
    "theme": "auto",
    # фильтры библиотеки
    "libraryStatus": "all",
    "libraryFolder": None,
    "libraryType": "all",   # all / text / audio
    "audioRate": 1.0,
}

TYPE_FILTERS = (("all", "Книги и аудио"), ("text", "Книги"), ("audio", "Аудиокниги"))
# Аудио: сначала один файл M4B, иначе архив с MP3
AUDIO_FILE_TYPES = (("mobile_version_mp4", "m4b"), ("zip_with_mp3", "zip"))

# Особое значение фильтра по папкам: книги, не лежащие ни в одной папке
NO_FOLDER = "__none__"

STATUS_FILTERS = (("all", "Все"), ("reading", "Читаю"), ("unread", "Не читал"), ("finished", "Прочитано"))


def log(*args):
    if DEBUG:
        print("[litreader]", *args, file=sys.stderr, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path: Path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    if private:
        tmp.chmod(0o600)
    tmp.replace(path)


def absolute(url: str | None, base: str) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base + url
    return url


def looks_like_book(path: Path, fmt: str) -> bool:
    """ЛитРес на отказ отвечает HTML-страницей — отличаем её от настоящего файла."""
    try:
        with path.open("rb") as f:
            head = f.read(96)
    except OSError:
        return False
    if head[:2] == b"PK":
        return True
    if fmt == "m4b":
        return head[4:8] == b"ftyp"
    if fmt.endswith("pdf"):
        return head.startswith(b"%PDF")
    if fmt.startswith("mobi"):
        return head[60:68] in (b"BOOKMOBI", b"TEXtREAd")
    if fmt == "fb2":
        text = head.lstrip(b"\xef\xbb\xbf").lstrip()
        return text.startswith(b"<?xml") or text.startswith(b"<FictionBook")
    return False


# ─────────────────────────────────────────────────────────────── хранилище

class Library:
    """Список книг (library.json) и позиции чтения (progress.json)."""

    def __init__(self):
        data = load_json(LIBRARY_FILE, {})
        self.books: dict[str, dict] = data.get("books", {})
        self.order: list[str] = data.get("order", list(self.books))
        # Папки пользователя на ЛитРес: {id: название}
        self.folders: dict[str, str] = data.get("folders", {})
        # Изменения папок, ещё не отправленные на ЛитРес: [{op, folder, art}]
        self.folder_ops: list[dict] = data.get("folder_ops", [])
        self.progress: dict[str, dict] = load_json(PROGRESS_FILE, {})
        self._progress_timer = 0
        for d in (BOOKS_DIR, COVERS_DIR, SESSION_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def save(self):
        save_json(LIBRARY_FILE, {"books": self.books, "order": self.order,
                                 "folders": self.folders, "folder_ops": self.folder_ops})

    def ordered(self):
        return [self.books[i] for i in self.order if i in self.books]

    def merge_litres(self, arts: list[dict]):
        """Добавляет/обновляет книги из аккаунта, не трогая скачанные файлы."""
        ids = []
        for art in arts:
            bid = str(art.get("id"))
            authors = [p.get("full_name") for p in art.get("persons") or []
                       if p.get("role") == "author" and p.get("full_name")]
            book = self.books.setdefault(bid, {"id": bid, "source": "litres"})
            book.update(
                title=art.get("title") or bid,
                authors=authors,
                cover_url=absolute(art.get("cover_url"), COVERS_BASE),
                is_drm=bool(art.get("is_drm")),
                url=absolute(art.get("url"), SITE),
                finished=bool(art.get("is_finished")),
                is_audio=art.get("art_type") == 1,
            )
            if art.get("read_percent") is not None:
                book["remote_percent"] = float(art["read_percent"] or 0)
            if art.get("in_folders") is not None:
                book["folders"] = [str(f.get("folder_id")) for f in art["in_folders"]
                                   if f.get("folder_id") is not None]
            ids.append(bid)
        local = [i for i in self.order if i in self.books and i not in ids]
        self.order = ids + local
        self.apply_pending_folder_ops()
        self.save()

    def set_in_progress(self, ids):
        """Книги из списка ЛитРес «Читаю сейчас»."""
        ids = {str(i) for i in ids}
        for bid, book in self.books.items():
            if book.get("source") == "litres":
                book["in_progress"] = bid in ids
        self.save()

    def set_in_folder(self, bid, fid, inside: bool):
        """Локально кладёт книгу в папку (или убирает) и ставит изменение в очередь."""
        book = self.books[bid]
        folders = [f for f in book.get("folders") or [] if f != fid]
        if inside:
            folders.append(fid)
        book["folders"] = folders
        op = "add" if inside else "remove"
        # Противоположное неотправленное изменение просто отменяем
        opposite = {"op": "remove" if inside else "add", "folder": fid, "art": bid}
        if opposite in self.folder_ops:
            self.folder_ops.remove(opposite)
        else:
            self.folder_ops.append({"op": op, "folder": fid, "art": bid})
        self.save()

    def apply_pending_folder_ops(self):
        """Неотправленные изменения папок важнее ответа сервера — накладываем их поверх."""
        for op in self.folder_ops:
            book = self.books.get(op["art"])
            if not book:
                continue
            folders = [f for f in book.get("folders") or [] if f != op["folder"]]
            if op["op"] == "add":
                folders.append(op["folder"])
            book["folders"] = folders

    def set_folders(self, folders: dict[str, str], members: dict[str, list[str]] | None):
        """folders — {id: название}; members — {id папки: [id книг]} (если известно)."""
        self.folders = folders
        if members is not None:
            for book in self.books.values():
                if book.get("source") == "litres":
                    book["folders"] = [fid for fid, ids in members.items() if book["id"] in ids]
        self.apply_pending_folder_ops()
        self.save()

    def status(self, book) -> str:
        """finished — прочитано, reading — читаю, unread — не читал."""
        if book.get("finished"):
            return "finished"
        local = self.progress.get(book["id"], {}).get("fraction") or 0
        if book.get("in_progress") or local > 0.005 or (book.get("remote_percent") or 0) > 0:
            return "reading"
        return "unread"

    def percent(self, book) -> int | None:
        """Процент прочитанного: наибольший из своего и с ЛитРес."""
        local = (self.progress.get(book["id"], {}).get("fraction") or 0) * 100
        remote = book.get("remote_percent") or 0
        best = max(local, remote)
        return round(best) if best > 0 else None

    def add_local(self, src: Path) -> str:
        name = src.name.lower()
        fmt = "fb2.zip" if name.endswith(".fb2.zip") else src.suffix.lstrip(".").lower()
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:12]
        bid = f"local-{digest}"
        dest = BOOKS_DIR / f"{bid}.{fmt}"
        if not dest.exists():
            shutil.copyfile(src, dest)
        title = src.name[: -len(fmt) - 1] if name.endswith("." + fmt) else src.stem
        self.books.setdefault(bid, {"id": bid, "source": "local", "title": title, "authors": []})
        self.books[bid].update(file=dest.name, format=fmt)
        if bid in self.order:
            self.order.remove(bid)
        self.order.insert(0, bid)
        self.save()
        return bid

    def file_path(self, book) -> Path | None:
        if book.get("file"):
            p = BOOKS_DIR / book["file"]
            if p.exists():
                return p
        return None

    def cover_path(self, book) -> Path | None:
        p = COVERS_DIR / f"{book['id']}.jpg"
        return p if p.exists() and p.stat().st_size > 0 else None

    def remove_file(self, bid):
        book = self.books.get(bid)
        if not book:
            return
        p = self.file_path(book)
        if p and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p:
            p.unlink(missing_ok=True)
        book.pop("file", None)
        book.pop("format", None)
        self.progress.pop(bid, None)
        if book.get("source") == "local":
            self.books.pop(bid, None)
            self.order = [i for i in self.order if i != bid]
        self.save()
        save_json(PROGRESS_FILE, self.progress)

    def set_audio_progress(self, bid, track, position, fraction):
        self.progress[bid] = {"track": track, "pos": position, "fraction": fraction}
        if not self._progress_timer:
            self._progress_timer = GLib.timeout_add_seconds(2, self._flush_progress)

    def set_progress(self, bid, cfi, fraction):
        self.progress[bid] = {"cfi": cfi, "fraction": fraction}
        # Пишем на диск не чаще раза в 2 секунды — при листании событий много
        if not self._progress_timer:
            self._progress_timer = GLib.timeout_add_seconds(2, self._flush_progress)

    def _flush_progress(self):
        self._progress_timer = 0
        save_json(PROGRESS_FILE, self.progress)
        return False

    def flush(self):
        if self._progress_timer:
            GLib.source_remove(self._progress_timer)
            self._flush_progress()


# ─────────────────────────────────────────────────────────────── ЛитРес

class LitresSession:
    """Сессия ЛитРес внутри WebKit.

    Все запросы идут из настоящей страницы www.litres.ru: так проходят защита
    от ботов (DDoS-Guard) и проверка служебных заголовков API.
    """

    def __init__(self, on_state_changed):
        self.on_state_changed = on_state_changed
        self.logged_in = False
        self.user_name = ""
        self.user_id = None
        self.headers: dict = load_json(HEADERS_FILE, {})
        self.page_ready = False
        self._pending: list = []
        self._check_scheduled = 0

        self.network = WebKit.NetworkSession.new(str(SESSION_DIR), str(CACHE_DIR / "session"))
        self.network.get_cookie_manager().set_persistent_storage(
            str(SESSION_DIR / "cookies.sqlite"), WebKit.CookiePersistentStorage.SQLITE)

        ucm = WebKit.UserContentManager()
        ucm.add_script(WebKit.UserScript.new(
            (WEB_DIR / "litres-hook.js").read_text(),
            WebKit.UserContentInjectedFrames.TOP_FRAME,
            WebKit.UserScriptInjectionTime.START,
            ["https://*.litres.ru/*"], None))
        ucm.register_script_message_handler("litres", None)
        ucm.connect("script-message-received::litres", self._on_message)

        self.view = WebKit.WebView(network_session=self.network, user_content_manager=ucm)
        self.view.set_vexpand(True)
        self.view.get_settings().set_enable_developer_extras(DEBUG)
        self.view.connect("load-changed", self._on_load_changed)
        self.view.connect("create", self._on_create)
        self.view.load_uri(SITE + "/")

    # --- состояние страницы

    def _on_create(self, view, action):
        # Ссылки «в новом окне» открываем в этом же окне входа
        view.load_request(action.get_request())
        return None

    def _on_load_changed(self, view, event):
        uri = view.get_uri() or ""
        if event == WebKit.LoadEvent.STARTED:
            self.page_ready = False
        elif event == WebKit.LoadEvent.COMMITTED and uri.startswith(SITE):
            # Полной загрузки не ждём: счётчики и реклама на сайте грузятся
            # бесконечно, а для запросов к API достаточно готового документа.
            GLib.timeout_add(1500, self._mark_ready, uri)

    def _mark_ready(self, uri):
        if self.view.get_uri() == uri and not self.page_ready:
            self.page_ready = True
            log("page ready", uri)
            self._schedule_check(500)
            self._run_pending()
        return False

    def _on_message(self, _ucm, value):
        try:
            msg = json.loads(value.to_string())
        except ValueError:
            return
        if msg.get("type") != "headers":
            return
        headers = {k: v for k, v in (msg.get("headers") or {}).items()
                   if k.lower() not in DROP_HEADERS}
        # Нужен набор с идентификатором приложения; берём самый свежий
        if headers.get("app-id") or len(headers) > len(self.headers):
            if headers != self.headers:
                self.headers = headers
                save_json(HEADERS_FILE, self.headers, private=True)
                log("captured headers:", sorted(self.headers))
            if not self.logged_in:
                self._schedule_check(800)

    def _schedule_check(self, ms):
        if self._check_scheduled:
            GLib.source_remove(self._check_scheduled)

        def run():
            self._check_scheduled = 0
            self.check_login()
            return False
        self._check_scheduled = GLib.timeout_add(ms, run)

    # --- API

    def api_get(self, url: str, callback, _attempt=0, method="GET", body=None):
        """Запрос к API ЛитРес из контекста страницы. callback(status, json|None).

        На свежем профиле защита от ботов пускает к api.litres.ru не сразу —
        сетевую ошибку повторяем с паузой, а перед третьей попыткой
        перезагружаем страницу сайта, чтобы она получила новые куки.
        """
        def retry_or_done(status, data):
            if status != 0 or _attempt >= 4:
                callback(status, data)
                return
            if _attempt == 2:
                self.view.load_uri(SITE + "/")
            GLib.timeout_add_seconds(
                2 ** (_attempt + 1),
                lambda: self.api_get(url, callback, _attempt + 1, method, body) and False)

        if not self.page_ready:
            self._pending.append((url, method, body, retry_or_done))
            return
        self._api_get_once(url, method, body, retry_or_done)

    def _api_get_once(self, url: str, method: str, payload, callback):
        body = """
            const f = window.__litreaderFetch || window.fetch;
            const h = JSON.parse(headers);
            const opts = {method, credentials: 'include', headers: h};
            if (payload) {
                h['content-type'] = 'application/json';
                opts.body = payload;
            }
            const r = await f(url, opts);
            return JSON.stringify({status: r.status, body: await r.text()});
        """
        args = GLib.Variant("a{sv}", {
            "url": GLib.Variant("s", url),
            "method": GLib.Variant("s", method),
            "headers": GLib.Variant("s", json.dumps(self.headers)),
            "payload": GLib.Variant("s", json.dumps(payload) if payload is not None else ""),
        })

        def done(view, res):
            try:
                out = json.loads(view.call_async_javascript_function_finish(res).to_string())
                status, text = out["status"], out["body"]
                try:
                    data = json.loads(text)
                except ValueError:
                    data = None
            except Exception as e:  # noqa: BLE001 — ошибки JS/сети
                log("api error", url, e)
                status, data = 0, None
            log(method, url, "->", status)
            callback(status, data)

        self.view.call_async_javascript_function(body, -1, args, None, None, None, done)

    def _run_pending(self):
        pending, self._pending = self._pending, []
        for url, method, payload, cb in pending:
            self._api_get_once(url, method, payload, cb)

    def check_login(self):
        def done(status, data):
            was = self.logged_in
            self.logged_in = status == 200
            if self.logged_in:
                user = (data or {}).get("payload", {}).get("data") or {}
                self.user_id = user.get("id")
                self.user_name = (user.get("login") or user.get("mail") or user.get("email")
                                  or " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
                                  or "")
            if was != self.logged_in or self.logged_in:
                self.on_state_changed()
        self.api_get(f"{API}/users/me", done)

    def fetch_library(self, callback):
        """Все купленные книги. callback(list_of_arts | None, status)."""
        self.fetch_list("/users/me/arts", callback)

    def fetch_list(self, path, callback, _url=None, _acc=None):
        """Постраничный список из API (курсор в pagination.next_page)."""
        acc = [] if _acc is None else _acc
        url = _url or f"{API}{path}?limit=100"

        def done(status, data):
            if status != 200 or not data:
                callback(None, status)
                return
            payload = data.get("payload") or {}
            items = payload.get("data") or []
            acc.extend(items)
            nxt = (payload.get("pagination") or {}).get("next_page")
            if not items or not nxt:
                callback(acc, status)
                return
            query = dict(parse_qsl(urlsplit(nxt).query))
            query.setdefault("limit", "100")
            next_url = f"{API}{path}?{urlencode(query)}"
            GLib.timeout_add(400, lambda: self.fetch_list(path, callback, next_url, acc) and False)
        self.api_get(url, done)

    def fetch_folders(self, callback):
        """Папки пользователя. callback({id: название} | None, status)."""
        def done(status, data):
            if status != 200 or not data:
                callback(None, status)
                return
            folders = {}
            for f in (data.get("payload") or {}).get("data") or []:
                fid = f.get("folder_id", f.get("id"))
                if fid is not None:
                    folders[str(fid)] = f.get("title") or f.get("name") or f"Папка {fid}"
            callback(folders, status)
        self.api_get(f"{API}/users/me/folders", done)

    def folder_change(self, folder_id, art_ids, add: bool, callback):
        """Добавить книги в папку ЛитРес или убрать из неё. callback(ok)."""
        action = "add-arts" if add else "remove-arts"
        self.api_get(f"{API}/users/me/folders/{folder_id}/{action}",
                     lambda status, _d: callback(200 <= status < 300),
                     method="POST", body={"art_ids": [int(a) for a in art_ids]})

    def create_folder(self, title, callback):
        """Создать папку. callback({id: название} свежего списка | None, id новой | None)."""
        def created(status, _data):
            if not 200 <= status < 300:
                callback(None, None)
                return

            def listed(folders, _st):
                # Новую папку находим по названию — так не зависим от формата ответа
                new_id = None
                for fid, name in (folders or {}).items():
                    if name == title:
                        new_id = fid
                callback(folders, new_id)
            self.fetch_folders(listed)
        self.api_get(f"{API}/users/me/folders", created, method="POST", body={"title": title})

    def set_finished(self, art_id, finished: bool, callback):
        """Отметить книгу прочитанной (или снять отметку) на ЛитРес. callback(ok)."""
        if not self.user_id:
            callback(False)
            return
        action = "finish" if finished else "unfinish"
        self.api_get(f"{API}/users/{self.user_id}/arts/{art_id}/{action}",
                     lambda status, _d: callback(200 <= status < 300), method="PUT")

    def fetch_files(self, art_id, callback):
        """callback(list_of_files | None, status)."""
        def done(status, data):
            if status != 200 or not data:
                callback(None, status)
                return
            files = []
            for group in (data.get("payload") or {}).get("data") or []:
                for f in group.get("files") or []:
                    files.append({**f, "file_type": group.get("file_type")})
            callback(files, status)
        self.api_get(f"{API}/arts/{art_id}/files/grouped", done)

    def download(self, url: str, dest: Path, on_progress, on_done):
        """Скачивание через WebKit с куками сессии. on_done(ok, error_text)."""
        part = dest.with_name(dest.name + ".part")
        dl = self.view.download_uri(url)
        dl.set_allow_overwrite(True)
        errors = []

        def decide(d, _name):
            d.set_destination(str(part))
            return True

        def finished(d):
            resp = d.get_response()
            status = resp.get_status_code() if resp else 0
            log("download", url, "->", status, errors)
            if errors or not part.exists() or status >= 400:
                part.unlink(missing_ok=True)
                on_done(False, errors[0] if errors else f"HTTP {status}")
            else:
                part.replace(dest)
                on_done(True, None)

        dl.connect("decide-destination", decide)
        dl.connect("received-data", lambda d, _n: on_progress and on_progress(d.get_estimated_progress()))
        dl.connect("failed", lambda d, err: errors.append(err.message))
        dl.connect("finished", finished)

    def logout(self, callback):
        self.logged_in = False
        self.user_name = ""
        self.user_id = None
        self.headers = {}
        HEADERS_FILE.unlink(missing_ok=True)

        def cleared(mgr, res):
            try:
                mgr.clear_finish(res)
            except GLib.Error as e:
                log("clear error", e.message)
            self.view.load_uri(SITE + "/")
            callback()
        self.network.get_website_data_manager().clear(
            WebKit.WebsiteDataTypes.ALL, 0, None, cleared)


# ─────────────────────────────────────────────────────────────── библиотека

class BookCard(Gtk.FlowBoxChild):
    COVER_W, COVER_H = 132, 192

    def __init__(self, app, book):
        super().__init__()
        self.app = app
        self.book_id = book["id"]
        self.add_css_class("book-card")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        self.set_child(box)

        overlay = Gtk.Overlay()
        overlay.set_size_request(self.COVER_W, self.COVER_H)
        overlay.set_halign(Gtk.Align.CENTER)
        box.append(overlay)

        self.cover_stack = Gtk.Stack()
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self.picture.set_size_request(self.COVER_W, self.COVER_H)
        self.picture.add_css_class("book-cover")
        self.placeholder = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                     lines=6, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
        self.placeholder.set_size_request(self.COVER_W, self.COVER_H)
        self.placeholder.add_css_class("cover-placeholder")
        self.cover_stack.add_named(self.placeholder, "text")
        self.cover_stack.add_named(self.picture, "image")
        overlay.set_child(self.cover_stack)

        self.badge = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.START)
        self.badge.set_margin_top(6)
        self.badge.set_margin_end(6)
        self.badge.add_css_class("book-badge")
        overlay.add_overlay(self.badge)

        self.cloud = Gtk.Image(icon_name="folder-download-symbolic", pixel_size=16,
                               halign=Gtk.Align.START, valign=Gtk.Align.START,
                               tooltip_text="Не скачана — нажмите, чтобы скачать")
        self.cloud.set_margin_top(6)
        self.cloud.set_margin_start(6)
        self.cloud.add_css_class("book-badge")
        overlay.add_overlay(self.cloud)

        self.audio_icon = Gtk.Image(icon_name="litreader-audio-headphones-symbolic", pixel_size=16,
                                    halign=Gtk.Align.END, valign=Gtk.Align.END,
                                    tooltip_text="Аудиокнига", visible=False)
        self.audio_icon.set_margin_bottom(6)
        self.audio_icon.set_margin_end(6)
        self.audio_icon.add_css_class("book-badge")
        overlay.add_overlay(self.audio_icon)

        self.progress = Gtk.ProgressBar(valign=Gtk.Align.END, visible=False)
        self.progress.set_margin_start(8)
        self.progress.set_margin_end(8)
        self.progress.set_margin_bottom(8)
        overlay.add_overlay(self.progress)

        self.title = Gtk.Label(wrap=True, lines=2, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14,
                               justify=Gtk.Justification.CENTER)
        self.title.set_size_request(self.COVER_W, -1)
        self.title.add_css_class("heading")
        box.append(self.title)
        self.author = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=16)
        self.author.add_css_class("dim-label")
        self.author.add_css_class("caption")
        box.append(self.author)

        # Долгое нажатие пальцем или правая кнопка мыши — меню книги
        long = Gtk.GestureLongPress()
        long.connect("pressed", lambda *_: self.app.show_book_menu(self))
        self.add_controller(long)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *_: self.app.show_book_menu(self))
        self.add_controller(right)

        self.update(book)

    def update(self, book):
        lib = self.app.library
        self.title.set_label(book.get("title") or "")
        self.author.set_label(", ".join(book.get("authors") or []))
        self.placeholder.set_label(book.get("title") or "")
        cover = lib.cover_path(book)
        if cover:
            self.picture.set_filename(str(cover))
            self.cover_stack.set_visible_child_name("image")
        else:
            self.cover_stack.set_visible_child_name("text")
        downloaded = lib.file_path(book) is not None
        status = lib.status(book)
        self.badge.remove_css_class("finished")
        self.badge.set_tooltip_text(None)
        if status == "finished":
            self.badge.set_label("✓")
            self.badge.set_tooltip_text("Прочитано")
            self.badge.add_css_class("finished")
        elif status == "reading":
            pct = lib.percent(book)
            self.badge.set_label(f"{pct}%" if pct else "Читаю")
        else:
            self.badge.set_label("Новая")
        self.badge.set_visible(downloaded or status != "unread")
        self.cloud.set_visible(not downloaded)
        self.audio_icon.set_visible(bool(book.get("is_audio")))

    def set_download_progress(self, fraction):
        if fraction is None:
            self.progress.set_visible(False)
        else:
            self.progress.set_visible(True)
            self.progress.set_fraction(max(0.02, fraction))


# ─────────────────────────────────────────────────────────────── читалка

class ReaderPage(Adw.NavigationPage):
    def __init__(self, app, book, path: Path):
        super().__init__(title=book.get("title") or "Книга")
        self.app = app
        self.book = book
        self.path = path
        self.toc: list[dict] = []
        self.ui_visible = True

        self.window_title = Adw.WindowTitle(title=book.get("title") or "")
        header = Adw.HeaderBar(title_widget=self.window_title)

        toc_btn = Gtk.MenuButton(icon_name="view-list-symbolic", tooltip_text="Оглавление")
        self.toc_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.toc_list.add_css_class("navigation-sidebar")
        self.toc_list.connect("row-activated", self._on_toc_row)
        scroller = Gtk.ScrolledWindow(child=self.toc_list, propagate_natural_height=True,
                                      max_content_height=520, min_content_width=320,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.toc_popover = Gtk.Popover(child=scroller)
        toc_btn.set_popover(self.toc_popover)
        header.pack_end(toc_btn)

        settings_btn = Gtk.MenuButton(icon_name="font-select-symbolic", tooltip_text="Вид текста")
        settings_btn.set_popover(Gtk.Popover(child=self._build_settings()))
        header.pack_end(settings_btn)

        full_btn = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Во весь экран (F11)")
        full_btn.connect("clicked", lambda *_: app.toggle_fullscreen())
        header.pack_end(full_btn)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.001)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("change-value", self._on_seek)
        self.percent = Gtk.Label(width_chars=5)
        self.percent.add_css_class("numeric")
        bottom = Gtk.Box(spacing=12)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        bottom.set_margin_top(6)
        bottom.set_margin_bottom(6)
        bottom.append(self.scale)
        bottom.append(self.percent)
        bottom.add_css_class("toolbar")

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("reader", None)
        ucm.connect("script-message-received::reader", self._on_message)
        self.web = WebKit.WebView(user_content_manager=ucm)
        s = self.web.get_settings()
        s.set_enable_developer_extras(DEBUG)
        s.set_enable_write_console_messages_to_stdout(DEBUG)
        s.set_enable_back_forward_navigation_gestures(False)
        self.web.connect("context-menu", lambda *_: not DEBUG)
        self.web.connect("decide-policy", self._on_policy)

        self.toolbar = Adw.ToolbarView(content=self.web)
        self.toolbar.add_top_bar(header)
        self.toolbar.add_bottom_bar(bottom)
        # Панели лежат поверх текста — показ/скрытие не перестраивает страницы
        self.toolbar.set_extend_content_to_top_edge(True)
        self.toolbar.set_extend_content_to_bottom_edge(True)
        self.toolbar.set_top_bar_style(Adw.ToolbarStyle.RAISED)
        self.toolbar.set_bottom_bar_style(Adw.ToolbarStyle.RAISED)
        self.set_child(self.toolbar)

        self._style_handler = Adw.StyleManager.get_default().connect(
            "notify::dark", lambda *_: self.apply_settings())
        self.connect("hidden", self._on_hidden)
        self.web.load_uri(f"{SCHEME}://app/reader.html")
        GLib.timeout_add_seconds(3, self._auto_hide)

    # --- настройки вида

    def _build_settings(self):
        st = self.app.settings
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(12)

        def row(label, widget):
            r = Gtk.Box(spacing=12)
            r.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            r.append(widget)
            box.append(r)

        size = Gtk.Box(spacing=6)
        size.add_css_class("linked")
        minus = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text="Меньше")
        plus = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text="Больше")
        size_label = Gtk.Label(label=str(st["fontSize"]), width_chars=3)

        def change_size(delta):
            st["fontSize"] = max(12, min(40, st["fontSize"] + delta))
            size_label.set_label(str(st["fontSize"]))
            self.app.save_settings()
        minus.connect("clicked", lambda *_: change_size(-1))
        plus.connect("clicked", lambda *_: change_size(+1))
        size.append(minus)
        size.append(size_label)
        size.append(plus)
        row("Размер шрифта", size)

        themes = Gtk.Box()
        themes.add_css_class("linked")
        group = None
        for key, label in (("auto", "Авто"), ("light", "Светлая"), ("sepia", "Сепия"),
                           ("dark", "Тёмная"), ("black", "Чёрная")):
            b = Gtk.ToggleButton(label=label, active=st["theme"] == key)
            if group:
                b.set_group(group)
            group = group or b
            b.connect("toggled", lambda b, k=key: b.get_active() and self._set("theme", k))
            themes.append(b)
        box.append(Gtk.Label(label="Тема", xalign=0))
        box.append(themes)

        fonts = Gtk.DropDown.new_from_strings(["Как в книге", "С засечками", "Без засечек"])
        font_keys = ["book", "serif", "sans"]
        fonts.set_selected(font_keys.index(st["font"]) if st["font"] in font_keys else 0)
        fonts.connect("notify::selected", lambda d, _p: self._set("font", font_keys[d.get_selected()]))
        row("Шрифт", fonts)

        def slider(label, key, lo, hi, step, digits=0):
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            sc.set_value(st[key])
            sc.set_digits(digits)
            sc.set_size_request(180, -1)
            sc.connect("value-changed", lambda s: self._set(key, round(s.get_value(), 2)))
            row(label, sc)

        slider("Межстрочный интервал", "lineHeight", 1.1, 2.2, 0.1, 1)
        slider("Поля, %", "margin", 0, 20, 1)
        slider("Ширина строки", "lineWidth", 400, 1400, 20)

        for key, label in (("twoColumns", "Две страницы в горизонтальном положении"),
                           ("justify", "Выравнивать по ширине"),
                           ("hyphenate", "Переносы слов")):
            sw = Gtk.Switch(active=st[key], valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _p, k=key: self._set(k, s.get_active()))
            row(label, sw)
        return box

    def _set(self, key, value):
        self.app.settings[key] = value
        self.app.save_settings()

    def resolved_settings(self):
        s = dict(self.app.settings)
        if s["theme"] == "auto":
            s["theme"] = "dark" if Adw.StyleManager.get_default().get_dark() else "light"
        return s

    def apply_settings(self):
        self.js(f"window.reader?.applySettings({json.dumps(self.resolved_settings())})")

    # --- связь с JS

    def js(self, code):
        self.web.evaluate_javascript(code, -1, None, None, None, None, None)

    def _on_message(self, _ucm, value):
        try:
            msg = json.loads(value.to_string())
        except ValueError:
            return
        t = msg.get("type")
        if t == "ready":
            ext = self.path.name.split(".", 1)[1] if "." in self.path.name else ""
            params = {
                "url": f"{SCHEME}://app/book/{self.path.name}",
                "name": f"book.{ext}",
                "cfi": self.app.library.progress.get(self.book["id"], {}).get("cfi"),
                "settings": self.resolved_settings(),
            }
            self.js(f"window.reader.open({json.dumps(params)})")
        elif t == "opened":
            self._fill_toc(msg.get("toc") or [])
            self.app.on_book_metadata(self.book["id"], msg.get("title"), msg.get("author"))
            self._offer_remote_position()
        elif t == "relocate":
            if msg.get("fraction") is None:
                return
            frac = float(msg["fraction"])
            self.scale.set_value(frac)
            self.percent.set_label(f"{round(frac * 100)}%")
            self.window_title.set_subtitle(msg.get("chapter") or "")
            if msg.get("cfi"):
                self.app.library.set_progress(self.book["id"], msg["cfi"], frac)
            if msg.get("atEnd") and not self.book.get("finished"):
                self.app.set_finished(self.book, True, auto=True)
        elif t == "toggle-ui":
            self.set_ui_visible(not self.ui_visible)
        elif t == "escape":
            if self.app.is_fullscreen():
                self.app.toggle_fullscreen()
            else:
                self.app.nav.pop()
        elif t == "external-link":
            Gtk.UriLauncher.new(msg["href"]).launch(self.app.window, None, None)
        elif t == "error":
            self.app.toast(f"Не удалось открыть книгу: {msg.get('message')}")
        log("reader:", t)

    def _offer_remote_position(self):
        """Если на ЛитРес книга прочитана дальше, предлагаем перейти туда."""
        remote = self.book.get("remote_percent") or 0
        local = (self.app.library.progress.get(self.book["id"], {}).get("fraction") or 0) * 100
        if remote < 1 or remote - local < 1:
            return
        toast = Adw.Toast(title=f"На ЛитРес прочитано {round(remote)}%", button_label="Перейти",
                          timeout=10)
        toast.connect("button-clicked",
                      lambda *_: self.js(f"window.reader.goToFraction({min(remote, 100) / 100})"))
        self.app.toasts.add_toast(toast)

    def _fill_toc(self, toc):
        self.toc = toc
        while (child := self.toc_list.get_first_child()):
            self.toc_list.remove(child)
        for item in toc:
            label = Gtk.Label(label=item["label"] or "—", xalign=0, wrap=True)
            label.set_margin_start(12 + 16 * item["depth"])
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.set_margin_end(12)
            self.toc_list.append(label)

    def _on_toc_row(self, _list, row):
        href = self.toc[row.get_index()]["href"]
        self.js(f"window.reader.goTo({json.dumps(href)})")
        self.toc_popover.popdown()

    def _on_seek(self, _scale, _scroll, value):
        self.js(f"window.reader.goToFraction({max(0.0, min(1.0, value))})")
        return False

    def _on_policy(self, _view, decision, kind):
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith((f"{SCHEME}:", "blob:", "about:", "data:")):
                decision.ignore()
                Gtk.UriLauncher.new(uri).launch(self.app.window, None, None)
                return True
        return False

    # --- панели

    def set_ui_visible(self, visible):
        self.ui_visible = visible
        self.toolbar.set_reveal_top_bars(visible)
        self.toolbar.set_reveal_bottom_bars(visible)

    def _auto_hide(self):
        if self.get_mapped():
            self.set_ui_visible(False)
        return False

    def _on_hidden(self, *_):
        self.app.library.flush()
        Adw.StyleManager.get_default().disconnect(self._style_handler)
        if self.app.reader is self:
            self.app.reader = None
        self.app.refresh_card(self.book["id"])


# ─────────────────────────────────────────────────────────────── приложение

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.library: Library | None = None
        self.litres: LitresSession | None = None
        self.window = None
        self.reader: ReaderPage | None = None
        self.player: AudioPlayer | None = None
        self.player_page: PlayerPage | None = None
        self.cards: dict[str, BookCard] = {}
        self.downloading: set[str] = set()
        self.syncing = False
        self.only_downloaded = False
        self.settings = {**DEFAULT_SETTINGS, **load_json(CONFIG_FILE, {})}
        self._settings_timer = 0
        self._cover_queue: list[str] = []
        self._covers_running = 0
        self._pending_open: list[Path] = []

    # --- запуск

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        # Свои копии значков Adwaita: не во всех темах они отображаются правильно
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(
            str(HERE / "data" / "icons"))
        self.library = Library()
        self.player = AudioPlayer()
        self.player.connect("finished", self._on_audio_finished)
        self.player.connect("error", lambda _p, msg: self.toast(f"Ошибка воспроизведения: {msg}"))
        self.player.connect("state-changed", lambda *_: self._on_player_state())
        # Место прослушивания сохраняем раз в 5 секунд
        GLib.timeout_add_seconds(5, lambda: (self.save_audio_progress(), True)[1])

        ctx = WebKit.WebContext.get_default()
        ctx.register_uri_scheme(SCHEME, self._serve)
        sec = ctx.get_security_manager()
        sec.register_uri_scheme_as_secure(SCHEME)
        sec.register_uri_scheme_as_cors_enabled(SCHEME)

        css = Gtk.CssProvider()
        css.load_from_string("""
            .book-cover, .cover-placeholder { border-radius: 8px; }
            .cover-placeholder {
                padding: 12px;
                background: alpha(@accent_bg_color, .18);
                font-weight: bold;
            }
            .book-badge {
                padding: 2px 8px;
                border-radius: 99px;
                background: alpha(black, .65);
                color: white;
                font-size: 11px;
                font-weight: bold;
            }
            .book-badge.finished { background: alpha(@success_bg_color, .9); }
            .player-play { min-width: 64px; min-height: 64px; -gtk-icon-size: 28px; }
            flowboxchild.book-card { border-radius: 12px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, cb in (("open-file", self.on_open_file), ("sync", lambda *_: self.sync()),
                         ("login", lambda *_: self.show_login()), ("logout", self.on_logout),
                         ("about", self.on_about)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
        only = Gio.SimpleAction.new_stateful("only-downloaded", None, GLib.Variant("b", False))
        only.connect("change-state", self.on_only_downloaded)
        self.add_action(only)
        self.set_accels_for_action("app.open-file", ["<Ctrl>o"])
        self.set_accels_for_action("app.sync", ["<Ctrl>r", "F5"])

        self.litres = LitresSession(self.on_login_state)

    def do_activate(self):
        if not self.window:
            self._build_window()
        self.window.present()

    def do_open(self, files, *_):
        self.do_activate()
        for f in files:
            if f.get_path():
                self.import_and_open(Path(f.get_path()))

    def _serve(self, request):
        """litreader://app/… — файлы читалки и сами книги."""
        path = urlsplit(request.get_uri()).path.lstrip("/")
        if path.startswith("book/"):
            base, rel = BOOKS_DIR, path[5:]
        else:
            base, rel = WEB_DIR, path
        target = (base / rel).resolve()
        if not target.is_file() or base.resolve() not in target.parents:
            request.finish_error(GLib.Error.new_literal(
                Gio.io_error_quark(), f"Нет файла: {path}", Gio.IOErrorEnum.NOT_FOUND))
            return
        if target.suffix in (".js", ".mjs"):
            mime = "text/javascript"
        else:
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        stream = Gio.File.new_for_path(str(target)).read(None)
        resp = WebKit.URISchemeResponse.new(stream, target.stat().st_size)
        resp.set_content_type(mime)
        request.finish_with_response(resp)

    # --- окно

    def _build_window(self):
        self.window = Adw.ApplicationWindow(application=self, title=APP_NAME,
                                            default_width=1100, default_height=760)
        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.window.set_content(self.toasts)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.window.add_controller(keys)
        self.window.connect("close-request", self._on_close)

        self.nav.add(self._build_library_page())
        self.login_page = self._build_login_page()
        self.refresh_library()
        for p in self._pending_open:
            self.import_and_open(p)

    def _build_library_page(self):
        self.lib_title = Adw.WindowTitle(title="Библиотека")
        header = Adw.HeaderBar(title_widget=self.lib_title)

        self.sync_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                   tooltip_text="Обновить список книг с ЛитРес (F5)",
                                   action_name="app.sync")
        self.sync_spinner = Adw.Spinner(visible=False)
        header.pack_start(self.sync_btn)
        header.pack_start(self.sync_spinner)

        # Возврат к плееру, пока звучит (или поставлена на паузу) аудиокнига
        self.now_playing_btn = Gtk.Button(visible=False, tooltip_text="Вернуться к плееру")
        self.now_playing_btn.add_css_class("flat")
        self.now_playing_btn.connect("clicked", lambda *_: self.show_player())
        header.pack_start(self.now_playing_btn)

        menu = Gio.Menu()
        menu.append("Открыть файл…", "app.open-file")
        menu.append("Только скачанные", "app.only-downloaded")
        self.account_section = Gio.Menu()
        menu.append_section(None, self.account_section)
        about = Gio.Menu()
        about.append("О приложении", "app.about")
        menu.append_section(None, about)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       primary=True, tooltip_text="Меню"))

        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Поиск")
        header.pack_end(search_btn)
        self.search = Gtk.SearchEntry(placeholder_text="Название или автор", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.flow.invalidate_filter())
        clamp = Adw.Clamp(child=self.search, maximum_size=480)
        search_bar = Gtk.SearchBar(child=clamp)
        search_bar.connect_entry(self.search)
        search_btn.bind_property("active", search_bar, "search-mode-enabled",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=2, max_children_per_line=12,
                                activate_on_single_click=True, valign=Gtk.Align.START,
                                column_spacing=6, row_spacing=12)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.flow, f"set_margin_{m}")(12)
        self.flow.connect("child-activated", lambda _f, card: self.on_book_activated(card.book_id))
        self.flow.set_filter_func(self._filter)
        scroller = Gtk.ScrolledWindow(child=self.flow, vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)

        login_btn = Gtk.Button(label="Войти в ЛитРес", halign=Gtk.Align.CENTER,
                               action_name="app.login")
        login_btn.add_css_class("pill")
        login_btn.add_css_class("suggested-action")
        open_btn = Gtk.Button(label="Открыть файл с компьютера", halign=Gtk.Align.CENTER,
                              action_name="app.open-file")
        open_btn.add_css_class("pill")
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        buttons.append(login_btn)
        buttons.append(open_btn)
        self.empty = Adw.StatusPage(icon_name="accessories-dictionary-symbolic",
                                    title="Книг пока нет", child=buttons,
                                    description="Войдите в аккаунт ЛитРес, чтобы увидеть купленные "
                                                "книги, или откройте файл EPUB/FB2.")
        self.content_stack = Gtk.Stack()
        self.content_stack.add_named(self.empty, "empty")
        self.content_stack.add_named(scroller, "grid")

        toolbar = Adw.ToolbarView(content=self.content_stack)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(search_bar)
        toolbar.add_top_bar(self._build_filter_bar())
        self._update_account_ui()
        return Adw.NavigationPage(title="Библиотека", child=toolbar, tag="library")

    def _build_filter_bar(self):
        """Статус чтения (Все/Читаю/Не читал/Прочитано) и папки пользователя."""
        bar = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        seg = Gtk.Box()
        seg.add_css_class("linked")
        self.status_buttons = {}
        group = None
        for key, _label in STATUS_FILTERS:
            b = Gtk.ToggleButton(active=self.settings["libraryStatus"] == key)
            if group:
                b.set_group(group)
            group = group or b
            b.connect("toggled", lambda b, k=key: b.get_active() and self._set_status_filter(k))
            self.status_buttons[key] = b
            seg.append(b)
        bar.append(seg)

        self._folder_ids: list[str | None] = [None]
        self.folder_model = Gtk.StringList.new(["Все папки"])
        self.folder_drop = Gtk.DropDown(model=self.folder_model, tooltip_text="Папка на ЛитРес")
        self.folder_drop.connect("notify::selected", self._on_folder_selected)
        bar.append(self.folder_drop)

        self.type_drop = Gtk.DropDown.new_from_strings([label for _k, label in TYPE_FILTERS])
        keys = [k for k, _l in TYPE_FILTERS]
        current = self.settings.get("libraryType", "all")
        self.type_drop.set_selected(keys.index(current) if current in keys else 0)
        self.type_drop.connect("notify::selected", self._on_type_selected)
        bar.append(self.type_drop)
        self._update_filter_bar()
        return bar

    def _on_type_selected(self, drop, _pspec):
        self.settings["libraryType"] = TYPE_FILTERS[drop.get_selected()][0]
        self.save_settings()
        self.flow.invalidate_filter()

    def _set_status_filter(self, key):
        self.settings["libraryStatus"] = key
        self.save_settings()
        self.flow.invalidate_filter()

    def _on_folder_selected(self, drop, _pspec):
        if getattr(self, "_filling_folders", False):
            return
        idx = drop.get_selected()
        fid = self._folder_ids[idx] if 0 <= idx < len(self._folder_ids) else None
        self.settings["libraryFolder"] = fid
        self.save_settings()
        self.flow.invalidate_filter()

    def _update_filter_bar(self):
        """Счётчики на кнопках статуса и список папок."""
        books = self.library.ordered()
        counts = {"all": len(books), "reading": 0, "unread": 0, "finished": 0}
        for b in books:
            counts[self.library.status(b)] += 1
        for key, label in STATUS_FILTERS:
            self.status_buttons[key].set_label(f"{label} · {counts[key]}")

        folders = self.library.folders
        self._filling_folders = True
        self._folder_ids = [None, NO_FOLDER] + list(folders)
        self.folder_model.splice(0, self.folder_model.get_n_items(),
                                 ["Все папки", "Без папки"] + [folders[f] for f in folders])
        current = self.settings.get("libraryFolder")
        self.folder_drop.set_selected(self._folder_ids.index(current) if current in self._folder_ids else 0)
        self._filling_folders = False
        if current not in self._folder_ids:
            self.settings["libraryFolder"] = None
        self.folder_drop.set_visible(bool(folders))
        if hasattr(self, "type_drop"):
            self.type_drop.set_visible(any(b.get("is_audio") for b in books))

    def _build_login_page(self):
        header = Adw.HeaderBar(title_widget=Adw.WindowTitle(
            title="Вход в ЛитРес", subtitle="Пароль вводится на сайте ЛитРес"))
        reload_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Обновить страницу")
        reload_btn.connect("clicked", lambda *_: self.litres.view.reload())
        header.pack_end(reload_btn)
        self.login_toolbar = Adw.ToolbarView()
        self.login_toolbar.add_top_bar(header)
        page = Adw.NavigationPage(title="Вход", child=self.login_toolbar, tag="login")
        # Одна и та же WebView переезжает на страницу входа и обратно
        page.connect("showing", lambda *_: self.login_toolbar.set_content(self.litres.view))
        page.connect("hidden", lambda *_: self.login_toolbar.set_content(None))
        return page

    def _on_key(self, _ctl, keyval, _code, state):
        if keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        return False

    def _on_close(self, *_):
        self.save_audio_progress()
        self.player.unload()
        self.library.flush()
        return False

    def toast(self, text):
        if self.window:
            self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def is_fullscreen(self):
        return self.window.is_fullscreen()

    def toggle_fullscreen(self):
        if self.window.is_fullscreen():
            self.window.unfullscreen()
        else:
            self.window.fullscreen()

    # --- библиотека

    def _filter(self, card):
        book = self.library.books.get(card.book_id)
        if not book:
            return False
        if self.only_downloaded and not self.library.file_path(book):
            return False
        status = self.settings.get("libraryStatus", "all")
        if status != "all" and self.library.status(book) != status:
            return False
        kind = self.settings.get("libraryType", "all")
        if kind != "all" and bool(book.get("is_audio")) != (kind == "audio"):
            return False
        folder = self.settings.get("libraryFolder")
        if folder == NO_FOLDER:
            if book.get("folders"):
                return False
        elif folder and folder not in (book.get("folders") or []):
            return False
        q = self.search.get_text().strip().lower()
        if q:
            hay = " ".join([book.get("title") or ""] + (book.get("authors") or [])).lower()
            return q in hay
        return True

    def refresh_library(self):
        if not self.window:
            return
        while (child := self.flow.get_first_child()):
            self.flow.remove(child)
        self.cards = {}
        for book in self.library.ordered():
            card = BookCard(self, book)
            self.cards[book["id"]] = card
            self.flow.append(card)
            if book.get("cover_url") and not self.library.cover_path(book):
                self._queue_cover(book["id"])
        self.content_stack.set_visible_child_name("grid" if self.cards else "empty")
        self._update_filter_bar()

    def refresh_card(self, bid):
        card = self.cards.get(bid)
        book = self.library.books.get(bid)
        if card and book:
            card.update(book)
            self._update_filter_bar()
            self.flow.invalidate_filter()

    def set_finished(self, book, finished: bool, auto=False):
        """Отметка «прочитано»: локально и на ЛитРес (сразу или при следующей синхронизации)."""
        book["finished"] = finished
        if book.get("source") == "litres":
            book["finished_pending"] = finished
        self.library.save()
        self.refresh_card(book["id"])
        if auto:
            self.toast("Книга дочитана — отмечена прочитанной")
        if book.get("source") != "litres" or not self.litres.logged_in:
            return

        def done(ok):
            if ok:
                book.pop("finished_pending", None)
                self.library.save()
            else:
                self.toast("Не удалось обновить отметку на ЛитРес — повторю при синхронизации")
        self.litres.set_finished(book["id"], finished, done)

    def on_only_downloaded(self, action, value):
        action.set_state(value)
        self.only_downloaded = value.get_boolean()
        self.flow.invalidate_filter()

    def on_book_metadata(self, bid, title, author):
        book = self.library.books.get(bid)
        if book and book.get("source") == "local":
            if title:
                book["title"] = title
            if author:
                book["authors"] = [author]
            self.library.save()
            self.refresh_card(bid)

    def _queue_cover(self, bid):
        self._cover_queue.append(bid)
        self._next_cover()

    def _next_cover(self):
        while self._cover_queue and self._covers_running < 3:
            bid = self._cover_queue.pop(0)
            book = self.library.books.get(bid)
            if not book or not book.get("cover_url"):
                continue
            self._covers_running += 1

            def done(ok, _err, bid=bid):
                self._covers_running -= 1
                if ok:
                    self.refresh_card(bid)
                self._next_cover()
            self.litres.download(book["cover_url"], COVERS_DIR / f"{bid}.jpg", None, done)

    # --- аккаунт

    def on_login_state(self):
        self._update_account_ui()
        if self.litres.logged_in and self.window:
            if self.nav.get_visible_page() is self.login_page:
                self.nav.pop()
                self.toast("Вы вошли в ЛитРес")
                self.sync()
            elif not self.library.books:
                self.sync()

    def _update_account_ui(self):
        if not hasattr(self, "account_section"):
            return
        self.account_section.remove_all()
        if self.litres and self.litres.logged_in:
            self.account_section.append("Выйти из ЛитРес", "app.logout")
            self.lib_title.set_subtitle(f"ЛитРес: {self.litres.user_name}"
                                        if self.litres.user_name else "ЛитРес: вход выполнен")
        else:
            self.account_section.append("Войти в ЛитРес", "app.login")
            self.lib_title.set_subtitle("Вход в ЛитРес не выполнен")

    def show_login(self):
        if self.nav.get_visible_page() is not self.login_page:
            self.nav.push(self.login_page)
        if not self.litres.logged_in:
            self.litres.view.load_uri(LOGIN_URL)

    def on_logout(self, *_):
        dialog = Adw.AlertDialog(heading="Выйти из ЛитРес?",
                                 body="Скачанные книги и закладки останутся на этом компьютере.")
        dialog.add_response("cancel", "Отмена")
        dialog.add_response("logout", "Выйти")
        dialog.set_response_appearance("logout", Adw.ResponseAppearance.DESTRUCTIVE)

        def response(_d, r):
            if r == "logout":
                self.litres.logout(lambda: (self._update_account_ui(), self.toast("Вы вышли из ЛитРес")))
        dialog.connect("response", response)
        dialog.present(self.window)

    def flush_folder_ops(self, then=None):
        """Отправляет накопленные изменения папок на ЛитРес по одному."""
        ops = self.library.folder_ops
        if not ops or not self.litres.logged_in:
            if then:
                then()
            return
        op = ops[0]

        def done(ok):
            if ok:
                if op in self.library.folder_ops:
                    self.library.folder_ops.remove(op)
                self.library.save()
                self.flush_folder_ops(then)
            else:
                self.toast("Не удалось изменить папку на ЛитРес — повторю при синхронизации")
                if then:
                    then()
        self.litres.folder_change(op["folder"], [op["art"]], op["op"] == "add", done)

    def show_folders_dialog(self, book):
        """Окно выбора папок ЛитРес для книги: переключатель у каждой папки и новая папка."""
        dialog = Adw.Dialog(title="Папки", content_width=380)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title=book.get("title") or "",
                                     description="Изменения сразу отправляются на ЛитРес")
        page.add(group)
        rows = []

        def add_row(fid, name):
            row = Adw.SwitchRow(title=name, active=fid in (book.get("folders") or []))
            row.connect("notify::active", lambda r, _p: self.set_book_folder(book, fid, r.get_active()))
            group.add(row)
            rows.append(row)

        for fid, name in self.library.folders.items():
            add_row(fid, name)
        if not self.library.folders:
            group.set_description("Папок пока нет — создайте первую ниже")

        new_group = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title="Новая папка", show_apply_button=True)
        new_group.add(entry)
        page.add(new_group)

        def create(e):
            title = e.get_text().strip()
            if not title:
                return
            if not self.litres.logged_in:
                self.toast("Чтобы создать папку, войдите в ЛитРес")
                return
            e.set_sensitive(False)

            def done(folders, new_id):
                e.set_sensitive(True)
                if folders is None or new_id is None:
                    self.toast("Не удалось создать папку на ЛитРес")
                    return
                e.set_text("")
                self.library.set_folders(folders, None)
                add_row(new_id, folders[new_id])
                group.set_description("Изменения сразу отправляются на ЛитРес")
                rows[-1].set_active(True)   # сразу кладём книгу в новую папку
                self._update_filter_bar()
            self.litres.create_folder(title, done)
        entry.connect("apply", create)

        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(Adw.HeaderBar())
        dialog.set_child(toolbar)
        dialog.present(self.window)

    def set_book_folder(self, book, fid, inside: bool):
        if inside == (fid in (book.get("folders") or [])):
            return
        self.library.set_in_folder(book["id"], fid, inside)
        self._update_filter_bar()
        self.flow.invalidate_filter()
        self.flush_folder_ops()

    def sync(self):
        if self.syncing:
            return
        if not self.litres.logged_in:
            self.show_login()
            return
        self.syncing = True
        self.sync_btn.set_visible(False)
        self.sync_spinner.set_visible(True)

        problems = []

        def finish(text):
            self.syncing = False
            self.sync_btn.set_visible(True)
            self.sync_spinner.set_visible(False)
            self.refresh_library()
            if problems:
                text += ". Не получено: " + ", ".join(problems)
            self.toast(text)

        def got_arts(arts, status):
            if arts is None:
                self.syncing = False
                self.sync_btn.set_visible(True)
                self.sync_spinner.set_visible(False)
                if status in (401, 403):
                    self.litres.logged_in = False
                    self._update_account_ui()
                    self.toast("Сессия ЛитРес истекла — войдите снова")
                else:
                    self.toast(f"Не удалось получить список книг (код {status})")
                return
            # Отметки «прочитано», которые не успели уйти на ЛитРес, важнее ответа сервера
            pending = {bid: b["finished_pending"] for bid, b in self.library.books.items()
                       if "finished_pending" in b}
            self.library.merge_litres(arts)
            for bid, value in pending.items():
                if bid in self.library.books:
                    self.set_finished(self.library.books[bid], value)
            self.sync_state = {
                "count": len(arts),
                "has_folders_field": any("in_folders" in a for a in arts),
            }
            self.litres.fetch_list("/users/me/arts/in-progress", got_progress)

        def got_progress(arts, _status):
            if arts is None:
                problems.append("«Читаю сейчас»")
            else:
                self.library.set_in_progress(a.get("id") for a in arts)
            self.litres.fetch_folders(got_folders)

        def got_folders(folders, _status):
            if folders is None:
                problems.append("папки")
                finish(f"Книг в аккаунте: {self.sync_state['count']}")
                return
            if self.sync_state["has_folders_field"] or not folders:
                # Состав папок уже пришёл в полях книг (in_folders)
                self.library.set_folders(folders, None)
                finish(f"Книг в аккаунте: {self.sync_state['count']}")
                return
            members: dict[str, list[str]] = {}
            queue = list(folders)

            def next_folder(*_):
                if not queue:
                    self.library.set_folders(folders, members)
                    finish(f"Книг в аккаунте: {self.sync_state['count']}")
                    return
                fid = queue.pop(0)

                def got(arts, _st):
                    if arts is None:
                        problems.append(f"папка «{folders[fid]}»")
                    else:
                        members[fid] = [str(a.get("id")) for a in arts]
                    next_folder()
                self.litres.fetch_list(f"/folders/{fid}/arts", got)
            next_folder()

        # Сначала отправляем свои изменения папок, потом забираем состояние с сервера
        self.flush_folder_ops(lambda: self.litres.fetch_library(got_arts))

    # --- книги

    def on_book_activated(self, bid):
        book = self.library.books.get(bid)
        if not book:
            return
        path = self.library.file_path(book)
        if path:
            self.open_book(book, path)
        elif book.get("source") == "litres":
            self.download_book(book, open_after=True)

    def open_book(self, book, path: Path):
        fmt = book.get("format") or ""
        if fmt in AUDIO_FORMATS:
            self.open_player(book, path)
            return
        if fmt not in READABLE:
            # PDF и прочее — в приложении по умолчанию
            Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self.window, None, None)
            return
        if self.reader:
            self.nav.pop_to_tag("library")
        self.reader = ReaderPage(self, book, path)
        self.nav.push(self.reader)

    # --- аудиокниги

    def open_player(self, book, path: Path):
        if self.player.book_id != book["id"]:
            tracks = audio_tracks(path)
            if not tracks:
                self.toast("В аудиокниге не найдено звуковых файлов")
                return
            self.save_audio_progress()
            saved = self.library.progress.get(book["id"], {})
            if (saved.get("fraction") or 0) >= 0.999:
                saved = {}   # прослушанную книгу начинаем сначала
            self.player.rate = self.settings.get("audioRate", 1.0)
            self.player.load(book["id"], tracks, saved.get("track", 0), saved.get("pos", 0.0))
            if self.player_page:
                self.player_page.destroy_page()
            self.player_page = PlayerPage(self, book)
        elif not self.player.playing:
            self.player.play()
        self.show_player()

    def show_player(self):
        if not self.player_page:
            return
        if self.nav.get_visible_page() is not self.player_page:
            self.nav.pop_to_tag("library")
            self.nav.push(self.player_page)

    def save_audio_progress(self):
        bid = self.player.book_id if self.player else None
        if not bid or not self.player.tracks:
            return
        self.library.set_audio_progress(bid, self.player.index, self.player.position(),
                                        self.player.fraction())
        if bid in self.cards and not self.player.playing:
            self.refresh_card(bid)

    def _on_player_state(self):
        book = self.library.books.get(self.player.book_id or "")
        if not book or not hasattr(self, "now_playing_btn"):
            return
        icon = "media-playback-start-symbolic" if self.player.playing else "media-playback-pause-symbolic"
        content = Gtk.Box(spacing=6)
        content.append(Gtk.Image(icon_name=icon))
        content.append(Gtk.Label(label=book.get("title") or "", ellipsize=Pango.EllipsizeMode.END,
                                 max_width_chars=24))
        self.now_playing_btn.set_child(content)
        self.now_playing_btn.set_visible(True)
        self.save_audio_progress()

    def _on_audio_finished(self, *_):
        book = self.library.books.get(self.player.book_id or "")
        if not book:
            return
        self.library.set_audio_progress(book["id"], len(self.player.tracks) - 1, 0.0, 1.0)
        if not book.get("finished"):
            self.set_finished(book, True)
            self.toast("Аудиокнига прослушана — отмечена прочитанной")

    def _extract_audio_zip(self, zip_path: Path, dest_dir: Path, on_done):
        """Распаковка MP3-архива в отдельном потоке (архивы бывают большими)."""
        import threading
        import zipfile

        def work():
            try:
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(dest_dir)
                zip_path.unlink(missing_ok=True)
                GLib.idle_add(on_done, None)
            except (OSError, zipfile.BadZipFile) as e:
                shutil.rmtree(dest_dir, ignore_errors=True)
                GLib.idle_add(on_done, str(e))
        threading.Thread(target=work, daemon=True).start()

    def download_book(self, book, open_after=False):
        bid = book["id"]
        if bid in self.downloading:
            return
        if not self.litres.logged_in:
            self.toast("Сначала войдите в ЛитРес")
            self.show_login()
            return
        self.downloading.add(bid)
        card = self.cards.get(bid)
        if card:
            card.set_download_progress(0)

        def fail(text):
            self.downloading.discard(bid)
            if card:
                card.set_download_progress(None)
            self.toast(text)

        def got_files(files, status):
            if files is None:
                fail(f"Не удалось получить файлы книги (код {status})")
                return
            main = [f for f in files if not f.get("is_additional")] or files
            if book.get("is_audio"):
                by_type = {f.get("file_type"): f for f in main if f.get("file_type")}
                choice = next(((t, ext) for t, ext in AUDIO_FILE_TYPES if t in by_type), None)
                if not choice:
                    fail("Для этой аудиокниги доступны только отдельные главы — пока не поддерживается")
                    return
                ftype, local = choice
                f = by_type[ftype]
                remote_ext = f.get("extension") or local
                dest = BOOKS_DIR / f"{bid}.{local}"
                attempts = [f"{SITE}/download_book/{bid}/{f['id']}/{bid}.{remote_ext}",
                            f"{SITE}/download_book_subscr/{bid}/{f['id']}/{bid}.{remote_ext}"]
                try_next(attempts, dest, local, local)
                return
            by_ext = {f.get("extension"): f for f in main if f.get("extension")}
            fmt = next((e for e in FORMAT_ORDER if e in by_ext), None)
            if not fmt:
                fail("У этой книги нет формата для чтения (возможно, только онлайн-чтение)")
                return
            file_id = by_ext[fmt]["id"]
            local_ext = LOCAL_SUFFIX.get(fmt, fmt)
            dest = BOOKS_DIR / f"{bid}.{local_ext}"
            attempts = [f"{SITE}/download_book/{bid}/{file_id}/{bid}.{fmt}",
                        f"{SITE}/download_book_subscr/{bid}/{file_id}/{bid}.{fmt}"]
            try_next(attempts, dest, fmt, local_ext)

        def try_next(attempts, dest, fmt, local_ext):
            url = attempts.pop(0)

            def done(ok, err):
                if ok and looks_like_book(dest, fmt) and book.get("is_audio") and fmt == "zip":
                    # MP3-архив распаковываем в папку книги
                    folder = BOOKS_DIR / bid

                    def extracted(err):
                        self.downloading.discard(bid)
                        if card:
                            card.set_download_progress(None)
                        if err:
                            self.toast(f"Не удалось распаковать аудиокнигу: {err}")
                            return
                        book.update(file=folder.name, format="mp3dir")
                        self.library.save()
                        self.refresh_card(bid)
                        if open_after:
                            self.open_book(book, folder)
                    self._extract_audio_zip(dest, folder, extracted)
                    return
                if ok and looks_like_book(dest, fmt):
                    self.downloading.discard(bid)
                    if card:
                        card.set_download_progress(None)
                    book.update(file=dest.name, format=local_ext if local_ext in READABLE | AUDIO_FORMATS
                                else fmt)
                    self.library.save()
                    self.refresh_card(bid)
                    if book.get("is_drm"):
                        self.toast("Книга защищена DRM — она может не открыться")
                    if open_after:
                        self.open_book(book, dest)
                    return
                dest.unlink(missing_ok=True)
                if attempts:
                    try_next(attempts, dest, fmt, local_ext)
                else:
                    fail(f"ЛитРес не отдал файл книги ({err or 'неверный ответ'})")

            self.litres.download(url, dest, lambda f: card and card.set_download_progress(f), done)

        self.litres.fetch_files(bid, got_files)

    def show_book_menu(self, card: BookCard):
        book = self.library.books.get(card.book_id)
        if not book:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pop = Gtk.Popover(child=box, has_arrow=True)
        pop.set_parent(card)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))

        def item(label, cb):
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (pop.popdown(), cb()))
            box.append(b)

        downloaded = self.library.file_path(book) is not None
        if downloaded:
            item("Слушать" if book.get("is_audio") else "Читать",
                 lambda: self.on_book_activated(book["id"]))
        if book.get("finished"):
            item("Снять отметку «Прочитано»", lambda: self.set_finished(book, False))
        else:
            item("Отметить прочитанной", lambda: self.set_finished(book, True))
        if book.get("source") == "litres":
            item("Папки…", lambda: self.show_folders_dialog(book))
        if book.get("source") == "litres":
            item("Скачать заново" if downloaded else "Скачать",
                 lambda: self.download_book(book))
            if book.get("url"):
                item("Открыть на сайте ЛитРес",
                     lambda: Gtk.UriLauncher.new(book["url"]).launch(self.window, None, None))
        if downloaded or book.get("source") == "local":
            item("Удалить с устройства", lambda: self.remove_book_file(book["id"]))
        pop.popup()

    def remove_book_file(self, bid):
        if self.player.book_id == bid:
            # Удаляем то, что сейчас звучит — сначала останавливаем плеер
            if self.player_page:
                if self.nav.get_visible_page() is self.player_page:
                    self.nav.pop_to_tag("library")
                self.player_page.destroy_page()
                self.player_page = None
            self.player.unload()
            self.now_playing_btn.set_visible(False)
        self.library.remove_file(bid)
        self.refresh_library()

    def import_and_open(self, path: Path):
        if not self.window:
            self._pending_open.append(path)
            return
        try:
            bid = self.library.add_local(path)
        except OSError as e:
            self.toast(f"Не удалось открыть файл: {e.strerror}")
            return
        self.refresh_library()
        book = self.library.books[bid]
        self.open_book(book, self.library.file_path(book))

    def on_open_file(self, *_):
        filt = Gtk.FileFilter(name="Электронные книги")
        for pattern in ("*.epub", "*.fb2", "*.fb2.zip", "*.fbz", "*.mobi", "*.azw3"):
            filt.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dialog = Gtk.FileDialog(title="Открыть книгу", filters=filters, default_filter=filt)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                self.import_and_open(Path(f.get_path()))
        dialog.open(self.window, None, done)

    # --- прочее

    def save_settings(self):
        if self.reader:
            self.reader.apply_settings()
        if self._settings_timer:
            GLib.source_remove(self._settings_timer)

        def write():
            self._settings_timer = 0
            save_json(CONFIG_FILE, self.settings)
            return False
        self._settings_timer = GLib.timeout_add(500, write)

    def on_about(self, *_):
        Adw.AboutDialog(
            application_name=APP_NAME, application_icon=APP_ID,
            version="1.0",
            comments="Чтение книг, купленных на ЛитРес. Вход выполняется на сайте ЛитРес; "
                     "приложение не хранит пароль.",
            license_type=Gtk.License.MIT_X11,
        ).present(self.window)



if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
