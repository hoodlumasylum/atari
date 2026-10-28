"""The bridge between Python (data, launching) and the QML user interface."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent

from . import apps, bios, controls, covers, diagnose, emulators, freegames, importer, installer, launcher, paths, roms, updater, webapps, windows
from . import __version__
from .config import Config, load_config, save_config
from .import_model import ImportModel
from .library import STEAM, LibraryResult, build_library, demo_library
from .model import SORT_MODES, GameModel, filter_games
from .store import Store
from .systems_meta import system_look

NTFS_NOTE = ("Tip: Steam libraries on Windows (NTFS) drives often fail to start under Proton. "
             "A library on a Linux drive (ext4) is strongly recommended.")

MIN_PLAYTIME_SEC = 5  # shorter sessions are not counted (accidental launches)

ACTION_KEYS = {
    "up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right,
    "accept": Qt.Key_Return, "back": Qt.Key_Escape, "search": Qt.Key_Slash,
    "favorite": Qt.Key_F, "menu": Qt.Key_F10, "options": Qt.Key_F10,
    "system": Qt.Key_Tab, "prev": Qt.Key_Q, "next": Qt.Key_E,
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
    sortChanged = Signal()
    tilesChanged = Signal()
    importChanged = Signal()
    importProgressChanged = Signal()
    importScanned = Signal(object)    # ScanResult (from worker thread)
    importProgressed = Signal(float, str)
    importFinished = Signal(object)   # CopyResult (from worker thread)
    sessionEnded = Signal(str, str, float, str)  # gid, title, seconds, error (from worker thread)
    gamepadNote = Signal(str)
    coversChanged = Signal()
    coverArrived = Signal(str, str, str)   # gid, file, kind (from worker thread)
    coverProgressed = Signal(int, int, int)  # done, total, got
    coversFinished = Signal(object)         # covers.Report
    sessionStarted = Signal()               # the emulator process is up (from worker thread)
    runningHintChanged = Signal()
    updateChanged = Signal()
    updateEvent = Signal(str, str, float)       # state, text, fraction (from the worker thread)
    updateChecked = Signal(object, str, bool)   # release or None, error text, was it asked for by the user
    uiPrefsChanged = Signal()
    pageChanged = Signal()                      # the rows of the help / fix / Windows pages changed
    studioRequested = Signal()                  # the Studio tile / menu entry: the screen opens the Studio
    pageRequested = Signal(str)                 # a worker wants the screen to show this page ('close' = go to the library)
    winEvent = Signal(str, str, object)         # Windows game archive progress (from the worker thread)

    def __init__(self, cfg: Config | None = None, store: Store | None = None, demo: bool = False,
                 enable_gamepad: bool = True):
        super().__init__()
        self.cfg = cfg or load_config()
        if store is None and demo:
            store = self._demo_store()
        self.store = store or Store()
        self._demo = demo
        self.model = GameModel(self.store, self)
        self._sort = self.store.get_pref("sort", "az")
        if self._sort not in dict(SORT_MODES):
            self._sort = "az"
        self._show_all = bool(self.store.get_pref("show_all_systems", False))
        self._tiles: list[dict] = []
        # USB / folder import
        self.import_model = ImportModel(self)
        self._imp_state = "drives"
        self._imp_msg = ""
        self._imp_progress = 0.0
        self._imp_file = ""
        self._imp_source = ""
        self._imp_cancel = threading.Event()
        self._imp_kind = "games"          # "games" | "bios" - the same USB picker serves both
        self.importScanned.connect(self._on_import_scanned, Qt.QueuedConnection)
        self.importProgressed.connect(self._on_import_progress, Qt.QueuedConnection)
        self.importFinished.connect(self._on_import_finished, Qt.QueuedConnection)
        self._lib = LibraryResult()
        self._all = []
        self._filter = "all"
        self._query = ""
        self._filters: list[dict] = []
        self._running = False
        self._running_title = ""
        self._toast = ""
        # the welcome/setup screen shows only once: not if a config exists, nor if it was already dismissed
        self._first_run = bool(self.cfg.first_run and not self.store.get_pref("setup_done", False)) and not demo
        self._gamepad_proc: QProcess | None = None
        self._window = None
        self._toast_timer = QTimer(self, singleShot=True, interval=5000)
        self._toast_timer.timeout.connect(lambda: self._set_toast(""))
        self.sessionEnded.connect(self._on_session_ended, Qt.QueuedConnection)
        self.sessionStarted.connect(self._on_session_started, Qt.QueuedConnection)
        self._running_hint = ""
        self._minimized_for_game = False
        # covers (background download)
        self._cover_busy = False
        self._cover_text = ""
        self._cover_cancel = threading.Event()
        self._cover_rerun = False
        self._cover_by_gid: dict[str, object] = {}
        self.coverArrived.connect(self._on_cover_arrived, Qt.QueuedConnection)
        self.coverProgressed.connect(self._on_cover_progress, Qt.QueuedConnection)
        self.coversFinished.connect(self._on_covers_finished, Qt.QueuedConnection)
        self._cover_timer = QTimer(self, singleShot=True, interval=2500)
        self._cover_timer.timeout.connect(lambda: self.startCovers(auto=True))
        # sounds (a helper process plays them) and animations
        self._snd_proc = None
        self._snd_dead = False
        self._studio = None
        self._sound_sink = None          # tests put a function here to see the commands instead of playing them
        self._last_tick = 0.0
        self._start_timer = QTimer(self, singleShot=True, interval=700)
        self._start_timer.timeout.connect(lambda: self.playSound("start"))
        if not self._demo:
            self._start_timer.start()
            if self.cfg.music:
                QTimer.singleShot(1200, self._sync_music)
        # pages (help / fix my game / add Windows game)
        self._fix_gid = ""
        self._reset_armed = False
        self._remove_armed = False
        self._win_cancel = threading.Event()
        self._win_reset()
        self.winEvent.connect(self._on_win_event, Qt.QueuedConnection)
        # self-update
        self._upd_state = "idle"
        self._upd_text = ""
        self._upd_frac = -1.0
        self._upd_cancel = threading.Event()
        self._upd_release = None
        self._restart_spawn = subprocess.Popen
        rel = updater.Release.from_dict(self.store.get_pref("update_latest") or {})
        if rel and updater.is_newer(rel.version, __version__):
            self._upd_release = rel
        self.updateEvent.connect(self._on_update_event, Qt.QueuedConnection)
        self.updateChecked.connect(self._on_update_checked, Qt.QueuedConnection)
        self._upd_timer = QTimer(self, singleShot=True, interval=8000)
        self._upd_timer.timeout.connect(self._auto_check_update)
        if (self.cfg.update_check and not self._demo and not self._first_run
                and not os.environ.get("ATARI_NO_UPDATE_CHECK")
                and updater.due(self.store.get_pref("update_last_check", 0))):
            self._upd_timer.start()
        self._hide_timer = QTimer(self, singleShot=True, interval=2500)
        self._hide_timer.timeout.connect(self._hide_for_game)
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
        return self._real_count()

    def _real_count(self) -> int:
        """Games from Steam / ROM folders (the always-present PC / Apps entry does not count)."""
        return sum(1 for g in self._all if g.platform not in apps.NON_GAME)

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

    @Property("QVariantList", notify=tilesChanged)
    def tiles(self):
        return self._tiles

    @Property(bool, notify=tilesChanged)
    def showAllSystems(self):
        return self._show_all

    @Slot()
    def toggleShowAllSystems(self) -> None:
        self._show_all = not self._show_all
        self.store.set_pref("show_all_systems", self._show_all)
        self._rebuild_filters()
        if not self._show_all and not any(f["key"] == self._filter for f in self._filters):
            self.setFilter("all")

    @Property(str, notify=sortChanged)
    def sortKey(self):
        return self._sort

    @Property(str, notify=sortChanged)
    def sortLabel(self):
        return dict(SORT_MODES).get(self._sort, "A-Z")

    @Property("QVariantList", constant=True)
    def sortModes(self):
        return [{"key": k, "label": v} for k, v in SORT_MODES]

    @Slot(str)
    def setSort(self, key: str) -> None:
        if key in dict(SORT_MODES) and key != self._sort:
            self._sort = key
            self.store.set_pref("sort", key)
            self.sortChanged.emit()
            self._apply()

    @Slot()
    def cycleSort(self) -> None:
        keys = [k for k, _ in SORT_MODES]
        self.setSort(keys[(keys.index(self._sort) + 1) % len(keys)])

    @Property(str, constant=True)
    def ntfsNote(self):
        return NTFS_NOTE

    @Property(str, notify=currentFilterChanged)
    def currentLabel(self):
        for f in self._filters:
            if f["key"] == self._filter:
                return f["label"]
        return "All Games"

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
    def rescan(self, initial: bool = False, toast: bool = True) -> None:
        self._lib = demo_library() if self._demo else build_library(self.cfg)
        self._all = self._lib.games
        self._rebuild_filters()
        if not any(f["key"] == self._filter for f in self._filters):
            self._filter = "all"
        self.currentFilterChanged.emit()
        self._apply()
        self.statusChanged.emit()
        self.libraryChanged.emit()
        if not initial and toast:
            n = self._real_count()
            self.show_toast(f"Library updated: {n} game" + ("" if n == 1 else "s"))
        self._schedule_covers()

    def _rebuild_filters(self) -> None:
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for g in self._all:
            counts[g.platform] = counts.get(g.platform, 0) + 1
            names[g.platform] = g.platform_name
        recent_ids = set(self.store.recent_ids())
        fl = [
            {"key": "all", "label": "All Games", "count": len(self._all)},
            {"key": "favorites", "label": "Favourites",
             "count": sum(1 for g in self._all if self.store.is_favorite(g.gid))},
            {"key": "recent", "label": "Recent", "count": sum(1 for g in self._all if g.gid in recent_ids)},
        ]
        # system tiles: only systems that have games (or all of them with "Show all systems"), Steam last
        tiles = []
        for sid, sc in self.cfg.systems.items():
            if counts.get(sid, 0) > 0 or self._show_all:
                tiles.append(self._tile(sid, sc.name, counts.get(sid, 0)))
        for sid in counts:
            if sid != STEAM and sid not in self.cfg.systems:
                tiles.append(self._tile(sid, names[sid], counts[sid]))
        if STEAM in counts or (self.cfg.steam_enabled and (self._show_all or self._lib.steam_scan.found)):
            tiles.append(self._tile(STEAM, "Steam", counts.get(STEAM, 0)))
        self._tiles = tiles
        fl += [{"key": t["key"], "label": t["label"], "count": t["count"]} for t in tiles]
        self._filters = fl
        self.filtersChanged.emit()
        self.tilesChanged.emit()

    def _tile(self, key: str, name: str, count: int) -> dict:
        look = system_look(key, name)
        return {"key": key, "label": name, "short": look["short"], "glyph": look["glyph"],
                "c1": look["c1"], "c2": look["c2"], "count": count}

    def _apply(self) -> None:
        self.model.set_visible(filter_games(self._all, self.store, self._filter, self._query, self._sort))

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
        if self._real_count() == 0 and self._filter in ("all", "favorites", "recent"):
            if self._demo:
                return "Demo mode"
            return ("No games yet!\n\nChoose \"Add Games\" to copy games from a USB stick, or open Settings "
                    "to add your Steam library and ROM folders.\n\n"
                    "Not sure where to start? Press the Options button (F10 / Start) and choose "
                    "\"Help & getting started\".\n\n" + NTFS_NOTE)
        if self._filter == "favorites":
            return "No favourites yet.\n\nHighlight a game and press X (gamepad) or F (keyboard)."
        if self._filter == "recent":
            return "Nothing played yet.\n\nGames you play will show up here."
        if self._filter == STEAM:
            return self._lib.steam_note or "No Steam games found."
        if self._filter == "free":
            return ("No free games listed.\n\n" + freegames.MINECRAFT_NOTE)
        if self._filter in apps.NON_GAME:
            return "No apps found."
        sc = self.cfg.systems.get(self._filter)
        if sc is not None:
            _ready, label, hint = emulators.status_line(self.cfg, sc)
            folder = sc.roms[0] if sc.roms else "~/Games/Atari/" + sc.id
            return (f"No {sc.name} games yet.\n\nUse \"Add Games\" to import some, or put them in {folder}.\n\n"
                    f"Emulator: {label}" + ("" if _ready else "\n" + hint))
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
        self.playSound("fav")
        self.show_toast(("Added to favourites: " if now else "Removed from favourites: ") + g.title, 2500)

    @Slot(int)
    def launch(self, row: int) -> None:
        g = self.model.game_at(row)
        if g is None or self._running:
            return
        if g.gid == "studio:open":
            self.studioRequested.emit()
            return
        if self._demo:
            self.show_toast("Demo mode: nothing to launch.")
            return
        self.playSound("launch")
        if self.cfg.music and self._snd_enabled():
            self._snd_write("music off")        # the game gets the speakers
        self._running = True
        self._running_title = g.title
        self._running_is_rom = g.platform != "steam"
        self._running_hint = launcher.controls_hint(self.cfg, g)
        self.runningHintChanged.emit()
        self.runningChanged.emit()
        cfg = self.cfg

        def started():
            self.store.mark_launched(g.gid)
            self.sessionStarted.emit()

        def worker():
            err, secs = "", 0.0
            try:
                secs, err = launcher.run_game(cfg, g, on_started=started)
            except launcher.LaunchError as exc:
                err = str(exc)
            except Exception as exc:  # pragma: no cover - safety net
                err = f"Something went wrong: {exc}"
            self.sessionEnded.emit(g.gid, g.title, secs, err)

        threading.Thread(target=worker, daemon=True).start()

    @Property(str, notify=runningHintChanged)
    def runningHint(self):
        return self._running_hint

    @Slot()
    def _on_session_started(self) -> None:
        """The emulator process is up. Atari's own (full screen) window must not sit between the keyboard and the
        emulator, so after a moment it is minimised; it comes back when the game ends."""
        if getattr(self, "_running_is_rom", False) and not os.environ.get("ATARI_NO_MINIMIZE") and self._window is not None:
            self._hide_timer.start()

    def _hide_for_game(self) -> None:
        if self._running and self._window is not None and not self._minimized_for_game:
            self._minimized_for_game = True
            self._window.showMinimized()

    def _restore_window(self) -> None:
        win = self._window
        if win is None:
            return
        if self._minimized_for_game:
            self._minimized_for_game = False
            if self.cfg.fullscreen:
                win.showFullScreen()
            else:
                win.showNormal()
        win.raise_()
        win.requestActivate()

    @Slot(str, str, float, str)
    def _on_session_ended(self, gid: str, title: str, secs: float, err: str) -> None:
        if secs >= MIN_PLAYTIME_SEC:
            self.store.add_playtime(gid, secs)
        self._hide_timer.stop()
        self._running = False
        self._running_title = ""
        self._running_hint = ""
        self.runningHintChanged.emit()
        self.runningChanged.emit()
        self._rebuild_filters()
        self._apply()
        self._restore_window()
        self._sync_music()
        if err and err.startswith(launcher.INFO):
            self.playSound("select")
        elif err:
            self.playSound("error")
            launcher._log("error: " + err)
            if err.startswith(launcher.INFO):
                err = err[len(launcher.INFO):]
            elif "Fix my game" not in err:
                err += "   (Options > Fix my game can check what is wrong.)"
        self.show_toast(err or f"Welcome back! You played {title} for {max(1, int(secs // 60))} min.", 12000 if err else 8000)

    @Slot()
    def toggleFullscreen(self) -> None:
        self.cfg.fullscreen = not self.cfg.fullscreen
        self.fullscreenChanged.emit()

    @Slot()
    def quit(self) -> None:
        self.stop_gamepad()
        self.stop_sound()
        QGuiApplication.quit()

    # ----- emulators page --------------------------------------------------
    @Slot(result="QVariantList")
    def emulatorRows(self):
        rows = [{"kind": "info", "title": "Emulators are separate programs. Atari finds them automatically "
                                          "(installed programs and Flatpaks).", "value": "", "detail": ""},
                {"kind": "info", "title": "Press Enter on a console to switch between its emulators. "
                                          "Atari never includes BIOS, firmware, keys or games - bring your own.",
                 "value": "", "detail": ""},
                {"kind": "install", "title": "Install emulators and apps",
                 "value": "",
                 "detail": "Opens a window that installs every emulator and PC app Atari knows (safe to run again). "
                           "Needs an internet connection and takes a while."},
                {"kind": "bios", "title": "Add BIOS files",
                 "value": "",
                 "detail": "Copy BIOS / firmware files from your own consoles (USB stick or folder) to the right places. "
                           "Only use files from consoles you own."},
                {"kind": "controls", "title": "Controls (keyboard keys)", "value": "",
                 "detail": "Which keys to press in each emulator."}]
        counts = {}
        for g in self._all:
            counts[g.platform] = counts.get(g.platform, 0) + 1
        order = sorted(self.cfg.systems.values(), key=lambda sc: -1 if counts.get(sc.id) else 0)
        for sc in order:
            ready, label, hint = emulators.status_line(self.cfg, sc)
            n = counts.get(sc.id, 0)
            games = f"{n} game{'s' if n != 1 else ''}  \u00b7  " if n else ""
            bstate, btext = bios.missing_for(sc.id)
            bios_line = ""
            if bstate in ("missing", "recommended", "note"):
                bios_line = "   BIOS: " + btext
            elif bstate == "ok":
                bios_line = "   BIOS: found."
            value = "Ready" if ready else "Not installed"
            if ready and bstate == "missing":
                value = "Needs BIOS"
            rows.append({"kind": "emu", "id": sc.id, "title": sc.name, "value": value,
                         "detail": games + (label if ready else (label + ": " + hint))
                                   + (f"   [{hint}]" if ready and hint else "") + bios_line})
        for app in apps.APP_DEFS:
            ready, text = apps.app_status(self.cfg, app)
            rows.append({"kind": "app", "title": app.title + "  (PC Apps)", "value": "Ready" if ready else "Not installed",
                         "detail": app.note if ready else text})
        b, how = webapps.find_browser(self.cfg)
        rows.append({"kind": "app", "title": "Streaming web apps  (browser)", "value": "Ready" if b else "Not installed",
                     "detail": (f"Open in {b.name}. " + ("Netflix & co. work." if b.drm else "Netflix & co. may not play (no Widevine) - use Chrome.")
                                if b else webapps.HELP_TEXT)})
        wok, wlabel = windows.runner_status(self.cfg)
        rows.append({"kind": "app", "title": "Windows games  (umu / Proton / Wine)", "value": "Ready" if wok else "Not installed",
                     "detail": ("Runs with " + wlabel + ".") if wok else wlabel})
        for name, text in emulators.NOTES:
            rows.append({"kind": "info", "title": f"{name}: {text}", "value": "", "detail": ""})
        rows.append({"kind": "back", "title": "Back to Settings", "value": "",
                     "detail": "To use your own program or Flatpak, edit [emulators] in " + self.configPath})
        return rows

    @Slot(result="QVariantList")
    def controlsRows(self):
        return controls.cheat_rows()

    @Slot()
    def installEmulators(self) -> None:
        """Open a terminal window that runs the emulator installer (needs the user's own Flatpak setup)."""
        ok, msg = installer.open_in_terminal()
        self.show_toast(msg, 9000)

    @Slot(str)
    def cycleEmulator(self, system_id: str) -> None:
        sc = self.cfg.systems.get(system_id)
        if sc is None:
            return
        sc.emulator = emulators.next_preference(self.cfg, sc)
        if not self._demo and not self._first_run:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)

    # ----- add games (USB stick / folder) ---------------------------------------
    @Property(str, notify=importChanged)
    def importState(self):
        return self._imp_state

    @Property(str, notify=importChanged)
    def importMessage(self):
        return self._imp_msg

    @Property(float, notify=importProgressChanged)
    def importProgress(self):
        return self._imp_progress

    @Property(str, notify=importProgressChanged)
    def importCurrent(self):
        return self._imp_file

    @Property(QObject, constant=True)
    def importItems(self):
        return self.import_model

    @Property(str, notify=importChanged)
    def importSource(self):
        return self._imp_source

    @Property(str, notify=importChanged)
    def importKind(self):
        return self._imp_kind

    @Slot()
    def openImport(self) -> None:
        self.openImportKind("games")

    @Slot(str)
    def openImportKind(self, kind: str) -> None:
        self._imp_kind = "bios" if kind == "bios" else "games"
        self._imp_state = "drives"
        self._imp_msg = ""
        self._imp_source = ""
        self.import_model.set_items([])
        self.importChanged.emit()

    @Slot(result="QVariantList")
    def importRows(self):
        """Rows of the first import screen: detected USB drives, then Browse / Refresh."""
        drives = importer.detect_drives()
        rows = [{"kind": "drive", "title": d.label, "detail": d.detail, "path": d.path, "value": d.fs_name}
                for d in drives]
        msg = "" if drives else "No USB stick found. Plug in your USB stick, then press Refresh."
        if msg != self._imp_msg:
            self._imp_msg = msg
            self.importChanged.emit()
        rows.append({"kind": "refresh", "title": "Refresh", "detail": "Look for USB sticks again", "value": ""})
        rows.append({"kind": "browse", "title": "Browse folder...", "detail": "Pick any folder instead "
                     "(for example a card reader or a folder on another drive)", "value": ""})
        rows.append({"kind": "close", "title": "Back", "detail": "", "value": ""})
        return rows

    @Slot(str)
    def startImportScan(self, path: str) -> None:
        if not path:
            return
        self._imp_source = path
        self._imp_state = "scanning"
        self._imp_msg = ("Looking for BIOS files on " if self._imp_kind == "bios" else "Looking for games on ") + path + " ..."
        self._imp_cancel = threading.Event()
        self.importChanged.emit()
        cancel, cfg, kind = self._imp_cancel, self.cfg, self._imp_kind

        def worker():
            try:
                if kind == "bios":
                    res = bios.scan_for_bios(path, cancel)
                else:
                    res = importer.scan_for_roms(path, cfg, cancel)
            except Exception as exc:  # pragma: no cover - safety net
                res = bios.BiosScan() if kind == "bios" else importer.ScanResult()
                res.unclear = -1
                print(f"[atari] import scan failed: {exc}")
            self.importScanned.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(object)
    def _on_import_scanned(self, res) -> None:
        if self._imp_state != "scanning":  # cancelled meanwhile
            return
        if res.cancelled:
            self._imp_state = "drives"
            self.importChanged.emit()
            return
        names = {sid: sc.name for sid, sc in self.cfg.systems.items()}
        if isinstance(res, bios.BiosScan):
            self.import_model.set_items(res.items, names, kind="bios")
            self._imp_state = "list"
            n = len(res.items)
            self._imp_msg = (f"Found {n} BIOS / firmware file{'s' if n != 1 else ''} on {self._imp_source}. "
                             "Tick the ones to copy - they go to each emulator's own folder. "
                             if n else f"No known BIOS files found on {self._imp_source}. ") + bios.LEGAL
            self.importChanged.emit()
            return
        self.import_model.set_items(res.items, names)
        self._imp_state = "list"
        extra = ""
        if res.unclear > 0:
            extra = (f" {res.unclear} other file{'s' if res.unclear != 1 else ''} (zip, iso...) were skipped because "
                     "the console is unclear - put them in a folder named after the console, e.g. \"snes\".")
        if res.truncated:
            extra += " Only the first files are shown (very large folder)."
        if res.unclear < 0:
            extra = " Something went wrong while reading this folder."
        self._imp_msg = (f"Found {len(res.items)} game{'s' if len(res.items) != 1 else ''} on {self._imp_source}."
                         if res.items else f"No games found on {self._imp_source}.") + extra
        self.importChanged.emit()

    @Slot(int)
    def toggleImportItem(self, row: int) -> None:
        self.import_model.toggle(row)

    @Slot(bool)
    def setAllImport(self, on: bool) -> None:
        self.import_model.set_all(on)

    @Slot()
    def startImportCopy(self) -> None:
        items = self.import_model.selected_items()
        if not items:
            return
        self._imp_state = "copying"
        self._imp_progress = 0.0
        self._imp_file = ""
        what = "BIOS file" if self._imp_kind == "bios" else "game"
        self._imp_msg = f"Copying {len(items)} {what}{'s' if len(items) != 1 else ''}..."
        self._imp_cancel = threading.Event()
        self.importChanged.emit()
        self.importProgressChanged.emit()
        cancel, cfg = self._imp_cancel, self.cfg
        last = [0.0]
        if self._imp_kind == "bios":
            def bios_progress(done, total, name):
                self.importProgressed.emit(done / total if total else 1.0, name)

            def bios_worker():
                try:
                    res = bios.copy_items(items, cfg, None, bios_progress, cancel)
                except Exception as exc:  # pragma: no cover - safety net
                    res = bios.BiosCopyResult(error=f"Something went wrong: {exc}")
                self.importFinished.emit(res)

            threading.Thread(target=bios_worker, daemon=True).start()
            return

        def progress(done, total, name, files):
            now = time.monotonic()
            if now - last[0] > 0.1 or done >= total:
                last[0] = now
                self.importProgressed.emit(done / total if total else 1.0, name)

        def worker():
            try:
                res = importer.copy_items(items, cfg, progress, cancel)
            except Exception as exc:  # pragma: no cover - safety net
                res = importer.CopyResult(error=f"Something went wrong: {exc}")
            self.importFinished.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(float, str)
    def _on_import_progress(self, frac: float, name: str) -> None:
        self._imp_progress = frac
        self._imp_file = name
        self.importProgressChanged.emit()

    @Slot(object)
    def _on_import_finished(self, res) -> None:
        if isinstance(res, bios.BiosCopyResult):
            self._on_bios_finished(res)
            return
        # make sure the library looks into the folders the games went to
        changed = False
        for sid, folder in res.systems.items():
            sc = self.cfg.systems.get(sid)
            if sc is not None and not sc.roms:
                sc.roms = [str(folder)]
                changed = True
        if changed and not self._first_run and not self._demo:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)
        if res.error:
            msg = res.error
        else:
            msg = f"Copied {res.copied} game{'s' if res.copied != 1 else ''} ({importer.human_size(res.bytes_copied)})."
            if res.skipped_duplicates:
                msg += f" {res.skipped_duplicates} already in your library (skipped)."
            if res.failed:
                msg += f" {len(res.failed)} could not be copied: " + "; ".join(res.failed[:3])
            if res.cancelled:
                msg = "Cancelled. " + msg
            elif res.copied:
                msg += " Your USB stick can be removed safely."
        self._imp_msg = msg
        self._imp_state = "done"
        self._imp_progress = 1.0
        self.importChanged.emit()
        self.importProgressChanged.emit()
        self.rescan(toast=False)

    def _on_bios_finished(self, res) -> None:
        if res.error:
            msg = res.error
        else:
            msg = (f"Copied {res.copied} BIOS file{'s' if res.copied != 1 else ''}." if res.copied
                   else "Nothing new to copy." if res.skipped_same else "Nothing was copied.")
            if res.skipped_same:
                msg += f" {res.skipped_same} already in place."
            if res.failed:
                msg += f" {len(res.failed)} could not be copied: " + "; ".join(res.failed[:2])
            if res.cancelled:
                msg = "Cancelled. " + msg
            for note in res.notes:
                msg += "  " + note
            if res.copied:
                msg += "  Your USB stick can be removed safely."
        self._imp_msg = msg
        self._imp_state = "done"
        self._imp_progress = 1.0
        self.importChanged.emit()
        self.importProgressChanged.emit()
        self.show_toast("BIOS files copied" if res.copied else "No BIOS files were copied", 4000)

    @Slot()
    def cancelImport(self) -> None:
        """Cancel a scan or copy in progress."""
        self._imp_cancel.set()
        if self._imp_state == "scanning":
            self._imp_state = "drives"
            self.importChanged.emit()

    @Slot(result=str)
    def importBrowseStart(self) -> str:
        """Where the folder browser opens for "Browse folder...": the user's USB mount area if there is one."""
        user = os.environ.get("USER") or Path.home().name
        for base in (Path("/media") / user, Path("/run/media") / user):
            if base.is_dir():
                return str(base)
        return str(Path.home())

    @Slot()
    def backToDrives(self) -> None:
        self.openImportKind(self._imp_kind)

    # ----- self-update ---------------------------------------------------------
    @Property(str, constant=True)
    def version(self):
        return __version__

    @Property(str, notify=updateChanged)
    def updateState(self):
        """idle | checking | uptodate | available | downloading | verifying | installing | done | error"""
        return self._upd_state

    @Property(str, notify=updateChanged)
    def updateText(self):
        return self._upd_text

    @Property(float, notify=updateChanged)
    def updateFraction(self):
        return self._upd_frac

    @Property(str, notify=updateChanged)
    def updateVersion(self):
        return self._upd_release.version if self._upd_release else ""

    @Property(str, notify=updateChanged)
    def updateNotes(self):
        return self._upd_release.notes if self._upd_release else ""

    @Property(bool, notify=updateChanged)
    def updateAvailable(self):
        """A newer release is known (checked quietly in the background): drives the badge on the top bar."""
        return self._upd_release is not None and self._upd_state != "done"

    @Property(bool, notify=updateChanged)
    def updateBusy(self):
        return self._upd_state in ("checking", "downloading", "verifying", "installing")

    # ----- sounds and animations --------------------------------------------------
    @Property(bool, notify=uiPrefsChanged)
    def soundEffects(self):
        return self.cfg.sound_effects

    @Property(bool, notify=uiPrefsChanged)
    def music(self):
        return self.cfg.music

    @Property(float, notify=uiPrefsChanged)
    def volume(self):
        return self.cfg.volume

    @Property(bool, notify=uiPrefsChanged)
    def animations(self):
        return not self.cfg.reduce_animations

    def _save_prefs(self) -> None:
        if not self._demo and not self._first_run:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)
        self.uiPrefsChanged.emit()

    @Slot()
    def toggleSoundEffects(self) -> None:
        self.cfg.sound_effects = not self.cfg.sound_effects
        self._save_prefs()
        if self.cfg.sound_effects:
            self.playSound("select")

    @Slot()
    def toggleMusic(self) -> None:
        self.cfg.music = not self.cfg.music
        self._save_prefs()
        self._sync_music()

    @Slot()
    def cycleVolume(self) -> None:
        steps = [0.2, 0.4, 0.6, 0.8, 1.0]
        nxt = next((s for s in steps if s > self.cfg.volume + 0.01), steps[0])
        self.cfg.volume = nxt
        self._save_prefs()
        self._snd_write(f"volume {nxt:.2f}")
        self.playSound("select")

    @Slot()
    def toggleAnimations(self) -> None:
        self.cfg.reduce_animations = not self.cfg.reduce_animations
        self._save_prefs()

    @Property(QObject, constant=True)
    def studio(self):
        if self._studio is None:
            from .studio_ui import StudioController
            self._studio = StudioController(self, self)
        return self._studio

    def _snd_enabled(self) -> bool:
        return self._sound_sink is not None or (not self._demo and not os.environ.get("ATARI_NO_SOUND"))

    def _snd_write(self, line: str) -> None:
        """One command to the sound helper (started the first time it is needed). Never raises."""
        if self._sound_sink is not None:
            self._sound_sink(line)
            return
        if os.environ.get("ATARI_NO_SOUND") or self._demo or self._snd_dead:
            return
        try:
            if self._snd_proc is None:
                proc = QProcess(self)
                proc.setProgram(sys.executable)
                proc.setArguments(["-m", "atarilauncher.sound_helper"])
                from PySide6.QtCore import QProcessEnvironment
                env = QProcessEnvironment.systemEnvironment()
                env.insert("PYTHONPATH", str(Path(__file__).resolve().parent.parent) + os.pathsep
                           + env.value("PYTHONPATH", ""))
                proc.setProcessEnvironment(env)
                proc.readyReadStandardOutput.connect(self._read_snd_status)
                proc.finished.connect(lambda *a: setattr(self, "_snd_proc", None))
                proc.start()
                self._snd_proc = proc
                proc.write(f"volume {self.cfg.volume:.2f}\n".encode())
                if self.cfg.music:
                    proc.write(b"music on\n")
            self._snd_proc.write((line + "\n").encode())
        except Exception:  # pragma: no cover - sound must never break the launcher
            self._snd_dead = True

    def _read_snd_status(self) -> None:
        text = bytes(self._snd_proc.readAllStandardOutput()).decode(errors="replace") if self._snd_proc else ""
        if "unavailable" in text:
            self._snd_dead = True        # no audio library or player: stay quiet from now on
            self._snd_proc = None

    def _sync_music(self) -> None:
        if self._snd_enabled():
            self._snd_write("music on" if (self.cfg.music and not self._running) else "music off")

    @Slot(str)
    def playSound(self, name: str) -> None:
        """tick | select | back | fav | launch | error | start. Silent when sound effects are off."""
        if not self.cfg.sound_effects or not self._snd_enabled():
            return
        if name == "tick":
            now = time.monotonic()
            if now - self._last_tick < 0.03:
                return
            self._last_tick = now
        self._snd_write(name)

    def stop_sound(self) -> None:
        proc, self._snd_proc = self._snd_proc, None
        if proc is not None:
            try:
                proc.write(b"quit\n")
                proc.waitForBytesWritten(300)
                if not proc.waitForFinished(800):
                    proc.kill()
            except Exception:
                pass

    @Property(bool, notify=updateChanged)
    def updateAuto(self):
        return self.cfg.update_check

    def _set_update(self, state: str, text: str = "", frac: float = -1.0) -> None:
        self._upd_state, self._upd_text, self._upd_frac = state, text, frac
        self.updateChanged.emit()

    @Slot()
    def toggleUpdateCheck(self) -> None:
        self.cfg.update_check = not self.cfg.update_check
        if not self._demo and not self._first_run:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)
        self.updateChanged.emit()

    def _auto_check_update(self) -> None:
        if self.cfg.update_check and self._upd_state == "idle":
            self._start_check(manual=False)

    def _start_check(self, manual: bool) -> None:
        if manual:
            self._set_update("checking", "Looking for a newer version ...")

        def worker():
            rel, err = None, ""
            try:
                rel = updater.check(__version__)
            except updater.UpdateError as exc:
                err = str(exc)
            except Exception as exc:  # pragma: no cover - safety net
                err = f"Could not check for updates ({exc})."
            self.updateChecked.emit(rel, err, manual)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(object, str, bool)
    def _on_update_checked(self, rel, err: str, manual: bool) -> None:
        if not err:   # remember that we looked (also "nothing new"): at most one silent check a day
            self.store.set_pref("update_last_check", time.time())
            self.store.set_pref("update_latest", rel.as_dict() if rel else {})
        if rel:
            self._upd_release = rel
        elif not err:
            self._upd_release = None
        if not manual:
            if self._upd_state == "idle":
                self.updateChanged.emit()
            return
        if err:
            self._set_update("error", err)
        elif rel:
            self._set_update("available", f"Atari {rel.version} is available (you have {__version__}).")
        else:
            self._set_update("uptodate", f"You have the newest version ({__version__}).")

    @Slot()
    def openUpdate(self) -> None:
        """The Update screen was opened: show what is known, or look now."""
        if self.updateBusy or self._upd_state == "done":
            return
        ok, why = updater.can_self_update(Path(os.environ.get("ATARI_UPDATE_ROOT") or updater.app_dir()))
        if not ok:
            self._set_update("error", why)
            return
        if self._upd_release is not None:
            self._set_update("available", f"Atari {self._upd_release.version} is available (you have {__version__}).")
        else:
            self._start_check(manual=True)

    @Slot()
    def recheckUpdate(self) -> None:
        if not self.updateBusy and self._upd_state != "done":
            self._start_check(manual=True)

    @Slot()
    def startUpdate(self) -> None:
        rel = self._upd_release
        if rel is None or self.updateBusy or self._running:
            return
        root = Path(os.environ.get("ATARI_UPDATE_ROOT") or updater.app_dir())
        self._upd_cancel = threading.Event()
        cancel = self._upd_cancel
        self._set_update("downloading", "Starting ...")

        def worker():
            try:
                updater.perform(rel, root, lambda st, tx, fr: self.updateEvent.emit(st, tx, fr), cancel)
                self.updateEvent.emit("done", f"Atari {rel.version} is installed. Restart Atari to use it.", 1.0)
            except updater.Cancelled:
                self.updateEvent.emit("available", f"Cancelled. Atari {rel.version} is still available.", -1.0)
            except updater.UpdateError as exc:
                self.updateEvent.emit("error", str(exc), -1.0)
            except Exception as exc:  # pragma: no cover - safety net
                self.updateEvent.emit("error", f"The update did not work ({exc}). Nothing of yours was changed.", -1.0)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, str, float)
    def _on_update_event(self, state: str, text: str, frac: float) -> None:
        self._set_update(state, text, frac)
        if state == "done":
            self.store.set_pref("update_latest", {})

    @Slot()
    def cancelUpdate(self) -> None:
        if self._upd_state == "downloading":
            self._upd_cancel.set()

    @Slot()
    def restartAtari(self) -> None:
        """Start the new Atari a moment after this one has quit."""
        root = Path(os.environ.get("ATARI_UPDATE_ROOT") or updater.app_dir())
        cmd = updater.restart_command(root, sys.argv[1:])
        try:
            self._restart_spawn(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.show_toast(f"Could not restart: {exc}. Please start Atari again yourself.", 8000)
            return
        self.quit()

    # ----- cover art (background download) -------------------------------------
    @Property(str, notify=coversChanged)
    def coverStatus(self):
        """'Covers 12/80' while downloading, else the last result ('' when there is nothing to say)."""
        return self._cover_text

    @Property(bool, notify=coversChanged)
    def coversBusy(self):
        return self._cover_busy

    @Property(bool, notify=coversChanged)
    def coversAuto(self):
        return self.cfg.covers_auto

    def _covers_allowed(self) -> bool:
        return not self._demo and not os.environ.get("ATARI_NO_COVERS")

    def _schedule_covers(self) -> None:
        """After a scan: look for missing covers a moment later, if the toggle is on."""
        if self.cfg.covers_auto and self._covers_allowed() and not self._first_run:
            self._cover_timer.start()

    def _set_cover_text(self, text: str) -> None:
        if text != self._cover_text:
            self._cover_text = text
        self.coversChanged.emit()

    @Slot()
    def toggleCoversAuto(self) -> None:
        self.cfg.covers_auto = not self.cfg.covers_auto
        if not self._demo and not self._first_run:
            try:
                save_config(self.cfg)
            except OSError as exc:
                self.show_toast(f"Could not save settings: {exc}", 8000)
        self.coversChanged.emit()

    @Slot()
    def downloadCoversNow(self) -> None:
        """The Settings button: start (or stop, if already running) and retry games that had no cover before."""
        if self._cover_busy:
            self.stopCovers()
            return
        if not self._covers_allowed():
            self.show_toast("Cover download is not available in demo mode.")
            return
        self.startCovers(auto=False, force=True)

    @Slot()
    def stopCovers(self) -> None:
        self._cover_cancel.set()

    def startCovers(self, auto: bool = True, force: bool = False) -> None:
        if not self._covers_allowed():
            return
        if self._cover_busy:
            self._cover_rerun = True
            return
        games = list(self._all)
        jobs = covers.jobs_for_games(games)
        self._cover_by_gid = {g.gid: g for g in games}
        if not jobs:
            if not auto:
                self._set_cover_text("All games already have a cover.")
            return
        self._cover_busy = True
        self._cover_cancel = threading.Event()
        self._cover_rerun = False
        self._set_cover_text(f"Covers 0/{len(jobs)}")
        cancel = self._cover_cancel
        base = os.environ.get("ATARI_COVERS_THUMBS_URL") or covers.THUMBS_URL
        steam_base = os.environ.get("ATARI_COVERS_STEAM_URL") or covers.STEAM_URL
        fast = bool(os.environ.get("ATARI_COVERS_FAST"))   # testing aid: no polite pauses

        def worker():
            try:
                http = covers.Http(pause=0.0 if fast else 0.25, backoff=0.01 if fast else 1.0,
                                   timeout=5 if fast else 15, cancel=cancel)
                dl = covers.CoverDownloader(base, steam_base, http=http, force=force)
                rep = dl.run(jobs, progress=lambda d, t, g: self.coverProgressed.emit(d, t, g),
                             on_cover=lambda j: self.coverArrived.emit(j.gid, str(j.dest), j.kind), cancel=cancel)
            except Exception as exc:  # pragma: no cover - safety net
                print(f"[atari] cover download failed: {exc}")
                rep = covers.Report(offline=True)
            self.coversFinished.emit(rep)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(int, int, int)
    def _on_cover_progress(self, done: int, total: int, got: int) -> None:
        self._set_cover_text(f"Covers {done}/{total}")

    @Slot(str, str, str)
    def _on_cover_arrived(self, gid: str, path: str, kind: str) -> None:
        """A picture is on disk: show it on the tile right away."""
        g = self._cover_by_gid.get(gid)
        # the library may have been rescanned meanwhile: use the current object for that game
        for cur in self._all:
            if cur.gid == gid:
                g = cur
                break
        if g is None:
            return
        if kind == "steam-header":
            g.header = path
        else:
            g.cover = path
            if not g.platform == "steam":
                g.header = path
            elif not g.header:
                g.header = path
        self.model.cover_updated(gid)

    @Slot(object)
    def _on_covers_finished(self, rep) -> None:
        self._cover_busy = False
        self._set_cover_text(rep.text() if (rep.got or rep.offline or rep.cancelled or rep.failed) else
                             (rep.text() if rep.total else ""))
        if self._cover_rerun:
            self._cover_rerun = False
            self._schedule_covers()

    # ----- setup screen ----------------------------------------------------
    @Slot(result="QVariantList")
    def setupRows(self):
        rows = [self._done_row()]  # a DONE / CONTINUE row at the top...
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
        rows.append({"kind": "import", "title": "Add games from a USB stick or folder", "value": "",
                     "detail": "Copies games into your library. The USB stick is never changed."})
        rows.append({"kind": "bios", "title": "Add BIOS files (from your own consoles)", "value": "",
                     "detail": "Finds BIOS / firmware files on a USB stick or folder and copies them to the emulators. "
                               "Only use files from consoles you own."})
        rows.append({"kind": "covers", "title": "Download covers",
                     "value": self._cover_text if self._cover_busy else "",
                     "detail": (self._cover_text if (self._cover_text and not self._cover_busy) else
                                "Fetches box art from the internet for games without a picture (press again to stop).")})
        rows.append({"kind": "coversauto", "title": "Download covers automatically after a scan",
                     "value": "ON" if self.cfg.covers_auto else "OFF",
                     "detail": "Only when the internet is reachable; runs quietly in the background."})
        rows.append({"kind": "update", "title": "Update Atari",
                     "value": ("New: " + self._upd_release.version) if self._upd_release else "Version " + __version__,
                     "detail": ("A newer version is ready to install." if self._upd_release else
                                "Checks for a newer version and installs it. Your games and settings are kept.")})
        rows.append({"kind": "updateauto", "title": "Check for updates automatically",
                     "value": "ON" if self.cfg.update_check else "OFF",
                     "detail": "At most once a day, quietly, only when the internet is reachable."})
        rows.append({"kind": "sfx", "title": "Sound effects",
                     "value": "ON" if self.cfg.sound_effects else "OFF",
                     "detail": "Small clicks and chimes when you move around, choose, go back or start a game."})
        rows.append({"kind": "music", "title": "Music (soft background loop)",
                     "value": "ON" if self.cfg.music else "OFF",
                     "detail": "Quiet and off by default. It stops while a game is running."})
        rows.append({"kind": "volume", "title": "Volume", "value": f"{int(round(self.cfg.volume * 100))}%",
                     "detail": "Press Enter to step through 20 / 40 / 60 / 80 / 100 %."})
        rows.append({"kind": "anim", "title": "Reduce animations",
                     "value": "ON" if self.cfg.reduce_animations else "OFF",
                     "detail": "Turns off the moving background, bobbing icons and fades. Choose ON on a slow computer."})
        rows.append({"kind": "emulators", "title": "Emulators", "value": "",
                        "detail": "See what is installed, install emulators, and which consoles still need BIOS files."})
        for sc in self.cfg.systems.values():
            n = self._lib.rom_counts.get(sc.id, 0)
            folder = ", ".join(sc.roms) if sc.roms else "Not set - press Enter to choose a folder"
            if not sc.roms and not n and sc.id not in self._setup_shown():
                continue
            rows.append({"kind": "system", "id": sc.id, "title": sc.name,
                         "value": (f"{n} game" + ("" if n == 1 else "s")) if sc.roms else "",
                         "detail": folder})
        rows.append(self._done_row())
        return rows

    def _done_row(self) -> dict:
        """...and at the bottom of the setup list; Enter on it (or Esc / B) goes to the main screen."""
        return {"kind": "done", "title": "DONE / CONTINUE", "value": "",
                "detail": ("Go to your games. You can come back here any time from Options > Settings."
                           if self._first_run else "Save and go back to your games.")}

    def _setup_shown(self) -> set:
        """Consoles always listed in Settings (the popular ones); others appear after "Show all systems"."""
        if self._show_all:
            return set(self.cfg.systems)
        return {"atari2600", "atari7800", "nes", "snes", "genesis", "gba", "n64", "ps1", "ps2", "ps3", "psp",
                "dreamcast", "gamecube", "wii", "xbox", "nds"}

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
            self.store.set_pref("setup_done", True)  # second marker, in case the config could not be written
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

    # ----- help, "fix my game", Windows games: simple row-list pages -------------------
    @Slot(str, result=str)
    def pageTitle(self, name: str) -> str:
        return {"help": "HELP & GETTING STARTED", "fix": "FIX MY GAME", "winform": "ADD A WINDOWS GAME",
                "winchoose": "WHICH PROGRAM STARTS THE GAME?", "winwork": "OPENING THE ARCHIVE"}.get(name, name.upper())

    @Slot(str, result=str)
    def pageSub(self, name: str) -> str:
        return {"help": "Up/Down to choose, Enter / A to press.  Esc / B = back.",
                "fix": "Atari checked everything it can.  Esc / B = back.",
                "winform": "Check the details, then choose \"Add this game\".  Esc / B = cancel.",
                "winchoose": "Pick the main program (the biggest .exe is usually it).  Esc / B = cancel.",
                "winwork": "Please wait - big games take a minute.  Esc / B = cancel."}.get(name, "")

    @Slot(str, result="QVariantList")
    def pageRows(self, name: str):
        if name == "help":
            return self._help_rows()
        if name == "fix":
            return self._fix_rows()
        if name == "winform":
            return self._winform_rows()
        if name == "winchoose":
            return self._winchoose_rows()
        if name == "winwork":
            return [{"kind": "info", "title": self._win_text or "Working..."},
                    {"kind": "item", "id": "cancel", "title": "Cancel"}]
        return []

    def _info(self, text: str) -> dict:
        return {"kind": "info", "title": text}

    def _help_rows(self) -> list:
        n_games = self._real_count()
        rows = [self._info(diagnose.controller_text())]
        rows.append(self._info("Getting started - press each step in order (you can skip steps you do not need):"))
        for step in diagnose.checklist(self.cfg, n_games > 0):
            done = step["done"] and not (step["id"] == "covers")
            rows.append({"kind": "item", "id": "ck_" + step["id"], "title": step["title"],
                         "value": "Done" if done else "", "tone": "ok" if done else "",
                         "detail": step["detail"]})
        rows += [
            {"kind": "item", "id": "winadd", "title": "Add a Windows game (.exe or .zip)",
             "detail": "For PC games you downloaded yourself. Runs through Proton / Wine."},
            {"kind": "item", "id": "controls", "title": "Controls (keyboard keys)",
             "detail": "Which keys to press inside each emulator."},
            self._info("Q: Make music?  A: Options > Studio (or the Studio tile). Make a beat, record your voice over it, then mix and save a WAV or MP3 "
                       "in ~/Music/Atari Studio. Use headphones when you record."),
            self._info("Q: Netflix, YouTube, Instagram...?  A: open the Streaming tile (Systems row). Each opens in its own browser window - "
                       "sign in once per app (it remembers you). You may need a mouse or touch screen inside web pages; "
                       "AntiMicroX can make a controller act as a mouse. Netflix, Prime and Disney+ stream at about 720p on Linux."),
            self._info("Q: Fortnite / Call of Duty / Warzone?  A: they do not work on Linux - their anti-cheat blocks it and the makers do not support it. "
                       "The Free Games tile lists free games that do work (checked on ProtonDB). Minecraft Java: Prism Launcher in PC Apps (needs your own licence)."),
            self._info("Q: A game does not start.  A: highlight it, press the Options button (F10 / Start), choose \"Fix my game\"."),
            self._info("Q: The game has no picture.  A: step 4 above downloads covers (needs internet). Names must look like the real game title."),
            self._info("Q: A console says it needs a BIOS.  A: those are files from your own console. Atari cannot download them - use step 3 with a USB stick or folder."),
            self._info("Q: Where are my games?  A: ~/Games/Atari/<console>/ . Your favourites and play time are kept when you update Atari."),
            self._info("Q: How do I quit a game?  A: use the emulator's own exit (see Controls). Atari comes back by itself."),
            {"kind": "item", "id": "copylog", "title": "Copy log (to send to someone who is helping you)",
             "detail": "Copies Atari's recent messages and your setup to the clipboard. It contains no passwords."},
            {"kind": "item", "id": "reset",
             "title": "Press again to reset my settings" if self._reset_armed else "Safe mode: reset my settings",
             "detail": "Puts Atari's settings back to normal if something looks wrong. Your games, favourites and "
                       "play time are kept, and the old settings are saved next to the new ones."},
            {"kind": "item", "id": "back", "title": "Back"},
        ]
        return rows

    def _fix_game(self):
        return next((g for g in self._all if g.gid == self._fix_gid), None)

    def _fix_rows(self) -> list:
        g = self._fix_game()
        if g is None:
            return [self._info("Highlight a game first, then open Options > Fix my game."),
                    {"kind": "item", "id": "back", "title": "Back"}]
        checks = diagnose.check_game(self.cfg, g)
        rows = [self._info(g.title + " - " + diagnose.summary(checks))]
        for c in checks:
            tone = {"ok": "ok", "bad": "bad", "note": "warn"}[c["state"]]
            rows.append({"kind": "item", "id": "noop", "title": c["title"], "tone": tone,
                         "value": {"ok": "OK", "bad": "Fix needed", "note": "Note"}[c["state"]],
                         "detail": c["advice"]})
        if any(c["state"] == "bad" for c in checks):
            rows.append({"kind": "item", "id": "emus", "title": "Install emulators and apps",
                         "detail": "Opens a window that installs what is missing (needs internet)."})
        if g.platform != "steam" and not g.launch and g.platform not in apps.NON_GAME:
            rows.append({"kind": "item", "id": "bios", "title": "Add BIOS files",
                         "detail": "From your own console, via USB stick or folder."})
        rows.append({"kind": "item", "id": "copylog", "title": "Copy log"})
        if g.platform == windows.PLATFORM:
            rows.append({"kind": "item", "id": "remove",
                         "title": "Press again to remove this game from Atari" if self._remove_armed
                         else "Remove this game from Atari",
                         "detail": "Only Atari's entry goes - the game's files stay on your disk."})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    @Slot(int, result=bool)
    def openFix(self, row: int) -> bool:
        g = self.model.game_at(row)
        self._fix_gid = g.gid if g else ""
        self._remove_armed = False
        return g is not None

    @Slot(result=str)
    def controllerText(self) -> str:
        return diagnose.controller_text()

    @Slot(result=str)
    def copyLog(self) -> str:
        lines = []
        try:
            lines = Path(paths.log_file()).read_text(errors="replace").splitlines()[-150:]
        except OSError:
            pass
        head = [f"Atari {__version__}  python {sys.version.split()[0]}  {os.environ.get('XDG_CURRENT_DESKTOP', '')}",
                diagnose.controller_text(), ""]
        text = "\n".join(head + (lines or ["(the log is empty)"]))
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
        self.show_toast("Copied Atari's log to the clipboard - paste it into a message to whoever is helping you.", 7000)
        return text

    @Slot(result=str)
    def resetSettings(self) -> str:
        """Safe mode: settings back to normal. State (favourites, play time) and games stay; the old file is kept."""
        cfgfile = paths.config_file()
        kept = ""
        try:
            if cfgfile.is_file():
                kept = str(cfgfile.with_name(cfgfile.name + ".before-reset-" + time.strftime("%Y%m%d-%H%M%S")))
                cfgfile.replace(kept)
        except OSError as exc:
            self.show_toast(f"Could not reset settings: {exc}", 8000)
            return ""
        self.cfg = load_config()
        self.cfg.first_run = False
        self.cfg.fullscreen = True
        try:
            save_config(self.cfg)
        except OSError:
            pass
        for key in ("sort", "show_all_systems"):
            self.store.set_pref(key, {"sort": "az", "show_all_systems": False}[key])
        self._sort, self._show_all = "az", False
        self.rescan(toast=False)
        self.show_toast("Settings are back to normal." + (" Your old settings were saved as " + Path(kept).name + "." if kept else ""), 9000)
        return kept

    @Slot(str, str, result=str)
    def pageActivate(self, name: str, rid: str) -> str:
        """Press a row. Returns what the screen should do next: '' | refresh | back | close | page:X | browse:X | osk:winname | import:games | import:bios | controls | emus"""
        if rid in ("back", "noop"):
            return "back" if rid == "back" else ""
        if name == "help":
            return self._help_activate(rid)
        if name == "fix":
            if rid == "emus":
                self.installEmulators()
                return ""
            if rid == "bios":
                return "import:bios"
            if rid == "copylog":
                self.copyLog()
                return ""
            if rid == "remove":
                if not self._remove_armed:
                    self._remove_armed = True
                    return "refresh"
                self._remove_armed = False
                windows.remove_game(self._fix_gid)
                self.rescan(toast=False)
                self.show_toast("Removed from Atari. The game's files are still on your disk.")
                return "close"
        if name == "winform":
            if rid == "name":
                return "osk:winname"
            if rid == "cover":
                return "browse:wincover"
            if rid == "add":
                return self.winFinish()
        if name == "winchoose" and rid.startswith("c"):
            try:
                self._win_exe = str(self._win_cands[int(rid[1:])].path)
            except (ValueError, IndexError):
                return ""
            return "page:winform"
        if name == "winwork" and rid == "cancel":
            self._win_cancel.set()
            return "back"
        return ""

    def _help_activate(self, rid: str) -> str:
        if rid != "reset":
            self._reset_armed = False
        if rid == "ck_emus":
            self.installEmulators()
            return ""
        if rid == "ck_games":
            return "import:games"
        if rid == "ck_bios":
            return "import:bios"
        if rid == "ck_covers":
            self.show_toast("Looking for covers... (needs internet)", 4000)
            self.startCovers(auto=False)
            return ""
        if rid == "winadd":
            return "browse:winfile"
        if rid == "controls":
            return "controls"
        if rid == "copylog":
            self.copyLog()
            return ""
        if rid == "reset":
            if not self._reset_armed:
                self._reset_armed = True
                return "refresh"
            self._reset_armed = False
            self.resetSettings()
            return "refresh"
        return ""

    # ----- Windows games ------------------------------------------------------------
    @Slot(result=str)
    def winBrowseStart(self) -> str:
        dl = Path.home() / "Downloads"
        return str(dl if dl.is_dir() else Path.home())

    @Slot(str, str, result="QVariantMap")
    def listFiles(self, path: str, kind: str):
        """Like listDir, plus the files of one kind: 'exe' (programs and archives) or 'image'."""
        data = dict(self.listDir(path))
        exts = {"exe": (".exe",) + windows.ARCHIVE_EXT, "image": windows.IMAGE_EXT}.get(kind, ())
        files = []
        if path and exts:
            try:
                for child in sorted(Path(path).iterdir(), key=lambda c: c.name.lower()):
                    if (not child.name.startswith(".") and child.name.lower().endswith(exts) and child.is_file()):
                        files.append({"name": child.name, "path": str(child)})
            except OSError:
                pass
        data["files"] = files
        return data

    def _win_reset(self) -> None:
        self._win_exe = ""
        self._win_name = ""
        self._win_cover = ""
        self._win_cands = []
        self._win_text = ""

    @Slot(str, result=str)
    def winPicked(self, path: str) -> str:
        """The user chose a file. Returns the page to show next."""
        p = Path(path)
        self._win_reset()
        if windows.is_archive(p):
            self._win_name = windows.clean_name(p.name)
            self._win_text = "Opening " + p.name + " ..."
            self._win_cancel = threading.Event()
            dest = windows.unique_dir(windows.games_dir() / windows.clean_name(p.name))
            cancel = self._win_cancel

            def worker():
                try:
                    def prog(done, total):
                        self.winEvent.emit("progress", f"Opening {p.name}: {done} of {total} files" if total
                                           else f"Opening {p.name} ...", None)
                    windows.extract_archive(p, dest, prog, cancel)
                    cands = windows.find_exes(dest)
                    self.winEvent.emit("done", str(dest), cands)
                except windows.WinError as exc:
                    self.winEvent.emit("error", str(exc), None)
                except Exception as exc:  # pragma: no cover - safety net
                    self.winEvent.emit("error", f"Could not open that file: {exc}", None)

            threading.Thread(target=worker, daemon=True).start()
            return "winwork"
        if p.name.lower().endswith(".exe") and p.is_file():
            self._win_exe = str(p)
            stem = windows.clean_name(p.name)
            generic = {"game", "launcher", "start", "main", "play", "app", "run", "windows windowed"}
            self._win_name = p.parent.name if stem.lower() in generic and p.parent.name else stem
            return "winform"
        self.show_toast("Choose a .exe file, or a .zip / .7z that has one inside.")
        return ""

    @Slot(str, str, object)
    def _on_win_event(self, kind: str, text: str, payload) -> None:
        if kind == "progress":
            self._win_text = text
            self.pageChanged.emit()
            return
        if kind == "error":
            self.show_toast(text, 9000)
            self.pageRequested.emit("close")
            return
        if self._win_cancel.is_set():
            self.pageRequested.emit("close")
            return
        cands = payload or []
        self._win_cands = cands
        if not cands:
            self.show_toast("Atari could not find a Windows program (.exe) inside that archive. "
                            "Files were opened in " + text, 10000)
            self.pageRequested.emit("close")
        elif len(cands) == 1:
            self._win_exe = str(cands[0].path)
            self.pageRequested.emit("winform")
        else:
            self.pageRequested.emit("winchoose")

    def _winchoose_rows(self) -> list:
        rows = []
        for i, c in enumerate(self._win_cands[:30]):
            mb = c.size / (1024 * 1024)
            rows.append({"kind": "item", "id": f"c{i}", "title": c.rel,
                         "detail": (f"{mb:.0f} MB" if mb >= 1 else f"{c.size // 1024} KB")
                                   + ("  - most likely the game" if i == 0 else "")})
        rows.append({"kind": "item", "id": "back", "title": "Cancel"})
        return rows

    def _winform_rows(self) -> list:
        ok, label = windows.runner_status(self.cfg)
        return [
            self._info("Atari runs Windows games with " + (label if ok else "a helper that is not installed yet") + "."
                       + ("" if ok else "  " + windows.UMU_HINT)),
            self._info("Program: " + self._win_exe),
            {"kind": "item", "id": "name", "title": "Name", "value": self._win_name or "(none)",
             "detail": "Press Enter to change the name."},
            {"kind": "item", "id": "cover", "title": "Cover picture (optional)",
             "value": Path(self._win_cover).name if self._win_cover else "None",
             "detail": "A .png or .jpg. Skip it for now if you do not have one."},
            {"kind": "done", "id": "add", "title": "Add this game"},
            {"kind": "item", "id": "back", "title": "Cancel"},
        ]

    @Slot(result=str)
    def winName(self) -> str:
        return self._win_name

    @Slot(str)
    def winSetName(self, text: str) -> None:
        self._win_name = text.strip()
        self.pageChanged.emit()

    @Slot(str, result=str)
    def winPickedCover(self, path: str) -> str:
        self._win_cover = path
        return "winform"

    @Slot(result=str)
    def winFinish(self) -> str:
        if not self._win_exe or not Path(self._win_exe).is_file():
            self.show_toast("That program is missing. Choose the game again.", 7000)
            return "close"
        name = self._win_name.strip() or "Windows game"
        windows.add_game(name, self._win_exe, self._win_cover)
        self._win_reset()
        self.rescan(toast=False)
        self._filter = windows.PLATFORM
        self.currentFilterChanged.emit()
        self._apply()
        ok, label = windows.runner_status(self.cfg)
        self.show_toast(f"Added {name} to Windows / PC." + ("" if ok else "  " + windows.UMU_HINT), 10000)
        return "close"

    @Slot(result=str)
    def homeDir(self) -> str:
        return str(Path.home())
