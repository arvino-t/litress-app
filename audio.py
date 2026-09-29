"""Аудиокниги: проигрыватель на GStreamer и экран плеера.

Книга — это один файл (M4B) или папка с MP3, каждый файл которой считается главой.
Скорость меняется без искажения голоса (фильтр scaletempo).
"""
from __future__ import annotations

import re
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gio, Gst, Gtk, Pango  # noqa: E402

AUDIO_FORMATS = {"m4b", "mp3dir"}
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


class AudioPlayer(GObject.Object):
    """Проигрывает список файлов подряд, помнит скорость, умеет перематывать."""

    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "track-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        Gst.init(None)
        self.pipe = Gst.ElementFactory.make("playbin", "audiobook")
        self.pipe.set_property("video-sink", Gst.ElementFactory.make("fakesink", None))
        tempo = Gst.ElementFactory.make("scaletempo", None)
        if tempo:
            self.pipe.set_property("audio-filter", tempo)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        bus.connect("message::async-done", self._on_async_done)

        self.book_id: str | None = None
        self.tracks: list[Path] = []
        self.index = 0
        self.rate = 1.0
        self.playing = False
        self._pending_seek: float | None = None

    # --- загрузка

    def load(self, book_id, tracks, index=0, position=0.0, play=True):
        self.book_id = book_id
        self.tracks = tracks
        self.playing = play
        self._set_track(min(max(index, 0), len(tracks) - 1), position)

    def unload(self):
        self.pipe.set_state(Gst.State.NULL)
        self.book_id = None
        self.tracks = []
        self.playing = False
        self.emit("state-changed")

    def _set_track(self, index, position=0.0):
        self.index = index
        self.pipe.set_state(Gst.State.NULL)
        self.pipe.set_property("uri", Gio.File.new_for_path(str(self.tracks[index])).get_uri())
        # Перемотать можно только после подготовки файла — делаем это в async-done
        self._pending_seek = position
        self.pipe.set_state(Gst.State.PAUSED)
        self.emit("track-changed")

    def _on_async_done(self, _bus, _msg):
        if self._pending_seek is None:
            return
        pos, self._pending_seek = self._pending_seek, None
        self._seek_raw(pos)
        if self.playing:
            self.pipe.set_state(Gst.State.PLAYING)
        self.emit("state-changed")

    def _seek_raw(self, seconds):
        self.pipe.seek(self.rate, Gst.Format.TIME,
                       Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                       Gst.SeekType.SET, int(max(0, seconds) * Gst.SECOND),
                       Gst.SeekType.NONE, -1)

    # --- управление

    def play(self):
        if not self.tracks:
            return
        self.playing = True
        self.pipe.set_state(Gst.State.PLAYING)
        self.emit("state-changed")

    def pause(self):
        self.playing = False
        self.pipe.set_state(Gst.State.PAUSED)
        self.emit("state-changed")

    def toggle(self):
        self.pause() if self.playing else self.play()

    def position(self) -> float:
        if self._pending_seek is not None:
            return self._pending_seek
        ok, pos = self.pipe.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else 0.0

    def duration(self) -> float:
        ok, dur = self.pipe.query_duration(Gst.Format.TIME)
        return dur / Gst.SECOND if ok and dur > 0 else 0.0

    def seek(self, seconds):
        dur = self.duration()
        if dur and seconds >= dur:
            self.next_track()
            return
        if seconds < 0 and self.index > 0 and self.position() < 3:
            self.prev_track()
            return
        self._seek_raw(max(0.0, seconds))

    def skip(self, delta):
        self.seek(self.position() + delta)

    def next_track(self):
        if self.index + 1 < len(self.tracks):
            self._set_track(self.index + 1)

    def prev_track(self):
        # Как в плеерах: в начале главы — на предыдущую, иначе — в начало текущей
        if self.position() > 3 or self.index == 0:
            self._seek_raw(0)
        else:
            self._set_track(self.index - 1)

    def go_to_track(self, index):
        self._set_track(index)

    def set_rate(self, rate):
        self.rate = rate
        if self.tracks and self._pending_seek is None:
            self._seek_raw(self.position())

    def fraction(self) -> float:
        """Доля прослушанного во всей книге (для MP3-папки — по числу файлов)."""
        if not self.tracks:
            return 0.0
        dur = self.duration()
        inside = self.position() / dur if dur else 0.0
        return min(1.0, (self.index + inside) / len(self.tracks))

    # --- события

    def _on_eos(self, *_):
        if self.index + 1 < len(self.tracks):
            self._set_track(self.index + 1)
        else:
            self.playing = False
            self.pipe.set_state(Gst.State.PAUSED)
            self.emit("state-changed")
            self.emit("finished")

    def _on_error(self, _bus, msg):
        err, _dbg = msg.parse_error()
        self.playing = False
        self.pipe.set_state(Gst.State.NULL)
        self.emit("state-changed")
        self.emit("error", err.message)


