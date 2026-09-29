"""Аудиокниги: проигрыватель на QtMultimedia и экран плеера.

Книга — это один файл (M4B) или папка с MP3, каждый файл которой считается главой.
Скорость меняется без искажения голоса (pitchCompensation, Qt 6.10+).
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from . import style
from .widgets import HeaderBar, IconButton, Popover, attach_popover, cls, label

SPEEDS = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
SLEEP_MINUTES = (0, 15, 30, 45, 60)


def natural_key(name: str):
    """«Глава 2» раньше «Глава 10»."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def audio_tracks(path: Path) -> list[Path]:
    """Файлы аудиокниги по порядку: сам M4B или MP3 из папки."""
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.suffix.lower() in (".mp3", ".m4a", ".m4b", ".ogg")]
        return sorted(files, key=lambda p: natural_key(str(p.relative_to(path))))
    return [path]


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
        self.index = 0
        self.rate = 1.0
        self.playing = False
        self._pending_seek: float | None = None
        self._loading_seen = False

    # --- загрузка

    def load(self, book_id, tracks, index=0, position=0.0, play=True):
        self.book_id = book_id
        self.tracks = tracks
        self.playing = play
        self._set_track(min(max(index, 0), len(tracks) - 1), position)

    def unload(self):
        self.media.stop()
        self.media.setSource(QUrl())
        self.book_id = None
        self.tracks = []
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = HeaderBar(app.window, book.get("title") or "Аудиокнига")
        back = IconButton("go-previous", "Назад")
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)
        self.tracks_btn = IconButton("view-list", "Главы")
        self.track_list = QListWidget()
        self.track_list.setMinimumSize(300, 360)
        self.track_list.itemClicked.connect(self._on_track_row)
        self.tracks_popover = Popover(self.track_list)
        attach_popover(self.tracks_btn, self.tracks_popover)
        self.header.pack_end(self.tracks_btn)
        self.sleep_btn = IconButton("alarm", "Таймер сна")
        sleep_box = QWidget()
        sl = QVBoxLayout(sleep_box)
        sl.setContentsMargins(0, 0, 0, 0)
        for minutes in SLEEP_MINUTES:
            b = QPushButton(f"Через {minutes} мин" if minutes else "Выключить таймер")
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

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderReleased.connect(lambda: self.player.seek(self.slider.value()))
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

        ctl("media-skip-backward", "Предыдущая глава", self.player.prev_track)
        ctl("media-seek-backward", "Назад на 15 секунд", lambda: self.player.skip(-15))
        self.play_btn = IconButton("media-playback-start", "Слушать / пауза (пробел)", flat=False, size=28)
        cls(self.play_btn, "play")
        self.play_btn.set_icon_name("media-playback-start", "#ffffff")
        self.play_btn.clicked.connect(self.player.toggle)
        controls.addWidget(self.play_btn)
        ctl("media-seek-forward", "Вперёд на 30 секунд", lambda: self.player.skip(30))
        ctl("media-skip-forward", "Следующая глава", self.player.next_track)
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
        tracks = self.player.tracks
        self.tracks_btn.setVisible(len(tracks) > 1)
        self.track_list.clear()
        self.track_list.addItems([f"{i + 1}. {t.stem}" for i, t in enumerate(tracks)])

    def _on_track_changed(self):
        n = len(self.player.tracks)
        if n > 1:
            self.track_label.setText(f"Глава {self.player.index + 1} из {n}: "
                                     f"{self.player.tracks[self.player.index].stem}")
        self.track_label.setVisible(n > 1)

    def _sync_buttons(self):
        self.play_btn.set_icon_name("media-playback-pause" if self.player.playing
                                    else "media-playback-start", "#ffffff")

    def _update_position(self):
        pos, dur = self.player.position(), self.player.duration()
        if dur and not self.slider.isSliderDown():
            self.slider.setRange(0, int(dur))
            self.slider.setValue(int(pos))
        self.pos_label.setText(fmt_time(pos))
        self.left_label.setText(f"−{fmt_time(dur - pos)}" if dur else "")
        self.total_label.setText(f"{round(self.player.fraction() * 100)}% книги")

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
        self.player.go_to_track(self.track_list.row(item))
        self.player.play()
        self.tracks_popover.hide()

    def _set_sleep(self, minutes):
        self.sleep_popover.hide()
        self._sleep_timer.stop()
        self.sleep_btn.set_icon_name("alarm")
        if not minutes:
            self.app.toast("Таймер сна выключен")
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
