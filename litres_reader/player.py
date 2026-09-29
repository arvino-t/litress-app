"""Аудиокниги: проигрыватель на QtMultimedia и экран плеера.

Книга — это один файл (M4B) или папка с MP3, каждый файл которой считается главой.
Скорость меняется без искажения голоса (pitchCompensation, Qt 6.10+).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea,
                               QVBoxLayout, QWidget)

from . import style
from .widgets import HeaderBar, IconButton, Popover, SeekSlider, attach_popover, cls, label

SPEEDS = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
SLEEP_MINUTES = (0, -1, 15, 30, 45, 60)   # -1 — в конце текущей главы


def natural_key(name: str):
    """«Глава 2» раньше «Глава 10»."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def audio_tracks(path: Path) -> list[Path]:
    """Файлы аудиокниги по порядку: сам M4B или MP3 из папки."""
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.suffix.lower() in (".mp3", ".m4a", ".m4b", ".ogg")]
        return sorted(files, key=lambda p: natural_key(str(p.relative_to(path))))
    return [path]


def _mp4_atoms(f, start, end):
    """Атомы MP4 в диапазоне [start, end): (тип, начало данных, конец атома)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind.decode("latin1"), pos + header, pos + size
        pos += size


def _find(f, start, end, *path):
    """Первый атом по пути, например ("moov", "udta", "chpl")."""
    for kind, body, stop in _mp4_atoms(f, start, end):
        if kind == path[0]:
            return (body, stop) if len(path) == 1 else _find(f, body, stop, *path[1:])
    return None


def _nero_chapters(f, body, stop):
    """Атом chpl (формат Nero): время в единицах 100 нс и название в UTF-8."""
    f.seek(body)
    version = f.read(4)[0]
    if version == 1:
        f.read(4)   # зарезервировано
    count = f.read(1)[0]
    chapters = []
    for _ in range(count):
        if f.tell() + 9 > stop:
            break
        start = struct.unpack(">Q", f.read(8))[0] / 10_000_000
        title = f.read(f.read(1)[0]).decode("utf-8", "replace")
        chapters.append((start, title))
    return chapters


def _quicktime_chapters(f, moov_body, moov_end):
    """Текстовая дорожка глав QuickTime (на неё ссылается tref/chap звуковой дорожки)."""
    for kind, body, stop in _mp4_atoms(f, moov_body, moov_end):
        if kind != "trak":
            continue
        hdlr = _find(f, body, stop, "mdia", "hdlr")
        if not hdlr:
            continue
        f.seek(hdlr[0] + 8)
        if f.read(4) != b"text":
            continue
        mdhd = _find(f, body, stop, "mdia", "mdhd")
        f.seek(mdhd[0])
        version = f.read(1)[0]
        f.seek(mdhd[0] + (20 if version == 1 else 12))
        timescale = struct.unpack(">I", f.read(4))[0] or 1000
        stbl = _find(f, body, stop, "mdia", "minf", "stbl")
        if not stbl:
            continue
        stts = _find(f, *stbl, "stts")
        stco = _find(f, *stbl, "stco") or _find(f, *stbl, "co64")
        if not stts or not stco:
            continue
        f.seek(stts[0] + 4)
        durations = []
        for _ in range(struct.unpack(">I", f.read(4))[0]):
            n, d = struct.unpack(">II", f.read(8))
            durations += [d] * n
        wide = _find(f, *stbl, "co64") is not None and _find(f, *stbl, "stco") is None
        f.seek(stco[0] + 4)
        n = struct.unpack(">I", f.read(4))[0]
        offsets = [struct.unpack(">Q" if wide else ">I", f.read(8 if wide else 4))[0] for _ in range(n)]
        chapters, t = [], 0
        for i, off in enumerate(offsets):
            f.seek(off)
            length = struct.unpack(">H", f.read(2))[0]
            title = f.read(length).decode("utf-8", "replace")
            chapters.append((t / timescale, title))
            t += durations[i] if i < len(durations) else 0
        return chapters
    return []


def mp4_chapters(path: Path) -> list[tuple[float, str]]:
    """Главы из файла M4B/M4A: [(начало в секундах, название)], пусто — если разметки нет."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            moov = _find(f, 0, f.tell(), "moov")
            if not moov:
                return []
            chpl = _find(f, *moov, "udta", "chpl")
            chapters = _nero_chapters(f, *chpl) if chpl else []
            if not chapters:
                chapters = _quicktime_chapters(f, *moov)
            return sorted(chapters)
    except (OSError, struct.error, IndexError, TypeError):
        return []


