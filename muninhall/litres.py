"""Сессия ЛитРес внутри встроенного Chromium (QtWebEngine).

Все запросы идут из настоящей страницы www.litres.ru: так проходят защита от
ботов (DDoS-Guard) и проверка служебных заголовков API. Неофициальные адреса
API взяты из кода сайта и проекта bookvault — они могут измениться.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile,
                                     QWebEngineScript)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .core import (API, CACHE_DIR, DROP_HEADERS, HEADERS_FILE, SESSION_DIR, SITE, WEB_DIR, load_json,
                   log, save_json)
from .i18n import tr

PREFIX = "⁣LITREADER:"   # метка наших сообщений в консоли страницы


class _Page(QWebEnginePage):
    message = Signal(dict)

    def javaScriptConsoleMessage(self, level, text, line, source):
        if text.startswith(PREFIX):
            try:
                self.message.emit(json.loads(text[len(PREFIX):]))
            except ValueError:
                pass

    def createWindow(self, _type):
        # Ссылки «в новом окне» открываем в этом же окне входа
        return self


class LitresSession(QObject):
    state_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logged_in = False
        self.user_name = ""
        self.user_id = None
        self.headers: dict = load_json(HEADERS_FILE, {})
        self.page_ready = False
        self._pending: list = []
        self._callbacks: dict[int, callable] = {}
        self._next_id = 1
        self._downloads: list[dict] = []
        # Метка ответов API: запросы выполняются в изолированном мире JavaScript, где скрипты
        # сайта (реклама, счётчики) её не видят и не могут подделать ответ
        self._token = secrets.token_hex(16)
        # Встроенный Chromium поднимается не сразу, а когда он нужен (start): без подключённого
        # ЛитРес — никогда, с ЛитРес — после того как окно приложения уже показано
        self.started = False
        self.profile = self.page = self.view = None
        self.view_holder: list = []        # куда положить страницу входа, когда она появится

        self._check_timer = QTimer(self, singleShot=True)
        self._check_timer.timeout.connect(self.check_login)

    def start(self):
        """Создаёт профиль и страницу ЛитРес (один раз). Можно звать сколько угодно."""
        if self.started:
            return
        self.started = True
        self.profile = QWebEngineProfile("litres", self)
        self.profile.setPersistentStoragePath(str(SESSION_DIR / "storage"))
        self.profile.setCachePath(str(CACHE_DIR / "webengine"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.downloadRequested.connect(self._on_download)

        hook = QWebEngineScript()
        hook.setName("litreader-hook")
        hook.setSourceCode(f"window.__litreaderPrefix = {json.dumps(PREFIX)};\n"
                           + (WEB_DIR / "litres-hook.js").read_text(encoding="utf-8"))
        hook.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        hook.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        hook.setRunsOnSubFrames(False)
        self.profile.scripts().insert(hook)

        self.page = _Page(self.profile, self)
        self.page.message.connect(self._on_message)
        self.page.loadStarted.connect(self._on_load_started)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        for attach in self.view_holder:        # страница входа ждала браузер
            attach(self.view)
        self.page.load(QUrl(SITE + "/"))

    # --- состояние страницы

    def _on_load_started(self):
        self.page_ready = False

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "ready":
            # DOM готов: полной загрузки не ждём — счётчики и реклама грузятся бесконечно
            if msg.get("url", "").startswith(SITE) and not self.page_ready:
                self.page_ready = True
                log("page ready", msg.get("url"))
                self._schedule_check(500)
                self._run_pending()
        elif t == "headers":
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
        elif t == "api":
            if msg.get("token") != self._token:
                log("отброшен ответ API без метки сессии (подделка со страницы?)")
                return
            cb = self._callbacks.pop(msg.get("id"), None)
            if cb:
                status = msg.get("status") or 0
                data = None
                if msg.get("body"):
                    try:
                        data = json.loads(msg["body"])
                    except ValueError:
                        data = None
                if msg.get("error"):
                    log("api error", msg.get("error"))
                cb(status, data)

    def _schedule_check(self, ms):
        self._check_timer.start(ms)

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
                self.page.load(QUrl(SITE + "/"))
            QTimer.singleShot(1000 * 2 ** (_attempt + 1),
                              lambda: self.api_get(url, callback, _attempt + 1, method, body))

        self.start()
        if not self.page_ready:
            self._pending.append((url, method, body, retry_or_done))
            return
        self._api_get_once(url, method, body, retry_or_done)

    def _api_get_once(self, url, method, payload, callback):
        rid = self._next_id
        self._next_id += 1
        self._callbacks[rid] = lambda st, d: (log(method, url, "->", st), callback(st, d))
        # Изолированный мир (ApplicationWorld): свои fetch и console, не подменённые сайтом;
        # куки и адрес страницы — те же, что у litres.ru
        js = f"""(async () => {{
            const prefix = {json.dumps(PREFIX)}, token = {json.dumps(self._token)};
            const post = msg => console.log(prefix + JSON.stringify({{...msg, token}}));
            try {{
                const h = {json.dumps(self.headers)};
                const opts = {{method: {json.dumps(method)}, credentials: 'include', headers: h}};
                const payload = {json.dumps(json.dumps(payload) if payload is not None else "")};
                if (payload) {{ h['content-type'] = 'application/json'; opts.body = payload; }}
                const r = await fetch({json.dumps(url)}, opts);
                post({{type: 'api', id: {rid}, status: r.status, body: await r.text()}});
            }} catch (e) {{
                post({{type: 'api', id: {rid}, status: 0, error: String(e)}});
            }}
        }})();"""
        self.page.runJavaScript(js, QWebEngineScript.ScriptWorldId.ApplicationWorld)

        # Страница могла перезагрузиться посреди запроса — не ждём вечно
        def timeout():
            cb = self._callbacks.pop(rid, None)
            if cb:
                cb(0, None)
        QTimer.singleShot(60000, timeout)

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
                self.state_changed.emit()
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
            QTimer.singleShot(400, lambda: self.fetch_list(path, callback, next_url, acc))
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
                    folders[str(fid)] = f.get("title") or f.get("name") or tr('Папка {0}', fid)
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

    # --- скачивание через браузер (с куками и «отпечатком» настоящего Chromium)

    def download(self, url: str, dest: Path, on_progress, on_done):
        """on_progress(доля 0..1), on_done(ok, текст ошибки)."""
        self._downloads.append({"url": url, "dest": dest, "progress": on_progress, "done": on_done,
                                "started": False})
        self.start()
        self.page.download(QUrl(url), dest.name + ".part")

    def _on_download(self, req: QWebEngineDownloadRequest):
        url = req.url().toString()
        job = next((d for d in self._downloads if not d["started"] and d["url"] == url), None)
        if job is None:
            # После переадресации адрес может отличаться — берём самый ранний ожидающий
            job = next((d for d in self._downloads if not d["started"]), None)
        if job is None:
            req.cancel()   # скачивание, начатое самим сайтом на странице входа
            return
        job["started"] = True
        dest: Path = job["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        part.unlink(missing_ok=True)
        req.setDownloadDirectory(str(dest.parent))
        req.setDownloadFileName(part.name)

        def progress():
            total = req.totalBytes()
            if job["progress"] and total > 0:
                job["progress"](req.receivedBytes() / total)

        def finished():
            if not req.isFinished():
                return
            self._downloads.remove(job)
            state = req.state()
            log("download", url, "->", state.name if hasattr(state, "name") else state)
            if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted and part.exists():
                part.replace(dest)
                job["done"](True, None)
            else:
                part.unlink(missing_ok=True)
                job["done"](False, req.interruptReasonString() or tr("прервано"))

        req.receivedBytesChanged.connect(progress)
        req.isFinishedChanged.connect(finished)
        req.accept()

    def shutdown(self):
        """Страницу удаляем раньше профиля — иначе WebEngine ругается при выходе."""
        if not self.started:
            return
        self.view.setPage(None)
        self.page.deleteLater()

    def logout(self, callback):
        self.logged_in = False
        self.user_name = ""
        self.user_id = None
        self.headers = {}
        HEADERS_FILE.unlink(missing_ok=True)
        self.start()
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        self.page.load(QUrl(SITE + "/"))
        callback()
