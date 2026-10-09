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
from PySide6.QtWidgets import QMessageBox

from . import litres_data, litres_folders
from .i18n import plural, tr
from .core import (AUDIO_FILE_TYPES, AUDIO_FORMATS, FORMAT_ORDER, LOCAL_SUFFIX, LOGIN_URL, API, READABLE,
                   SITE, books_dir, looks_like_book)
from .widgets import confirm

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
        _SyncRun(self, quiet).start()

    def download_book(self, book, open_after=False, on_finished=None):
        """on_finished(ok, текст ошибки) — для скачивания всех книг: тогда ошибки не всплывают по одной."""
        if book["id"] in self.downloading:
            return
        if not self.app.litres.logged_in:
            self.app.toast(tr("Сначала войдите в ЛитРес"))
            self.show_login()
            return
        _Download(self, book, open_after, on_finished).start()

    def download_all(self):
        if self.bulk:
            self.bulk["queue"].clear()      # текущая книга докачается, остальные — нет
            self.app.library_view.download_all_action.setText(tr("Скачивание останавливается…"))
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
        self.app.library_view.download_all_action.setText(tr("Остановить скачивание книг"))
        self._bulk_next()

    def _bulk_next(self):
        b = self.bulk
        self.app._update_account_ui()
        if not b["queue"]:
            self.bulk = None
            self.app.library_view.download_all_action.setText(tr("Скачать все книги…"))
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
        litres_folders.show_folders_dialog(self, book)

    def set_book_folder(self, book, fid, inside: bool):
        if inside == (fid in (book.get("folders") or [])):
            return
        litres_data.set_in_folder(self.app.library, book["id"], fid, inside)
        self.app.library_view._update_filter_bar()
        self.app.library_view._apply_filter()
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


def pick_download(book: dict, files: list[dict], bid: str):
    """Какой файл книги скачать: (адреса по очереди, формат на ЛитРес, расширение у себя) или (None, ошибка)."""
    main = [f for f in files if not f.get("is_additional")] or files
    if book.get("is_audio"):
        by_type = {f.get("file_type"): f for f in main if f.get("file_type")}
        choice = next(((t, ext) for t, ext in AUDIO_FILE_TYPES if t in by_type), None)
        if not choice:
            return None, tr("Для этой аудиокниги доступны только отдельные главы — пока не поддерживается")
        ftype, local = choice
        f = by_type[ftype]
        remote_ext = f.get("extension") or local
        return ([f"{SITE}/download_book/{bid}/{f['id']}/{bid}.{remote_ext}",
                 f"{SITE}/download_book_subscr/{bid}/{f['id']}/{bid}.{remote_ext}"], local, local), None
    by_ext = {f.get("extension"): f for f in main if f.get("extension")}
    fmt = next((e for e in FORMAT_ORDER if e in by_ext), None)
    if not fmt:
        return None, tr("У этой книги нет формата для чтения (возможно, только онлайн-чтение)")
    file_id = by_ext[fmt]["id"]
    return ([f"{SITE}/download_book/{bid}/{file_id}/{bid}.{fmt}",
             f"{SITE}/download_book_subscr/{bid}/{file_id}/{bid}.{fmt}"], fmt, LOCAL_SUFFIX.get(fmt, fmt)), None


