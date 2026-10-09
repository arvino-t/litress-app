"""Синхронизация с планировщиком SingularityApp (REST API v2, личный токен).

- «Читаю»: для каждой начатой книги — задача в проекте «📚 Книги»; дочитана — задача закрыта;
- прогресс: процент и текущая глава в заметке задачи;
- «Хочу прочитать»: непрочитанные книги — задачи в отдельном проекте; начатая книга
  переезжает в «Книги» (та же задача, а не новая);
- ежедневное чтение: привычка «Чтение N минут» отмечается сама, когда за день набралось N минут.

Свои задачи и привычку находим по externalId, поэтому повторная синхронизация
ничего не удваивает. Документация API: https://singularity-app.com/wiki/api/
"""
from __future__ import annotations

import datetime as dt
import json
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from . import libraries
from .core import CONFIG_DIR, load_json, log, save_json
from .i18n import tr
from .widgets import (BoxedList, cls, exec_dialog, frameless_dialog, label, Switch)

API = "https://api.singularity-app.com/v2"
STATE_FILE = CONFIG_DIR / "singularity.json"   # токен и служебные id — только для владельца

EXT_BOOKS = "litreader-project-books"
EXT_WISHLIST = "litreader-project-wishlist"
EXT_HABIT = "litreader-habit-daily"

TASK_EXT = "litreader-book-"   # + id книги

DEFAULTS = {
    "token": "",
    "reading": True,      # задачи «Читаю»
    "progress": True,     # процент и глава в заметке
    "wishlist": False,    # «Хочу прочитать»
    "daily": False,       # привычка «Чтение N минут»
    "dailyMinutes": 20,
    "libraries": None,    # книги каких библиотек ведём задачами (id; "litres"); None — всех
}


def minutes_word(n: int) -> str:
    """1 минута, 2 минуты, 5 минут, 21 минута…"""
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "минуты"
    return "минут"