class PlayerPage(Adw.NavigationPage):
    """Экран плеера. Звук не прерывается, если уйти с экрана."""

    def __init__(self, app, book):
        super().__init__(title=book.get("title") or "Аудиокнига", tag="player")
        self.app = app
        self.book = book
        self.player: AudioPlayer = app.player
        self._sleep_timer = 0

        header = Adw.HeaderBar()
        self.tracks_btn = Gtk.MenuButton(icon_name="view-list-symbolic", tooltip_text="Главы")
        self.track_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.track_list.add_css_class("navigation-sidebar")
        self.track_list.connect("row-activated", self._on_track_row)
        self.tracks_popover = Gtk.Popover(child=Gtk.ScrolledWindow(
            child=self.track_list, propagate_natural_height=True, max_content_height=480,
            min_content_width=300, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.tracks_btn.set_popover(self.tracks_popover)
        header.pack_end(self.tracks_btn)

        self.sleep_btn = Gtk.MenuButton(icon_name="litreader-alarm-symbolic", tooltip_text="Таймер сна")
        sleep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sleep_popover = Gtk.Popover(child=sleep_box)
        for minutes in SLEEP_MINUTES:
            b = Gtk.Button(label=f"Через {minutes} мин" if minutes else "Выключить таймер")
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, m=minutes: self._set_sleep(m))
            sleep_box.append(b)
        self.sleep_btn.set_popover(self.sleep_popover)
        header.pack_end(self.sleep_btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(24)

        cover = app.library.cover_path(book)
        if cover:
            pic = Gtk.Picture.new_for_filename(str(cover))
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_size_request(-1, 300)
            pic.add_css_class("book-cover")
        else:
            pic = Gtk.Image(icon_name="litreader-audio-headphones-symbolic", pixel_size=160)
            pic.add_css_class("dim-label")
        box.append(pic)

        title = Gtk.Label(label=book.get("title") or "", wrap=True, justify=Gtk.Justification.CENTER)
        title.add_css_class("title-2")
        box.append(title)
        author = Gtk.Label(label=", ".join(book.get("authors") or []), wrap=True,
                           justify=Gtk.Justification.CENTER)
        author.add_css_class("dim-label")
        box.append(author)
        self.track_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.track_label.add_css_class("caption")
        box.append(self.track_label)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self._on_seek)
        box.append(self.scale)
        times = Gtk.CenterBox()
        self.pos_label = Gtk.Label()
        self.pos_label.add_css_class("numeric")
        self.left_label = Gtk.Label()
        self.left_label.add_css_class("numeric")
        self.total_label = Gtk.Label()
        self.total_label.add_css_class("dim-label")
        self.total_label.add_css_class("caption")
        times.set_start_widget(self.pos_label)
        times.set_center_widget(self.total_label)
        times.set_end_widget(self.left_label)
        box.append(times)

        controls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)

        def ctl(icon, tip, cb, big=False):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
            b.add_css_class("circular")
            if big:
                b.add_css_class("suggested-action")
                b.add_css_class("player-play")
            else:
                b.add_css_class("flat")
            b.connect("clicked", lambda *_: cb())
            controls.append(b)
            return b

        ctl("litreader-media-skip-backward-symbolic", "Предыдущая глава", self.player.prev_track)
        ctl("litreader-media-seek-backward-symbolic", "Назад на 15 секунд", lambda: self.player.skip(-15))
        self.play_btn = ctl("media-playback-start-symbolic", "Слушать / пауза (пробел)",
                            self.player.toggle, big=True)
        ctl("litreader-media-seek-forward-symbolic", "Вперёд на 30 секунд", lambda: self.player.skip(30))
        ctl("litreader-media-skip-forward-symbolic", "Следующая глава", self.player.next_track)
        box.append(controls)

        speed = Gtk.DropDown.new_from_strings([f"{s:g}×" for s in SPEEDS])
        speed.set_halign(Gtk.Align.CENTER)
        speed.set_tooltip_text("Скорость")
        rate = app.settings.get("audioRate", 1.0)
        speed.set_selected(SPEEDS.index(rate) if rate in SPEEDS else SPEEDS.index(1.0))
        speed.connect("notify::selected", self._on_speed)
        box.append(speed)

        clamp = Adw.Clamp(child=box, maximum_size=520)
        scroller = Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar = Adw.ToolbarView(content=scroller)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self._handlers = [
            self.player.connect("state-changed", lambda *_: self._sync_buttons()),
            self.player.connect("track-changed", lambda *_: self._on_track_changed()),
        ]
        self._fill_tracks()
        self._on_track_changed()
        self._sync_buttons()
        self._tick = GLib.timeout_add(500, self._update_position)

    # --- обновление экрана

    def _fill_tracks(self):
        tracks = self.player.tracks
        self.tracks_btn.set_visible(len(tracks) > 1)
        while (row := self.track_list.get_first_child()):
            self.track_list.remove(row)
        for i, t in enumerate(tracks):
            label = Gtk.Label(label=f"{i + 1}. {t.stem}", xalign=0, ellipsize=Pango.EllipsizeMode.END)
            for m in ("top", "bottom", "start", "end"):
                getattr(label, f"set_margin_{m}")(8)
            self.track_list.append(label)

    def _on_track_changed(self):
        n = len(self.player.tracks)
        if n > 1:
            self.track_label.set_label(f"Глава {self.player.index + 1} из {n}: "
                                       f"{self.player.tracks[self.player.index].stem}")
        self.track_label.set_visible(n > 1)

    def _sync_buttons(self):
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if self.player.playing
                                    else "media-playback-start-symbolic")

    def _update_position(self):
        pos, dur = self.player.position(), self.player.duration()
        if dur:
            self.scale.set_range(0, dur)
            self.scale.set_value(pos)
        self.pos_label.set_label(fmt_time(pos))
        self.left_label.set_label(f"−{fmt_time(dur - pos)}" if dur else "")
        self.total_label.set_label(f"{round(self.player.fraction() * 100)}% книги")
        return True

    # --- действия

    def _on_seek(self, _scale, _scroll, value):
        self.player.seek(value)
        return False

    def _on_speed(self, drop, _pspec):
        rate = SPEEDS[drop.get_selected()]
        self.app.settings["audioRate"] = rate
        self.app.save_settings()
        self.player.set_rate(rate)

    def _on_track_row(self, _list, row):
        self.player.go_to_track(row.get_index())
        self.player.play()
        self.tracks_popover.popdown()

    def _set_sleep(self, minutes):
        self.sleep_popover.popdown()
        if self._sleep_timer:
            GLib.source_remove(self._sleep_timer)
            self._sleep_timer = 0
        self.sleep_btn.remove_css_class("accent")
        if not minutes:
            self.app.toast("Таймер сна выключен")
            return

        def fire():
            self._sleep_timer = 0
            self.sleep_btn.remove_css_class("accent")
            self.player.pause()
            self.app.save_audio_progress()
            self.app.toast("Таймер сна: воспроизведение остановлено")
            return False
        self._sleep_timer = GLib.timeout_add_seconds(minutes * 60, fire)
        self.sleep_btn.add_css_class("accent")
        self.app.toast(f"Остановлю через {minutes} мин")

    def _on_key(self, _ctl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval == Gdk.KEY_space:
            self.player.toggle()
        elif keyval == Gdk.KEY_Left:
            self.player.skip(-15)
        elif keyval == Gdk.KEY_Right:
            self.player.skip(30)
        else:
            return False
        return True

    def destroy_page(self):
        """Вызывается, когда плеер переключают на другую книгу."""
        GLib.source_remove(self._tick)
        if self._sleep_timer:
            GLib.source_remove(self._sleep_timer)
        for h in self._handlers:
            self.player.disconnect(h)