def build_chapters(tracks: list[Path]) -> list[dict]:
    """Главы книги: разметка внутри M4B или по одному файлу на главу для папки MP3."""
    chapters = []
    for i, t in enumerate(tracks):
        inner = mp4_chapters(t) if t.suffix.lower() in (".m4b", ".m4a", ".mp4") else []
        if len(inner) > 1:
            for j, (start, title) in enumerate(inner):
                end = inner[j + 1][0] if j + 1 < len(inner) else None
                chapters.append({"track": i, "start": start, "end": end, "title": title or f"Глава {j + 1}"})
        else:
            chapters.append({"track": i, "start": 0.0, "end": None, "title": t.stem})
    return chapters


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


class AudioPlayer(QObject):
    """Проигрывает список файлов подряд, помнит скорость, умеет перематывать."""

    state_changed = Signal()
    track_changed = Signal()
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.media = QMediaPlayer(self)
        self.media.setAudioOutput(self.output)
        if hasattr(self.media, "setPitchCompensation"):
            self.media.setPitchCompensation(True)
        self.media.mediaStatusChanged.connect(self._on_status)
        self.media.errorOccurred.connect(self._on_error)

        self.book_id: str | None = None
        self.tracks: list[Path] = []
        self.chapters: list[dict] = []
        self.index = 0
        self.rate = 1.0
        self.playing = False
        self._pending_seek: float | None = None
        self._loading_seen = False

    # --- загрузка

    def load(self, book_id, tracks, index=0, position=0.0, play=True):
        self.book_id = book_id
        self.tracks = tracks
        self.chapters = build_chapters(tracks)
        self.playing = play
        self._set_track(min(max(index, 0), len(tracks) - 1), position)

    def unload(self):
        self.media.stop()
        self.media.setSource(QUrl())
        self.book_id = None
        self.tracks = []
        self.chapters = []
        self.playing = False
        self.state_changed.emit()

    def _set_track(self, index, position=0.0):
        self.index = index
        # Перемотать можно только после загрузки файла — делаем это в _on_status
        self._pending_seek = position
        # После смены файла сначала приходят запоздалые состояния старого —
        # готовым считаем новый файл только после его собственного LoadingMedia
        self._loading_seen = False
        self.media.setSource(QUrl.fromLocalFile(str(self.tracks[index])))
        self.media.setPlaybackRate(self.rate)
        self.track_changed.emit()

    def _on_status(self, status):
        S = QMediaPlayer.MediaStatus
        if status == S.LoadingMedia:
            self._loading_seen = True
        elif status in (S.LoadedMedia, S.BufferedMedia) and self._pending_seek is not None \
                and self._loading_seen:
            pos, self._pending_seek = self._pending_seek, None
            self.media.setPosition(int(pos * 1000))
            if self.playing:
                self.media.play()
            self.state_changed.emit()
        elif status == S.EndOfMedia:
            if self.index + 1 < len(self.tracks):
                self._set_track(self.index + 1)
            else:
                self.playing = False
                self.state_changed.emit()
                self.finished.emit()

    def _on_error(self, _err, message):
        self.playing = False
        self.state_changed.emit()
        self.error.emit(message)

    # --- управление

    def play(self):
        if not self.tracks:
            return
        self.playing = True
        self.media.play()
        self.state_changed.emit()

    def pause(self):
        self.playing = False
        self.media.pause()
        self.state_changed.emit()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def position(self) -> float:
        if self._pending_seek is not None:
            return self._pending_seek
        return self.media.position() / 1000

    def duration(self) -> float:
        return self.media.duration() / 1000

    def seek(self, seconds):
        dur = self.duration()
        if dur and seconds >= dur:
            self.next_track()
            return
        if seconds < 0 and self.index > 0 and self.position() < 3:
            self.prev_track()
            return
        self.media.setPosition(int(max(0.0, seconds) * 1000))

    def skip(self, delta):
        self.seek(self.position() + delta)

    def next_track(self):
        if self.index + 1 < len(self.tracks):
            self._set_track(self.index + 1)

    def prev_track(self):
        # Как в плеерах: в начале главы — на предыдущую, иначе — в начало текущей
        if self.position() > 3 or self.index == 0:
            self.media.setPosition(0)
        else:
            self._set_track(self.index - 1)

    def go_to_track(self, index):
        self._set_track(index)

    # --- главы: разметка внутри M4B или файлы MP3

    def current_chapter(self) -> int:
        pos = self.position()
        current = 0
        for i, ch in enumerate(self.chapters):
            if ch["track"] < self.index or (ch["track"] == self.index and ch["start"] <= pos + 0.25):
                current = i
        return current

    def chapter_bounds(self, i) -> tuple[float, float]:
        """Начало и конец главы в секундах внутри её файла (конец 0 — пока неизвестен)."""
        ch = self.chapters[i]
        end = ch["end"]
        if end is None:
            end = self.duration() if ch["track"] == self.index else 0.0
        return ch["start"], end

    def go_to_chapter(self, i):
        if not 0 <= i < len(self.chapters):
            return
        ch = self.chapters[i]
        if ch["track"] == self.index and self._pending_seek is None:
            self.media.setPosition(int(ch["start"] * 1000))
        else:
            self._set_track(ch["track"], ch["start"])
        self.track_changed.emit()

    def next_chapter(self):
        self.go_to_chapter(self.current_chapter() + 1)

    def prev_chapter(self):
        # Как в плеерах: в начале главы — на предыдущую, иначе — в начало текущей
        i = self.current_chapter()
        start, _ = self.chapter_bounds(i)
        self.go_to_chapter(i if self.position() - start > 3 or i == 0 else i - 1)

    def go_to_fraction(self, fraction):
        """Перейти к доле всей книги (например, к месту, прослушанному на ЛитРес)."""
        if not self.tracks:
            return
        fraction = max(0.0, min(fraction, 0.999))
        if len(self.tracks) == 1:
            if self.duration():
                self.seek(self.duration() * fraction)
            return
        exact = fraction * len(self.tracks)
        index = int(exact)
        if index == self.index and self.duration():
            self.seek(self.duration() * (exact - index))
        else:
            self._set_track(index, 0.0)

    def set_rate(self, rate):
        self.rate = rate
        self.media.setPlaybackRate(rate)

    def fraction(self) -> float:
        """Доля прослушанного во всей книге (для MP3-папки — по числу файлов)."""
        if not self.tracks:
            return 0.0
        dur = self.duration()
        inside = self.position() / dur if dur else 0.0
        return min(1.0, (self.index + inside) / len(self.tracks))


