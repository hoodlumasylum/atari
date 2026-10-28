"""The bridge between Python (data, launching) and the QML user interface."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent

from . import launcher, paths, roms
from .config import Config, load_config, save_config
from .library import STEAM, LibraryResult, build_library, demo_library
from .model import GameModel, filter_games
from .store import Store

MIN_PLAYTIME_SEC = 5  # shorter sessions are not counted (accidental launches)

ACTION_KEYS = {
    "up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right,
    "accept": Qt.Key_Return, "back": Qt.Key_Escape, "search": Qt.Key_Slash,
    "favorite": Qt.Key_F, "menu": Qt.Key_F10, "prev": Qt.Key_PageUp, "next": Qt.Key_PageDown,
}


class Backend(QObject):
    filtersChanged = Signal()
    currentFilterChanged = Signal()
    queryChanged = Signal()
    statusChanged = Signal()
    runningChanged = Signal()
    toastChanged = Signal()
    firstRunChanged = Signal()
    fullscreenChanged = Signal()
    libraryChanged = Signal()
    sessionEnded = Signal(str, str, float, str)  # gid, title, seconds, error (from worker thread)
    gamepadNote = Signal(str)

    def __init__(self, cfg: Config | None = None, store: Store | None = None, demo: bool = False,
                 enable_gamepad: bool = True):
        super().__init__()
        self.cfg = cfg or load_config()
        if store is None and demo:
            store = self._demo_store()
        self.store = store or Store()
        self._demo = demo
        self.model = GameModel(self.store, self)
        self._lib = LibraryResult()
        self._all = []
        self._filter = "all"
        self._query = ""
        self._filters: list[dict] = []
        self._running = False
        self._running_title = ""
        self._toast = ""
        self._first_run = self.cfg.first_run and not demo
        self._gamepad_proc: QProcess | None = None
        self._window = None
        self._toast_timer = QTimer(self, singleShot=True, interval=5000)
        self._toast_timer.timeout.connect(lambda: self._set_toast(""))
        self.sessionEnded.connect(self._on_session_ended, Qt.QueuedConnection)
        if self._first_run:
            self._prefill_first_run()
        self.rescan(initial=True)
        if enable_gamepad:
            self._start_gamepad()

    @staticmethod
    def _demo_store() -> Store:
        """Throw-away store with pretend favorites/play time, so demo mode never touches real data."""
        import tempfile
        import time
        st = Store(Path(tempfile.mkdtemp(prefix="atari-demo-")) / "state.json")
        now = time.time()
        for i, (gid, mins) in enumerate([("steam:9000001", 340), ("rom:atari2600:/demo/Blocky Breakout", 95),
                                         ("rom:nes:/demo/Castle Quest", 410), ("steam:9000004", 1210),
                                         ("rom:snes:/demo/Cloud Racers", 55), ("steam:9000000", 20)]):
            st.games[gid] = {"last_played": now - i * 86400 * 0.7, "playtime_sec": mins * 60, "launches": 3,
                             "favorite": i % 2 == 0}
        return st

    # ----- plumbing --------------------------------------------------------
    def set_window(self, window) -> None:
        self._window = window

    def _prefill_first_run(self) -> None:
        for sc in self.cfg.systems.values():
            guess = roms.suggest_rom_dir(Path.home(), sc.id, sc.aliases)
            if guess and not sc.roms:
                sc.roms = [guess]

    def _start_gamepad(self) -> None:
        if os.environ.get("ATARI_NO_GAMEPAD"):
            return
        proc = QProcess(self)
        proc.setProgram(sys.executable)
        proc.setArguments(["-m", "atarilauncher.gamepad_helper"])
        from PySide6.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        pkg_parent = str(Path(__file__).resolve().parent.parent)
        env.insert("PYTHONPATH", pkg_parent + os.pathsep + env.value("PYTHONPATH", ""))
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._read_gamepad)
        proc.start()
        self._gamepad_proc = proc

    def stop_gamepad(self) -> None:
        if self._gamepad_proc is not None:
            self._gamepad_proc.readyReadStandardOutput.disconnect()
            self._gamepad_proc.terminate()
            if not self._gamepad_proc.waitForFinished(1500):
                self._gamepad_proc.kill()
            self._gamepad_proc = None

    def _read_gamepad(self) -> None:
        data = bytes(self._gamepad_proc.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#pad "):
                self.show_toast("Controller connected: " + line[5:])
            elif not line.startswith("#"):
                self.send_action(line)

    def send_action(self, action: str) -> None:
        """Turn a gamepad action into a key press for the UI (only while Atari has focus)."""
        key = ACTION_KEYS.get(action)
        win = self._window
        if key is None or win is None or self._running:
            return
        if QGuiApplication.applicationState() != Qt.ApplicationActive and not os.environ.get("ATARI_TEST_INPUT"):
            return
        for kind in (QKeyEvent.KeyPress, QKeyEvent.KeyRelease):
            QGuiApplication.postEvent(win, QKeyEvent(kind, key, Qt.NoModifier))

    # ----- properties ------------------------------------------------------
    @Property("QVariantList", notify=filtersChanged)
    def filters(self):
        return self._filters

    @Property(str, notify=currentFilterChanged)
    def currentFilter(self):
        return self._filter

    @Property(str, notify=queryChanged)
    def query(self):
        return self._query

    @Property(int, notify=libraryChanged)
    def totalGames(self):
        return len(self._all)

    @Property(str, notify=statusChanged)
    def steamStatus(self):
        return self._lib.steam_note

    @Property(bool, notify=runningChanged)
    def running(self):
        return self._running

    @Property(str, notify=runningChanged)
    def runningTitle(self):
        return self._running_title

    @Property(str, notify=toastChanged)
    def toast(self):
        return self._toast

    @Property(bool, notify=firstRunChanged)
    def firstRun(self):
        return self._first_run

    @Property(bool, notify=fullscreenChanged)
    def fullscreen(self):
        return self.cfg.fullscreen

    @Property(bool, constant=True)
    def demo(self):
        return self._demo

    @Property(QObject, constant=True)
    def games(self):
        return self.model

    @Property(str, constant=True)
    def configPath(self):
        return str(self.cfg.path or paths.config_file())

    def _set_toast(self, msg: str) -> None:
        self._toast = msg
        self.toastChanged.emit()

    def show_toast(self, msg: str, ms: int = 5000) -> None:
        self._set_toast(msg)
        self._toast_timer.start(ms)

    # ----- library ---------------------------------------------------------
    @Slot()
    def rescan(self, initial: bool = False) -> None:
        self._lib = demo_library() if self._demo else build_library(self.cfg)
        self._all = self._lib.games
        self._rebuild_filters()
        if initial:
            self._filter = "recent" if self.store.recent_ids() and any(
                g.gid in set(self.store.recent_ids()) for g in self._all) else "all"
        elif not any(f["key"] == self._filter for f in self._filters):
            self._filter = "all"
        self.currentFilterChanged.emit()
        self._apply()
        self.statusChanged.emit()
        self.libraryChanged.emit()
        if not initial:
            self.show_toast(f"Library updated: {len(self._all)} games")

    def _rebuild_filters(self) -> None:
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for g in self._all:
            counts[g.platform] = counts.get(g.platform, 0) + 1
            names[g.platform] = g.platform_name
        recent_ids = set(self.store.recent_ids())
        fl = [
            {"key": "recent", "label": "Recent", "count": sum(1 for g in self._all if g.gid in recent_ids)},
            {"key": "favorites", "label": "Favorites",
             "count": sum(1 for g in self._all if self.store.is_favorite(g.gid))},
            {"key": "all", "label": "All games", "count": len(self._all)},
        ]
        if STEAM in counts or (self.cfg.steam_enabled and self._lib.steam_scan.found):
            fl.append({"key": STEAM, "label": "Steam", "count": counts.get(STEAM, 0)})
        order = [sid for sid in self.cfg.systems if sid in counts]
        order += [sid for sid in counts if sid not in order and sid != STEAM]
        for sid in order:
            fl.append({"key": sid, "label": names[sid], "count": counts[sid]})
        self._filters = fl
        self.filtersChanged.emit()

    def _apply(self) -> None:
        self.model.set_visible(filter_games(self._all, self.store, self._filter, self._query))

    @Slot(str)
    def setFilter(self, key: str) -> None:
        if key != self._filter:
            self._filter = key
            self.currentFilterChanged.emit()
        self._apply()

    @Slot(str)
    def setQuery(self, q: str) -> None:
        if q != self._query:
            self._query = q
            self.queryChanged.emit()
            self._apply()

    @Slot(result=str)
    def emptyMessage(self) -> str:
        """Friendly text for an empty grid."""
        if self._query:
            return f'No games match "{self._query}".'
        if not self._all:
            if self._demo:
                return "Demo mode"
            return ("No games yet!\n\nPress Menu (Start button or F10), then choose \"Set up folders\" "
                    "to point Atari at Steam and your ROM folders.")
        if self._filter == "favorites":
            return "No favorites yet.\n\nHighlight a game and press Y (gamepad) or F (keyboard)."
        if self._filter == "recent":
            return "Nothing played yet.\n\nGames you play will show up here."
        if self._filter == STEAM:
            return self._lib.steam_note or "No Steam games found."
        return "No games here."

    # ----- actions ---------------------------------------------------------
    @Slot(int)
    def toggleFavorite(self, row: int) -> None:
        g = self.model.game_at(row)
        if g is None:
            return
        now = self.store.toggle_favorite(g.gid)
        self._rebuild_filters()
        if self._filter == "favorites" and not now:
            self._apply()
        else:
            self.model.row_changed(row)
        self.show_toast(("Added to favorites: " if now else "Removed from favorites: ") + g.title, 2500)

    @Slot(int)
    def launch(self, row: int) -> None:
        g = self.model.game_at(row)
        if g is None or self._running:
            return
        if self._demo:
            self.show_toast("Demo mode: nothing to launch.")
            return
        self._running = True
        self._running_title = g.title
        self.runningChanged.emit()
        cfg = self.cfg

        def worker():
            err, secs = "", 0.0
            try:
                secs, err = launcher.run_game(cfg, g, on_started=lambda: self.store.mark_launched(g.gid))
            except launcher.LaunchError as exc:
                err = str(exc)
            except Exception as exc:  # pragma: no cover - safety net
                err = f"Something went wrong: {exc}"
            self.sessionEnded.emit(g.gid, g.title, secs, err)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, str, float, str)
    def _on_session_ended(self, gid: str, title: str, secs: float, err: str) -> None:
        if secs >= MIN_PLAYTIME_SEC:
            self.store.add_playtime(gid, secs)
        self._running = False
        self._running_title = ""
        self.runningChanged.emit()
        self._rebuild_filters()
        self._apply()
        if self._window is not None:
            self._window.raise_()
            self._window.requestActivate()
        self.show_toast(err or f"Welcome back! You played {title} for {max(1, int(secs // 60))} min.", 8000)

    @Slot()
    def toggleFullscreen(self) -> None:
        self.cfg.fullscreen = not self.cfg.fullscreen
        self.fullscreenChanged.emit()

    @Slot()
    def quit(self) -> None:
        self.stop_gamepad()
        QGuiApplication.quit()

    # ----- setup screen ----------------------------------------------------
    @Slot(result="QVariantList")
    def setupRows(self):
        rows = []
        scan = self._lib.steam_scan
        rows.append({"kind": "steam", "title": "Steam games",
                     "value": "ON" if self.cfg.steam_enabled else "OFF",
                     "detail": self._lib.steam_note})
        if self.cfg.steam_enabled:
            for lib in scan.libraries:
                tag = "" if lib.exists else "  (not mounted)"
                tag += "  [Windows NTFS drive]" if lib.on_ntfs else ""
                rows.append({"kind": "info", "title": "   Steam library", "value": "",
                             "detail": f"{lib.path}{tag} - {lib.game_count} games"})
            rows.append({"kind": "steamlib", "title": "Add another Steam library folder", "value": "",
                         "detail": "Only needed if a drive Steam knows about is not listed above."})
        for sc in self.cfg.systems.values():
            n = self._lib.rom_counts.get(sc.id, 0)
            folder = ", ".join(sc.roms) if sc.roms else "Not set - press Enter to choose a folder"
            rows.append({"kind": "system", "id": sc.id, "title": sc.name,
                         "value": (f"{n} game" + ("" if n == 1 else "s")) if sc.roms else "",
                         "detail": folder})
        rows.append({"kind": "done", "title": "Save and start playing", "value": "",
                     "detail": f"Settings are saved in {self.configPath}"})
        return rows

    @Slot(str, str)
    def setSystemFolder(self, system_id: str, folder: str) -> None:
        sc = self.cfg.systems.get(system_id)
        if sc and folder:
            sc.roms = [folder]
            self._lib = build_library(self.cfg)
            self.statusChanged.emit()

    @Slot(str)
    def clearSystemFolder(self, system_id: str) -> None:
        sc = self.cfg.systems.get(system_id)
        if sc:
            sc.roms = []
            self._lib = build_library(self.cfg)
            self.statusChanged.emit()

    @Slot()
    def toggleSteam(self) -> None:
        self.cfg.steam_enabled = not self.cfg.steam_enabled
        self._lib = build_library(self.cfg) if not self._demo else self._lib
        self.statusChanged.emit()

    @Slot(str)
    def addSteamLibrary(self, folder: str) -> None:
        if folder and folder not in self.cfg.steam_extra_libraries:
            self.cfg.steam_extra_libraries.append(folder)
            self._lib = build_library(self.cfg)
            self.statusChanged.emit()

    @Slot()
    def finishSetup(self) -> None:
        if not self._demo:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)
        self._first_run = False
        self.firstRunChanged.emit()
        self.rescan(initial=False)

    @Slot(str, result="QVariantMap")
    def listDir(self, path: str):
        """Folder browser data: {path, parent, dirs:[{name,path}]}. Empty path = places."""
        home = Path.home()
        if not path:
            places = [("Home", home)]
            for base in (Path("/media") / os.environ.get("USER", ""), Path("/run/media") / os.environ.get("USER", ""),
                         Path("/mnt")):
                try:
                    places += [(f"{base.name or base} / {p.name}", p) for p in sorted(base.iterdir()) if p.is_dir()]
                except OSError:
                    pass
            places.append(("Whole computer (/)", Path("/")))
            return {"path": "", "parent": "", "dirs": [{"name": n, "path": str(p)} for n, p in places]}
        p = Path(path)
        dirs = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
                if child.name.startswith("."):
                    continue
                try:
                    if child.is_dir():
                        dirs.append({"name": child.name, "path": str(child)})
                except OSError:
                    pass
        except OSError:
            pass
        parent = "" if str(p) == "/" else str(p.parent)
        return {"path": str(p), "parent": parent, "dirs": dirs}

    @Slot(result=str)
    def homeDir(self) -> str:
        return str(Path.home())
