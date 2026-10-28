"""The bridge between Python (data, launching) and the QML user interface."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent

from . import emulators, importer, launcher, paths, roms
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
            self.show_toast(f"Library updated: {len(self._all)} game" + ("" if len(self._all) == 1 else "s"))

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
        if not self._all:
            if self._demo:
                return "Demo mode"
            return ("No games yet!\n\nChoose \"Add Games\" to copy games from a USB stick, or open Settings "
                    "to add your Steam library and ROM folders.\n\n" + NTFS_NOTE)
        if self._filter == "favorites":
            return "No favourites yet.\n\nHighlight a game and press X (gamepad) or F (keyboard)."
        if self._filter == "recent":
            return "Nothing played yet.\n\nGames you play will show up here."
        if self._filter == STEAM:
            return self._lib.steam_note or "No Steam games found."
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
        self.show_toast(("Added to favourites: " if now else "Removed from favourites: ") + g.title, 2500)

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

    # ----- emulators page --------------------------------------------------
    @Slot(result="QVariantList")
    def emulatorRows(self):
        rows = [{"kind": "info", "title": "Emulators are separate programs. Atari finds them automatically "
                                          "(installed programs and Flatpaks).", "value": "", "detail": ""},
                {"kind": "info", "title": "Press Enter on a console to switch between its emulators. "
                                          "Atari never includes BIOS, firmware, keys or games - bring your own.",
                 "value": "", "detail": ""}]
        counts = {}
        for g in self._all:
            counts[g.platform] = counts.get(g.platform, 0) + 1
        order = sorted(self.cfg.systems.values(), key=lambda sc: -1 if counts.get(sc.id) else 0)
        for sc in order:
            ready, label, hint = emulators.status_line(self.cfg, sc)
            n = counts.get(sc.id, 0)
            games = f"{n} game{'s' if n != 1 else ''}  \u00b7  " if n else ""
            rows.append({"kind": "emu", "id": sc.id, "title": sc.name,
                         "value": "Ready" if ready else "Not installed",
                         "detail": games + (label if ready else (label + ": " + hint))
                                   + (f"   [{hint}]" if ready and hint else "")})
        for name, text in emulators.NOTES:
            rows.append({"kind": "info", "title": f"{name}: {text}", "value": "", "detail": ""})
        rows.append({"kind": "back", "title": "Back to Settings", "value": "",
                     "detail": "To use your own program or Flatpak, edit [emulators] in " + self.configPath})
        return rows

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

    @Slot()
    def openImport(self) -> None:
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
        self._imp_msg = "Looking for games on " + path + " ..."
        self._imp_cancel = threading.Event()
        self.importChanged.emit()
        cancel, cfg = self._imp_cancel, self.cfg

        def worker():
            try:
                res = importer.scan_for_roms(path, cfg, cancel)
            except Exception as exc:  # pragma: no cover - safety net
                res = importer.ScanResult()
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
        self._imp_msg = f"Copying {len(items)} game{'s' if len(items) != 1 else ''}..."
        self._imp_cancel = threading.Event()
        self.importChanged.emit()
        self.importProgressChanged.emit()
        cancel, cfg = self._imp_cancel, self.cfg
        last = [0.0]

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
        self.openImport()

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
        rows.append({"kind": "emulators", "title": "Emulators", "value": "",
                        "detail": "See which emulators are installed, and how to install the missing ones."})
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

    @Slot(result=str)
    def homeDir(self) -> str:
        return str(Path.home())