class PlayerPage(QWidget):
    """Экран плеера. Звук не прерывается, если уйти с экрана."""

    def __init__(self, app, book):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        self.book = book
        self.player: AudioPlayer = app.player
        self._sleep_timer = QTimer(self, singleShot=True)
        self._sleep_timer.timeout.connect(self._sleep_fire)
        self._sleep_at_chapter: int | None = None   # остановиться, когда закончится эта глава
        self._shown_chapter = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = HeaderBar(app.window, book.get("title") or "Аудиокнига")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)
        self.tracks_btn = IconButton("view-list", "Главы")
        self.track_list = QListWidget()
        self.track_list.setMinimumSize(420, 400)
        self.track_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.track_list.setWordWrap(True)
        self.track_list.itemClicked.connect(self._on_track_row)
        self.tracks_popover = Popover(self.track_list)
        attach_popover(self.tracks_btn, self.tracks_popover)
        self.header.pack_end(self.tracks_btn)
        self.sleep_btn = IconButton("alarm", "Таймер сна")
        sleep_box = QWidget()
        sl = QVBoxLayout(sleep_box)
        sl.setContentsMargins(0, 0, 0, 0)
        for minutes in SLEEP_MINUTES:
            b = QPushButton("Выключить таймер" if minutes == 0 else "В конце главы" if minutes < 0
                            else f"Через {minutes} мин")
            cls(b, "flat")
            b.setStyleSheet("text-align: left; font-weight: normal;")
            b.clicked.connect(lambda _c=False, m=minutes: self._set_sleep(m))
            sl.addWidget(b)
        self.sleep_popover = Popover(sleep_box)
        attach_popover(self.sleep_btn, self.sleep_popover)
        self.header.pack_end(self.sleep_btn)
        outer.addWidget(self.header)

        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(12)
        box.addStretch()

        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_path = app.library.cover_path(book)
        if cover_path:
            pix = QPixmap(str(cover_path))
            dpr = self.devicePixelRatioF()
            pix = pix.scaledToHeight(int(300 * dpr), Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            self.cover.setPixmap(pix)
        else:
            self._cover_icon = True
            self.cover.setPixmap(style.icon("audio-headphones", "#9a9a9e", 160).pixmap(160, 160))
        box.addWidget(self.cover)

        box.addWidget(label(book.get("title") or "", "title2", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
        box.addWidget(label(", ".join(book.get("authors") or []), "dim", wrap=True,
                            align=Qt.AlignmentFlag.AlignCenter))
        self.track_label = label("", "caption", align=Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.track_label)

        self.slider = SeekSlider()
        # Ползунок и время — внутри текущей главы; при перетаскивании время меняется сразу
        self.slider.sliderReleased.connect(self._on_seek)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        box.addWidget(self.slider)
        times = QHBoxLayout()
        self.pos_label = label("0:00")
        self.total_label = label("", "dim", "caption", align=Qt.AlignmentFlag.AlignCenter)
        self.left_label = label("", align=Qt.AlignmentFlag.AlignRight)
        times.addWidget(self.pos_label, 1)
        times.addWidget(self.total_label, 1)
        times.addWidget(self.left_label, 1)
        box.addLayout(times)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addStretch()

        def ctl(icon, tip, cb):
            b = IconButton(icon, tip, circular=True)
            b.clicked.connect(cb)
            controls.addWidget(b)
            return b

        ctl("media-skip-backward", "Предыдущая глава", self.player.prev_chapter)
        ctl("media-seek-backward", "Назад на 15 секунд", lambda: self.player.skip(-15))
        self.play_btn = IconButton("media-playback-start", "Слушать / пауза (пробел)", flat=False, size=28)
        cls(self.play_btn, "play")
        self.play_btn.set_icon_name("media-playback-start", "#ffffff")
        self.play_btn.clicked.connect(self.player.toggle)
        controls.addWidget(self.play_btn)
        ctl("media-seek-forward", "Вперёд на 30 секунд", lambda: self.player.skip(30))
        ctl("media-skip-forward", "Следующая глава", self.player.next_chapter)
        controls.addStretch()
        box.addLayout(controls)

        self.speed = QComboBox()
        self.speed.setToolTip("Скорость")
        self.speed.addItems([f"{s:g}×" for s in SPEEDS])
        rate = app.settings.get("audioRate", 1.0)
        self.speed.setCurrentIndex(SPEEDS.index(rate) if rate in SPEEDS else SPEEDS.index(1.0))
        self.speed.currentIndexChanged.connect(self._on_speed)
        sp = QHBoxLayout()
        sp.addStretch()
        sp.addWidget(self.speed)
        sp.addStretch()
        box.addLayout(sp)
        box.addStretch()

        # Колонка по центру не шире 520 px (как Adw.Clamp)
        clamp = QWidget()
        cl = QHBoxLayout(clamp)
        cl.addStretch()
        body.setMaximumWidth(520)
        cl.addWidget(body, 10)
        cl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(clamp)
        outer.addWidget(scroll, 1)

        self.player.state_changed.connect(self._sync_buttons)
        self.player.track_changed.connect(self._on_track_changed)
        self._fill_tracks()
        self._on_track_changed()
        self._sync_buttons()
        self._tick = QTimer(self, interval=500)
        self._tick.timeout.connect(self._update_position)
        self._tick.start()

    # --- обновление экрана

    def _fill_tracks(self):
        chapters = self.player.chapters
        self.tracks_btn.setVisible(len(chapters) > 1)
        self.track_list.clear()
        one_file = len(self.player.tracks) == 1
        for ch in chapters:
            # Строка как в GNOME: название с переносом, справа — время начала
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 4, 2)
            h.setSpacing(12)
            h.addWidget(label(ch["title"], wrap=True), 1)
            if one_file:
                h.addWidget(label(fmt_time(ch["start"]), "dim", "caption"), 0, Qt.AlignmentFlag.AlignVCenter)
            item = QListWidgetItem(self.track_list)
            width = self.track_list.minimumWidth() - 40
            row.setFixedWidth(width)
            # Высота — по реальной ширине строки, иначе однострочные главы выходят высокими
            item.setSizeHint(QSize(width, h.totalHeightForWidth(width) + 12))
            self.track_list.setItemWidget(item, row)

    def _on_track_changed(self):
        self._shown_chapter = -1
        self._update_position()

    def _show_chapter(self, i):
        """Подпись и отметка в списке для текущей главы."""
        self._shown_chapter = i
        chapters = self.player.chapters
        many = len(chapters) > 1
        if many:
            self.track_label.setText(chapters[i]["title"])
            self.track_list.setCurrentRow(i)
        self.track_label.setVisible(many)

    def _sync_buttons(self):
        self.play_btn.set_icon_name("media-playback-pause" if self.player.playing
                                    else "media-playback-start", "#ffffff")

    def _update_position(self):
        p = self.player
        if not p.chapters:
            return
        i = p.current_chapter()
        if i != self._shown_chapter:
            if self._sleep_at_chapter is not None and i != self._sleep_at_chapter:
                self._sleep_at_chapter = None
                self._sleep_fire()
            self._show_chapter(i)
        start, end = p.chapter_bounds(i)
        pos = p.position() - start
        length = end - start if end > start else 0
        if length and not self.slider.isSliderDown():
            self.slider.setRange(0, int(length))
            self.slider.setValue(int(pos))
        self.pos_label.setText(fmt_time(pos))
        self.left_label.setText(f"−{fmt_time(length - pos)}" if length else "")
        percent = f"{round(p.fraction() * 100)}% книги"
        self.total_label.setText(f"{i + 1} / {len(p.chapters)} · {percent}"
                                 if len(p.chapters) > 1 else percent)

    def _on_slider_moved(self, value):
        start, end = self.player.chapter_bounds(self.player.current_chapter())
        self.pos_label.setText(fmt_time(value))
        if end > start:
            self.left_label.setText(f"−{fmt_time(end - start - value)}")

    def _on_seek(self):
        start, _ = self.player.chapter_bounds(self.player.current_chapter())
        self.player.seek(start + self.slider.value())

    def refresh_style(self):
        self.header.refresh_icons()
        for b in self.findChildren(IconButton):
            b.refresh_icon()
        self._sync_buttons()

    # --- действия

    def _on_speed(self, i):
        rate = SPEEDS[i]
        self.app.settings["audioRate"] = rate
        self.app.save_settings()
        self.player.set_rate(rate)

    def _on_track_row(self, item):
        self.player.go_to_chapter(self.track_list.row(item))
        self.player.play()
        self.tracks_popover.hide()

    def _set_sleep(self, minutes):
        self.sleep_popover.hide()
        self._sleep_timer.stop()
        self._sleep_at_chapter = None
        self.sleep_btn.set_icon_name("alarm")
        if not minutes:
            self.app.toast("Таймер сна выключен")
            return
        if minutes < 0:
            self._sleep_at_chapter = self.player.current_chapter()
            self.sleep_btn.set_icon_name("alarm", style.ACCENT)
            self.app.toast("Остановлю в конце главы")
            return
        self._sleep_timer.start(minutes * 60 * 1000)
        self.sleep_btn.set_icon_name("alarm", style.ACCENT)
        self.app.toast(f"Остановлю через {minutes} мин")

    def _sleep_fire(self):
        self.sleep_btn.set_icon_name("alarm")
        self.player.pause()
        self.app.save_audio_progress()
        self.app.toast("Таймер сна: воспроизведение остановлено")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.player.toggle()
        elif e.key() == Qt.Key.Key_Left:
            self.player.skip(-15)
        elif e.key() == Qt.Key.Key_Right:
            self.player.skip(30)
        else:
            super().keyPressEvent(e)

    def close_page(self):
        """Вызывается, когда плеер переключают на другую книгу."""
        self._tick.stop()
        self._sleep_timer.stop()
        self.player.state_changed.disconnect(self._sync_buttons)
        self.player.track_changed.disconnect(self._on_track_changed)
