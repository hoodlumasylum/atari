"""The top bar's music control (a QObject the QML reads). playerctl runs on a worker thread so the home screen never stalls."""
from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import media


class MediaController(QObject):
    changed = Signal()
    _done = Signal(object)

    def __init__(self, parent=None, now=None, send=None):
        super().__init__(parent)
        self._now = now or media.now_playing
        self._send = send or media.send
        self._track: media.Track | None = None
        self._busy = False
        self._done.connect(self._on_done)

    @Property(bool, notify=changed)
    def active(self):
        return self._track is not None

    @Property(bool, notify=changed)
    def playing(self):
        return self._track is not None and self._track.playing

    @Property(str, notify=changed)
    def text(self):
        return self._track.text if self._track else ""

    @Property(str, notify=changed)
    def player(self):
        return self._track.player if self._track else ""

    def _on_done(self, track) -> None:
        self._busy = False
        if track != self._track:
            self._track = track
            self.changed.emit()

    def _work(self, action: str = "") -> None:
        def go():
            try:
                if action:
                    self._send(action)
                t = self._now()
            except Exception:
                t = None
            self._done.emit(t)
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=go, name="atari-media", daemon=True).start()

    @Slot()
    def refresh(self) -> None:
        self._work()

    @Slot(str)
    def press(self, action: str) -> None:
        """play-pause | next | previous, then re-read what is playing."""
        self._work(action)
