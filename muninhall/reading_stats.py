"""Статистика чтения: секунды по дням, по книгам и по библиотекам, даты дочитывания (stats.json)."""
from __future__ import annotations

import time
from typing import Callable

from .core import READING_CHARS_PER_MIN, REMOTE_MAX_PER_SYNC, STATS_FILE, load_json, log, save_json


class ReadingStats:
    """data — словарь stats.json: days, books, finished, remote_days, lib_days, lib_remote_days.

    library_of(bid) говорит, к какой библиотеке относится книга ("litres", id своей или "local").
    """

    def __init__(self, library_of: Callable[[str], str], path=STATS_FILE):
        self.path = path
        self.library_of = library_of
        self.chars_per_min = READING_CHARS_PER_MIN     # скорость для оценки чтения на телефоне
        self.data: dict = {"days": {}, "books": {}, "finished": {}, **load_json(path, {})}
        if "lib_days" not in self.data:
            # по библиотекам время пишется с версии 0.15; раньше в приложении читали только книги ЛитРес —
            # если в статистике нет других книг, прошлое время целиком относим к ЛитРес
            only_litres = all(str(b).isdigit() for b in self.data["books"])
            self.data["lib_days"] = {"litres": dict(self.data["days"])} if only_litres and self.data["days"] else {}
            self.data["lib_remote_days"] = ({"litres": dict(self.data.get("remote_days", {}))}
                                            if only_litres and self.data.get("remote_days") else {})

    def save(self):
        save_json(self.path, self.data)

    def _add_lib_day(self, key, bid, day, seconds):
        days = self.data.setdefault(key, {}).setdefault(self.library_of(bid), {})
        days[day] = days.get(day, 0) + seconds

    def add_reading_time(self, bid, seconds):
        day = time.strftime("%Y-%m-%d")
        self.data["days"][day] = self.data["days"].get(day, 0) + seconds
        if bid:
            self.data["books"][bid] = self.data["books"].get(bid, 0) + seconds
            self._add_lib_day("lib_days", bid, day, seconds)
        self.save()

    def add_remote_reading(self, book, percent_delta: float, when: float):
        """Время, прочитанное или прослушанное вне приложения (оценка по приросту процента)."""
        size = book.get("symbols") or 0
        if size <= 0 or percent_delta <= 0:
            return
        part = size * percent_delta / 100
        speed = self.chars_per_min or READING_CHARS_PER_MIN
        seconds = part if book.get("is_audio") else part / speed * 60
        seconds = int(min(seconds, REMOTE_MAX_PER_SYNC))
        if seconds < 30:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(when))
        for key, k in (("days", day), ("books", book["id"])):
            self.data[key][k] = self.data[key].get(k, 0) + seconds
        remote = self.data.setdefault("remote_days", {})
        remote[day] = remote.get(day, 0) + seconds
        self._add_lib_day("lib_days", book["id"], day, seconds)
        self._add_lib_day("lib_remote_days", book["id"], day, seconds)
        self.save()
        log(f"чтение вне приложения: {book.get('title')} +{percent_delta:g}% ≈ {seconds // 60} мин ({day})")

    def mark_finished(self, bid):
        if bid not in self.data["finished"]:
            self.data["finished"][bid] = time.strftime("%Y-%m-%d")
            self.save()
