"""Настройки приложения (settings.json): словарь с автосохранением и сигналом об изменениях.

Модули читают и меняют настройки как обычный словарь (`settings["fontSize"] = 20`), а за запись на диск
отвечает этот класс: изменения сохраняются через полсекунды пачкой, сигнал changed(ключ) говорит,
что поменялось. Так модули не зависят от того, где и когда хранятся настройки.
"""
from __future__ import annotations

from collections.abc import Iterator, MutableMapping

from PySide6.QtCore import QObject, QTimer, Signal

from .core import CONFIG_FILE, DEFAULT_SETTINGS, load_json, save_json


class _Signals(QObject):
    changed = Signal(str)


class Settings(MutableMapping):
    """Словарь настроек. Сигнал и таймер — во вложенном QObject: у QObject и MutableMapping разные
    метаклассы, наследоваться сразу от обоих нельзя."""

    def __init__(self, path=CONFIG_FILE, defaults: dict | None = None, parent=None):
        self.path = path
        self._data: dict = {**(DEFAULT_SETTINGS if defaults is None else defaults), **load_json(path, {})}
        self._qt = _Signals(parent)
        self.changed = self._qt.changed
        self._timer = QTimer(self._qt, singleShot=True, interval=500)
        self._timer.timeout.connect(self.save_now)

    # --- словарь

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self.changed.emit(key)
        self.schedule_save()

    def __delitem__(self, key):
        del self._data[key]
        self.changed.emit(key)
        self.schedule_save()

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def as_dict(self) -> dict:
        """Копия для сохранения в JSON (например, в резервную копию)."""
        return dict(self._data)

    # --- запись на диск

    def schedule_save(self):
        self._timer.start()

    def save_now(self):
        self._timer.stop()
        save_json(self.path, self._data)