class _SyncRun:
    """Одна синхронизация с ЛитРес: свои изменения папок → список книг → «Читаю сейчас» → папки."""

    def __init__(self, connector: LitresConnector, quiet: bool):
        self.c = connector
        self.app = connector.app
        self.quiet = quiet
        self.problems: list[str] = []
        self.count = 0
        self.has_folders_field = False

    def start(self):
        self.app._set_syncing(True)
        # Сначала отправляем свои изменения папок, потом забираем состояние с сервера
        self.c.flush_folder_ops(lambda: self.app.litres.fetch_library(self.got_arts))

    def got_arts(self, arts, status):
        app = self.app
        if arts is None:
            app._set_syncing(False)
            if status in (401, 403):
                app.litres.logged_in = False
                app._update_account_ui()
                app.toast(tr("Сессия ЛитРес истекла — войдите снова"))
            else:
                app.toast(tr('Не удалось получить список книг (код {0})', status))
            return
        # Отметки «прочитано», которые не успели уйти на ЛитРес, важнее ответа сервера
        pending = {bid: b["finished_pending"] for bid, b in app.library.books.items() if "finished_pending" in b}
        litres_data.merge_litres(app.library, arts)
        for bid, value in pending.items():
            if bid in app.library.books:
                app.set_finished(app.library.books[bid], value)
        self.count = len(arts)
        self.has_folders_field = any("in_folders" in a for a in arts)
        app.litres.fetch_list("/users/me/arts/in-progress", self.got_progress)

    def got_progress(self, arts, _status):
        if arts is None:
            self.problems.append(tr("«Читаю сейчас»"))
        else:
            litres_data.set_in_progress(self.app.library, [a.get("id") for a in arts])
        self.app.litres.fetch_folders(self.got_folders)

    def got_folders(self, folders, _status):
        if folders is None:
            self.problems.append(tr("папки"))
            self.finish()
        elif self.has_folders_field or not folders:
            litres_data.set_folders(self.app.library, folders, None)
            self.finish()
        else:
            self.fetch_members(folders, {}, list(folders))

    def fetch_members(self, folders, members: dict[str, list[str]], queue: list[str]):
        """Старый ответ API без in_folders: состав папок — по одной папке за запрос."""
        if not queue:
            litres_data.set_folders(self.app.library, folders, members)
            self.finish()
            return
        fid = queue.pop(0)

        def got(arts, _st):
            if arts is None:
                self.problems.append(tr('папка «{0}»', folders[fid]))
            else:
                members[fid] = [str(a.get("id")) for a in arts]
            self.fetch_members(folders, members, queue)
        self.app.litres.fetch_list(f"/folders/{fid}/arts", got)

    def finish(self):
        app = self.app
        app._set_syncing(False)
        app.library_view.refresh_library()
        self.c._fetch_details()
        # Открытая книга могла уйти дальше на ЛитРес — подтягиваем место
        for bid in {app.reader.book["id"] if app.reader else None, app.player.book_id} - {None}:
            if bid in app.library.books:
                self.c.apply_remote_position(app.library.books[bid])
        text = tr('Книг в аккаунте: {0}', self.count)
        if self.problems:
            text += tr(". Не получено: ") + ", ".join(self.problems)
        if not self.quiet or self.problems:
            app.toast(text)
        app.singularity.schedule(soon=True)


class _Download:
    """Скачивание одной книги ЛитРес: выбор файла → попытки по адресам → распаковка MP3-архива."""

    def __init__(self, connector: LitresConnector, book: dict, open_after: bool, on_finished):
        self.c = connector
        self.app = connector.app
        self.book = book
        self.bid = book["id"]
        self.open_after = open_after
        self.on_finished = on_finished
        self.card = self.app.library_view.cards.get(self.bid)

    def start(self):
        self.c.downloading.add(self.bid)
        self._progress(0)
        self.app.litres.fetch_files(self.bid, self.got_files)

    def _progress(self, fraction):
        if self.card:
            self.card.set_download_progress(fraction)

    def _done(self):
        self.c.downloading.discard(self.bid)
        self._progress(None)

    def fail(self, text):
        self._done()
        if self.on_finished:
            self.on_finished(False, text)
        else:
            self.app.toast(text)

    def got_files(self, files, status):
        if files is None:
            self.fail(tr('Не удалось получить файлы книги (код {0})', status))
            return
        choice, error = pick_download(self.book, files, self.bid)
        if error:
            self.fail(error)
            return
        urls, fmt, local_ext = choice
        self.try_next(urls, books_dir() / f"{self.bid}.{local_ext}", fmt, local_ext)

    def try_next(self, attempts, dest, fmt, local_ext):
        url = attempts.pop(0)

        def done(ok, err):
            good = ok and looks_like_book(dest, fmt)
            if good and self.book.get("is_audio") and fmt == "zip":
                self.extract(dest)
            elif good:
                self.finished_ok(dest.name, local_ext if local_ext in READABLE | AUDIO_FORMATS else fmt, dest)
            else:
                dest.unlink(missing_ok=True)
                if attempts:
                    self.try_next(attempts, dest, fmt, local_ext)
                else:
                    self.fail(tr('ЛитРес не отдал файл книги ({0})', err or tr('неверный ответ')))

        self.app.litres.download(url, dest, self._progress, done)

    def extract(self, archive):
        """MP3-архив распаковываем в папку книги."""
        folder = books_dir() / self.bid

        def extracted(error):
            if error:
                self.fail(tr('Не удалось распаковать аудиокнигу: {0}', error))
            else:
                self.finished_ok(folder.name, "mp3dir", folder)
        self.c._extract_zip(archive, folder, extracted)

    def finished_ok(self, file_name, fmt_saved, path):
        self._done()
        self.book.update(file=file_name, format=fmt_saved)
        self.app.library.save()
        self.app.library_view.refresh_card(self.bid)
        if self.on_finished:
            self.on_finished(True, None)
            return
        if self.book.get("is_drm"):
            self.app.toast(tr("Книга защищена DRM — она может не открыться"))
        if self.open_after:
            self.app.open_book(self.book, path)

