"""Данные библиотеки ЛитРес: книги аккаунта, «Читаю сейчас», папки и очередь их изменений.

Функции работают с model.Library (книги, порядок, папки ЛитРес, очередь изменений папок, статистика);
сеть и интерфейс — в litres.py и litres_connector.py.
"""
from __future__ import annotations

from .core import COVERS_BASE, SITE, absolute, log, parse_time
from .i18n import tr


def merge_litres(lib, arts: list[dict]):
    """Добавляет/обновляет книги из аккаунта, не трогая скачанные файлы."""
    ids = []
    for art in arts:
        bid = str(art.get("id"))
        if not bid.isdigit():
            log("пропущена книга с некорректным id:", repr(bid)[:40])
            continue
        prev = lib.books.get(bid, {})
        prev_percent, prev_at, was_finished = (prev.get("remote_percent"), prev.get("remote_read_at"),
                                               prev.get("finished"))
        authors = [p.get("full_name") for p in art.get("persons") or []
                   if p.get("role") == "author" and p.get("full_name")]
        book = lib.books.setdefault(bid, {"id": bid, "source": "litres"})
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
        # Когда и где читали на ЛитРес (телефон, сайт) — для панели «Продолжить чтение»
        read_at = parse_time(art.get("read_at"))
        if read_at:
            book["remote_read_at"] = read_at
        else:
            book.pop("remote_read_at", None)
        chapter = art.get("last_read_chapter_number")
        if chapter:
            book["remote_chapter"] = tr('Глава {0}', chapter)
        else:
            book.pop("remote_chapter", None)
        if art.get("symbols_count"):
            book["symbols"] = int(art["symbols_count"])
        # Прочитанное на телефоне/сайте — в статистику (только прирост с прошлой синхронизации)
        new_percent = book.get("remote_percent")
        if (prev_percent is not None and new_percent is not None and new_percent > prev_percent
                and read_at and read_at > (prev_at or 0)):
            lib.reading.add_remote_reading(book, new_percent - prev_percent, read_at)
        if book["finished"] and was_finished is False:
            lib.reading.mark_finished(bid)
        if art.get("in_folders") is not None:
            book["folders"] = [str(f.get("folder_id")) for f in art["in_folders"]
                               if f.get("folder_id") is not None]
        if art.get("purchased_at"):
            book["purchased_at"] = art["purchased_at"]
        # Серия: первая из списка — название и номер книги в ней
        series = [s for s in art.get("series") or [] if isinstance(s, dict) and s.get("name")]
        if series:
            order = series[0].get("art_order")
            book["series"] = {"name": series[0]["name"],
                              "order": float(order) if order is not None else None}
        else:
            book.pop("series", None)
        ids.append(bid)
    local = [i for i in lib.order if i in lib.books and i not in ids]
    lib.order = ids + local
    apply_pending_folder_ops(lib)
    lib.save()


def set_in_progress(lib, ids):
    """Книги из списка ЛитРес «Читаю сейчас»."""
    ids = {str(i) for i in ids}
    for bid, book in lib.books.items():
        if book.get("source") == "litres":
            book["in_progress"] = bid in ids
    lib.save()


def set_in_folder(lib, bid, fid, inside: bool):
    """Локально кладёт книгу в папку (или убирает) и ставит изменение в очередь."""
    book = lib.books[bid]
    folders = [f for f in book.get("folders") or [] if f != fid]
    if inside:
        folders.append(fid)
    book["folders"] = folders
    op = "add" if inside else "remove"
    # Противоположное неотправленное изменение просто отменяем
    opposite = {"op": "remove" if inside else "add", "folder": fid, "art": bid}
    if opposite in lib.folder_ops:
        lib.folder_ops.remove(opposite)
    else:
        lib.folder_ops.append({"op": op, "folder": fid, "art": bid})
    lib.save()


def apply_pending_folder_ops(lib):
    """Неотправленные изменения папок важнее ответа сервера — накладываем их поверх."""
    for op in lib.folder_ops:
        book = lib.books.get(op["art"])
        if not book:
            continue
        folders = [f for f in book.get("folders") or [] if f != op["folder"]]
        if op["op"] == "add":
            folders.append(op["folder"])
        book["folders"] = folders


def set_folders(lib, folders: dict[str, str], members: dict[str, list[str]] | None):
    """folders — {id: название}; members — {id папки: [id книг]} (если известно)."""
    lib.folders = folders
    if members is not None:
        for book in lib.books.values():
            if book.get("source") == "litres":
                book["folders"] = [fid for fid, ids in members.items() if book["id"] in ids]
    apply_pending_folder_ops(lib)
    lib.save()
