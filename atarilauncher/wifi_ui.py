"""The WiFi screen's brain (a QObject the QML talks to). The nmcli work is in wifi.py and runs on a worker thread, so the
screen never freezes while a scan or a connection attempt is going on."""
from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import wifi


class WifiController(QObject):
    changed = Signal()                       # networks / state / message changed: the screen redraws
    summaryChanged = Signal()
    _done = Signal(str, object)              # worker thread -> main thread (kind, payload)

    def __init__(self, parent=None, run=None, which=None):
        super().__init__(parent)
        self._run = run or wifi.run_nmcli
        self._which = which
        self._state = "idle"                 # idle | scanning | connecting | ready | unavailable
        self._adapter = wifi.Adapter("ok")
        self._networks: list[dict] = []
        self._status = wifi.Status()
        self._message = ""
        self._ok = True
        self._summary = ""
        self._busy = False
        self._done.connect(self._on_done)

    # ---- what the screen reads
    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property("QVariantList", notify=changed)
    def networks(self):
        return self._networks

    @Property(str, notify=changed)
    def message(self):
        return self._message

    @Property(bool, notify=changed)
    def messageOk(self):
        return self._ok

    @Property(str, notify=changed)
    def statusText(self):
        return self._status.text

    @Property(str, notify=changed)
    def adapterState(self):
        return self._adapter.state

    @Property(str, notify=summaryChanged)
    def summary(self):
        return self._summary

    # ---- worker plumbing
    def _spawn(self, name: str, fn) -> None:
        def work():
            try:
                res = fn()
            except Exception as exc:  # pragma: no cover - safety net, nmcli problems already come back as text
                res = ("error", str(exc))
            self._done.emit(name, res)
        threading.Thread(target=work, daemon=True, name="code-wifi-" + name).start()

    def _kw(self) -> dict:
        return {"which": self._which} if self._which else {}

    def _scan_job(self, rescan: bool = True):
        ad = wifi.adapter(self._run, **self._kw())
        if not ad.usable:
            return ("scan", ad, [], wifi.status(self._run) if ad.state in ("radio_off", "noadapter") else wifi.Status(), "")
        nets, err = wifi.scan(self._run, rescan)
        return ("scan", ad, nets, wifi.status(self._run), err)

    @Slot()
    def refresh(self) -> None:
        """Look for networks (also the first thing the screen does when it opens)."""
        if self._busy:
            return
        self._busy = True
        self._state = "scanning"
        self._message = ""
        self.changed.emit()
        self._spawn("scan", self._scan_job)

    @Slot()
    def updateSummary(self) -> None:
        """Quietly refresh the one-line status shown on the home screen."""
        self._spawn("summary", lambda: ("summary", wifi.summary(self._run, **self._kw())))

    @Slot(str, str, bool)
    def connect(self, ssid: str, password: str, hidden: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        self._state = "connecting"
        self._message = "Connecting to " + ssid + "..."
        self._ok = True
        self.changed.emit()

        def job():
            ok, text = wifi.connect(ssid, password, hidden, self._run)
            res = self._scan_job(rescan=False)
            return ("action", ok, text, res)
        self._spawn("connect", job)

    @Slot(str)
    def forget(self, ssid: str) -> None:
        if self._busy:
            return

        self._busy = True
        self._state = "scanning"
        self.changed.emit()

        def job():
            ok, text = wifi.forget(ssid, self._run)
            return ("action", ok, text, self._scan_job(rescan=False))
        self._spawn("forget", job)

    @Slot()
    def turnOn(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._state = "scanning"
        self.changed.emit()

        def job():
            ok, text = wifi.radio_on(self._run)
            return ("action", ok, text, self._scan_job(rescan=True))
        self._spawn("radio", job)

    @Slot(str, object)
    def _on_done(self, kind: str, res) -> None:
        if kind == "summary":
            if res[1] != self._summary:
                self._summary = res[1]
                self.summaryChanged.emit()
            return
        self._busy = False
        if kind == "error" or res[0] == "error":
            self._state, self._ok, self._message = "ready", False, "That did not work: " + str(res[1])
            self.changed.emit()
            return
        if res[0] == "action":
            _, ok, text, scanned = res
            self._apply_scan(scanned)
            self._ok, self._message = ok, text
        else:
            self._apply_scan(res)
        self._summary_from_state()
        self.changed.emit()

    def _apply_scan(self, scanned) -> None:
        _, ad, nets, st, err = scanned
        self._adapter, self._status = ad, st
        self._networks = [n.as_dict() for n in nets]
        if not ad.usable:
            self._state, self._ok, self._message = "unavailable", False, ad.text
        else:
            self._state = "ready"
            self._ok, self._message = (not err), err or ""

    def _summary_from_state(self) -> None:
        s = self._status.ssid or ("Cable" if self._status.wired else
                                  ("No WiFi" if self._adapter.state in ("noadapter", "nonmcli", "nm_off") else
                                   "WiFi off" if self._adapter.state == "radio_off" else "Offline"))
        if s != self._summary:
            self._summary = s
            self.summaryChanged.emit()
