"""ЛитРес — подключаемая коммерческая библиотека.

Вход и выход, синхронизация списка книг и папок, отметка «прочитано», скачивание книг
(по одной и все разом), папки ЛитРес, место чтения с телефона и сайта, жанры и теги для графа.
Окно, фильтры и страницы — в App (app.py); сессия и API — в LitresSession (litres.py).
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWidgets import QLineEdit, QMessageBox, QVBoxLayout, QWidget

from . import litres_data
from .i18n import plural, tr
from .core import (AUDIO_FILE_TYPES, AUDIO_FORMATS, FORMAT_ORDER, LOCAL_SUFFIX, LOGIN_URL, API, READABLE,
                   SITE, books_dir, looks_like_book)
from .widgets import BoxedList, confirm, exec_dialog, frameless_dialog, label, Switch

class _Bridge(QObject):
    """Передаёт результат из рабочего потока в главный."""
    done = Signal(object, object)


class LitresConnector(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.downloading: set[str] = set()
        self.bulk = None        # скачивание всех книг разом: очередь и счётчики
        self.syncing = False
        self._startup_synced = False

    def on_login_state(self):
        if not self.app.has_litres():          # ЛитРес отключён — только заголовок
            self.app._update_account_ui()
            return
        self.app._update_account_ui()
        if self.app.litres.logged_in:
            if self.app.current() is self.app.login_page:
                self.app.go_back()
                self.app.toast(tr("Вы вошли в ЛитРес"))
                self.sync()
            elif not getattr(self, "_startup_synced", False):
                # При запуске тихо забираем свежие данные (в том числе место чтения на ЛитРес)
                self._startup_synced = True
                self.sync(quiet=bool(self.app.library.books))

    def toggle_account(self):
        self.on_logout() if self.app.litres.logged_in else self.show_login()

    def show_login(self):
        self.app.litres.start()
        self.app.push(self.app.login_page)
        if not self.app.litres.logged_in:
            self.app.litres.page.load(QUrl(LOGIN_URL))

    def on_logout(self):
        if confirm(self.app.window, tr("Выйти из ЛитРес?"), tr("<b>Выйти из ЛитРес?</b>"),
                   tr("Скачанные книги и закладки останутся на этом компьютере."), tr("Выйти")):
            self.app.litres.logout(lambda: (self.app._update_account_ui(), self.app.toast(tr("Вы вышли из ЛитРес"))))

    def flush_folder_ops(self, then=None):
        """Отправляет накопленные изменения папок на ЛитРес по одному."""
        ops = self.app.library.folder_ops
        if not ops or not self.app.litres.logged_in:
            if then:
                then()
            return
        op = ops[0]

        def done(ok):
            if ok:
                if op in self.app.library.folder_ops:
                    self.app.library.folder_ops.remove(op)
                self.app.library.save()
                self.flush_folder_ops(then)
            else:
                self.app.toast(tr("Не удалось изменить папку на ЛитРес — повторю при синхронизации"))
                if then:
                    then()
        self.app.litres.folder_change(op["folder"], [op["art"]], op["op"] == "add", done)

    def sync(self, quiet=False):
        if self.syncing:
            return
        self.app.rescan_local()
        if not self.app.litres.logged_in:
            self.show_login()
            return
        self.app._set_syncing(True)
        problems = []
        state = {}

        def finish(text):
            self.app._set_syncing(False)
            self.app.refresh_library()
            self._fetch_details()
            # Открытая книга могла уйти дальше на ЛитРес — подтягиваем место
            for bid in {self.app.reader.book["id"] if self.app.reader else None, self.app.player.book_id} - {None}:
                if bid in self.app.library.books:
                    self.apply_remote_position(self.app.library.books[bid])
            if problems:
                text += tr(". Не получено: ") + ", ".join(problems)
            if not quiet or problems:
                self.app.toast(text)
            self.app.singularity.schedule(soon=True)

        def got_arts(arts, status):
            if arts is None:
                self.app._set_syncing(False)
                if status in (401, 403):
                    self.app.litres.logged_in = False
                    self.app._update_account_ui()
                    self.app.toast(tr("Сессия ЛитРес истекла — войдите снова"))
                else:
                    self.app.toast(tr('Не удалось получить список книг (код {0})', status))
                return
            # Отметки «прочитано», которые не успели уйти на ЛитРес, важнее ответа сервера
            pending = {bid: b["finished_pending"] for bid, b in self.app.library.books.items()
                       if "finished_pending" in b}
            litres_data.merge_litres(self.app.library, arts)
            for bid, value in pending.items():
                if bid in self.app.library.books:
                    self.app.set_finished(self.app.library.books[bid], value)
            state["count"] = len(arts)
            state["has_folders_field"] = any("in_folders" in a for a in arts)
            self.app.litres.fetch_list("/users/me/arts/in-progress", got_progress)

        def got_progress(arts, _status):
            if arts is None:
                problems.append(tr("«Читаю сейчас»"))
            else:
                litres_data.set_in_progress(self.app.library, [a.get("id") for a in arts])
            self.app.litres.fetch_folders(got_folders)

        def got_folders(folders, _status):
            if folders is None:
                problems.append(tr("папки"))
                finish(tr('Книг в аккаунте: {0}', state['count']))
                return
            if state["has_folders_field"] or not folders:
                litres_data.set_folders(self.app.library, folders, None)
                finish(tr('Книг в аккаунте: {0}', state['count']))
                return
            members: dict[str, list[str]] = {}
            queue = list(folders)

            def next_folder():
                if not queue:
                    litres_data.set_folders(self.app.library, folders, members)
                    finish(tr('Книг в аккаунте: {0}', state['count']))
                    return
                fid = queue.pop(0)

                def got(arts, _st):
                    if arts is None:
                        problems.append(tr('папка «{0}»', folders[fid]))
                    else:
                        members[fid] = [str(a.get("id")) for a in arts]
                    next_folder()
                self.app.litres.fetch_list(f"/folders/{fid}/arts", got)
            next_folder()

        # Сначала отправляем свои изменения папок, потом забираем состояние с сервера
        self.flush_folder_ops(lambda: self.app.litres.fetch_library(got_arts))

    def download_book(self, book, open_after=False, on_finished=None):
        """on_finished(ok, текст ошибки) — для скачивания всех книг: тогда ошибки не всплывают по одной."""
        bid = book["id"]
        if bid in self.downloading:
            return
        if not self.app.litres.logged_in:
            self.app.toast(tr("Сначала войдите в ЛитРес"))
            self.show_login()
            return
        self.downloading.add(bid)
        card = self.app.cards.get(bid)
        if card:
            card.set_download_progress(0)

        def fail(text):
            self.downloading.discard(bid)
            if card:
                card.set_download_progress(None)
            if on_finished:
                on_finished(False, text)
            else:
                self.app.toast(text)

        def got_files(files, status):
            if files is None:
                fail(tr('Не удалось получить файлы книги (код {0})', status))
                return
            main = [f for f in files if not f.get("is_additional")] or files
            if book.get("is_audio"):
                by_type = {f.get("file_type"): f for f in main if f.get("file_type")}
                choice = next(((t, ext) for t, ext in AUDIO_FILE_TYPES if t in by_type), None)
                if not choice:
                    fail(tr("Для этой аудиокниги доступны только отдельные главы — пока не поддерживается"))
                    return
                ftype, local = choice
                f = by_type[ftype]
                remote_ext = f.get("extension") or local
                dest = books_dir() / f"{bid}.{local}"
                try_next([f"{SITE}/download_book/{bid}/{f['id']}/{bid}.{remote_ext}",
                          f"{SITE}/download_book_subscr/{bid}/{f['id']}/{bid}.{remote_ext}"], dest, local, local)
                return
            by_ext = {f.get("extension"): f for f in main if f.get("extension")}
            fmt = next((e for e in FORMAT_ORDER if e in by_ext), None)
            if not fmt:
                fail(tr("У этой книги нет формата для чтения (возможно, только онлайн-чтение)"))
                return
            file_id = by_ext[fmt]["id"]
            local_ext = LOCAL_SUFFIX.get(fmt, fmt)
            dest = books_dir() / f"{bid}.{local_ext}"
            try_next([f"{SITE}/download_book/{bid}/{file_id}/{bid}.{fmt}",
                      f"{SITE}/download_book_subscr/{bid}/{file_id}/{bid}.{fmt}"], dest, fmt, local_ext)

        def finished_ok(file_name, fmt_saved, path):
            self.downloading.discard(bid)
            if card:
                card.set_download_progress(None)
            book.update(file=file_name, format=fmt_saved)
            self.app.library.save()
            self.app.refresh_card(bid)
            if on_finished:
                on_finished(True, None)
                return
            if book.get("is_drm"):
                self.app.toast(tr("Книга защищена DRM — она может не открыться"))
            if open_after:
                self.app.open_book(book, path)

        def try_next(attempts, dest, fmt, local_ext):
            url = attempts.pop(0)

            def done(ok, err):
                if ok and looks_like_book(dest, fmt) and book.get("is_audio") and fmt == "zip":
                    folder = books_dir() / bid   # MP3-архив распаковываем в папку книги

                    def extracted(error):
                        if error:
                            fail(tr('Не удалось распаковать аудиокнигу: {0}', error))
                        else:
                            finished_ok(folder.name, "mp3dir", folder)
                    self._extract_zip(dest, folder, extracted)
                    return
                if ok and looks_like_book(dest, fmt):
                    finished_ok(dest.name, local_ext if local_ext in READABLE | AUDIO_FORMATS else fmt, dest)
                    return
                dest.unlink(missing_ok=True)
                if attempts:
                    try_next(attempts, dest, fmt, local_ext)
                else:
                    fail(tr('ЛитРес не отдал файл книги ({0})', err or tr('неверный ответ')))

            self.app.litres.download(url, dest, lambda f: card and card.set_download_progress(f), done)

        self.app.litres.fetch_files(bid, got_files)


    def download_all(self):
        if self.bulk:
            self.bulk["queue"].clear()      # текущая книга докачается, остальные — нет
            self.app.download_all_action.setText(tr("Скачивание останавливается…"))
            return
        if not self.app.litres.logged_in:
            self.app.toast(tr("Сначала войдите в ЛитРес"))
            self.show_login()
            return
        missing = [b for b in self.app.library.ordered()
                   if b.get("source") == "litres" and b["id"] not in self.downloading
                   and not self.app.library.file_path(b)]
        texts = [b for b in missing if not b.get("is_audio")]
        audio = [b for b in missing if b.get("is_audio")]
        if not missing:
            self.app.toast(tr("Все книги ЛитРес уже скачаны"))
            return
        box = QMessageBox(self.app.window)
        box.setWindowTitle(tr("Скачать все книги?"))
        box.setText(tr("<b>Скачать все книги на компьютер?</b>"))
        box.setInformativeText(
            tr('Не скачано: {0} {1}', len(texts), plural(len(texts), 'книга', 'книги', 'книг'))
            + (tr(' и {0} {1} (аудиокниги большие — сотни мегабайт каждая)', len(audio),
                  plural(len(audio), 'аудиокнига', 'аудиокниги', 'аудиокниг')) if audio else "")
            + tr('.\nПапка: {0}\nКниги скачиваются по одной; остановить можно в меню.', books_dir()))
        cancel = box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
        only_text = box.addButton(tr('Книги ({0})', len(texts)), QMessageBox.ButtonRole.AcceptRole) if texts else None
        everything = (box.addButton(tr('Всё, с аудио ({0})', len(missing)), QMessageBox.ButtonRole.AcceptRole)
                      if audio else None)
        box.setDefaultButton(only_text or everything)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel or clicked is None:
            return
        queue = missing if clicked is everything else texts
        self.bulk = {"queue": list(queue), "total": len(queue), "done": 0, "failed": 0, "errors": []}
        self.app.download_all_action.setText(tr("Остановить скачивание книг"))
        self._bulk_next()

    def _bulk_next(self):
        b = self.bulk
        self.app._update_account_ui()
        if not b["queue"]:
            self.bulk = None
            self.app.download_all_action.setText(tr("Скачать все книги…"))
            self.app._update_account_ui()
            stopped = b["done"] + b["failed"] < b["total"]
            text = tr('Скачано {0} из {1}', b['done'], b['total']) + (tr(" — остановлено") if stopped else "")
            if b["failed"]:
                text += tr(', не удалось: {0} (список — в журнале)', b['failed'])
                for title, err in b["errors"]:
                    print(f"muninhall: не скачалась «{title}»: {err}", file=sys.stderr, flush=True)
            self.app.toast(text, timeout=8000)
            return
        book = b["queue"].pop(0)

        def finished(ok, err):
            if ok:
                b["done"] += 1
            else:
                b["failed"] += 1
                b["errors"].append((book.get("title") or book["id"], err))
            # небольшая пауза между книгами — не дёргаем ЛитРес слишком часто
            QTimer.singleShot(500, self._bulk_next)

        if not self.app.litres.logged_in:
            b["queue"].clear()
            finished(False, tr("вход в ЛитРес не выполнен"))
            return
        self.download_book(book, on_finished=finished)

    def _extract_zip(self, zip_path: Path, dest_dir: Path, on_done):
        """Распаковка MP3-архива в отдельном потоке (архивы бывают большими)."""
        bridge = _Bridge(self)
        bridge.done.connect(lambda err, _x: (on_done(err), bridge.deleteLater()))

        def work():
            try:
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(dest_dir)
                zip_path.unlink(missing_ok=True)
                bridge.done.emit(None, None)
            except (OSError, zipfile.BadZipFile) as e:
                shutil.rmtree(dest_dir, ignore_errors=True)
                bridge.done.emit(str(e), None)
        threading.Thread(target=work, daemon=True).start()

    def show_folders_dialog(self, book):
        """Окно выбора папок ЛитРес для книги: переключатель у каждой папки и новая папка."""
        dlg, v = frameless_dialog(self.app.window, tr("Папки"), 400)

        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 18, 18, 18)
        b.setSpacing(6)
        b.addWidget(label(book.get("title") or "", "heading", wrap=True))
        desc = label(tr("Изменения сразу отправляются на ЛитРес"), "dim", wrap=True)
        b.addWidget(desc)
        b.addSpacing(6)
        boxed = BoxedList()
        b.addWidget(boxed)
        switches = []

        def add_row(fid, name):
            sw = Switch(fid in (book.get("folders") or []))
            sw.toggled.connect(lambda on: self.set_book_folder(book, fid, on))
            boxed.add_row(name, "", sw, padding=(14, 10))
            switches.append(sw)
            boxed.setVisible(True)

        for fid, name in self.app.library.folders.items():
            add_row(fid, name)
        if not self.app.library.folders:
            boxed.setVisible(False)
            desc.setText(tr("Папок пока нет — создайте первую ниже"))

        b.addSpacing(12)
        entry = QLineEdit()
        entry.setPlaceholderText(tr("Новая папка — введите название и нажмите Enter"))
        b.addWidget(entry)

        def create():
            title = entry.text().strip()
            if not title:
                return
            if not self.app.litres.logged_in:
                self.app.toast(tr("Чтобы создать папку, войдите в ЛитРес"))
                return
            entry.setEnabled(False)

            def done(folders, new_id):
                entry.setEnabled(True)
                if folders is None or new_id is None:
                    self.app.toast(tr("Не удалось создать папку на ЛитРес"))
                    return
                entry.clear()
                litres_data.set_folders(self.app.library, folders, None)
                add_row(new_id, folders[new_id])
                desc.setText(tr("Изменения сразу отправляются на ЛитРес"))
                switches[-1].setChecked(True)   # сразу кладём книгу в новую папку
                self.app._update_filter_bar()
            self.app.litres.create_folder(title, done)
        entry.returnPressed.connect(create)
        v.addWidget(body)

        exec_dialog(dlg)

    def set_book_folder(self, book, fid, inside: bool):
        if inside == (fid in (book.get("folders") or [])):
            return
        litres_data.set_in_folder(self.app.library, book["id"], fid, inside)
        self.app._update_filter_bar()
        self.app._apply_filter()
        self.flush_folder_ops()

    def apply_remote_position(self, book, _attempt=0):
        """Синхронизация места: если на ЛитРес ушли дальше — переходим туда сами.

        В уведомлении есть «Вернуть»; после него это место с ЛитРес больше не применяется.
        """
        remote = book.get("remote_percent") or 0
        if remote < 1 or book.get("remote_ignored") == remote:
            return
        bid = book["id"]
        target = min(remote, 99.9) / 100

        def ignore():
            book["remote_ignored"] = remote
            self.app.library.save()

        if self.app.reader and self.app.reader.book["id"] == bid:
            local = (self.app.library.progress.get(bid, {}).get("fraction") or 0) * 100
            if remote - local < 1:
                return
            back_cfi = self.app.library.progress.get(bid, {}).get("cfi")
            self.app.reader.js(f"window.reader.goToFraction({target})")

            def undo():
                ignore()
                if back_cfi and self.app.reader and self.app.reader.book["id"] == bid:
                    self.app.reader.js(f"window.reader.goTo({json.dumps(back_cfi)})")
            self.app.toast(tr('Продолжаю с места на ЛитРес — {0}%', round(remote)), button=tr("Вернуть"),
                       on_button=undo, timeout=8000)
        elif self.app.player.book_id == bid:
            if not self.app.player.duration():
                # Файл ещё загружается — попробуем чуть позже
                if _attempt < 10:
                    QTimer.singleShot(1000, lambda: self.apply_remote_position(book, _attempt + 1))
                return
            if remote - self.app.player.fraction() * 100 < 1:
                return
            index, pos = self.app.player.index, self.app.player.position()
            self.app.player.go_to_fraction(target)

            def undo():
                ignore()
                if self.app.player.book_id == bid:
                    self.app.player.go_to(index, pos)
            self.app.toast(tr('Продолжаю с места на ЛитРес — {0}%', round(remote)), button=tr("Вернуть"),
                       on_button=undo, timeout=8000)

    def _fetch_details(self):
        """Жанры и теги книг ЛитРес — их нет в списке книг, только в карточке каждой.
        Подгружаем в фоне по одной (раз на книгу), потом обновляем граф."""
        if self.app._details_running or not self.app.litres.logged_in:
            return
        todo = [b for b in self.app.library.books.values() if b.get("source") == "litres" and "genres" not in b]
        if not todo:
            return
        self.app._details_running = True

        def step(i):
            if self.app.graph_page:
                self.app.graph_page.set_fetch_progress(i, len(todo))
            if i >= len(todo) or not self.app.litres.logged_in:
                self.app._details_running = False
                self.app.library.save()
                if self.app.graph_page:
                    self.app.graph_page.refresh()
                return
            book = todo[i]

            def done(status, data):
                if status == 200 and data:
                    d = (data.get("payload") or {}).get("data") or {}
                    book["genres"] = [g["name"] for g in d.get("genres") or [] if g.get("name")]
                    book["tags"] = [t["name"] for t in d.get("tags") or [] if t.get("name")][:8]
                elif status == 404:
                    book["genres"], book["tags"] = [], []
                if i % 20 == 19:
                    self.app.library.save()
                    if self.app.graph_page:
                        self.app.graph_page.refresh()
                QTimer.singleShot(250, lambda: step(i + 1))
            self.app.litres.api_get(f"{API}/arts/{book['id']}", done)
        step(0)

    def _periodic_sync(self):
        if not self.app.has_litres():
            return
        if self.app.litres.logged_in and not self.syncing and self.app.window.isVisible():
            self.sync(quiet=True)

    def apply_remote_sync(self):
        minutes = int(self.app.settings.get("remoteSyncMin") or 0)
        if minutes > 0:
            self.app._remote_timer.start(minutes * 60 * 1000)
        else:
            self.app._remote_timer.stop()