class SingularitySync(QObject):
    """Односторонняя синхронизация: приложение → Singularity."""

    status = Signal(str)          # текст для окна настроек и уведомлений

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.state = {**DEFAULTS, **load_json(STATE_FILE, {})}
        self.state.setdefault("ids", {})           # externalId → id в Singularity
        self.state.setdefault("sent", {})          # id книги → что отправлено (чтобы не слать лишнего)
        self.state.setdefault("minutes", {})       # дата → секунд чтения/прослушивания
        self.state.setdefault("habitDone", [])     # даты, когда привычка уже отмечена
        self.net = QNetworkAccessManager(self)
        self.running = False
        self._again = False
        # Изменения собираем и отправляем пачкой: не чаще раза в 2 минуты
        self._debounce = QTimer(self, singleShot=True, interval=120_000)
        self._debounce.timeout.connect(self.sync)

    # --- настройки

    @property
    def enabled(self) -> bool:
        return bool(self.state.get("token"))

    def save(self):
        save_json(STATE_FILE, self.state, private=True)

    def configure(self, **values):
        token_changed = "token" in values and values["token"] != self.state.get("token")
        self.state.update(values)
        if token_changed:
            # Другой аккаунт — прежние id задач и проектов к нему не относятся
            self.state["ids"] = {}
            self.state["sent"] = {}
        self.save()

    # --- учёт времени чтения для привычки

    def add_reading_time(self, seconds: int):
        today = dt.date.today().isoformat()
        minutes = self.state["minutes"]
        minutes[today] = minutes.get(today, 0) + seconds
        # Храним только последние 14 дней
        for day in sorted(minutes)[:-14]:
            minutes.pop(day, None)
        self.save()
        goal = int(self.state.get("dailyMinutes") or 20) * 60
        if self.enabled and self.state.get("daily") and minutes[today] >= goal \
                and today not in self.state["habitDone"]:
            self.schedule(soon=True)

    def today_minutes(self) -> int:
        return self.state["minutes"].get(dt.date.today().isoformat(), 0) // 60

    def schedule(self, soon=False):
        if not self.enabled:
            return
        if soon:
            self._debounce.start(3000)
        elif not self._debounce.isActive():
            self._debounce.start()

    # --- HTTP

    def _request(self, method, path, body=None, query=None, done=None):
        url = QUrl(f"{API}{path}" + (f"?{urlencode(query)}" if query else ""))
        req = QNetworkRequest(url)
        req.setRawHeader(b"Authorization", f"Bearer {self.state['token']}".encode())
        req.setRawHeader(b"Accept", b"application/json")
        req.setTransferTimeout(30_000)
        data = QByteArray(json.dumps(body).encode()) if body is not None else QByteArray()
        if body is not None:
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self.net.sendCustomRequest(req, method.encode(), data)

        def finished():
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            raw = bytes(reply.readAll())
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = None
            err = reply.errorString() if reply.error() != QNetworkReply.NetworkError.NoError else ""
            log("singularity", method, path, "->", status, err)
            reply.deleteLater()
            if done:
                done(status, payload, err)
        reply.finished.connect(finished)

    def _list_all(self, path, key, query, done, _acc=None, _offset=0):
        """Постраничный список (maxCount/offset)."""
        acc = [] if _acc is None else _acc

        def got(status, payload, err):
            if status != 200:
                done(None, status, err)
                return
            items = (payload or {}).get(key) or []
            acc.extend(items)
            if len(items) < 500:
                done(acc, status, "")
            else:
                self._list_all(path, key, query, done, acc, _offset + len(items))
        self._request("GET", path, query={**query, "maxCount": 500, "offset": _offset}, done=got)

    # --- синхронизация

    def check_token(self, done):
        """Проверка токена одним лёгким запросом. done(ok, текст)."""
        def got(status, _payload, err):
            if status == 200:
                done(True, tr("Токен работает"))
            elif status in (401, 403):
                done(False, tr("Токен не подходит — создайте новый с доступом к задачам, проектам и привычкам"))
            elif status == 0:
                done(False, tr('Сервер Singularity недоступен ({0}). '
                               'Если включён VPN — нужен обход (см. vpn-bypass).', err or tr('нет связи')))
            else:
                done(False, tr('Ошибка Singularity: код {0}', status))
        self._request("GET", "/project", query={"maxCount": 1}, done=got)

    def sync(self):
        if not self.enabled:
            return
        if self.running:
            self._again = True
            return
        self.running = True
        self._again = False
        steps = []
        if self.state.get("reading") or self.state.get("wishlist"):
            steps.append(self._sync_tasks)
        if self.state.get("daily"):
            steps.append(self._sync_habit)
        errors = self._errors = []

        def next_step(err=None):
            if err:
                errors.append(err)
            if steps:
                steps.pop(0)(next_step)
                return
            self.running = False
            self.save()
            self.status.emit("; ".join(errors) if errors else
                             tr('Синхронизировано с Singularity {0:%H:%M}', dt.datetime.now()))
            if self._again:
                self.schedule(soon=True)
        next_step()

    # --- проекты

    def _ensure_project(self, ext, title, emoji, done):
        """Проект по externalId: находим среди существующих или создаём. done(id | None)."""
        pid = self.state["ids"].get(ext)
        if pid:
            done(pid)
            return

        def listed(projects, status, err):
            if projects is None:
                done(None)
                return
            found = next((p for p in projects if p.get("externalId") == ext and not p.get("removed")), None) \
                or next((p for p in projects if p.get("title") == title and not p.get("removed")), None)
            if found:
                self.state["ids"][ext] = found["id"]
                done(found["id"])
                return

            def created(status, payload, err):
                if status in (200, 201) and payload and payload.get("id"):
                    self.state["ids"][ext] = payload["id"]
                    done(payload["id"])
                else:
                    done(None)
            self._request("POST", "/project", body={"title": title, "emoji": emoji, "externalId": ext},
                          done=created)
        self._list_all("/project", "projects", {}, listed)

    # --- задачи книг

    def _book_note(self, book, lib) -> str:
        p = lib.progress.get(book["id"], {})
        percent = lib.percent(book) or 0
        lines = [f"Прочитано {percent}%" if not book.get("is_audio") else f"Прослушано {percent}%"]
        if p.get("chapter"):
            lines.append(f"Глава: {p['chapter']}")
        if book.get("authors"):
            lines.append("Автор: " + ", ".join(book["authors"]))
        if book.get("url"):
            lines.append(book["url"])
        lines.append(f"Обновлено из Muninhall {dt.datetime.now():%d.%m.%Y %H:%M}")
        return "\n".join(lines)

    def _sync_tasks(self, next_step):
        lib = self.app.library
        need_wishlist = bool(self.state.get("wishlist"))

        def with_books(books_pid):
            if not books_pid:
                next_step(tr("не удалось создать проект «Книги» в Singularity"))
                return
            if need_wishlist:
                def with_wishlist(wish_pid):
                    if not wish_pid:
                        # Не молчим: без проекта «Хочу прочитать» пропускаем только его
                        self._errors.append(tr("не удалось создать проект «Хочу прочитать» в Singularity"))
                    with_projects(books_pid, wish_pid)
                self._ensure_project(EXT_WISHLIST, "Хочу прочитать", "1f516", with_wishlist)
            else:
                with_projects(books_pid, None)

        def with_projects(books_pid, wish_pid):
            # Все наши задачи ищем во всех проектах сразу: книга могла переехать
            def listed(tasks, status, err):
                if tasks is None:
                    next_step(tr('не удалось получить задачи Singularity ({0})', status or err))
                    return
                ours = {t["externalId"]: t for t in tasks
                        if (t.get("externalId") or "").startswith(TASK_EXT) and not t.get("removed")}
                ops = self._plan(lib, ours, books_pid, wish_pid)
                self._run_ops(ops, next_step)
            self._list_all("/task", "tasks", {"includeArchived": "true"}, listed)

        self._ensure_project(EXT_BOOKS, "Книги", "1f4da", with_books)

    def _plan(self, lib, ours, books_pid, wish_pid):
        """Что поменять в Singularity: список (метод, путь, тело, id книги, отметка отправленного)."""
        ops = []
        allowed = self.state.get("libraries")
        for book in lib.ordered():
            if allowed is not None and lib.library_key(book) not in allowed:
                continue
            bid = book["id"]
            ext = TASK_EXT + bid
            status = lib.status(book)
            task = ours.get(ext)
            title = book.get("title") or bid
            if book.get("authors"):
                title += " — " + ", ".join(book["authors"][:2])
            if book.get("is_audio"):
                title = "🎧 " + title

            if status in ("reading", "finished") and self.state.get("reading"):
                note = self._book_note(book, lib) if self.state.get("progress") else None
                checked = 1 if status == "finished" else 0
                sent = self.state["sent"].get(bid, {})
                if task is None:
                    if status == "finished":
                        continue   # старые дочитанные книги задачами не заводим
                    body = {"title": title, "projectId": books_pid, "externalId": ext, "checked": 0}
                    if note:
                        body["note"] = note
                    ops.append(("POST", "/task", body, bid, {"checked": 0, "percent": lib.percent(book)}))
                    continue
                patch = {}
                if task.get("projectId") != books_pid and status == "reading":
                    patch["projectId"] = books_pid   # переезд из «Хочу прочитать»
                if int(task.get("checked") or 0) != checked:
                    patch["checked"] = checked
                percent = lib.percent(book)
                chapter = lib.progress.get(bid, {}).get("chapter", "")
                if note and (sent.get("percent") != percent or sent.get("chapter") != chapter):
                    patch["note"] = note
                if patch:
                    ops.append(("PATCH", f"/task/{task['id']}", patch, bid,
                                {"checked": checked, "percent": percent, "chapter": chapter}))
            elif status == "unread" and wish_pid and book.get("source") != "folder":
                if task is None:
                    body = {"title": title, "projectId": wish_pid, "externalId": ext, "checked": 0}
                    if book.get("url"):
                        body["note"] = book["url"]
                    ops.append(("POST", "/task", body, bid, {"checked": 0}))
        return ops

    def _run_ops(self, ops, next_step):
        done_count = [0]
        failed = []

        def run():
            if not ops:
                if failed:
                    next_step(tr('не записано задач: {0}', len(failed)))
                else:
                    if done_count[0]:
                        log("singularity: изменено задач", done_count[0])
                    next_step()
                return
            method, path, body, bid, mark = ops.pop(0)

            def got(status, payload, err):
                if status in (200, 201):
                    done_count[0] += 1
                    self.state["sent"][bid] = {**self.state["sent"].get(bid, {}), **mark}
                else:
                    failed.append(bid)
                QTimer.singleShot(150, run)   # бережём API: запросы по одному
            self._request(method, path, body=body, done=got)
        run()

    # --- привычка «Чтение N минут»

    def _sync_habit(self, next_step):
        today = dt.date.today().isoformat()
        goal = int(self.state.get("dailyMinutes") or 20)
        title = f"Чтение {goal} {minutes_word(goal)}"

        def with_habit(hid):
            if not hid:
                next_step(tr("не удалось создать привычку в Singularity"))
                return
            if self.state["minutes"].get(today, 0) < goal * 60 or today in self.state["habitDone"]:
                next_step()
                return

            def marked(status, payload, err):
                if status in (200, 201):
                    self.state["habitDone"] = (self.state["habitDone"] + [today])[-30:]
                    self.app.toast(f"Singularity: привычка «{title}» отмечена")
                    next_step()
                else:
                    next_step(tr('не удалось отметить привычку ({0})', status or err))
            self._request("POST", "/habit-progress",
                          body={"habit": hid, "date": today, "progress": 2,
                                "externalId": f"{EXT_HABIT}-{today}"}, done=marked)

        hid = self.state["ids"].get(EXT_HABIT)
        if hid and self.state.get("habitTitle") == title:
            with_habit(hid)
            return

        def listed(habits, status, err):
            if habits is None:
                next_step(tr('не удалось получить привычки ({0})', status or err))
                return
            found = next((h for h in habits if h.get("externalId") == EXT_HABIT and not h.get("removed")), None)

            def remember(h_id):
                self.state["ids"][EXT_HABIT] = h_id
                self.state["habitTitle"] = title
                with_habit(h_id)
            if found:
                if found.get("title") != title:   # цель поменяли — переименуем привычку
                    self._request("PATCH", f"/habit/{found['id']}", body={"title": title},
                                  done=lambda *_: remember(found["id"]))
                else:
                    remember(found["id"])
                return
            self._request("POST", "/habit",
                          body={"title": title, "externalId": EXT_HABIT, "color": "lightBlue",
                                "description": "Отмечается само из Muninhall"},
                          done=lambda st, p, e: remember(p.get("id")) if st in (200, 201) and p else with_habit(None))
        self._list_all("/habit", "habits", {}, listed)


# --- окно настроек (раньше было в App)

def _switches():
    """Что синхронизировать: (ключ состояния, заголовок, пояснение)."""
    return (
        ("reading", tr("Задачи «Читаю»"), tr("Начатые книги — задачи в проекте «Книги», дочитанные закрываются")),
        ("progress", tr("Прогресс в задаче"), tr("Процент и текущая глава в заметке задачи")),
        ("wishlist", tr("«Хочу прочитать»"), tr("Непрочитанные книги — задачи в отдельном проекте")),
        ("daily", tr("Ежедневное чтение"), tr("Привычка отмечается сама, когда за день набралось N минут")),
    )


class SingularityDialog:
    """Окно «Singularity»: токен, что синхронизировать, библиотеки, цель чтения в день."""

    def __init__(self, app):
        self.app = app
        self.sync: SingularitySync = app.singularity
        self.dlg, v = frameless_dialog(app.window, "Singularity", 460)
        body = QWidget()
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(18, 18, 18, 18)
        self.box.setSpacing(8)
        self._build_token()
        self._build_switches()
        self._build_libraries()
        self._build_goal()
        self._build_buttons()
        v.addWidget(body)

    def exec(self):
        self.sync.status.connect(self.status.setText)
        exec_dialog(self.dlg)
        self.apply()
        self.sync.status.disconnect(self.status.setText)

    # --- разделы окна

    def _build_token(self):
        b = self.box
        intro = label(tr("Книги, прогресс и ежедневное чтение — в планировщике SingularityApp.<br>"
                      "Токен создаётся в <a href='https://me.singularity-app.com'>личном кабинете</a> → "
                      "«Доступ к API» (нужен доступ к задачам, проектам и привычкам)."), wrap=True, rich=True)
        intro.setOpenExternalLinks(True)
        b.addWidget(intro)
        self.token = QLineEdit(self.sync.state.get("token", ""))
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText(tr("API-токен Singularity"))
        b.addWidget(self.token)
        b.addSpacing(6)

    def _build_switches(self):
        boxed = BoxedList()
        self.switches = {}
        for key, title, hint in _switches():
            sw = Switch(bool(self.sync.state.get(key)))
            boxed.add_row(title, hint, sw)
            self.switches[key] = sw
        self.box.addWidget(boxed)

    def _build_libraries(self):
        """Книги каких библиотек ведутся задачами («Хочу прочитать» — только ЛитРес)."""
        libs = libraries.all_libraries(self.app.settings)
        allowed = self.sync.state.get("libraries")
        self.lib_switches = {}
        if len(libs) < 2:
            return
        self.box.addWidget(label(tr("Библиотеки"), "heading"))
        lib_box = BoxedList()
        for lib in libs:
            sw = Switch(allowed is None or lib["id"] in allowed)
            lib_box.add_row(lib["name"], "", sw, padding=(14, 6))
            self.lib_switches[lib["id"]] = sw
        self.box.addWidget(lib_box)

    def _build_goal(self):
        goal_row = QHBoxLayout()
        goal_row.addWidget(label(tr("Цель чтения в день, минут")), 1)
        self.goal = QSpinBox()
        self.goal.setRange(5, 240)
        self.goal.setSingleStep(5)
        self.goal.setValue(int(self.sync.state.get("dailyMinutes") or 20))
        goal_row.addWidget(self.goal)
        self.box.addLayout(goal_row)
        self.box.addWidget(label(tr('Сегодня прочитано и прослушано: {0} мин', self.sync.today_minutes()),
                                 "dim", "caption"))

    def _build_buttons(self):
        self.status = label("", "dim", wrap=True)
        self.box.addWidget(self.status)
        buttons = QHBoxLayout()
        disconnect = QPushButton(tr("Отключить"))
        disconnect.clicked.connect(self.disconnect)
        self.run = QPushButton(tr("Проверить и синхронизировать"))
        cls(self.run, "suggested")
        self.run.clicked.connect(self.check_and_sync)
        buttons.addWidget(disconnect)
        buttons.addStretch()
        buttons.addWidget(self.run)
        self.box.addSpacing(6)
        self.box.addLayout(buttons)

    # --- действия

    def apply(self):
        chosen = [lid for lid, sw in self.lib_switches.items() if sw.isChecked()]
        self.sync.configure(token=self.token.text().strip(), dailyMinutes=self.goal.value(),
                            libraries=None if len(chosen) == len(self.lib_switches) else chosen,
                            **{k: sw.isChecked() for k, sw in self.switches.items()})

    def check_and_sync(self):
        self.apply()
        if not self.sync.enabled:
            self.status.setText(tr("Вставьте токен"))
            return
        self.status.setText(tr("Проверяю токен…"))
        self.run.setEnabled(False)

        def checked(ok, text):
            self.run.setEnabled(True)
            self.status.setText(text + (tr("; синхронизирую…") if ok else ""))
            if ok:
                self.sync.sync()
        self.sync.check_token(checked)

    def disconnect(self):
        self.sync.configure(token="")
        self.token.clear()
        self.status.setText(tr("Синхронизация с Singularity отключена"))


def show_dialog(app):
    SingularityDialog(app).exec()
