"""The bridge between Python (data, launching) and the QML user interface."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import dataclasses
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QProcess, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QWindow

from . import brightness, worldgames, bootscreen, create, steam, simtycoon, themes, biosfind, findgames, bluetooth, padbattery, pads, screentv, xemuconfig, branding, donate, gamedelete, gamesroot, power, rootauth, files, steamfix, downloads, golive, icons, inputfix, intro, kiosk, quietboot, sober, studio_fix, appinstall, apps, bios, controls, covers, diagnose, recorder, emulators, exitwatch, freegames, importer, installer, launcher, paths, roms, updater, webapps, windows
from . import __version__
from .config import Config, load_config, save_config
from .import_model import ImportModel
from .library import STEAM, Game, LibraryResult, build_library, demo_library
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


def _intro_log(msg: str) -> None:
    launcher._log(msg)


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
    deleteFinished = Signal(object)   # gamedelete.Result (from the worker thread)
    importUnpacked = Signal(object)   # a BIOS pack that could not be opened (files.Extraction, from the worker thread)
    sessionEnded = Signal(str, str, float, str)  # gid, title, seconds, error (from worker thread)
    gamepadNote = Signal(str)
    coversChanged = Signal()
    coverArrived = Signal(str, str, str)   # gid, file, kind (from worker thread)
    coverProgressed = Signal(int, int, int)  # done, total, got
    coversFinished = Signal(object)         # covers.Report
    introChanged = Signal()
    introEnded = Signal(str)               # why the intro ended (from the player thread)
    powerFailed = Signal(str)               # the system refused the restart / shut down
    bootReportDone = Signal(bool, str)      # (saved, text) from the boot-report thread
    quietbootDone = Signal(bool, str)       # (worked, text) from the quiet-boot worker thread
    filesEvent = Signal(str, bool, str)     # (kind, ok, text) from the file viewer's worker: progress | done
    inputRequested = Signal()               # a worker thread queued a text / password request -> GUI thread shows it
    inputChanged = Signal()
    launchStatus = Signal(str, str)         # (phase, text) from the Steam launch worker -> queued to the GUI thread
    runningStatusChanged = Signal()
    kioskDone = Signal(bool, str)           # (worked, text) from the CodeAque-only mode worker thread
    inputFixDone = Signal(bool, str)        # (worked, text) from the permissions-fix thread
    iconArrived = Signal(str, str, bool)    # gid, file, fit (from the icon worker thread)
    iconsDone = Signal()
    sessionStarted = Signal()               # the emulator process is up (from worker thread)
    runningHintChanged = Signal()
    recChanged = Signal()
    hotkeyPressed = Signal()
    pickEvent = Signal(str, object)             # cover picker worker -> UI (kind, payload)
    installEvent = Signal(str, str)             # kind (step | line | done), text - from the install worker thread
    updateChanged = Signal()
    updateEvent = Signal(str, str, float)       # state, text, fraction (from the worker thread)
    updateChecked = Signal(object, str, bool)   # release or None, error text, was it asked for by the user
    uiPrefsChanged = Signal()
    robloxFixDone = Signal(object, str)         # (steps, verdict) from the Roblox fix thread
    pageChanged = Signal()                      # the rows of the help / fix / Windows pages changed
    padBatteriesChanged = Signal()
    brightnessChanged = Signal()                # the brightness % in the top bar / Settings changed
    themeChanged = Signal()              # the battery pills in the top bar
    _raiseMe = Signal()                         # a background job wants CodeAque back in front (GUI thread)
    _bgDone = Signal()                          # a background job (Bluetooth, batteries) finished: refresh on the GUI thread
    _batteryRead = Signal("QVariantList")
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
        self._imp_tmp: Path | None = None  # where a BIOS pack was unpacked (deleted when the import is over)
        self._imp_pack = ""                # the BIOS pack's file name, when the files come from one
        self._imp_kind = "games"          # "games" | "bios" - the same USB picker serves both
        self._imp_done_items: list = []
        self._imp_left: list = []          # files whose console is still unknown ("Which system is this?")
        self._imp_groups: list = []
        self._imp_group: list = []
        self._imp_seen = ""
        self._imp_truncated = False
        self._imp_failed_scan = False
        self._imp_nfiles = 0
        self._add_result = ""             # what the last Add Games run did, shown on the wizard page
        self.importScanned.connect(self._on_import_scanned, Qt.QueuedConnection)
        self.inputFixDone.connect(self._input_fix_finished, Qt.QueuedConnection)
        self.robloxFixDone.connect(self._roblox_fix_finished, Qt.QueuedConnection)
        self._rbx_state, self._rbx_steps, self._rbx_verdict = "idle", [], ""
        self._input_fixing = False
        self.kioskDone.connect(self._kiosk_finished, Qt.QueuedConnection)
        self.launchStatus.connect(self._on_launch_status, Qt.QueuedConnection)
        self.inputRequested.connect(self._input_next, Qt.QueuedConnection)
        self.filesEvent.connect(self._files_event, Qt.QueuedConnection)
        if not os.environ.get("ATARI_NO_ROOTAUTH"):
            rootauth.set_provider(lambda prompt, error: self.ask_text_blocking("ADMINISTRATOR PASSWORD", prompt, True, "", error))
        self._kiosk_busy = False
        self._kiosk_msg = ""
        self._xm_msg = ""
        self._ct_msg = ""
        self._ct_seen = -100.0
        self._pad_events: list[str] = []          # newest first: what the Controllers page shows while testing
        self._pad_test_until = 0.0
        self._sdl_pads: list[str] = []            # pads the gamepad reader (SDL) recognised as standard controllers
        self._pad_timer = QTimer(self, interval=1000)
        self._pad_timer.timeout.connect(self._pad_tick)
        self._sm_changed = ""            # "desktop" / "console" after a successful switch on the Start mode page (shows the log-out / restart prompt)
        self._kiosk_layout = kiosk.DEFAULT
        self.quietbootDone.connect(self._quietboot_finished, Qt.QueuedConnection)
        self.bootReportDone.connect(self._boot_report_finished, Qt.QueuedConnection)
        self.powerFailed.connect(self._on_power_failed, Qt.QueuedConnection)
        self._fm_dir: Path | None = None        # file viewer: the folder being shown (None = the list of places)
        self._fm_items: list = []
        self._fm_places: list = []                # files.Place list behind the "fmroot:<n>" rows of the place list
        self._fm_pick: Path | None = None       # the file / folder the actions page is about
        self._fm_msg = ""
        self._fm_ok = True
        self._fm_busy = ""                      # what the worker is doing ("" = nothing)
        self._fm_prog = None                    # files.Progress of the unpack in the background (None = nothing yet)
        self._fm_progress = ""
        self._fm_tool = ""                      # app id CodeAque can install so the pick can be unpacked
        self._fm_cancel = threading.Event()
        self._fm_pending_delete = False
        self._dl_from_files = False
        self._input_queue: list = []        # pending text / password requests: [title, prompt, secret, initial, error, callback]
        self._input_cur: list | None = None
        self._steam_busy = False
        self._run_status = ""
        self._run_cancelable = False
        self._launch_cancel = threading.Event()
        self._steam_run = subprocess.run
        self._running_gid = ""
        self._power_pending = ""            # "reboot" / "poweroff" while the Yes / No question is on the screen
        self._power_run = power.run
        self._qb_busy = False
        self._qb_msg = ""
        self._qb_ok = True
        self._qb_report_msg = ""
        self._qb_report_busy = False
        self._qb_layout = quietboot.DEFAULT
        self.importProgressed.connect(self._on_import_progress, Qt.QueuedConnection)
        self.importUnpacked.connect(self._on_import_unpacked, Qt.QueuedConnection)
        self.deleteFinished.connect(self._on_delete_finished, Qt.QueuedConnection)
        self._del_plan = None
        self._del_saves = False
        self._del_cover = False
        self._del_busy = False
        self._del_result = None
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
        self._running_appid = ""
        self._run_playing = False
        self._minimized_for_game = False
        # screen recorder + cover picker
        self._rec = recorder.Recorder()
        self._rec_env = None                 # tests can put a dict of env vars / stubs here
        self._rec_timer = QTimer(self, interval=1000)
        self._rec_timer.timeout.connect(self.recChanged.emit)
        self._hotkey = None
        self.hotkeyPressed.connect(self.toggleRecording, Qt.QueuedConnection)
        self._pick_gid = ""
        self._pick_title = ""
        self._pick_state = "idle"            # idle | searching | ready | saving
        self._pick_cands: list[dict] = []
        self._pick_dir = None
        self._pick_msg = ""
        self.pickEvent.connect(self._on_pick_event, Qt.QueuedConnection)
        # one-press installs (appinstall.py)
        self._inst_job = None
        self._inst_env = None                # tests put a stubbed appinstall.Env here
        self._inst_state = "idle"            # idle | ask | running | done
        self._inst_specs: list[str] = []     # "id" or "id|core" items
        self._inst_titles: dict[str, str] = {}
        self._inst_what = ""
        self._inst_step = ""
        self._inst_lines: list[str] = []
        self._inst_summary = ""
        self._inst_ok = False
        self._inst_for_gid = ""
        self.installEvent.connect(self._on_install_event, Qt.QueuedConnection)
        # covers (background download)
        self._cover_busy = False
        self._cover_text = ""
        self._cover_cancel = threading.Event()
        self._cover_rerun = False
        self._cover_by_gid: dict[str, object] = {}
        self.coverArrived.connect(self._on_cover_arrived, Qt.QueuedConnection)
        self.iconArrived.connect(self._on_icon_arrived, Qt.QueuedConnection)
        self.iconsDone.connect(self._icons_finished, Qt.QueuedConnection)
        self._icon_busy = False
        self.coverProgressed.connect(self._on_cover_progress, Qt.QueuedConnection)
        self.coversFinished.connect(self._on_covers_finished, Qt.QueuedConnection)
        self._cover_timer = QTimer(self, singleShot=True, interval=2500)
        self._cover_timer.timeout.connect(lambda: (self.startCovers(auto=True), self.startIcons()))
        # sounds (a helper process plays them) and animations
        self._snd_proc = None
        self._snd_dead = False
        self._studio = None
        self._wifi = None
        self._media = None
        self._sound_sink = None          # tests put a function here to see the commands instead of playing them
        self._last_tick = 0.0
        self._start_timer = QTimer(self, singleShot=True, interval=700)
        self._start_timer.timeout.connect(lambda: self.playSound("start"))
        # start-up intro (your own video, or CodeAque's own short animation)
        self._intro_plan = intro.Plan() if self._demo else intro.plan(self.cfg)
        self._intro_mode = self._intro_plan.mode
        self._intro_play = None
        self._intro_timer = QTimer(self, singleShot=True)
        self._intro_timer.timeout.connect(lambda: self._end_intro("finished"))
        self.introEnded.connect(self._end_intro, Qt.QueuedConnection)
        self._intro_active = bool(self._intro_mode)
        self._intro_skip_early = False
        if not self._demo and not self._intro_mode:      # with an intro, its own sound replaces the start chime
            self._start_timer.start()
            if self.cfg.music:
                QTimer.singleShot(1200, self._sync_music)
        if not self._demo and not os.environ.get("ATARI_NO_WIFI"):
            QTimer.singleShot(2500, self._wifi_poll)         # the WiFi name next to the clock
        if not self._demo:
            kiosk.log_event("started - " + kiosk.running_description()[1] + f" (pid {os.getpid()}, DESKTOP_SESSION={os.environ.get('DESKTOP_SESSION', '')})")
        if not self._demo and not os.environ.get("ATARI_NO_BRANDFIX"):
            try:
                changed = branding.refresh()
                if changed:
                    kiosk.log_event("branding: refreshed " + ", ".join(changed))
            except Exception as exc:  # pragma: no cover
                print(f"[atari] branding refresh failed: {exc}")
        if not self._demo and self._lib.unknown and not self._first_run:
            QTimer.singleShot(4500, lambda: self.show_toast(
                gamesroot.hint_text(self.cfg, self._lib.unknown[0])
                + ("  (more in Settings)" if len(self._lib.unknown) > 1 else "  (see Settings)"), 14000))
        if not self._demo and kiosk.session_outdated(self._kiosk_layout):
            QTimer.singleShot(7000, lambda: self.show_toast("CodeAque-only mode needs a one-time update so CodeAque never drops to the desktop: "
                                                            "Settings > \"Update CodeAque-only mode\".", 15000))
        if not self._demo and not os.environ.get("ATARI_NO_STEAMFIX") and self._shell_mode():
            self._start_steam_guard()
        if not self._demo and not os.environ.get("ATARI_NO_MEDIA"):
            QTimer.singleShot(3000, self._media_poll)        # the music control in the top bar
        # pages (help / fix my game / add Windows game)
        self._fix_gid = ""
        self._dl_items = []
        self._dl_pick = None
        self._dl_msg = ""
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
        # Bluetooth pairing, controller batteries, Screen to TV
        self._win_busy = False
        self._win_msg = ""
        self._bf_busy = ""
        self._bf_res = None
        self._bf_msg = ""
        self._fg_busy = ""
        self._fg_res = None
        self._fg_msg = ""
        self._fg_move = False
        self._bt_busy = ""
        self._bt_msg = ""
        self._bt_found: list = []
        self._bt_searched = False
        self._seen_pages: dict[str, float] = {}
        self._bgDone.connect(self._on_bg_done, Qt.QueuedConnection)
        self._raiseMe.connect(self._raise_window_if_idle, Qt.QueuedConnection)
        self._batteryRead.connect(self._on_battery_read, Qt.QueuedConnection)
        self._pad_batt: list = []
        self._batt_low_warned: set = set()
        self._batt_busy = False
        self._br_level, self._br_how, self._br_msg, self._br_busy = -1, "", "", ""
        self._br_lock = threading.Lock()
        if not demo and not os.environ.get("ATARI_NO_BRIGHTNESS"):
            threading.Thread(target=self._br_read, daemon=True, name="atari-brightread").start()
        self._batt_timer = QTimer(self, interval=20000)
        self._batt_timer.timeout.connect(self.refreshBatteries)
        if not os.environ.get("ATARI_NO_BATTERY") and not demo:
            self._batt_timer.start()
            QTimer.singleShot(1500, self.refreshBatteries)
        if not demo and not os.environ.get("ATARI_NO_STEAM_AUTOSTART"):
            QTimer.singleShot(3500, self._steam_autostart)
        self._tv_msg = ""
        self._tv_undo: list = []
        self._tv_until = 0.0
        self._tv_timer = QTimer(self, interval=1000)
        self._tv_timer.timeout.connect(self._tv_tick)
        if enable_gamepad:
            self._start_gamepad()
            self._start_hotkey()

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
        if self._intro_active:
            QTimer.singleShot(0, self._intro_begin)

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

    def stop_all_helpers(self) -> None:
        self.stop_intro()
        self.stop_recording()
        self.stop_hotkey()

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
            if line == "record":                       # gamepad Guide + X
                self.hotkeyPressed.emit()
                continue
            if line == "quitapp":                       # gamepad Guide + B: close the web app / Kodi that is running
                if exitwatch.request_quit("gamepad"):
                    self.show_toast("Closing the app...", 2000)
                continue
            if line.startswith("#"):
                self._pad_info_line(line)
            elif time.monotonic() >= self._pad_test_until:       # while testing buttons, the pad does not move the menu
                self.send_action(line)

    # ----- Controllers page: live button readout ----------------------------------------------
    BUTTON_WORDS = {"a": "A", "b": "B", "x": "X", "y": "Y", "start": "Start / Menu", "back": "Back / View / Select", "guide": "Guide / Home",
                    "leftshoulder": "Left bumper (LB)", "rightshoulder": "Right bumper (RB)", "leftstick": "Left stick pressed in",
                    "rightstick": "Right stick pressed in", "dpad_up": "D-pad up", "dpad_down": "D-pad down", "dpad_left": "D-pad left",
                    "dpad_right": "D-pad right", "misc1": "Extra button (share / capture)", "touchpad": "Touchpad press"}
    AXIS_WORDS = {"leftx": "Left stick", "lefty": "Left stick", "rightx": "Right stick", "righty": "Right stick",
                  "triggerleft": "Left trigger (LT)", "triggerright": "Right trigger (RT)"}

    def _pad_info_line(self, line: str) -> None:
        """'#...' lines from the gamepad reader: pads coming and going, and (for the Controllers page) every button and stick movement."""
        if line.startswith("#pad "):
            name = line[5:]
            if name not in self._sdl_pads:
                self._sdl_pads.append(name)
            self.show_toast("Controller connected: " + name)
            self._pad_page_changed()
        elif line.startswith("#pad-removed"):
            if self._sdl_pads:
                self._sdl_pads.pop()
            self._pad_page_changed()
        elif line.startswith("#btn "):
            name = line[5:].strip()
            self._pad_event(self.BUTTON_WORDS.get(name, "Button " + name) + " pressed")
        elif line.startswith("#axis "):
            parts = line.split()
            if len(parts) >= 3:
                self._pad_event(f"{self.AXIS_WORDS.get(parts[1], parts[1])} {parts[2]}")

    def _pad_event(self, text: str) -> None:
        if not self._ct_page_visible():
            return                                             # nobody is on the Controllers page
        self._pad_events.insert(0, text)
        del self._pad_events[8:]
        self._pad_page_changed()

    def _pad_page_changed(self) -> None:
        if self._ct_page_visible():
            self.pageChanged.emit()

    def _ct_page_visible(self) -> bool:
        """The Controllers page asks for its rows every time it draws; it counts as open for a few seconds after the last time."""
        return time.monotonic() - self._ct_seen < 2.5

    def _pad_tick(self) -> None:
        if time.monotonic() >= self._pad_test_until:
            self._pad_timer.stop()
        self._pad_page_changed()

    @property
    def pad_testing(self) -> bool:
        return time.monotonic() < self._pad_test_until

    def send_action(self, action: str) -> None:
        """Turn a gamepad action into a key press for the UI (only while CodeAque has focus)."""
        key = ACTION_KEYS.get(action)
        win = self._window
        if self._intro_active and action != "none":      # any controller button skips the intro (the player has the focus)
            self.skipIntro()
            return
        if key is None or win is None or self._running:
            return
        if QGuiApplication.applicationState() != Qt.ApplicationActive and not os.environ.get("ATARI_TEST_INPUT"):
            return
        for kind in (QKeyEvent.KeyPress, QKeyEvent.KeyRelease):
            QGuiApplication.postEvent(win, QKeyEvent(kind, key, Qt.NoModifier))

    # ----- screen recorder -------------------------------------------------------------
    def _start_hotkey(self) -> None:
        """F9 works everywhere (also while a game has the focus) - the same no-grab watcher method as Esc-to-return."""
        if os.environ.get("ATARI_NO_HOTKEY") or self._hotkey is not None:
            return
        hk = exitwatch.HotkeyWatch(self.hotkeyPressed.emit)
        if hk.available:
            self._hotkey = hk.start()
        else:
            hk.stop()

    def stop_hotkey(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None

    @Property(bool, notify=recChanged)
    def recording(self):
        return self._rec.active

    @Property(str, notify=recChanged)
    def recText(self):
        if not self._rec.active:
            return ""
        s = int(self._rec.elapsed())
        return f"REC {s // 60:02d}:{s % 60:02d}"

    @Slot()
    def toggleRecording(self) -> None:
        if self._rec.active:
            path = self._rec.stop()
            self._rec_timer.stop()
            self.recChanged.emit()
            msg = f"Recording saved: {path.name}  (Tools > Recordings)" if path else "The recording could not be saved."
            self.playSound("select" if path else "error")
            self.show_toast(msg, 8000)
            exitwatch.notify(msg)
            return
        if self._demo:
            self.show_toast("Demo mode: nothing to record.")
            return
        env = self._rec_env or {}
        reason = recorder.why_not(self.cfg, env.get("env"), env.get("which", shutil.which))
        if reason and "ffmpeg is not installed" in reason:
            self.begin_install(["ffmpeg"], what="FFmpeg (the screen recorder)")
            return
        path = self._rec.start(self.cfg, size=env.get("size"), env=env.get("env"), which=env.get("which", shutil.which),
                               run=env.get("run", subprocess.run), sources=env.get("sources"), home=env.get("home"))
        if path is None:
            self.playSound("error")
            self.show_toast(self._rec.error or "Recording did not start.", 10000)
            self.recChanged.emit()
            return
        self._rec_timer.start()
        self.recChanged.emit()
        self.playSound("select")
        exitwatch.notify("Recording started - press F9 to stop")
        self.show_toast("Recording started. Press F9 (or Guide + X) to stop.", 6000)

    def stop_recording(self) -> None:
        if self._rec.active:
            self._rec.stop()
        self._rec_timer.stop()

    @Slot()
    def cycleRecAudio(self) -> None:
        i = recorder.AUDIO_MODES.index(self.cfg.rec_audio) if self.cfg.rec_audio in recorder.AUDIO_MODES else 1
        self.cfg.rec_audio = recorder.AUDIO_MODES[(i + 1) % len(recorder.AUDIO_MODES)]
        self._save_prefs()

    @Slot()
    def cycleRecQuality(self) -> None:
        order = list(recorder.QUALITIES)
        i = order.index(self.cfg.rec_quality) if self.cfg.rec_quality in order else 1
        self.cfg.rec_quality = order[(i + 1) % len(order)]
        self._save_prefs()

    @Slot()
    def toggleRecFps(self) -> None:
        self.cfg.rec_fps = 60 if self.cfg.rec_fps != 60 else 30
        self._save_prefs()

    @Slot(str)
    def setRecDir(self, folder: str) -> None:
        self.cfg.rec_dir = folder
        self._save_prefs()

    def _rec_rows(self) -> list:
        why = recorder.why_not(self.cfg)
        return [
            {"kind": "recnow", "title": "Stop recording" if self._rec.active else "Start recording (F9)",
             "value": "ON" if self._rec.active else ("" if not why else "Needs setup"),
             "detail": why or "Records the whole screen to an MP4. F9 (or Guide + X on a controller) starts and stops it, even inside a game."},
            {"kind": "recaudio", "title": "Recording sound", "value": recorder.AUDIO_LABELS.get(self.cfg.rec_audio, self.cfg.rec_audio),
             "detail": "Press Enter to change: none, game / desktop sound, microphone, or both."},
            {"kind": "recquality", "title": "Recording quality", "value": self.cfg.rec_quality.title(),
             "detail": "Low = small files, medium = good for most, high = sharper (bigger files, more CPU)."},
            {"kind": "recfps", "title": "Recording frame rate", "value": f"{self.cfg.rec_fps} fps",
             "detail": "30 is light on the CPU. 60 is smoother for fast games."},
            {"kind": "recdir", "title": "Recordings folder", "value": "",
             "detail": str(recorder.out_dir(self.cfg)) + "   (press Enter to choose another folder)"},
        ]

    def _recordings_rows(self) -> list:
        recs = recorder.list_recordings(self.cfg)
        rows = [self._info("Pick a recording to watch it (mpv, full screen; press Q or Esc in the player to come back)."
                           if recs else "No recordings yet. Press F9 (or Guide + X) to start one; press it again to stop.")]
        for i, r in enumerate(recs[:40]):
            when = time.strftime("%d %b %Y, %H:%M", time.localtime(r["mtime"]))
            rows.append({"kind": "item", "id": f"rec{i}", "title": r["name"], "value": f"{r['size_mb']:.0f} MB", "detail": when})
        rows.append({"kind": "item", "id": "recfolder", "title": "Open the recordings folder", "detail": str(recorder.out_dir(self.cfg))})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _recordings_activate(self, rid: str) -> str:
        recs = recorder.list_recordings(self.cfg)
        if rid.startswith("rec") and rid[3:].isdigit():
            i = int(rid[3:])
            if i < len(recs):
                cmd = recorder.player_command(recs[i]["path"], self.cfg)
                if not cmd:
                    self.begin_install(["mpv"], what="mpv (the video player)")
                    return ""
                try:
                    subprocess.Popen(cmd, env=launcher.clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError as exc:
                    self.show_toast(f"Could not play it: {exc}", 8000)
        elif rid == "recfolder":
            opener = shutil.which("xdg-open")
            d = recorder.out_dir(self.cfg)
            if opener:
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    subprocess.Popen([opener, str(d)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    pass
            else:
                self.show_toast(f"Your recordings are in {d}", 8000)
        return ""

    # ----- covers: pick one, list the ones not found ---------------------------------------
    def _cover_downloader(self, http=None):
        base = os.environ.get("ATARI_COVERS_THUMBS_URL") or covers.THUMBS_URL
        steam_base = os.environ.get("ATARI_COVERS_STEAM_URL") or covers.STEAM_URL
        fast = bool(os.environ.get("ATARI_COVERS_FAST"))
        http = http or covers.Http(pause=0.0 if fast else 0.25, backoff=0.01 if fast else 1.0, timeout=5 if fast else 15)
        return covers.CoverDownloader(
            base, steam_base, http=http, force=True,
            wiki_url=os.environ.get("ATARI_COVERS_WIKI_URL") or covers.WIKI_API,
            sgdb_url=os.environ.get("ATARI_COVERS_SGDB_URL") or covers.SGDB_API,
            sgdb_key=self.cfg.steamgriddb_key, wikipedia=self.cfg.cover_wikipedia and not os.environ.get("ATARI_NO_WIKI"))

    def _game_by_gid(self, gid: str):
        return next((g for g in self._all if g.gid == gid), None)

    @Slot(int)
    def openCoverPicker(self, row: int) -> None:
        g = self.model.game_at(row) if row >= 0 else None
        if g is None:
            self.show_toast("Highlight a game first.")
            return
        self.pickCoverFor(g.gid)

    def pickCoverFor(self, gid: str) -> None:
        g = self._game_by_gid(gid)
        job = covers.job_for_game(g) if g is not None else None
        self._pick_gid, self._pick_title = gid, (g.title if g else "")
        self._pick_cands = []
        if job is None:
            self._pick_state = "idle"
            self._pick_msg = ("Covers can be picked for games from your ROM folders and Steam. Windows games and apps use the picture "
                              "chosen when they were added.")
            self.pageChanged.emit()
            return
        if not self._covers_allowed():
            self._pick_state, self._pick_msg = "ready", "Searching online is switched off here. You can still choose a picture file."
            self.pageChanged.emit()
            return
        self._pick_state, self._pick_msg = "searching", "Searching libretro, Wikipedia and (if you set a key) SteamGridDB..."
        import tempfile
        self._pick_dir = Path(tempfile.mkdtemp(prefix="atari-pick-"))

        def worker():
            try:
                dl = self._cover_downloader()
                cands = dl.candidates(job.system, job.stem, job.title, 8)
                self.pickEvent.emit("cands", cands)
                for i, c in enumerate(cands):
                    data = dl.http.get(c["url"], max_bytes=4 * 1024 * 1024)
                    if data and covers.looks_like_image(data):
                        f = self._pick_dir / f"{i}.img"
                        f.write_bytes(data)
                        self.pickEvent.emit("thumb", (i, str(f)))
            except Exception as exc:    # a bad network must never break the screen
                self.pickEvent.emit("error", str(exc))
            self.pickEvent.emit("done", None)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, object)
    def _on_pick_event(self, kind: str, payload) -> None:
        if kind == "cands":
            self._pick_cands = list(payload)
            self._pick_msg = (f"Found {len(self._pick_cands)} picture{'s' if len(self._pick_cands) != 1 else ''} for {self._pick_title}. "
                              "Choose one - or pick a file from a disk / USB stick.") if self._pick_cands else \
                f"Nothing found online for {self._pick_title}. You can choose a picture file from a disk or USB stick."
        elif kind == "thumb":
            i, f = payload
            if i < len(self._pick_cands):
                self._pick_cands[i]["thumb"] = f
        elif kind == "error":
            self._pick_msg = "Could not search right now (" + str(payload)[:80] + "). Check the internet connection."
        elif kind == "done":
            if self._pick_state == "searching":
                self._pick_state = "ready"
        elif kind == "saved":
            self._pick_state = "ready"
            self._pick_msg = payload
        self.pageChanged.emit()

    def _coverpick_rows(self) -> list:
        rows = [self._info(self._pick_msg or "Pick a cover.")]
        for i, c in enumerate(self._pick_cands):
            row = {"kind": "item", "id": f"cand{i}", "title": c["label"][:70], "detail": "Press Enter to use this picture"}
            if c.get("thumb"):
                row["image"] = "file://" + c["thumb"]
            rows.append(row)
        rows.append({"kind": "item", "id": "coverfile", "title": "Choose a picture from this computer or a USB stick",
                     "detail": ".png / .jpg / .webp"})
        if self._pick_state != "searching" and self._pick_gid:
            rows.append({"kind": "item", "id": "coveragain", "title": "Search again"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _coverpick_activate(self, rid: str) -> str:
        if rid.startswith("cand") and rid[4:].isdigit():
            i = int(rid[4:])
            if i < len(self._pick_cands) and self._pick_state != "saving":
                url = self._pick_cands[i]["url"]
                gid = self._pick_gid
                g = self._game_by_gid(gid)
                job = covers.job_for_game(g) if g is not None else None
                if job is None:
                    return ""
                self._pick_state = "saving"
                self._pick_msg = "Saving the picture..."

                def worker():
                    try:
                        data = self._cover_downloader().http.get(url)
                        if not (data and covers.looks_like_image(data)):
                            self.pickEvent.emit("saved", "That picture could not be downloaded. Try another one.")
                            return
                        covers._write_atomic(job.dest, data)
                        self.coverArrived.emit(gid, str(job.dest), job.kind)
                        covers.forget_not_found(gid)
                        self.pickEvent.emit("saved", "Cover saved.")
                    except Exception as exc:
                        self.pickEvent.emit("saved", f"Could not save it: {exc}")

                threading.Thread(target=worker, daemon=True).start()
                return "refresh"
        elif rid == "coverfile":
            return "browse:gamecover"
        elif rid == "coveragain":
            self.pickCoverFor(self._pick_gid)
            return "refresh"
        return ""

    @Slot(result=str)
    def pickGid(self) -> str:
        return self._pick_gid

    @Slot(str, str, result=str)
    def coverFromFile(self, gid: str, path: str) -> str:
        """Use a picture file from the disk / a USB stick as this game's cover."""
        g = self._game_by_gid(gid)
        job = covers.job_for_game(g) if g is not None else None
        if job is None:
            self.show_toast("That game cannot take a picture here.")
            return "back"
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            self.show_toast(f"Could not read that file: {exc}", 8000)
            return "back"
        if len(data) > covers.MAX_IMAGE_BYTES or not covers.looks_like_image(data):
            self.show_toast("Choose a .png, .jpg or .webp picture (under 12 MB).", 8000)
            return "back"
        try:
            covers._write_atomic(job.dest, data)
        except OSError as exc:
            self.show_toast(f"Could not save the cover: {exc}", 8000)
            return "back"
        self._on_cover_arrived(gid, str(job.dest), job.kind)
        covers.forget_not_found(gid)
        self.show_toast(f"Cover set for {g.title}.", 5000)
        return "close"

    def _nocovers_rows(self) -> list:
        nf = [r for r in covers.not_found_list() if self._game_by_gid(r["gid"]) is not None]
        rows = [self._info(f"{len(nf)} game{'s' if len(nf) != 1 else ''} without a cover after the last search. Press one to pick a cover yourself."
                           if nf else "Every game that could get a cover has one (or has not been searched yet).")]
        for i, r in enumerate(nf[:60]):
            rows.append({"kind": "item", "id": f"nc{i}", "title": r.get("title", r["gid"]), "detail": r.get("system", "")})
        rows.append({"kind": "item", "id": "redownload", "title": "Re-download covers (try every game again)",
                     "detail": "Forgets the 'not found' list and searches libretro, Wikipedia (and SteamGridDB with your key) again."})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _nocovers_activate(self, rid: str) -> str:
        if rid == "redownload":
            covers.forget_not_found()
            self.downloadCoversNow() if not self._cover_busy else None
            self.show_toast("Looking for covers again...", 4000)
            return "refresh"
        if rid.startswith("nc") and rid[2:].isdigit():
            nf = [r for r in covers.not_found_list() if self._game_by_gid(r["gid"]) is not None]
            i = int(rid[2:])
            if i < len(nf):
                self.pickCoverFor(nf[i]["gid"])
                return "page:coverpick"
        return ""

    @Slot(str)
    def setSteamGridKey(self, text: str) -> None:
        self.cfg.steamgriddb_key = text.strip()
        self._save_prefs()

    @Slot(result=str)
    def steamGridKey(self) -> str:
        return self.cfg.steamgriddb_key

    # ----- one-press installs ------------------------------------------------------
    def _inst_items(self) -> list:
        items = []
        for spec in self._inst_specs:
            tid, _, core = spec.partition("|")
            t = appinstall.target_for(tid, self._inst_titles.get(tid, ""))
            if t is not None:
                items.append((t, core))
        return items

    def begin_install(self, specs: list[str], for_gid: str = "", what: str = "", titles: dict | None = None) -> None:
        """Show the Install page for these programs ("id" or "id|core"); nothing is installed until the user presses Install."""
        if self._inst_state == "running":
            self.pageRequested.emit("install")
            return
        self._inst_specs = list(specs)
        self._inst_titles = dict(titles or {})
        self._inst_for_gid = for_gid
        items = self._inst_items()
        if not items:
            self.show_toast("CodeAque does not know how to install that. See Help.", 6000)
            return
        self._inst_what = what or (items[0][0].title if len(items) == 1 else f"{len(items)} programs")
        self._inst_state, self._inst_lines, self._inst_summary, self._inst_step, self._inst_ok = "ask", [], "", "", False
        self.pageRequested.emit("install")

    @Slot()
    def installEmulators(self) -> None:
        """Settings > Emulators > Install...: the page that offers 'essentials only' or 'everything'."""
        self.pageRequested.emit("installmenu")

    @Slot()
    def installInTerminal(self) -> None:
        ok, msg = installer.open_in_terminal()
        self.show_toast(msg, 9000)

    def _install_missing(self, ids: list[str]) -> list[str]:
        specs = []
        for i in ids:
            t = appinstall.TARGETS.get(i)
            if t is None:
                continue
            if i == "retroarch":                  # RetroArch is more than the program: every core too
                specs.append("retroarch|" + ",".join(installer.wanted_cores()))
            elif not appinstall.is_installed(t, cfg=self.cfg):
                specs.append(i)
        return specs

    @Slot()
    def installEssentials(self) -> None:
        specs = self._install_missing(list(installer.ESSENTIAL_IDS))
        if not specs:
            self.show_toast("The essentials are already installed.", 5000)
            return
        self.begin_install(specs, what="the essentials")

    @Slot()
    def installAll(self) -> None:
        specs = self._install_missing(appinstall.all_ids())
        if not specs:
            self.show_toast("Everything is already installed.", 5000)
            return
        self.begin_install(specs, what="everything")

    def _install_start(self) -> None:
        if self._inst_state == "running":
            return
        items = self._inst_items()
        if not items:
            return
        self._inst_state, self._inst_lines, self._inst_step, self._inst_summary = "running", [], "Starting...", ""
        self.playSound("select")
        job = appinstall.Job(items, lambda kind, text: self.installEvent.emit(kind, text),
                             self._inst_env or appinstall.Env(), self.cfg)
        self._inst_job = job
        job.start()
        self.pageChanged.emit()

    @Slot(str, str)
    def _on_install_event(self, kind: str, text: str) -> None:
        if kind == "step":
            self._inst_step = text
        elif kind == "line":
            self._inst_lines = (self._inst_lines + [text])[-5:]
        elif kind == "done":
            res = self._inst_job.results if self._inst_job else []
            self._inst_summary = appinstall.summary_text(res)
            self._inst_ok = bool(res) and all(r.status in ("installed", "already") for r in res)
            self._inst_state = "done"
            self._inst_job = None
            if any(r.status == "installed" for r in res):
                self.rescan(toast=False)
            self.playSound("select" if self._inst_ok else "error")
            self.show_toast(self._inst_summary, 9000)
        self.pageChanged.emit()

    def _install_rows(self) -> list:
        st = self._inst_state
        what = self._inst_what or "this"
        if st == "ask":
            t = [x for x, _c in self._inst_items()]
            many = len(t) > 1
            how = ("CodeAque downloads it for your user only (Flathub, official sites). CodeAque may ask for your password on this screen for a few of them."
                   if many else "CodeAque downloads it for you (Flathub, or your system's software list - then CodeAque asks for your password on this screen).")
            rows = [self._info(f"{what[:1].upper() + what[1:]} {'are' if many else 'is'} not installed yet. {how} Needs internet."
                               + (f"  {len(t)} programs: this can take 20 minutes or more." if len(t) > 6 else ""))]
            for x in t[:6]:
                rows.append(self._info("  - " + x.title))
            if len(t) > 6:
                rows.append(self._info(f"  ... and {len(t) - 6} more"))
            rows.append({"kind": "done", "id": "install", "title": "Install now"})
            rows.append({"kind": "item", "id": "back", "title": "Not now"})
            return rows
        if st == "running":
            rows = [self._info("Installing - " + (self._inst_step or "starting...") + "   (you can leave this screen; it keeps going)")]
            for ln in self._inst_lines:
                rows.append(self._info(ln))
            rows.append({"kind": "item", "id": "cancel", "title": "Stop"})
            rows.append({"kind": "item", "id": "back", "title": "Hide this screen"})
            return rows
        rows = [self._info(self._inst_summary or "Done.")]
        g = next((x for x in self._all if x.gid == self._inst_for_gid), None) if self._inst_for_gid else None
        if self._inst_ok and g is not None and not g.missing:
            rows.append({"kind": "done", "id": "launch", "title": f"Open {g.title} now"})
        if not self._inst_ok and self._inst_specs:
            rows.append({"kind": "item", "id": "retry", "title": "Try again"})
            rows.append({"kind": "item", "id": "copylog", "title": "Copy log (to send to someone who is helping you)"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _installmenu_rows(self) -> list:
        return [
            self._info("Choose what to install. CodeAque only installs what is missing, for your user only, and never downloads games, BIOS files or keys. "
                       "You can run it again at any time."),
            {"kind": "item", "id": "inst_essentials", "title": "Install essentials only",
             "detail": "RetroArch with all its cores (PlayStation 1, Genesis, SNES ...), PCSX2, Dolphin, PPSSPP, melonDS, mGBA, Flycast. Quicker (about 10 minutes)."},
            {"kind": "item", "id": "inst_all", "title": "Install everything",
             "detail": "Every emulator and app CodeAque can start (about 38 programs, several GB, 20+ minutes). Fine to leave running."},
            {"kind": "item", "id": "inst_terminal", "title": "Open it in a terminal instead",
             "detail": "Same installer with a text window (atari-install-everything --essentials / --all)."},
            {"kind": "item", "id": "back", "title": "Back"},
        ]

    # ----- Steam: install, rescan, where to keep games ----------------------------------
    def steam_installed(self) -> bool:
        from . import steam as steam_mod
        return steam_mod.find_steam_root(None, self.cfg.steam_root) is not None or \
            appinstall.is_installed(appinstall.TARGETS["steam"], cfg=self.cfg)

    @Slot()
    def rescanSteam(self) -> None:
        self.rescan(toast=False)
        n = len([g for g in self._all if g.platform == STEAM])
        self.show_toast(f"Steam rescanned: {n} game" + ("" if n == 1 else "s") + " found."
                        if self.steam_installed() else "Steam is not installed yet - use Install Steam.", 6000)

    @Slot()
    def installSteam(self) -> None:
        self.begin_install(["steam"], for_gid="app:steam", what="Steam")

    @Slot()
    def fixInputPermissions(self) -> None:
        """One press: install Valve's udev rules so Steam stops saying "Missing permissions for input devices"."""
        if self._input_fixing:
            self.show_toast("Already working on it - CodeAque may be waiting for your password.", 5000)
            return
        self._input_fixing = True
        self.show_toast("Fixing controller permissions - CodeAque asks for your password on this screen...", 8000)

        def work():
            lines: list = []
            try:
                done, msg = inputfix.fix(lines.append)
            except Exception as exc:  # pragma: no cover - safety net
                done, msg = False, f"The fix hit a problem: {exc}"
            studio_fix.log("input permissions fix: " + msg + " | " + " / ".join(lines[-4:]))
            self.inputFixDone.emit(done, msg)

        threading.Thread(target=work, daemon=True, name="atari-input-fix").start()

    @Slot()
    def fixSober(self) -> None:
        """Sober's own advice for its "application bundle (APK) required" screen: flatpak update + check the connection."""
        if self._input_fixing:
            self.show_toast("Already working on it - please wait.", 5000)
            return
        self._input_fixing = True
        self.show_toast("Updating Sober and testing the connection - this can take a minute or two...", 8000)

        def work():
            try:
                checks = sober.service_checks()
                ok, out = sober.update_sober()
                studio_fix.log("sober fix: update " + ("ok" if ok else "failed: " + out[-200:]) + " | "
                               + " / ".join(c.text for c in checks))
                if all(c.ok for c in checks):
                    msg = ("Sober is up to date" if ok else "Sober could not be updated (is it installed? press Install on the Roblox tile)") \
                        + " and the connection to its servers works. Press the Roblox tile again; if it still asks for an \"application bundle\", "
                    msg += "Sober's download service is probably down right now - try again later."
                else:
                    msg = sober.explain(checks)
            except Exception as exc:  # pragma: no cover - safety net
                ok, msg = False, f"That hit a problem: {exc}"
            self.inputFixDone.emit(ok, msg)

        threading.Thread(target=work, daemon=True, name="atari-sober-fix").start()

    @Slot(bool, str)
    # ----- the Roblox fix screen (step by step, "Run fix") ------------------------------------
    def _roblox_fix_rows(self) -> list:
        import os
        rows = [self._info("Roblox shows a window asking for an \"application bundle (APK)\". That is Sober (the Roblox runner for Linux) saying: "
                           "\"I could not download Roblox myself.\" Your Roblox account and this computer are not damaged.")]
        if self._rbx_state == "running":
            rows.append(self._info("Working - checking everything, updating Sober. This can take a minute or two..."))
        elif self._rbx_state == "done":
            for st in self._rbx_steps:
                rows.append({"kind": "item", "id": "noop", "title": ("OK   " if st.ok else "FIX  ") + st.title, "detail": st.detail,
                             "value": "" if st.ok else "Problem"})
            rows.append(self._info("Result:  " + self._rbx_verdict))
        else:
            for t in ("1  Sober comes from Flathub and is up to date", "2  The internet and DNS can reach Sober's server and Google Play",
                      "3  The clock is right (a wrong clock breaks secure connections)",
                      "4  The file picker exists (only needed to pick a file by hand)"):
                rows.append(self._info(t))
            rows.append(self._info("5  Sober has the permissions it asks for (\"Permission Update Required\")"))
            rows.append(self._info(sober.OVERRIDE_PLAIN))
            rows.append(self._info("Press \"Run fix\": CodeAque checks all of this, adds the Flathub store if it is missing, gives Sober that permission if it "
                                   "lacks it, updates Sober, tells you the cause - and starts Roblox again if it changed something."))
        rows.append({"kind": "done", "id": "rbxrun", "title": "Working..." if self._rbx_state == "running" else "Run fix"})
        rows.append({"kind": "item", "id": "rbxopen", "title": "Open Roblox again", "detail": "Sober retries the download by itself."})
        rows.append(self._info("Sober's log:  " + sober.LATEST_LOG + "   (Sober's \"state\" file, which names the Roblox version it wants, is next to it)"))
        rows.append(self._info("CodeAque's log:  " + str(paths.log_file())))
        rows.append({"kind": "item", "id": "copylog", "title": "Copy CodeAque's log (to send to someone who is helping you)"})
        rows.append(self._info("Honest limit: if everything above is OK and Roblox still asks for a bundle, Sober's own download service is failing. "
                               "CodeAque cannot fix that and never downloads a Roblox file for you. Choosing a file by hand only works with the exact "
                               "Roblox version it names plus the x86_64 part, from a source you trust - not recommended."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _roblox_fix_activate(self, rid: str) -> str:
        if rid == "rbxrun":
            if self._rbx_state == "running":
                return ""
            self._rbx_state, self._rbx_steps, self._rbx_verdict = "running", [], ""

            def work():
                try:
                    steps, verdict = sober.run_fix()
                except Exception as exc:  # pragma: no cover - safety net
                    steps, verdict = [], f"That hit a problem: {exc}"
                self.robloxFixDone.emit(steps, verdict)
            threading.Thread(target=work, name="atari-roblox-fix", daemon=True).start()
            return "refresh"
        if rid == "rbxopen":
            g = next((x for x in self._all if x.gid == "app:roblox"), None)
            if g is None or g.missing:
                self.begin_install(["roblox"], for_gid="app:roblox", what="Roblox (Sober)")
                return ""
            self._launch_game(g)
            return "close"
        if rid == "copylog":
            self.copyLog()
            return ""
        return ""

    def _roblox_fix_finished(self, steps, verdict: str) -> None:
        self._rbx_state, self._rbx_steps, self._rbx_verdict = "done", list(steps), verdict
        self.pageChanged.emit()
        if any(getattr(st, "changed", False) for st in steps):          # it gave Sober the permission: start Roblox again for the person
            g = next((x for x in self._all if x.gid == "app:roblox"), None)
            if g is not None and not g.missing and not self._running:
                self._launch_game(g)
                self.pageRequested.emit("close")

    def _input_fix_finished(self, ok: bool, text: str) -> None:
        self._input_fixing = False
        self.show_toast(text, 12000)

    # ----- start-up intro ----------------------------------------------------------------
    @Property(bool, notify=introChanged)
    def introActive(self):
        return self._intro_active

    @Property(str, notify=introChanged)
    def introMode(self):
        return self._intro_mode if self._intro_active else ""

    def _intro_begin(self) -> None:
        if not self._intro_active:
            return
        if self._intro_mode == "default":
            self.playSound("intro")
            self._intro_timer.start(int(intro.DEFAULT_SECONDS * 1000))
            return
        video = self._intro_plan.file
        kind, exe = intro.find_player()
        if not exe or video is None:
            _intro_log("no video player (mpv / ffplay / vlc) found - skipping the intro")
            self._end_intro("failed")
            return
        muted = (not self.cfg.intro_sound) or bool(os.environ.get("ATARI_NO_SOUND"))      # the intro's sound has its own switch (not "sound effects")
        cmd = intro.player_command(kind, exe, video, muted, intro.write_input_conf())
        _intro_log("intro: " + " ".join(cmd))

        def work():
            limit = intro.time_limit(intro.probe_seconds(video))
            pb = intro.Playback(cmd, limit, lambda r: self.introEnded.emit(r), keys=exitwatch.X11Keys)
            self._intro_play = pb
            pb.start()
            if self._intro_skip_early:
                pb.skip()
        threading.Thread(target=work, daemon=True, name="atari-intro-start").start()

    @Slot()
    def skipIntro(self) -> None:
        """Any key, click or controller button: end the intro now."""
        if not self._intro_active:
            return
        if self._intro_mode == "default":
            self._end_intro("skipped")
            return
        self._intro_skip_early = True
        pb = self._intro_play
        if pb is not None:
            pb.skip()

    @Slot(str)
    def _end_intro(self, reason: str = "finished") -> None:
        if not self._intro_active:
            return
        self._intro_active = False
        self._intro_timer.stop()
        self._intro_skip_early = False
        pb, self._intro_play = self._intro_play, None
        if pb is not None and pb.active:
            pb.skip()
        _intro_log(f"intro ended: {reason}")
        self.introChanged.emit()
        if self._window is not None:                     # take the screen and the keyboard back from the player
            QTimer.singleShot(0, self._raise_window)
        if not self._demo and not self._running and not self._start_timer.isActive():
            if self.cfg.music:
                QTimer.singleShot(300, self._sync_music)

    def _raise_window(self) -> None:
        try:
            self._window.raise_()
            self._window.requestActivate()
        except (RuntimeError, AttributeError):           # the window is already gone (closing)
            pass

    def stop_intro(self) -> None:
        self._intro_timer.stop()
        pb, self._intro_play = self._intro_play, None
        if pb is not None and pb.active:
            pb.stop()

    @Slot()
    def previewIntro(self) -> None:
        """Settings > Play the intro now: your video if you chose one, else CodeAque's own animation. Ignores the toggles."""
        if self._intro_active:
            return
        f = intro.custom_file()
        self._intro_plan = intro.Plan("custom", f) if f is not None else intro.default_plan()
        self._intro_mode = self._intro_plan.mode
        self._intro_active = True
        self._intro_skip_early = False
        self.introChanged.emit()
        QTimer.singleShot(0, self._intro_begin)

    @Slot()
    def toggleIntro(self) -> None:
        self.cfg.intro_enabled = not self.cfg.intro_enabled
        self._save_prefs()

    @Slot()
    def toggleIntroSound(self) -> None:
        self.cfg.intro_sound = not self.cfg.intro_sound
        self._save_prefs()

    @Slot()
    def toggleIntroDefault(self) -> None:
        self.cfg.intro_default = not self.cfg.intro_default
        self._save_prefs()

    @Slot(result=str)
    def introBrowseStart(self) -> str:
        """The file picker for "Choose intro video" opens in Downloads, else Videos, else a USB stick, else Home."""
        home = Path.home()
        for sub_ in ("Downloads", "Videos"):
            if (home / sub_).is_dir():
                return str(home / sub_)
        for p in self.listDir("")["dirs"]:
            if p["name"].startswith("USB"):
                return p["path"]
        return str(home)

    @Slot(str, result=str)
    def introPicked(self, path: str) -> str:
        ok, msg = intro.install(path)
        if ok:
            self.cfg.intro_enabled = True
            self._save_prefs()
        self.show_toast(msg, 7000 if ok else 9000)
        self.playSound("select" if ok else "error")
        return "ok" if ok else "error"

    @Slot()
    def removeIntro(self) -> None:
        n = intro.remove()
        self.show_toast("Intro video removed." if n else "There was no intro video to remove.", 5000)

    def _intro_rows(self) -> list:
        f = intro.custom_file()
        rows = []
        if f is not None:
            rows.append({"kind": "introvideo", "title": "Intro video (your own)", "value": "ON" if self.cfg.intro_enabled else "OFF",
                         "detail": f"Plays {f.name} full screen when CodeAque starts. Any key, click or controller button skips it. "
                                   "Sound follows the Sound effects switch."})
        else:
            rows.append({"kind": "introvideo", "title": "Intro video (your own)", "value": "None",
                         "detail": "No video chosen yet. Press \"Choose intro video\" to pick an .mp4 / .webm / .mkv / .mov file."})
        rows.append({"kind": "introchoose", "title": "Choose intro video", "value": "",
                     "detail": "Pick a video from Downloads, Videos or a USB stick. CodeAque keeps its own copy."})
        if f is not None:
            rows.append({"kind": "introremove", "title": "Remove intro video", "value": "",
                         "detail": "Deletes CodeAque's copy only (your original file stays where it is)."})
        rows.append({"kind": "introdefault", "title": "CodeAque's start-up video (default)", "value": "ON" if self.cfg.intro_default else "OFF",
                     "detail": "The 10-second CodeAque logo reveal that comes with CodeAque. It plays only when you have no intro video of your own "
                               "(and, with no video player installed, a short animation is shown instead)."})
        rows.append({"kind": "introsound", "title": "Intro sound", "value": "ON" if self.cfg.intro_sound else "OFF",
                     "detail": "The intro plays with its own sound (the music in the video), whatever Sound effects is set to. OFF = silent intro."})
        rows.append({"kind": "intropreview", "title": "Play the intro now", "value": "", "detail": "Shows what happens at start-up."})
        return rows

    # ----- CodeAque-only mode (boot straight into CodeAque) ----------------------------------
    def _kiosk_rows(self) -> list:
        lay = self._kiosk_layout
        rows: list = []
        if self._kiosk_busy:
            return [self._info("Working - CodeAque asks for your password on this screen first..."), {"kind": "item", "id": "back", "title": "Back"}]
        if self._kiosk_msg:
            rows.append(self._info("Result:  " + self._kiosk_msg))
        if kiosk.enabled(lay):
            if kiosk.session_outdated(lay):
                rows.append(self._info("CodeAque-only mode's session file is from an older CodeAque. With it, closing CodeAque (or an app taking CodeAque down) can drop you "
                                       "to the Mint desktop. Press \"Update CodeAque-only mode\" once (password) to fix it."))
            else:
                rows.append(self._info("CodeAque-only mode's session file is up to date. \"Update CodeAque-only mode\" below just writes it again (safe any time)."))
            rows.append({"kind": "done", "id": "kioskupdate", "title": "Update CodeAque-only mode",
                         "detail": "Asks for your password once. Rewrites the same three files; nothing else changes."})
            if not kiosk.window_manager():
                rows.append(self._info("No window manager is installed, so Steam's own windows (game Properties, Settings, pop-ups) can open out of "
                                       "sight. CodeAque now hides itself while Steam runs, but the fix is the one below (password once, then restart)."))
                rows.append({"kind": "done", "id": "kioskwm", "title": "Install the window manager (openbox)",
                             "detail": "Asks for your password once. Installs the small 'openbox' package so windows stack, focus and can be clicked."})
            kind, rtext = kiosk.running_description()
            if kind != "code-only":
                rows.append(self._info("Note: " + rtext + " Closing an app can then show the desktop. Restart the computer (or log out and in) so the "
                                       "CodeAque-only session starts CodeAque."))
            facts = kiosk.diagnose(lay)
            problems = [t for t in facts if not t.startswith(("OK ", "    ", "session log")) and "CodeAque is running" not in t]
            tail = kiosk.log_tail(3)
            if problems:
                rows.append(self._info("Check: " + " | ".join(t.strip() for t in problems)))
            if tail:
                rows.append(self._info("Last start-ups (" + str(kiosk.session_log_path()) + "):  " + "  /  ".join(tail)))
            rows += [self._info("CodeAque-only mode is ON: the computer starts straight into CodeAque, with no Linux Mint desktop."),
                     {"kind": "done", "id": "kioskoff", "title": "Back to Mint desktop (turn CodeAque-only mode off)",
                      "detail": "Asks for your password once. The normal login and desktop come back after the next restart or log out."},
                     {"kind": "item", "id": "kioskonce", "title": "Open the Mint desktop once (log out now)",
                      "detail": "No password. This login only - the next start is CodeAque-only again."},
                     self._info(kiosk.RECOVERY),
                     self._info("If it ever starts the Mint desktop instead of CodeAque, paste this in a Terminal to put it right: " + kiosk.RESTORE_COMMAND)]
        else:
            checks = kiosk.preflight(lay)
            why = kiosk.blocked(checks)
            rows += [self._info("CodeAque-only mode makes this computer start straight into CodeAque, like a games console: no Linux Mint desktop, "
                                "no login screen. Your files and games are not touched."),
                     self._info("What changes (needs your password once): three small files named \"atari\" - the login screen's auto-login and a "
                                "\"session\" that starts CodeAque. Turning it off removes exactly those files."),
                     self._info("Ways back, always: Settings > Start mode > Use Linux desktop; or at the login screen pick the Cinnamon session; "
                                "or if CodeAque crashes five times in a row right after starting, the Mint desktop starts by itself."),
                     self._info(kiosk.RECOVERY)]
            for c in checks:
                if not c.ok:
                    rows.append(self._info(("CANNOT CONTINUE: " if c.fatal else "Note: ") + c.text))
            if why:
                rows.append({"kind": "item", "id": "back", "title": "Back"})
                return rows
            rows.append({"kind": "done", "id": "kioskon", "title": "Yes, turn CodeAque-only mode ON",
                         "detail": "CodeAque asks for your password on this screen. You can undo it any time."})
        rows += [self._info(t) for t in kiosk.FAST_BOOT_TIPS]
        rows.append({"kind": "item", "id": "back", "title": "No, keep my normal desktop" if not kiosk.enabled(lay) else "Back"})
        return rows

    # ----- Xbox / xemu settings ----------------------------------------------------------------
    def _xemu_rows(self) -> list:
        rep = xemuconfig.check()
        rows: list = []
        if self._xm_msg:
            rows.append(self._info("Result:  " + self._xm_msg))
        rows.append(self._info("xemu (the Xbox emulator) reads these four files from its settings file. CodeAque never includes them - they come from your own Xbox."))
        for c in rep.configs:
            rows.append(self._info("Settings file: " + c))
        tone = {"ok": "ok", "fixed": "ok"}
        for r in rep.rows:
            rows.append({"kind": "item", "id": "xmrow", "title": f"{r.label}:  {r.path or '(not set)'}",
                         "value": {"ok": "OK", "fixed": "FIXED", "todo": "CAN FIX", "missing": "MISSING", "bad": "WRONG SIZE"}.get(r.state, ""),
                         "tone": tone.get(r.state, ""), "detail": r.text})
        for n in rep.notes:
            rows.append(self._info(n))
        rows.append(self._info("All needed files are set and exist - xemu should start." if rep.ok else
                               "xemu is not ready yet: " + (xemuconfig.launch_problem(rep) or "press Repair.")))
        rows.append({"kind": "done", "id": "xmrepair", "title": "Repair xemu settings",
                     "detail": "Writes the paths of the files found into xemu's settings (only empty or wrong ones; a path that works is kept). "
                               "A copy of the old settings file is kept once. Close xemu first."})
        have_hdd = any(r.key == "hdd_path" and r.state in ("ok", "fixed") for r in rep.rows)
        busy = getattr(self, "_xm_busy", "")
        if busy:
            rows.append(self._info(busy))
        confirm = getattr(self, "_xm_confirm", False)
        tool = xemuconfig.hdd_tool()
        rows.append({"kind": "item", "id": "xmhdd",
                     "title": ("Yes, install the disk tool and make the hard disk" if confirm else "Make hard disk (8 GB)"),
                     "value": "CONFIRM" if confirm else ("HAVE ONE" if have_hdd else ""), "tone": "warn" if confirm else ("ok" if have_hdd else ""),
                     "detail": ("You already have a hard disk set; this makes no second one. " if have_hdd else "")
                               + ("Makes a blank xbox_hdd.qcow2 in xemu's own folder and writes it into xemu's settings. "
                                  if tool else "First installs the free disk tool (qemu-utils; asks for your password), then makes a blank "
                                  "xbox_hdd.qcow2 in xemu's own folder and writes it into xemu's settings. ")
                               + "A blank disk still needs formatting - see the note below."})
        rows.append(self._info(xemuconfig.FORMAT_HELP))
        rows.append({"kind": "item", "id": "xmhddpage", "title": "Open xemu's disk page", "detail": xemuconfig.HDD_PAGE + " (in the web browser)"})
        rows.append({"kind": "item", "id": "xmbios", "title": "Add BIOS files (from a USB stick or folder)",
                     "detail": "Copies your Xbox BIOS, boot ROM and disk image to xemu's folder. Names like Complex_4627.bin or Complex 4627 are fine."})
        rows.append({"kind": "item", "id": "biosfind", "title": "Find my BIOS files in Downloads",
                     "detail": "Looks through Downloads (also inside .zip / .7z / .rar) for your BIOS, boot ROM and disk image, then copies them on Yes."})
        rows.append(self._info("By hand: open xemu, Machine > System, and pick the files. Settings file in Flatpak: ~/.var/app/app.xemu.xemu/data/xemu/xemu/xemu.toml; "
                               "otherwise ~/.local/share/xemu/xemu/xemu.toml (section [sys.files]: bootrom_path, flashrom_path, eeprom_path, hdd_path)."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _xm_make_hdd(self, runner=None, which=shutil.which) -> str:
        """One tap: (install qemu-utils after a confirm) -> blank 8 GB disk in xemu's folder -> hdd_path written -> read back."""
        if getattr(self, "_xm_busy", ""):
            return "refresh"
        confirm, self._xm_confirm = getattr(self, "_xm_confirm", False), False
        if not xemuconfig.hdd_tool(which) and not confirm:
            self._xm_confirm = True
            return "refresh"

        def make() -> None:
            ok, msg = xemuconfig.create_empty_hdd(which=which)
            rep = xemuconfig.repair(which=which)
            row = next((r for r in xemuconfig.check(which=which).rows if r.key == "hdd_path"), None)
            back = f" xemu's settings now say: {row.path}" if row is not None and row.path else ""
            self._xm_msg = msg + (" Written to " + ", ".join(rep.written) + "." if rep.written else "") + back
            kiosk.log_event(f"xemu hdd: {ok} {self._xm_msg}")

        def work():
            try:
                if not xemuconfig.hdd_tool(which):
                    self._xm_busy = "Installing the disk tool (qemu-utils)..."
                    self._bgDone.emit()
                    full, secret, early = rootauth.prepare(["pkexec", "apt-get", "install", "-y", "qemu-utils"])
                    if early is not None:
                        self._xm_msg = "The password box was closed - nothing was installed or made."
                        return
                    p = (runner or subprocess.run)(full, capture_output=True, text=True, timeout=600,
                                                   **({"input": secret.decode()} if secret else {"stdin": subprocess.DEVNULL}))
                    kiosk.log_event(f"xemu hdd: apt-get install qemu-utils: exit {p.returncode}")
                    if p.returncode != 0 or not xemuconfig.hdd_tool(which):
                        self._xm_msg = "Could not install qemu-utils: " + (((p.stderr or p.stdout) or "").strip().splitlines() or ["?"])[-1]
                        return
                self._xm_busy = "Making the hard disk..."
                self._bgDone.emit()
                make()
            except Exception as exc:  # pragma: no cover
                self._xm_msg = f"Something went wrong: {exc}"
            finally:
                self._xm_busy = ""
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-xemuhdd").start()
        return "refresh"

    def _xemu_activate(self, rid: str) -> str:
        if rid == "xmrepair":
            rep = xemuconfig.repair()
            if rep.written:
                self._xm_msg = "Wrote " + ", ".join(rep.written) + ". " + ("xemu has all it needs." if rep.ok else xemuconfig.launch_problem(rep))
            else:
                self._xm_msg = ("Nothing needed changing - the paths already work." if rep.ok else "Nothing could be filled in. " + xemuconfig.launch_problem(rep))
            kiosk.log_event("xemu repair: " + " | ".join(rep.lines()))
            return "refresh"
        if rid == "xmhdd":
            return self._xm_make_hdd()
        if rid == "xmhddpage":
            if not self._running:
                self._launch_game(Game(gid=webapps.XEMU_HDD.gid, title=webapps.XEMU_HDD.title, platform=webapps.STREAMING,
                                       platform_name=webapps.STREAMING_NAME, note=webapps.XEMU_HDD.note))
            return ""
        if rid == "biosfind":
            return "page:biosfind"
        if rid == "xmbios":
            return "import:bios"
        return ""

    # ----- brightness (Settings > Brightness and the sun pill in the top bar) -------------------
    @Property(int, notify=brightnessChanged)
    def brightness(self):
        return self._br_level

    def _br_read(self) -> None:
        v = brightness.current()
        if v is not None:
            self._br_level = v
            self.brightnessChanged.emit()

    def _root_run(self, cmd: list, timeout: float = 600, runner=None) -> int:
        """A pkexec command through the in-app password dialog (rootauth). Exit code; -1 when the password box was closed."""
        full, secret, early = rootauth.prepare(cmd)
        if early is not None:
            return -1
        try:
            p = (runner or subprocess.run)(full, capture_output=True, text=True, timeout=timeout,
                                           **({"input": secret.decode()} if secret else {"stdin": subprocess.DEVNULL}))
        except (OSError, subprocess.SubprocessError) as exc:
            kiosk.log_event(f"brightness: {cmd[1:3]} failed: {exc}")
            return 1
        kiosk.log_event(f"brightness: {' '.join(cmd[1:4])}: exit {p.returncode}")
        return p.returncode

    @Slot(int)
    def setBrightness(self, pct: int) -> None:
        """Brightness to pct (5-100) in the background: brightnessctl, then /sys/class/backlight (password if needed), then xrandr."""
        pct = brightness.clamp(pct)
        self._br_level = pct
        self.brightnessChanged.emit()

        def work():
            if not self._br_lock.acquire(blocking=False):
                return
            try:
                ok, how = brightness.set_level(pct, root_run=self._root_run)
                self._br_how = how
                if not ok:
                    self._br_msg = "Could not change the brightness. Try Fix brightness below (needs a restart)."
                elif how == "xrandr":
                    self._br_msg = ("The screen's backlight could not be reached, so CodeAque is dimming the picture instead (xrandr). "
                                    "Fix brightness below may make the real backlight work.")
                else:
                    self._br_msg = ""
                kiosk.log_event(f"brightness: {pct}% via {how or 'nothing'}")
            finally:
                self._br_lock.release()
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-brightness").start()

    @Slot(int)
    def stepBrightness(self, delta: int) -> None:
        self.setBrightness((self._br_level if self._br_level >= 0 else 70) + delta)

    def _br_grub_text(self) -> str:
        try:
            return Path(brightness.GRUB).read_text()
        except OSError:
            return ""

    def _br_rows(self) -> list:
        lv = self._br_level
        rows = [{"kind": "info", "title": "Brightness now", "value": f"{lv}%" if lv >= 0 else "Unknown",
                 "detail": {"brightnessctl": "Set with brightnessctl.", "backlight": "Set through /sys/class/backlight.",
                            "xrandr": "Software dimming (xrandr) - the backlight itself was not reachable."}.get(self._br_how,
                            "Use the rows below, or the sun in the top bar of the home screen.")}]
        rows.append({"kind": "item", "id": "brup", "title": "Brighter (+10%)", "detail": ""})
        rows.append({"kind": "item", "id": "brdown", "title": "Dimmer (-10%)", "detail": ""})
        for v in (25, 50, 75, 100):
            rows.append({"kind": "item", "id": f"brset{v}", "title": f"Set to {v}%", "detail": ""})
        if not shutil.which("brightnessctl"):
            rows.append({"kind": "item", "id": "brinstall", "title": "Install the brightness tool (brightnessctl)",
                         "detail": "Free and small; asks for your password once. After that brightness changes need no password."})
        txt = self._br_grub_text()
        cur, nxt = brightness.applied_fix(txt), brightness.next_fix(txt)
        if nxt:
            rows.append({"kind": "item", "id": "brfix", "title": "Fix brightness" + (" (try the other way)" if cur else ""),
                         "detail": f"For laptops where the brightness keys and this slider do nothing. Adds acpi_backlight={nxt} to the "
                                   "start-up options (backs up /etc/default/grub first), updates GRUB, then asks you to restart."})
        if cur:
            rows.append({"kind": "item", "id": "brundo", "title": "Undo Fix brightness",
                         "detail": f"acpi_backlight={cur} is set. Puts the old /etc/default/grub back and updates GRUB (restart after)."})
        if self._br_busy:
            rows.append({"kind": "info", "title": self._br_busy, "value": "", "detail": ""})
        if self._br_msg:
            rows.append({"kind": "info", "title": self._br_msg, "value": "", "detail": ""})
        rows.append({"kind": "item", "id": "back", "title": "Back", "detail": ""})
        return rows

    def _br_activate(self, rid: str) -> str:
        if rid == "brup":
            self.stepBrightness(10)
        elif rid == "brdown":
            self.stepBrightness(-10)
        elif rid.startswith("brset"):
            self.setBrightness(int(rid[5:]))
        elif rid in ("brinstall", "brfix", "brundo") and not self._br_busy:
            txt = self._br_grub_text()

            def work():
                try:
                    if rid == "brinstall":
                        self._br_busy = "Installing brightnessctl..."
                        self._bgDone.emit()
                        rc = self._root_run(["pkexec", "apt-get", "install", "-y", "brightnessctl"])
                        self._br_msg = ("Installed. Try the slider again." if rc == 0 and shutil.which("brightnessctl") else
                                        "The password box was closed - nothing was installed." if rc == -1 else "Could not install brightnessctl.")
                    else:
                        mode = brightness.next_fix(txt)
                        self._br_busy = "Updating the start-up options..."
                        self._bgDone.emit()
                        script = brightness.fix_script(mode) if rid == "brfix" else brightness.restore_script()
                        rc = self._root_run(["pkexec", "sh", "-c", script])
                        if rc == 0:
                            self._br_msg = (f"Done: acpi_backlight={mode} is set (old file kept as {brightness.BACKUP}). Restart the computer "
                                            "for it to take effect, then try the slider. If it still does nothing, press Fix brightness again "
                                            "to try the other way." if rid == "brfix" else "Old start-up options put back. Restart the computer.")
                        else:
                            self._br_msg = "The password box was closed - nothing was changed." if rc == -1 else "That did not work - nothing was changed."
                finally:
                    self._br_busy = ""
                    self._bgDone.emit()
            threading.Thread(target=work, daemon=True, name="atari-brightfix").start()
        return "refresh"

    # ----- controller batteries (top bar) ------------------------------------------------------
    @Property("QVariantList", notify=padBatteriesChanged)
    def padBatteries(self):
        return self._pad_batt

    @Slot()
    def refreshBatteries(self) -> None:
        if self._batt_busy:
            return
        self._batt_busy = True

        def work():
            rows = []
            try:
                found = pads.detect()
                up, bz = None, None
                if bluetooth.available():
                    try:
                        bz = {d.name: d.battery for d in bluetooth.devices() if d.connected and d.is_pad}
                    except Exception:
                        bz = None
                if any(p.how == "Bluetooth" for p in found) or bz:
                    up = padbattery.upower_batteries()
                rows = padbattery.for_pads(found, upower=up, bluez=bz)
            except Exception:  # pragma: no cover - never let a battery read touch CodeAque
                rows = []
            self._batteryRead.emit(rows)
        threading.Thread(target=work, daemon=True, name="atari-battery").start()

    @Slot()
    def openControllerPill(self) -> None:
        """Top bar controller pill: no pad -> the pairing page; otherwise the Controllers page."""
        if not self._running:
            self.pageRequested.emit("controllers" if self._pad_batt else "btpair")

    @Slot("QVariantList")
    def _on_battery_read(self, rows) -> None:
        self._batt_busy = False
        self.set_pad_batteries(list(rows))

    def set_pad_batteries(self, rows: list) -> None:
        for r in rows:
            if r.get("low") and r["name"] not in self._batt_low_warned:
                self._batt_low_warned.add(r["name"])
                self.show_toast(f"Controller battery low ({r['text']}): {r['name']}. Charge it soon.", 10000)
            elif not r.get("low"):
                self._batt_low_warned.discard(r["name"])
        if rows != self._pad_batt:
            self._pad_batt = rows
            self.padBatteriesChanged.emit()

    # ----- helpers for pages that update while open ----------------------------------------------
    def _page_seen(self, name: str) -> None:
        self._seen_pages[name] = time.monotonic()

    def _page_visible(self, name: str) -> bool:
        return time.monotonic() - self._seen_pages.get(name, -100.0) < 2.5

    @Slot()
    def _on_bg_done(self) -> None:
        if any(self._page_visible(n) for n in ("btpair", "screentv", "winform", "biosfind", "findgames", "simtycoon", "boot", "xemusetup")) or self._ct_page_visible():
            self.pageChanged.emit()

    # ----- Themes ------------------------------------------------------------------------------
    @Property("QVariantMap", notify=themeChanged)
    def themeColors(self):
        t = themes.get(self.store.get_pref("theme", themes.DEFAULT))
        return t.qml(bool(self.store.get_pref("theme_rain", True)))

    @Slot(str)
    def setTheme(self, theme_id: str) -> None:
        t = themes.get(theme_id)
        self.store.set_pref("theme", t.id)
        self.themeChanged.emit()

    @Slot()
    def toggleRain(self) -> None:
        self.store.set_pref("theme_rain", not bool(self.store.get_pref("theme_rain", True)))
        self.themeChanged.emit()

    def _theme_rows(self) -> list:
        cur = themes.get(self.store.get_pref("theme", themes.DEFAULT))
        rows: list = [self._info("Changes the colours, the background and the buttons. It applies straight away and is remembered.")]
        for t in themes.all_themes():
            rows.append({"kind": "item", "id": "th:" + t.id, "title": t.name, "value": "SELECTED" if t.id == cur.id else "",
                         "tone": "ok" if t.id == cur.id else "", "detail": t.description})
        if cur.rain:
            on = bool(self.store.get_pref("theme_rain", True))
            rows.append({"kind": "item", "id": "thrain", "title": "Rain effect: " + ("ON" if on else "OFF"),
                         "detail": "The soft rain behind the menus. Press to switch. (Also off with Reduce animations.)"})
        rows.append(self._info("More themes: put a file in ~/.config/atari/themes/ (copy one of CodeAque's theme files and change the colours)."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _theme_activate(self, rid: str) -> str:
        if rid.startswith("th:"):
            self.setTheme(rid[3:])
            return "refresh"
        if rid == "thrain":
            self.toggleRain()
            return "refresh"
        return ""

    # ----- World Games ---------------------------------------------------------------------------
    def _wg_rows(self) -> list:
        reg = getattr(self, "_wg_region", "jp")
        rows: list = [self._info("Games from Japan, China and Korea: yours (found by the region in the file name, like \"(Japan)\") "
                                 "and a few that their makers give away for free.")]
        for rid, name in worldgames.REGIONS:
            rows.append({"kind": "item", "id": "wgtab:" + rid, "title": name, "value": "SHOWING" if rid == reg else "",
                         "tone": "ok" if rid == reg else ""})
        mine = sorted([g for g in self._all if g.platform not in apps.NON_GAME
                       and worldgames.region_of(g.title + " " + Path(g.rom_path or "").name) == reg], key=lambda g: g.title.lower())
        rows.append(self._info(f"Your games from {dict(worldgames.REGIONS)[reg]} ({len(mine)}):"))
        for i, g in enumerate(mine[:300]):
            rows.append({"kind": "item", "id": f"wgmine:{i}", "title": g.title, "value": g.platform_name.upper(), "detail": "Press to play."})
        rows.append(self._info("Top free games (free from their makers; Steam opens their page to install):"))
        for i, f in enumerate(worldgames.free_for(reg)):
            rows.append({"kind": "item", "id": f"wgfree:{i}", "title": f"{f.title} ({f.year})", "value": "FREE",
                         "detail": f"{f.system}. {f.about}" + (f" {f.note}" if f.note else "") + f"\nOfficial page: {f.url}"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _wg_activate(self, rid: str) -> str:
        reg = getattr(self, "_wg_region", "jp")
        if rid.startswith("wgtab:"):
            self._wg_region = rid[6:]
            return "refresh"
        if rid.startswith("wgmine:"):
            mine = sorted([g for g in self._all if g.platform not in apps.NON_GAME
                           and worldgames.region_of(g.title + " " + Path(g.rom_path or "").name) == reg], key=lambda g: g.title.lower())
            i = int(rid[7:])
            if 0 <= i < len(mine) and not self._running:
                self._launch_game(mine[i])
            return ""
        if rid.startswith("wgfree:"):
            fl = worldgames.free_for(reg)
            i = int(rid[7:])
            if 0 <= i < len(fl) and not self._running:
                f = fl[i]
                self._launch_game(Game(gid="steam:" + f.steam_appid, title=f.title, platform="steam", platform_name="Steam",
                                       steam_appid=f.steam_appid))
            return ""
        return ""

    # ----- Settings > Boot (CodeAque boot screen) ----------------------------------------------
    def _boot_rows(self) -> list:
        self._page_seen("boot")
        on = bootscreen.installed()
        anim = bool(self.store.get_pref("boot_anim", True))
        win = create.windows_entry()
        rows: list = [self._info("The screen you see when the computer starts: a CodeAque menu with \"CodeAque\" (starts by itself after 5 s) "
                                 "and \"Windows\", then the CodeAque splash on the way in. It never changes partitions or Windows itself. "
                                 "Not yet tried on a real computer's start - if anything looks wrong, use Restore.")]
        st = bootscreen.status()
        rows.append(self._info(bootscreen.status_line(st)))
        rows.append(self._info(bootscreen.FIRMWARE_NOTE))
        if st["quiet"]:
            rows.append(self._info("Quiet start is on: the menu stays hidden (hold Shift or press Esc at power-on to see it) and the "
                                   "CodeAque splash shows on the way in. Install (again) after switching Quiet boot on or off."))
        rows.append({"kind": "item", "id": "bootstate", "title": "Now: " + ("CodeAque boot screen" if on else "the computer's old boot screen"),
                     "value": "ON" if on else "OFF", "tone": "ok" if on else "",
                     "detail": "\n".join(bootscreen.read_back()) + ("\nWindows found in the boot menu." if win else "\nNo Windows entry found yet (it is looked for when you install).")})
        busy = getattr(self, "_boot_busy", "")
        if busy:
            rows.append(self._info(busy))
        msg = getattr(self, "_boot_msg", "")
        if msg:
            rows.append(self._info(msg))
        confirm = getattr(self, "_boot_confirm", "")
        rows.append({"kind": "item", "id": "bootinstall", "title": "Yes, install it now" if confirm == "install" else "Install CodeAque boot screen",
                     "tone": "warn" if confirm == "install" else "", "value": "CONFIRM" if confirm == "install" else "",
                     "detail": "Backs up /etc/default/grub and the old theme first, turns on the Windows search (os-prober), runs update-grub and "
                               "checks the result. Asks for the password." + (" Press again to go ahead." if confirm == "install" else "")})
        rows.append({"kind": "item", "id": "bootanim", "title": "Animated splash: " + ("ON" if anim else "OFF (still picture)"),
                     "detail": "Falling code and a soft glow. Switch off for older graphics cards; takes effect at the next Install."})
        rows.append({"kind": "item", "id": "bootrestore", "title": "Yes, restore the old boot screen" if confirm == "restore" else "Restore old boot screen",
                     "tone": "warn" if confirm == "restore" else "", "value": "CONFIRM" if confirm == "restore" else "",
                     "detail": "Puts back the backed-up files and runs update-grub." + (" Press again to go ahead." if confirm == "restore" else "")})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _boot_run(self, script: str, what: str) -> None:
        self._boot_busy, self._boot_msg = what + " (this can take a minute)...", ""

        def work():
            import tempfile
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
                    fh.write(script)
                    path = fh.name
                os.chmod(path, 0o644)
                full, secret, early = rootauth.prepare(["pkexec", "bash", path])
                if early is not None:
                    self._boot_msg = "The password box was closed - nothing was changed."
                    return
                p = subprocess.run(full, capture_output=True, text=True, timeout=900,
                                   **({"input": secret.decode()} if secret else {"stdin": subprocess.DEVNULL}))
                kiosk.log_event(f"boot screen: {what}: exit {p.returncode}: {(p.stdout + p.stderr).strip()[-400:]}")
                if p.returncode == 0 and "OK" in p.stdout:
                    self._boot_msg = ("Done. " + ("Windows is in the menu. " if "WINDOWS=yes" in p.stdout else "")
                                      + ("The splash is in the start-up files. " if "SPLASH=yes" in p.stdout else "")
                                      + ("Warning: the splash is NOT in the start-up files (initramfs) - it may not show. " if "SPLASH=no" in p.stdout else "")
                                      + ("The login screen uses CodeAque's picture too. " if "GREETER=yes" in p.stdout else "")
                                      + "Restart the computer to see it.")
                else:
                    self._boot_msg = "It did not work, so the old files were put back. Details: " + ((p.stderr or p.stdout).strip().splitlines() or ["?"])[-1]
            except Exception as exc:  # pragma: no cover
                self._boot_msg = f"Something went wrong: {exc}"
            finally:
                try:
                    os.unlink(path)
                except Exception:
                    pass
                self._boot_busy = ""
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-bootscreen").start()

    def _boot_activate(self, rid: str, run=None) -> str:
        run = run or self._boot_run
        confirm = getattr(self, "_boot_confirm", "")
        self._boot_confirm = ""
        if getattr(self, "_boot_busy", ""):
            return "refresh"
        if rid == "bootanim":
            self.store.set_pref("boot_anim", not bool(self.store.get_pref("boot_anim", True)))
        elif rid == "bootinstall":
            if confirm != "install":
                self._boot_confirm = "install"
            else:
                run(bootscreen.install_script(animated=bool(self.store.get_pref("boot_anim", True)), quiet=quietboot.enabled()),
                    "Installing the boot screen")
        elif rid == "bootrestore":
            if confirm != "restore":
                self._boot_confirm = "restore"
            else:
                run(bootscreen.restore_script(), "Restoring the old boot screen")
        return "refresh"

    # ----- Create (game-making tools) ---------------------------------------------------------
    def _create_rows(self) -> list:
        ue = create.find_unreal(custom=str(self.store.get_pref(create.UNREAL_PREF, "") or ""))
        rows: list = [self._info("Tools for making games. Nothing is downloaded by itself.")]
        rows.append({"kind": "item", "id": "crue", "title": "Unreal Engine", "value": "OPEN" if ue else "NOT FOUND",
                     "tone": "ok" if ue else "", "detail": (f"Found: {ue}\n" if ue else "") + create.UNREAL_NOTE})
        if not ue:
            for st in create.UNREAL_STEPS:
                rows.append(self._info(st))
        rows.append({"kind": "item", "id": "cruelink", "title": "Open the official Unreal Engine Linux page",
                     "detail": create.UNREAL_URL + "  (in the web browser; sign in there with your free Epic account)"})
        rows.append({"kind": "item", "id": "cruepick", "title": "Choose UnrealEditor...", "detail": "If you unpacked it somewhere else: pick Engine/Binaries/Linux/UnrealEditor."})
        rows.append({"kind": "item", "id": "cruelook", "title": "Look again", "detail": "Checks ~/UnrealEngine, ~/Games/UnrealEngine, Downloads, /opt and your home folder."})
        ok = bool(apps.app_command(self.cfg, create.GODOT)[1])
        rows.append({"kind": "item", "id": "crgodot", "title": create.GODOT.title, "value": "OPEN" if ok else "INSTALL",
                     "detail": create.GODOT.note + ("" if ok else " Press to install it (asks first).")})
        win = create.windows_entry()
        rows.append({"kind": "item", "id": "crrbx", "title": "Roblox Studio", "value": "NEEDS WINDOWS / MAC", "detail": create.ROBLOX_STUDIO_NOTE})
        if win:
            confirm = getattr(self, "_cr_confirm", False)
            rows.append({"kind": "item", "id": "crwin", "title": "Yes, restart into Windows now" if confirm else "Reboot into Windows",
                         "tone": "warn" if confirm else "", "value": "CONFIRM" if confirm else "",
                         "detail": f"Starts \"{win}\" once; the next start after that is CodeAque again. Save your games first. "
                                   + ("Press again to restart (asks for the password)." if confirm else "Asks you to confirm.")})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _create_activate(self, rid: str) -> str:
        if rid != "crwin":
            self._cr_confirm = False
        if rid == "crue":
            ue = create.find_unreal(custom=str(self.store.get_pref(create.UNREAL_PREF, "") or ""))
            if not ue:
                self.show_toast("Unreal Engine was not found. Follow the steps on this page, then press Look again.", 8000)
                return ""
            kiosk.log_event("create: starting " + ue)
            try:
                subprocess.Popen([ue], cwd=str(Path(ue).parent), env=launcher.clean_env(), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
                self.show_toast("Starting Unreal Engine - the first start can take several minutes.", 8000)
            except OSError as exc:
                self.show_toast(f"Could not start Unreal Engine: {exc}", 8000)
            return ""
        if rid == "cruelink":
            if not self._running:
                self._launch_game(Game(gid=webapps.UNREAL.gid, title=webapps.UNREAL.title, platform=webapps.STREAMING,
                                       platform_name=webapps.STREAMING_NAME, note=webapps.UNREAL.note))
            return ""
        if rid == "cruepick":
            return "browse:unreal"
        if rid == "cruelook":
            return "refresh"
        if rid == "crgodot":
            if apps.app_command(self.cfg, create.GODOT)[1]:
                self._launch_game(Game(gid=create.GODOT.gid, title=create.GODOT.title, platform=apps.APPS, platform_name="Create"))
            else:
                self.begin_install(["godot"], what=create.GODOT.title)
            return ""
        if rid == "crwin":
            entry = create.windows_entry()
            if not entry:
                return "refresh"
            if not getattr(self, "_cr_confirm", False):
                self._cr_confirm = True
                return "refresh"
            self._cr_confirm = False
            kiosk.log_event(f"create: reboot into Windows once ({entry})")
            for cmd in create.reboot_commands(entry):
                ok, msg = bluetooth._admin(cmd, None, shutil.which)
                if not ok:
                    self.show_toast("Could not restart into Windows: " + (msg or "the password was not accepted") + ". Nothing was changed.", 9000)
                    return "refresh"
            return ""
        return ""

    @Slot(str)
    def setUnrealEditor(self, path: str) -> None:
        self.store.set_pref(create.UNREAL_PREF, path)

    # ----- Start Steam at boot (hidden) ---------------------------------------------------------
    def _steam_installed(self) -> bool:
        return bool(apps.app_command(self.cfg, apps.BY_ID["steam"])[1]) or bool(self.cfg.steam_command.strip())

    def _steam_autostart_on(self) -> bool:
        v = self.store.get_pref(steam.AUTOSTART_PREF, None)
        return self._steam_installed() if v is None else bool(v)       # default ON when Steam is installed

    @Slot()
    def toggleSteamBoot(self) -> None:
        on = not self._steam_autostart_on()
        self.store.set_pref(steam.AUTOSTART_PREF, on)
        kiosk.log_event("steam autostart: " + ("on" if on else "off"))
        if on:
            self._steam_autostart()

    def _steam_autostart(self, spawn=None) -> str:
        """At session start: `steam -silent` so Steam signs in with its own saved login and waits in the background; game launches then
        only send steam://rungameid. Returns what it did (for the log / tests)."""
        try:
            if not self._steam_autostart_on() or not self._steam_installed():
                return "off"
            if steam.steam_running():
                kiosk.log_event("steam autostart: Steam is already running")
                return "running"
            if not steam.remembered_login():
                kiosk.log_event("steam autostart: no remembered Steam login - showing the hint, not starting Steam")
                self.show_toast(steam.LOGIN_HINT, 9000)
                return "login"
            try:
                kiosk.log_event("steam autostart: " + steamfix.set_startup_normal()[1])
            except Exception:
                pass
            guard = getattr(self, "_steam_guard", None)
            if guard is not None:
                guard.silent_start(time.monotonic())       # 0.5.0 bug: the watcher asked this Steam for Big Picture -> Steam in front
            cmd = steam.autostart_command(launcher.steam_base_command(self.cfg))
            kiosk.log_event("steam autostart: " + " ".join(cmd))
            (spawn or (lambda c: subprocess.Popen(c, env=launcher.clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                  stdin=subprocess.DEVNULL, start_new_session=True)))(cmd)
            if spawn is None:
                self._start_steam_hider()
            return "started"
        except Exception as exc:  # pragma: no cover
            kiosk.log_event(f"steam autostart: failed ({exc})")
            return "error"

    def _start_steam_hider(self, watcher=None, sleep=time.sleep) -> None:
        """For the first minutes after the silent start: minimise / hide every Steam window that shows up and give the screen back to
        CodeAque; once Steam has settled, bring CodeAque to the front one last time."""
        from . import steamhide
        if watcher is None:
            if not steamhide.x11():
                kiosk.log_event("steam autostart: not an X11 session - Steam windows cannot be hidden by CodeAque")
                return
            watcher = steamhide.Watcher(time.monotonic(), ui_ready=steam.steam_ui_ready)
            if not watcher.usable:
                kiosk.log_event("steam autostart: xdotool / wmctrl not installed - cannot minimise Steam's windows (sudo apt install xdotool "
                                "wmctrl); keeping CodeAque in front instead for 90 s")

                def keep_front():
                    for _ in range(45):
                        if self._running:
                            return
                        self._raiseMe.emit()
                        sleep(2.0)
                threading.Thread(target=keep_front, daemon=True, name="atari-steamfront").start()
                return

        def work():
            try:
                while True:
                    hidden, finished = watcher.tick(time.monotonic())
                    if hidden:
                        kiosk.log_event("steam autostart: hid Steam window(s) " + ", ".join(hidden) + " - CodeAque back in front")
                        self._raiseMe.emit()
                    if finished:
                        kiosk.log_event(f"steam autostart: Steam has finished loading (hid {len(watcher.hidden)} window(s))")
                        self._raiseMe.emit()
                        return
                    sleep(1.0)
            except Exception as exc:  # pragma: no cover
                kiosk.log_event(f"steam autostart: hider stopped ({exc})")
        threading.Thread(target=work, daemon=True, name="atari-steamhide").start()

    def _raise_window_if_idle(self) -> None:
        """Back to the front - unless a game or app was started meanwhile (then CodeAque must stay behind it)."""
        if not self._running and self._window is not None:
            self._raise_window()

    # ----- Sim & Tycoon ----------------------------------------------------------------------
    def _sim_tags(self) -> tuple[list, list]:
        return list(self.store.get_pref(simtycoon.TAGS_PREF, []) or []), list(self.store.get_pref(simtycoon.UNTAGS_PREF, []) or [])

    def _sim_games(self) -> list:
        tags, untags = self._sim_tags()
        out = [g for g in self._all if g.platform not in apps.NON_GAME
               and simtycoon.in_section(g.gid, g.title, tags, untags, str((g.meta or {}).get("genre", "")))]
        return sorted(out, key=lambda g: g.title.lower())

    def _sim_scan(self) -> None:
        if getattr(self, "_sim_busy", False):
            return
        self._sim_busy = True

        def work():
            found = {}
            try:
                roots = simtycoon.search_roots(steam_libraries=simtycoon.steam_libraries())
                for kind in ("th", "rct2", "rct1", "c3"):
                    found[kind] = simtycoon.find_data(kind, roots)
            except Exception:  # pragma: no cover
                pass
            finally:
                self._sim_data, self._sim_busy = found, False
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-simdata").start()

    def _sim_engine_state(self, eid: str) -> tuple[bool, str]:
        e = simtycoon.BY_ID[eid]
        ok = bool(apps.app_command(self.cfg, e.app)[1])
        data = ""
        if e.check:
            data = (self._sim_data or {}).get(e.check, "")
            if eid == "openrct2" and not data:
                data = (self._sim_data or {}).get("rct1", "")
        return ok, data

    def _sim_rows(self) -> list:
        self._page_seen("simtycoon")
        if getattr(self, "_sim_data", None) is None and not getattr(self, "_sim_busy", False):
            self._sim_data = None
            self._sim_scan()
        busy = getattr(self, "_sim_busy", False)
        rows: list = []
        ok, data = self._sim_engine_state("corsixth")
        if busy and not data:
            state, detail = "LOOKING...", "Looking for your Theme Hospital files..."
        elif not data:
            state, detail = "NEED FILES", simtycoon.NO_TH_DATA
        elif not ok:
            state, detail = "INSTALL", (f"Your Theme Hospital files: {data}\nPress to install CorsixTH (free, open source, MIT licence) - "
                                        "it asks first, then the game is one press away.")
        else:
            state, detail = "PLAY", f"Plays your own Theme Hospital files ({data}) with CorsixTH."
        rows.append({"kind": "item", "id": "simhero", "title": "★  THEME HOSPITAL  ·  FEATURED", "value": state,
                     "tone": "ok" if state == "PLAY" else ("warn" if state == "NEED FILES" else ""), "detail": detail})
        games = self._sim_games()
        rows.append(self._info(f"Your sim & tycoon games ({len(games)}): from Steam, PC Games, DOS and your consoles, picked by title or genre, "
                               "plus any you add yourself."))
        for i, g in enumerate(games[:200]):
            rows.append({"kind": "item", "id": f"simgame:{i}", "title": g.title, "value": g.platform_name.upper(), "detail": "Press to play."})
        rows.append({"kind": "item", "id": "simpick", "title": "Add or remove games...", "detail": "Pick any game from your library to show it here (or hide it)."})
        rows.append(self._info("Open-source engines (installed only if you press Install; no game files, logos or art are included):"))
        for e in simtycoon.ENGINES:
            ok, data = self._sim_engine_state(e.app.id)
            if e.needs_data and not data:
                value, d = ("INSTALLED" if ok else "OPTIONAL"), f"{e.app.note} Not found yet: your {e.data_name}."
            elif ok:
                value, d = "PLAY", e.app.note + (f" Your files: {data}" if data else "")
            else:
                value, d = "INSTALL", e.app.note + (f" Your files: {data}" if data else "")
            rows.append({"kind": "item", "id": "simeng:" + e.app.id, "title": e.app.title, "value": value,
                         "detail": d + f" Licence: {e.licence}."})
        rows.append({"kind": "item", "id": "simlook", "title": "Look again for my game files",
                     "detail": "Searches ~/Games, ~/GOG Games, Downloads, Documents, Heroic, CodeAque's PC Games folders and Steam."})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _sim_play_engine(self, eid: str) -> str:
        e = simtycoon.BY_ID[eid]
        ok, data = self._sim_engine_state(eid)
        if e.needs_data and not data:
            self.show_toast(simtycoon.NO_TH_DATA if eid == "corsixth" else f"You need your own {e.data_name}. Copy the game's folder into ~/Games, then press Look again.", 12000)
            return ""
        if not ok:
            self.begin_install([eid], what=e.app.title)
            return ""
        if data:
            simtycoon.point_engine_at(eid, data)
        self._launch_game(Game(gid=e.app.gid, title=e.app.title, platform=apps.APPS, platform_name=simtycoon.NAME, note=e.app.note))
        return ""

    def _sim_activate(self, rid: str) -> str:
        if rid == "simhero":
            return self._sim_play_engine("corsixth")
        if rid.startswith("simeng:"):
            return self._sim_play_engine(rid[7:])
        if rid == "simlook":
            self._sim_data = None
            self._sim_scan()
            return "refresh"
        if rid == "simpick":
            return "page:simpick"
        if rid.startswith("simgame:"):
            games = self._sim_games()
            i = int(rid[8:])
            if 0 <= i < len(games) and not self._running:
                self._launch_game(games[i])
            return ""
        return ""

    def _simpick_rows(self) -> list:
        tags, untags = self._sim_tags()
        rows: list = [self._info("Press a game to show it in Sim & Tycoon, press again to hide it.")]
        pool = sorted([g for g in self._all if g.platform not in apps.NON_GAME], key=lambda g: g.title.lower())
        for i, g in enumerate(pool[:500]):
            on = simtycoon.in_section(g.gid, g.title, tags, untags, str((g.meta or {}).get("genre", "")))
            rows.append({"kind": "item", "id": f"simtag:{i}", "title": g.title, "value": "SHOWN" if on else "",
                         "tone": "ok" if on else "", "detail": g.platform_name})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _simpick_activate(self, rid: str) -> str:
        if not rid.startswith("simtag:"):
            return ""
        pool = sorted([g for g in self._all if g.platform not in apps.NON_GAME], key=lambda g: g.title.lower())
        i = int(rid[7:])
        if not 0 <= i < len(pool):
            return ""
        g = pool[i]
        tags, untags = self._sim_tags()
        on = simtycoon.in_section(g.gid, g.title, tags, untags, str((g.meta or {}).get("genre", "")))
        tags = [t for t in tags if t != g.gid]
        untags = [t for t in untags if t != g.gid]
        if on:
            untags.append(g.gid)
        else:
            tags.append(g.gid)
        self.store.set_pref(simtycoon.TAGS_PREF, tags)
        self.store.set_pref(simtycoon.UNTAGS_PREF, untags)
        return "refresh"

    # ----- Find my BIOS files ----------------------------------------------------------------
    def _bf_rows(self) -> list:
        self._page_seen("biosfind")
        if self._bf_res is None and not self._bf_busy and not self._bf_msg:
            self._bf_start()
        rows: list = [self._info("Looks in Downloads and every folder below it (also inside .zip / .7z / .rar) for BIOS files from your own consoles. "
                                 "Nothing is downloaded and nothing is changed until you press Copy.")]
        if self._bf_busy:
            rows.append(self._info("Working:  " + self._bf_busy))
        if self._bf_msg:
            rows.append(self._info("Result:  " + self._bf_msg))
        res = self._bf_res
        if res is not None and not self._bf_busy:
            if not res.found:
                rows.append(self._info("No BIOS files found in Downloads. Copy them from your USB stick into Downloads (or use Add BIOS files), then press Look again."))
            for f in res.found:
                it = f.item
                odd = "   (unusual file - check it)" if it.status == "odd" else ""
                rows.append({"kind": "item", "id": "bfrow", "title": f"{it.label}:  {it.name}{odd}",
                             "value": it.system.upper(), "detail": f"Found in {f.source}  ->  goes to {f.dest or 'the emulator folder'}"})
            for n in res.notes[:6]:
                rows.append(self._info(n))
            if res.found:
                rows.append({"kind": "done", "id": "bfcopy", "title": f"Copy {len(res.found)} file{'s' if len(res.found) != 1 else ''} into place",
                             "detail": "Copies each file to its emulator's folder (never overwrites a different file of the same name without keeping it) "
                                       "and, for the Xbox, writes xemu's settings."})
        if not self._bf_busy:
            rows.append({"kind": "item", "id": "bfscan", "title": "Look again"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _bf_start(self) -> None:
        self._bf_busy, self._bf_msg = "Looking in Downloads...", ""

        def say(t):
            self._bf_busy = t
            self._bgDone.emit()

        def work():
            try:
                old, self._bf_res = self._bf_res, biosfind.find(say=say)
                if old is not None:
                    old.cleanup()
                n = len(self._bf_res.found)
                self._bf_msg = f"Found {n} BIOS file{'s' if n != 1 else ''}." + (" Check the list, then press Copy." if n else "")
            except Exception as exc:  # pragma: no cover
                self._bf_msg = f"Something went wrong: {exc}"
            finally:
                self._bf_busy = ""
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-biosfind").start()

    def _bf_activate(self, rid: str) -> str:
        if self._bf_busy:
            return ""
        if rid == "bfscan":
            self._bf_start()
            return "refresh"
        if rid == "bfcopy" and self._bf_res is not None:
            res = self._bf_res
            self._bf_busy = "Copying..."

            def work():
                try:
                    out, xemu = biosfind.install(res, self.cfg)
                    bits = [f"Copied {out.copied} file{'s' if out.copied != 1 else ''}"]
                    if out.skipped_same:
                        bits.append(f"{out.skipped_same} already in place")
                    if out.failed:
                        bits.append("problems: " + "; ".join(out.failed[:3]))
                    self._bf_msg = ", ".join(bits) + "." + (" " + " ".join(out.notes[:2]) if out.notes else "")
                    if xemu:
                        self._bf_msg += "  xemu: " + " | ".join(xemu[:5])
                    kiosk.log_event("find my bios: " + self._bf_msg)
                    self._bf_res = None
                    self._bf_done = True
                except Exception as exc:  # pragma: no cover
                    self._bf_msg = f"Something went wrong: {exc}"
                finally:
                    self._bf_busy = ""
                    self._bgDone.emit()
            threading.Thread(target=work, daemon=True, name="atari-bioscopy").start()
            return "refresh"
        return ""

    # ----- Find my games ----------------------------------------------------------------------
    def _sys_name(self, sid: str) -> str:
        if sid == findgames.PC:
            return windows.PLATFORM_NAME
        sc = self.cfg.systems.get(sid)
        return sc.name if sc else "Console not known yet"

    def _fg_rows(self) -> list:
        self._page_seen("findgames")
        if self._fg_res is None and not self._fg_busy and not self._fg_msg:
            self._fg_start()
        rows: list = [self._info("For your own games and backups. CodeAque looks in Downloads, Desktop, Documents and plugged-in drives (every folder, "
                                 "whole game folders and archives), tells which console each game is for, and puts it in ~/Games/CodeAque/<console>. "
                                 "Nothing is downloaded and nothing moves until you press the button below.")]
        if self._fg_busy:
            rows.append(self._info("Working:  " + self._fg_busy))
        if self._fg_msg:
            rows.append(self._info("Result:  " + self._fg_msg))
        res = self._fg_res
        if res is not None and not self._fg_busy:
            games = [e for e in res.entries if e.kind != "installer"]
            inst = [e for e in res.entries if e.kind == "installer"]
            if not games and not inst:
                rows.append(self._info("No games found in: " + ", ".join(res.roots) + "."))
            last = None
            for e in games:
                if e.system != last:
                    last = e.system
                    n = len([x for x in games if x.system == e.system])
                    rows.append(self._info(f"{self._sys_name(e.system)}  -  {n} game{'s' if n != 1 else ''}"))
                rows.append({"kind": "item", "id": "fgrow", "title": "   " + e.title,
                             "value": {"archive": "ARCHIVE", "pc": "PC FOLDER"}.get(e.kind, ""),
                             "detail": f"From {e.source}  ->  {e.dest}" + (f"   (starts with {e.exe})" if e.exe else "")})
            for i, e in enumerate(inst):
                rows.append({"kind": "item", "id": f"fginst:{i}", "title": f"Installer: {e.title}",
                             "detail": f"{e.source}  -  if this is a game, press to set it up with the PC Games Installer (it is not run otherwise)."})
            if res.unknown or res.skipped:
                rows.append(self._info(f"Skipped {res.unknown} file{'s' if res.unknown != 1 else ''} whose console could not be told"
                                       + (" (first: " + res.skipped[0] + ")" if res.skipped else "") + ". Games you already have are skipped when copying."))
            if games:
                rows.append({"kind": "item", "id": "fgmode", "title": "How:  " + ("Move (the originals are removed after copying)" if self._fg_move
                                                                               else "Copy (the originals stay where they are)"),
                             "detail": "Press to switch between copy and move."})
                rows.append({"kind": "done", "id": "fggo", "title": f"{'Move' if self._fg_move else 'Copy'} {len(games)} game{'s' if len(games) != 1 else ''} into my games",
                             "detail": "Then CodeAque scans again so they show up."})
        if not self._fg_busy:
            rows.append({"kind": "item", "id": "fgscan", "title": "Look again"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _fg_start(self) -> None:
        self._fg_busy, self._fg_msg = "Looking for games...", ""

        def say(t):
            self._fg_busy = t
            self._bgDone.emit()

        def work():
            try:
                self._fg_res = findgames.find(self.cfg, say=say)
                n = len([e for e in self._fg_res.entries if e.kind != "installer"])
                self._fg_msg = f"Found {n} game{'s' if n != 1 else ''}." + (" Check the list, then press the button at the bottom." if n else "")
            except Exception as exc:  # pragma: no cover
                self._fg_msg = f"Something went wrong: {exc}"
            finally:
                self._fg_busy = ""
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-findgames").start()

    def _fg_activate(self, rid: str) -> str:
        if self._fg_busy:
            return ""
        if rid == "fgscan":
            self._fg_start()
            return "refresh"
        if rid == "fgmode":
            self._fg_move = not self._fg_move
            return "refresh"
        if rid.startswith("fginst:") and self._fg_res is not None:
            inst = [e for e in self._fg_res.entries if e.kind == "installer"]
            try:
                e = inst[int(rid.split(":")[1])]
            except (ValueError, IndexError):
                return ""
            self._win_reset()
            self._win_exe, self._win_name = str(e.source), e.title
            return "page:winform"
        if rid == "fggo" and self._fg_res is not None:
            res, move = self._fg_res, self._fg_move
            self._fg_busy = "Copying..."

            def say(t):
                self._fg_busy = t
                self._bgDone.emit()

            def work():
                try:
                    d = findgames.install(res, self.cfg, move=move, say=say)
                    bits = [f"{'Moved' if move else 'Copied'} {d.added} game{'s' if d.added != 1 else ''}"]
                    if d.duplicates:
                        bits.append(f"{d.duplicates} already there (skipped)")
                    if d.unknown:
                        bits.append(f"{d.unknown} not recognised (skipped)")
                    if d.failed:
                        bits.append("problems: " + "; ".join(d.failed[:3]))
                    self._fg_msg = ", ".join(bits) + "."
                    kiosk.log_event("find my games: " + self._fg_msg)
                    self._fg_res = None
                    self._fg_done = True
                except Exception as exc:  # pragma: no cover
                    self._fg_msg = f"Something went wrong: {exc}"
                finally:
                    self._fg_busy = ""
                    self._bgDone.emit()
                    QTimer.singleShot(0, lambda: self.rescan(toast=False))
            threading.Thread(target=work, daemon=True, name="atari-findgames-copy").start()
            return "refresh"
        return ""

    # ----- Pair a Bluetooth controller ------------------------------------------------------------
    def _bt_rows(self) -> list:
        self._page_seen("btpair")
        rows: list = []
        if self._bt_busy:
            rows.append(self._info("Working:  " + self._bt_busy))
        elif self._bt_msg:
            rows.append(self._info("Result:  " + self._bt_msg))
        if not bluetooth.available():
            rows.append(self._info("The Bluetooth tools (BlueZ) are not installed on this computer. In a Terminal:  sudo apt install bluez   then restart."))
            rows.append({"kind": "item", "id": "back", "title": "Back"})
            return rows
        rows += [self._info(t) for t in bluetooth.PAIRING_STEPS]
        if not self._bt_busy:
            rows.append({"kind": "done", "id": "btscan", "title": f"Search for controllers ({bluetooth.SCAN_SECONDS} seconds)",
                         "detail": "Switches Bluetooth on if needed (asks for the password only if Bluetooth is blocked or stopped)."})
        pads_ = [d for d in self._bt_found if d.is_pad]
        other = [d for d in self._bt_found if not d.is_pad]
        if self._bt_searched and not self._bt_found:
            rows.append(self._info("Nothing found. Put the pad in pairing mode (fast flashing light) right before pressing Search, and keep it close."))
        for d in pads_ + other[:8]:
            state = "Connected" if d.connected else "Paired" if d.paired else "New"
            extra = f"   Battery {d.battery}%" if d.battery is not None else ""
            act = "Press to connect again" if d.paired and not d.connected else "Press to pair and connect" if not d.paired else "Already connected"
            rows.append({"kind": "item", "id": "btdev:" + d.mac, "title": ("" if d.is_pad else "(not a controller?)  ") + d.name,
                         "value": state, "detail": f"{act}.  {d.mac}{extra}"})
        for d in pads_:
            if d.paired:
                rows.append({"kind": "item", "id": "btforget:" + d.mac, "title": f"Forget {d.name}",
                             "detail": "Removes the pairing (do this if it will not reconnect, then pair it again)."})
        rows.append(self._info("Not tested with real Bluetooth pads on your computer: if a pad pairs but does nothing, pair it once in the desktop's "
                               "Bluetooth settings, then it shows here as Paired."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _bt_job(self, what: str, fn) -> None:
        if self._bt_busy:
            return
        self._bt_busy = what

        def work():
            try:
                fn()
            except Exception as exc:  # pragma: no cover
                self._bt_msg = f"Something went wrong: {exc}"
            finally:
                self._bt_busy = ""
                self._bgDone.emit()
        threading.Thread(target=work, daemon=True, name="atari-bluetooth").start()

    def _bt_activate(self, rid: str) -> str:
        if rid == "btscan":
            def scan():
                ok, text = bluetooth.ensure_on()
                if not ok:
                    self._bt_msg = text
                    return
                self._bt_busy = f"Searching for {bluetooth.SCAN_SECONDS} seconds - put the pad in pairing mode now..."
                self._bgDone.emit()
                self._bt_found = bluetooth.scan()
                self._bt_searched = True
                n = len([d for d in self._bt_found if d.is_pad])
                self._bt_msg = f"Found {n} controller{'s' if n != 1 else ''}." + (" Press one to pair it." if n else "")
                kiosk.log_event(f"bluetooth scan: {len(self._bt_found)} devices, {n} pads")
            self._bt_job("Switching Bluetooth on...", scan)
            return "refresh"
        if rid.startswith("btdev:"):
            mac = rid[6:]

            def pair():
                def say(t):
                    self._bt_busy = t
                    self._bgDone.emit()
                ok, self._bt_msg = bluetooth.connect_pad(mac, say=say)
                kiosk.log_event(f"bluetooth pair {mac}: {ok} {self._bt_msg}")
                self._bt_found = bluetooth.devices()
            self._bt_job("Pairing...", pair)
            return "refresh"
        if rid.startswith("btforget:"):
            mac = rid[9:]

            def forget():
                ok, self._bt_msg = bluetooth.forget(mac)
                self._bt_found = bluetooth.devices()
            self._bt_job("Removing...", forget)
            return "refresh"
        return ""

    # ----- Screen to TV ---------------------------------------------------------------------------
    def _tv_rows(self) -> list:
        self._page_seen("screentv")
        rows: list = []
        if self._tv_msg:
            rows.append(self._info("Result:  " + self._tv_msg))
        left = int(self._tv_until - time.monotonic() + 0.99)
        if self._tv_undo and left > 0:
            rows.append({"kind": "done", "id": "tvkeep", "title": f"Keep this  (undoes itself in {left} s)",
                         "detail": "Press if you can see this on the screen you wanted."})
            rows.append({"kind": "item", "id": "tvundo", "title": "Undo now"})
        outs = screentv.xrandr_outputs()
        kern = screentv.kernel_outputs()
        shown = outs if outs is not None else kern
        conn = [o for o in shown if o.connected]
        if conn:
            rows.append(self._info("Screens plugged in now:  " + ",  ".join(f"{o.name} ({o.kind}{', on' if o.active else ''})" for o in conn)))
        else:
            rows.append(self._info("CodeAque could not see which screens are plugged in."))
        inner, tv = screentv.pick(shown)
        rows += [self._info(t) for t in screentv.CABLE_STEPS]
        if outs is None:
            rows.append(self._info("Switching screens from here needs an X11 session with xrandr. Otherwise use the system's Display settings, "
                                   "or press the laptop's screen key (often Fn + F4 / F7 / a key with a screen picture)."))
        elif tv is None:
            rows.append(self._info("No TV found yet. Plug in the cable, switch the TV to that HDMI input, then press Refresh."))
        else:
            rows.append({"kind": "item", "id": "tvmirror", "title": f"Same picture on both screens ({tv.name})",
                         "detail": "Mirror: the TV shows the same as this screen."})
            rows.append({"kind": "item", "id": "tvonly", "title": f"TV only ({tv.name})",
                         "detail": f"Switches this screen off and uses the TV. Undoes itself after {screentv.REVERT_SECONDS} s unless you press Keep."})
            if inner is not None:
                rows.append({"kind": "item", "id": "tvhere", "title": f"This screen only ({inner.name})", "detail": "Switches the TV picture off."})
        rows += [self._info(t) for t in screentv.WIRELESS_STEPS]
        cmd = screentv.wireless_app()
        if cmd:
            rows.append({"kind": "item", "id": "tvwireless", "title": "Open wireless display (Miracast)",
                         "detail": "Opens GNOME Network Displays: pick your TV in its list."})
        else:
            rows.append(self._info("For wireless Miracast, install GNOME Network Displays (in a Terminal:  flatpak install flathub org.gnome.NetworkDisplays) "
                                   "- then this page gets an Open button."))
        rows.append({"kind": "item", "id": "tvrefresh", "title": "Refresh"})
        rows.append(self._info("Not tested on a real TV here: the screen switching is the standard xrandr command, and wireless depends on your TV."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _tv_apply(self, mode: str) -> str:
        outs = screentv.xrandr_outputs()
        if outs is None:
            self._tv_msg = "Screen switching is not possible here (needs X11 and xrandr)."
            return "refresh"
        inner, tv = screentv.pick(outs)
        cmd = screentv.commands(mode, inner, tv)
        if not cmd:
            self._tv_msg = "No TV found to switch to."
            return "refresh"
        undo = screentv.undo_command(outs)
        ok, err = screentv.run(cmd)
        kiosk.log_event(f"screen to tv {mode}: {ok} {' '.join(cmd)} {err}")
        if not ok:
            self._tv_msg = "The screen could not be switched: " + (err or "xrandr said no") + "."
            return "refresh"
        self._tv_msg = {"mirror": "Same picture on both screens.", "tv": "Showing on the TV only.", "here": "Showing on this screen only."}[mode]
        if mode != "here" and undo:
            self._tv_undo = undo
            self._tv_until = time.monotonic() + screentv.REVERT_SECONDS
            self._tv_timer.start()
        return "refresh"

    def _tv_tick(self) -> None:
        if self._tv_undo and time.monotonic() >= self._tv_until:
            self._tv_revert("Nobody pressed Keep, so the screens were put back.")
        if self._page_visible("screentv"):
            self.pageChanged.emit()
        if not self._tv_undo:
            self._tv_timer.stop()

    def _tv_revert(self, why: str) -> None:
        cmd, self._tv_undo = self._tv_undo, []
        if cmd:
            ok, err = screentv.run(cmd)
            kiosk.log_event(f"screen to tv undo: {ok} {' '.join(cmd)} {err}")
            self._tv_msg = why if ok else "Could not put the screens back: " + err

    def _tv_activate(self, rid: str) -> str:
        if rid in ("tvmirror", "tvonly", "tvhere"):
            return self._tv_apply({"tvmirror": "mirror", "tvonly": "tv", "tvhere": "here"}[rid])
        if rid == "tvkeep":
            self._tv_undo = []
            self._tv_msg = "Kept."
            return "refresh"
        if rid == "tvundo":
            self._tv_revert("Put back.")
            return "refresh"
        if rid == "tvwireless":
            cmd = screentv.wireless_app()
            if cmd:
                try:
                    subprocess.Popen(cmd, env=launcher.clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
                    self._tv_msg = "Opened the wireless display app - pick your TV there."
                    self._hide_for_wireless()
                except OSError as exc:
                    self._tv_msg = f"Could not open it: {exc}"
            return "refresh"
        if rid == "tvrefresh":
            self._tv_msg = ""
            return "refresh"
        return ""

    def _hide_for_wireless(self) -> None:
        if self._window is not None and not os.environ.get("ATARI_NO_MINIMIZE"):
            self._window.showMinimized()

    # ----- Controllers page ---------------------------------------------------------------------
    def _controllers_rows(self) -> list:
        self._ct_seen = time.monotonic()
        found = pads.detect()
        rows: list = []
        if self._ct_msg:
            rows.append(self._info("Result:  " + self._ct_msg))
        if not found:
            rows.append(self._info("No gamepad found. Plug it in (or pair it in Bluetooth settings), wait a few seconds, then press Refresh."))
            rows.append(self._info("A pad that is found by Linux but not usable? Settings > Fix Steam controller / gamepad permissions."))
        else:
            rows.append(self._info(f"{len(found)} gamepad{'s' if len(found) != 1 else ''} found by Linux (first one = player 1):"))
        for i, p in enumerate(found[:4]):
            rows.append({"kind": "item", "id": "ctpad", "title": f"Player {i + 1}:  {p.name}", "value": p.how,
                         "detail": f"Device {p.js}, vendor:product {p.ids}.  SDL id (what xemu stores): {p.guid}"})
        if found and not self._sdl_pads:
            rows.append(self._info("CodeAque's own button reader has not reported a standard gamepad yet. Press a button; if the test below stays "
                                   "empty, this pad is not a standard Xbox-style pad (a wheel, flight stick or arcade stick can need setting up inside xemu)."))
        cur = xemuconfig.read_pad()
        if cur["file"]:
            now = (f"{cur['driver'] or '(none)'} / {cur['guid'] or 'xemu picks the pad itself'}")
            rows.append(self._info(f"xemu's settings now ({cur['file']}):  player 1 = {now};  automatic binding "
                                   + {True: "ON", False: "OFF", None: "not set (xemu's default is ON)"}[cur["auto_bind"]]))
        else:
            rows.append(self._info("xemu has no settings file yet (it makes one the first time it starts). Setting up the pad creates the pad part of it."))
        for i, p in enumerate(found[:4]):
            title = "Set up pad for xemu" if len(found) == 1 else f"Set up '{p.name}' as player 1 for xemu"
            rows.append({"kind": "done", "id": f"ctxemu:{i}", "title": title,
                         "detail": "Writes this pad as player 1 (an Xbox controller) into xemu's settings and keeps xemu's automatic binding on. "
                                   "A copy of the old settings file is kept once. Close xemu first."})
        rows.append({"kind": "item", "id": "ctbt", "title": "Pair a Bluetooth controller",
                     "detail": "Search, pair and connect a wireless pad, with steps for putting it into pairing mode."})
        for b in self._pad_batt:
            rows.append(self._info(f"Battery:  {b['name']}  -  {b['text']}" + ("  (LOW - charge it soon)" if b.get("low") else "")))
        left = int(self._pad_test_until - time.monotonic())
        if left > 0:
            rows.append({"kind": "item", "id": "ctstop", "title": f"Testing: press buttons on the pad ({left} s left). Press here (keyboard / mouse) to stop",
                         "detail": "While testing, the pad does not move CodeAque's menus."})
        else:
            rows.append({"kind": "item", "id": "cttest", "title": "Test buttons (20 seconds)",
                         "detail": "Shows each button and stick you press, live. While testing, the pad does not move CodeAque's menus - "
                                   "use the keyboard or mouse to stop early."})
        if self._pad_events:
            for t in self._pad_events:
                rows.append(self._info("   " + t))
        elif left > 0:
            rows.append(self._info("   (nothing pressed yet)"))
        rows.append({"kind": "item", "id": "ctrefresh", "title": "Refresh"})
        rows.append(self._info("Honest note: CodeAque can write the settings and show what the pad sends, but it cannot run xemu for you here. "
                               "If the pad does not work in xemu afterwards, open xemu > Machine > Input and pick the pad there (xemu's own screen), "
                               "and tell us which pad it was. Not tested with real pads on every model; PlayStation pads over Bluetooth and "
                               "8BitDo pads are the likeliest to need that."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _controllers_activate(self, rid: str) -> str:
        if rid.startswith("ctxemu:"):
            found = pads.detect()
            try:
                p = found[int(rid.split(":")[1])]
            except (ValueError, IndexError):
                self._ct_msg = "That pad is no longer plugged in. Press Refresh."
                return "refresh"
            ok, files, text = xemuconfig.set_pad(p.guid)
            self._ct_msg = (f"{p.name} is now player 1 in xemu. " if ok else "") + text + (" Written: " + ", ".join(files) if files else "")
            kiosk.log_event(f"xemu pad setup: {ok} {p.name} {p.guid} {files}")
            if ok and files:                                  # read it back so the page shows what is really in the file
                self._ct_msg += " (read back: " + xemuconfig.read_pad()["guid"] + ")"
            return "refresh"
        if rid == "ctbt":
            return "page:btpair"
        if rid == "cttest":
            self._pad_events = []
            self._pad_test_until = time.monotonic() + 20
            self._pad_timer.start()
            return "refresh"
        if rid == "ctstop":
            self._pad_test_until = 0.0
            return "refresh"
        if rid == "ctrefresh":
            self._ct_msg = ""
            return "refresh"
        return ""

    # ----- Start mode: Linux desktop or CodeAque only ----------------------------------------
    def _startmode_rows(self) -> list:
        lay = self._kiosk_layout
        if self._kiosk_busy:
            return [self._info("Working - CodeAque asks for your password on this screen first..."), {"kind": "item", "id": "back", "title": "Back"}]
        rows: list = []
        if self._kiosk_msg:
            rows.append(self._info("Result:  " + self._kiosk_msg))
        mode = kiosk.read_mode(lay)
        nxt = mode["next"]
        if self._sm_changed:
            rows.append(self._info("The change is saved. It takes effect after you log out or restart - choose below."))
            rows.append({"kind": "item", "id": "smlogout", "title": "Log out now",
                         "detail": "No password. You come back to the " + ("Linux Mint login." if self._sm_changed == "desktop" else "computer's login, which then starts CodeAque.")})
            rows.append({"kind": "item", "id": "smreboot", "title": "Restart the computer now",
                         "detail": "Asks once more, with No highlighted."})
            rows.append({"kind": "item", "id": "back", "title": "Later (I will restart myself)"})
        rows += [self._info("Read back from the computer just now:  " + t) for t in mode["lines"]]
        rows.append(self._info("Choose how this computer starts. Your games, saves and settings are never touched; CodeAque stays installed either way."))
        rows.append({"kind": "done", "id": "smdesktop", "title": "Use Linux desktop",
                     "value": "SELECTED" if nxt == "desktop" else "",
                     "detail": "Normal Linux Mint login and desktop at start-up. CodeAque goes into the Mint menu and onto the desktop. "
                               "Asks for your password once; a backup of the old files is kept."})
        rows.append({"kind": "done", "id": "smconsole", "title": "Use CodeAque only (console mode)",
                     "value": "SELECTED" if nxt == "console" else "",
                     "detail": "The computer starts straight into CodeAque, like a games console, with no Mint desktop. Asks for your password once."})
        if mode["running"] == "console":
            rows.append({"kind": "item", "id": "smonce", "title": "Open the Mint desktop once (log out now)",
                         "detail": "No password. This login only - the next start is CodeAque again."})
        if nxt == "desktop":
            have = branding.launchers_present()
            rows.append({"kind": "item", "id": "smlaunchers", "title": "Put CodeAque on the desktop and in the Mint menu",
                         "value": "Both there" if all(have.values()) else "",
                         "detail": "Menu: " + ("yes" if have["menu"] else "missing") + ".  Desktop icon: " + ("yes" if have["desktop"] else "missing")
                                   + ".  Press to add whatever is missing (never replaces other programs' files)."})
        rows.append(self._info("If something goes wrong: " + kiosk.RECOVERY))
        rows.append(self._info("To go back to the Linux desktop by hand, in a Terminal:  sudo rm /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf  and restart."))
        rows.append(self._info("To turn console mode on again by hand (from the backup):  " + kiosk.restore_backup_command(lay)
                               + "  or the repair line:  " + kiosk.RESTORE_COMMAND))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _startmode_activate(self, rid: str) -> str:
        if rid in ("smdesktop", "smconsole"):
            if self._kiosk_busy:
                return ""
            lay = self._kiosk_layout
            mode = kiosk.read_mode(lay)
            want = "desktop" if rid == "smdesktop" else "console"
            if mode["next"] == want and not mode["leftovers"]:
                self.show_toast("It is already set that way. Nothing was changed.", 6000)
                return ""
            self._kiosk_busy = True
            self._kiosk_msg = ""
            self._sm_changed = ""
            self.show_toast("Type your password in the box that opens on this screen ...", 6000)

            def work():
                try:
                    if want == "desktop":
                        done, msg = kiosk.disable(lay)
                        if done:
                            added = branding.ensure_launchers(desktop=True)
                            msg += (" CodeAque was added to " + " and ".join(added) + ".") if added else ""
                    else:
                        done, msg = kiosk.enable(lay)
                    after = kiosk.read_mode(lay)["next"]             # read it back from the files, do not trust the exit code alone
                    if done and after != want:
                        done, msg = False, "The change did not take: the files say \"" + after + "\". " + msg
                    elif done:
                        msg += " Read back: next start is " + ("the Linux desktop." if after == "desktop" else "CodeAque only.")
                    if done:
                        self._sm_changed = want
                except Exception as exc:  # pragma: no cover
                    done, msg = False, f"The change hit a problem: {exc}"
                studio_fix.log(f"start mode {want}: ok={done} {msg}")
                self.kioskDone.emit(done, msg)
            threading.Thread(target=work, daemon=True, name="atari-startmode").start()
            return "refresh"
        if rid == "smlogout":
            ok, msg = kiosk.log_out()
            self.show_toast(msg, 8000)
            return ""
        if rid == "smreboot":
            self._power_pending = "reboot"
            return "page:power"
        if rid == "smonce":
            done, msg = kiosk.open_desktop_once()
            self.show_toast(msg, 8000)
            return ""
        if rid == "smlaunchers":
            added = branding.ensure_launchers(desktop=True)
            have = branding.launchers_present()
            self._kiosk_msg = ("Added to " + " and ".join(added) + "." if added else "Nothing to add.") + \
                f" Read back: menu {'yes' if have['menu'] else 'NO'}, desktop icon {'yes' if have['desktop'] else 'NO'}."
            self.pageChanged.emit()
            return "refresh"
        return ""

    # ----- Power menu ------------------------------------------------------------------
    @Slot()
    def powerReset(self) -> None:
        self._power_pending = ""

    def _power_rows(self) -> list:
        pend = self._power_pending
        if pend == "desktop":
            return [self._info("Quit to the Linux desktop?  CodeAque closes and the Linux Mint desktop opens for this login only (no password). "
                               "The next time the computer starts, it goes straight into CodeAque again."),
                    {"kind": "item", "id": "power_no", "title": "No, stay in CodeAque"},
                    {"kind": "item", "id": "power_yes", "title": "Yes, quit to the Linux desktop"}]
        if pend:
            what, _ = power.ACTIONS[pend]
            return [self._info(f"Really {what}?  Anything you are playing that is not saved will be lost."),
                    {"kind": "item", "id": "power_no", "title": "No, go back"},          # first: a stray Enter cancels
                    {"kind": "item", "id": "power_yes", "title": "Yes, " + what + " now"}]
        return [{"kind": "item", "id": "power_restartcode", "title": "Restart CodeAque" if kiosk.in_session() else "Restart CodeAque (close it and open it again)",
                 "detail": "Starts CodeAque again. Your games keep their settings and play time."},
                *([] if kiosk.in_session() else [{"kind": "item", "id": "power_quitcode", "title": "Quit CodeAque"}]),
                *([{"kind": "item", "id": "power_desktop", "title": "Quit to the Linux desktop",
                    "detail": "Opens the normal Mint desktop for this login only. The next start is CodeAque again."}] if kiosk.in_session() else []),
                {"kind": "item", "id": "power_reboot", "title": "Restart device", "detail": "Restarts the whole computer (asks first)."},
                {"kind": "item", "id": "power_poweroff", "title": "Shut down", "detail": "Turns the computer off (asks first)."},
                {"kind": "item", "id": "power_suspend", "title": "Sleep", "detail": "Suspends the computer; press the power button to wake it."},
                {"kind": "item", "id": "back", "title": "Back"}]

    def _power_activate(self, rid: str) -> str:
        if rid == "power_restartcode":
            self.restartCode()
            return ""
        if rid == "power_quitcode":
            self.quit()
            return ""
        if rid == "power_desktop":
            self._power_pending = "desktop"
            return "page:power"
        if rid == "power_yes" and self._power_pending == "desktop":
            self._power_pending = ""
            if self._demo:
                self.show_toast("Demo mode: nothing happens.")
                return "close"
            done, msg = kiosk.open_desktop_once()
            kiosk.log_event("quit to desktop: " + msg)
            self.show_toast(msg, 10000)
            return "close"
        if rid in ("power_reboot", "power_poweroff"):
            self._power_pending = rid[len("power_"):]
            return "page:power"          # reopen the page: the highlight goes to the first row, "No, go back" (a refresh would keep the old row = Yes)
        if rid == "power_no":
            self._power_pending = ""
            return "page:power"
        if rid in ("power_yes", "power_suspend"):
            action = self._power_pending if rid == "power_yes" else "suspend"
            self._power_pending = ""
            if action not in power.ACTIONS:
                return "page:power"
            self.doPower(action)
            return "close"
        return ""

    @Slot()
    def restartCode(self) -> None:
        """In the CodeAque-only session the session program starts CodeAque again when it ends; otherwise CodeAque starts itself again."""
        if self._demo:
            self.show_toast("Demo mode: nothing restarts.")
        elif kiosk.in_session():
            self.quit()
        else:
            self.restartAtari()

    @Slot(str)
    def doPower(self, action: str) -> None:
        """Restart / shut down / sleep, after the screen's own Yes (sleep needs none). Runs in the background; says what happened."""
        if action not in power.ACTIONS:
            return
        if self._demo:
            self.show_toast("Demo mode: the computer is left alone.")
            return
        self.show_toast(power.ACTIONS[action][1], 8000)

        def work():
            ok, text = self._power_run(action)
            studio_fix.log(f"power {action}: ok={ok} {text}")
            if not ok:
                self.powerFailed.emit(text)
        threading.Thread(target=work, daemon=True, name="atari-power").start()

    @Slot(str)
    def _on_power_failed(self, text: str) -> None:
        self.show_toast(text, 14000)

    # ----- Quiet boot (hide the Mint branding) ----------------------------------------
    def _quietboot_rows(self) -> list:
        lay = self._qb_layout
        if self._qb_busy:
            return [self._info("Working - CodeAque asks for your password on this screen first; then rebuilding the boot menu and boot image "
                               "takes up to a minute. Do not press anything."),
                    {"kind": "item", "id": "noop", "title": "Working ..."}]
        rows: list = []
        if self._qb_msg:                                      # a result is always on the screen until the page is left
            rows.append(self._info(("DONE:  " if self._qb_ok else "FAILED:  ") + self._qb_msg))
        tail = kiosk.log_tail(3)
        if self._qb_msg and tail:
            rows.append(self._info("Log (" + str(kiosk.session_log_path()) + "):  " + "  /  ".join(tail)))
        facts = self._qb_facts()
        rows.append(self._info("WHAT IS APPLIED RIGHT NOW (read back from the files, not assumed):  " + quietboot.status_summary(facts)))
        for f in facts:
            rows.append(self._info({"ok": "OK   ", "bad": "NOT APPLIED   ", "info": "Note   "}[f.state] + f.text))
        if quietboot.enabled(lay):
            hidden = quietboot.marker_hide(lay)
            if hidden is False:
                rows += [self._info("Quiet boot is ON for the logo and the start-up text only. The boot menu was NOT hidden, because another system looked present "
                                    "(on a Dell this is often a leftover recovery partition, not Windows)."),
                         {"kind": "done", "id": "qbforce", "title": "Hide the boot menu too",
                          "detail": "Only if you do not use Windows / another system on this computer any more. Shift / Esc still shows the menu."}]
            else:
                rows.append(self._info("Quiet boot is ON: no boot menu, no Mint logo, the CodeAque logo on black, hardly any text."))
            rows += [self._info(quietboot.HOW_TO_SHOW_MENU),
                     {"kind": "done", "id": "qboff", "title": "Turn quiet boot off (Mint's boot screens come back)",
                      "detail": "Asks for your password on this screen. Removes exactly the files quiet boot added."},
                     self._info(quietboot.RECOVERY)]
        else:
            checks = quietboot.preflight(lay, logo=quietboot.logo_path())
            why = quietboot.blocked(checks)
            rows += [self._info("Quiet boot replaces the Linux Mint start-up look with CodeAque's: the boot menu is hidden, the Mint logo screen becomes the "
                                "CodeAque logo on black, and the start-up text is switched off. Works best together with CodeAque-only mode."),
                     self._info("What changes (password once): a GRUB setting file, a boot-splash theme called \"code\", and a rebuild of the boot image "
                                "(update-grub, update-initramfs). Turning it off removes exactly those. " + quietboot.HOW_TO_SHOW_MENU),
                     self._info("Safe by design: the boot menu is NOT hidden when another system is really on the disk, Esc / Shift within 2 s at start-up still shows the menu "
                                "(it no longer pops up by itself after a power cut), recovery mode is untouched, and if anything fails CodeAque puts everything back and says which step failed.")]
            for c in checks:
                if not c.ok or "leftover" in c.text:
                    rows.append(self._info(("CANNOT CONTINUE: " if c.fatal else "Note: ") + c.text))
            if why:
                rows += self._qb_report_rows()
                rows.append({"kind": "item", "id": "back", "title": "Back"})
                return rows
            rows.append({"kind": "done", "id": "qbon", "title": "Yes, turn quiet boot ON", "detail": "CodeAque asks for your password on this screen. You can undo it any time."})
            if any(not c.ok and "Another system" in c.text for c in checks):
                rows.append({"kind": "item", "id": "qbforce", "title": "Turn it ON and hide the boot menu anyway",
                             "detail": "Only if no other system is on this disk (the entry above is a leftover). Shift / Esc still shows the menu."})
        rows += self._qb_report_rows()
        rows.append({"kind": "item", "id": "back", "title": "Back" if quietboot.enabled(lay) else "No, leave the boot screens as they are"})
        return rows

    def _qb_report_rows(self) -> list:
        rows = [{"kind": "item", "id": "qbreport", "title": "Copy boot report (saves a text file you can send)",
                 "detail": "Saves ~/Downloads/code-boot-report.txt: the boot menu settings, GRUB overrides and the firmware boot list. No passwords."}]
        if self._qb_report_msg:
            rows.append(self._info("Boot report:  " + self._qb_report_msg))
        rows.append(self._info(quietboot.BIOS_LOGO_NOTE))
        return rows

    def _qb_facts(self) -> list:
        """The read-back status, recomputed at most every 5 seconds (it lists the boot image)."""
        now = time.monotonic()
        cached = getattr(self, "_qb_facts_cache", None)
        if cached is None or now - cached[0] > 5.0:
            cached = (now, quietboot.status(self._qb_layout))
            self._qb_facts_cache = cached
        return cached[1]

    def _start_boot_report(self) -> None:
        if self._qb_report_busy:
            return
        self._qb_report_busy = True
        self._qb_report_msg = "Collecting ..."
        lay = self._qb_layout

        def work():
            try:
                text = quietboot.boot_report(lay, version=__version__)
                ok, msg, _f = quietboot.save_report(text)
            except Exception as exc:  # pragma: no cover - safety net
                ok, msg = False, f"Could not make the boot report: {exc}"
            kiosk.log_event(f"boot report: {'saved' if ok else 'FAILED'} - {msg}")
            self.bootReportDone.emit(ok, msg)
        threading.Thread(target=work, daemon=True, name="atari-bootreport").start()

    @Slot(bool, str)
    def _boot_report_finished(self, ok: bool, text: str) -> None:
        self._qb_report_busy = False
        self._qb_report_msg = text
        self.show_toast(text, 14000)
        self.pageChanged.emit()

    @Slot()
    def saveBootReport(self) -> None:
        """Settings row / Quiet boot page: write ~/Downloads/code-boot-report.txt."""
        self._start_boot_report()

    def _quietboot_activate(self, rid: str) -> str:
        if rid == "qbreport":
            self._start_boot_report()
            return "refresh"
        if rid in ("qbon", "qbforce", "qboff"):
            if self._qb_busy:
                return ""
            self._qb_busy = True
            self._qb_msg = ""
            lay = self._qb_layout
            self._qb_facts_cache = None
            self.show_toast("Type your password in the box that opens on this screen ...", 8000)

            def work():
                try:
                    if rid == "qboff":
                        done, msg = quietboot.disable(lay)
                    else:
                        done, msg = quietboot.enable(lay, force_hide=(rid == "qbforce"))
                except Exception as exc:  # pragma: no cover - safety net
                    done, msg = False, f"The change hit a problem: {exc}"
                studio_fix.log(f"quiet boot {rid}: ok={done} {msg}")
                kiosk.log_event(f"quiet boot {rid} finished: {'OK' if done else 'FAILED'} - {msg}")
                self.quietbootDone.emit(done, msg)
            threading.Thread(target=work, daemon=True, name="atari-quietboot").start()
            return "refresh"
        return ""

    @Slot(bool, str)
    def _quietboot_finished(self, ok: bool, text: str) -> None:
        self._qb_busy = False
        self._qb_facts_cache = None
        self._qb_ok = ok
        self._qb_msg = text
        self.show_toast(("Done: " if ok else "Failed: ") + text, 20000)
        self.pageChanged.emit()

    @Slot()
    def updateKioskSession(self) -> None:
        """The Settings row: the same one-password update as the button on the CodeAque-only page."""
        if kiosk.enabled(self._kiosk_layout):
            self._kiosk_activate("kioskupdate")

    def _kiosk_activate(self, rid: str) -> str:
        if rid in ("kioskon", "kioskoff", "kioskupdate", "kioskwm"):
            if self._kiosk_busy:
                return ""
            self._kiosk_busy = True
            self._kiosk_msg = ""
            lay = self._kiosk_layout
            self.show_toast("Type your password in the box that opens on this screen ...", 6000)

            def work():
                try:
                    if rid == "kioskwm":
                        done, msg = kiosk.install_wm()
                    else:
                        done, msg = (kiosk.disable(lay) if rid == "kioskoff" else kiosk.enable(lay))
                except Exception as exc:  # pragma: no cover - safety net
                    done, msg = False, f"The change hit a problem: {exc}"
                studio_fix.log(f"code-only mode {rid}: ok={done} {msg}")
                self.kioskDone.emit(done, msg)
            threading.Thread(target=work, daemon=True, name="atari-kiosk").start()
            return "refresh"
        if rid == "kioskonce":
            done, msg = kiosk.open_desktop_once()
            self.show_toast(msg, 8000)
            return ""
        return ""

    @Slot(bool, str)
    def _kiosk_finished(self, ok: bool, text: str) -> None:
        self._kiosk_busy = False
        self._kiosk_msg = text
        self.show_toast(text, 12000)
        self.pageChanged.emit()

    def _steam_rows(self) -> list:
        from . import steam as steam_mod
        have = self.steam_installed()
        rows = [self._info("Steam is installed." if have else
                           "Steam is not installed. One press installs it for you (Flatpak, no password; or your system's steam-installer package), "
                           "then opens it so you can sign in.")]
        if have:
            rows.append({"kind": "item", "id": "steamopen", "title": "Open Steam (sign in / install games there)"})
        else:
            rows.append({"kind": "done", "id": "steaminstall", "title": "Install Steam"})
        rows.append({"kind": "item", "id": "steamrescan", "title": "Rescan Steam",
                     "detail": "Use this after Steam installed a game, so it shows up in CodeAque."})
        if self._shell_mode():
            rows.append(self._info("CodeAque-only mode: Steam ALWAYS opens in Big Picture (from the tile, or started any other way). Use Big Picture's own "
                                   "menus for game Properties and Settings - the desktop Steam windows are not made for a TV and can open out of sight. "
                                   "Steam Play (Proton) is switched on for all games by default."))
            rows.append({"kind": "item", "id": "steamproton", "title": "Turn Steam Play (Proton) on for all games now",
                         "detail": "Needs Steam closed. Does nothing if you already picked a tool. Writes a backup first (config.vdf.code-backup)."})
        rows.append({"kind": "item", "id": "inputfix", "title": "Fix Steam controller / gamepad permissions",
                     "detail": "Use this if Steam says \"Missing permissions for input devices\". Installs Valve's controller rules (asks for your password once)."})
        rows.append(self._info("Where to keep Steam games: a Linux drive (ext4). Windows (NTFS) drives and USB sticks (exFAT / FAT) make many Proton games fail."))
        adv = steam_mod.drive_advice()
        for d in adv[:6]:
            rows.append({"kind": "info", "title": ("OK   " if d["ok"] else "AVOID   ") + d["text"]})
        if not adv:
            rows.append(self._info("No extra drives found. Plug one in, then in Steam: Steam > Settings > Storage > + > add the drive."))
        else:
            rows.append(self._info("To use another drive: in Steam open Steam > Settings > Storage, press + and choose the drive. Then press Rescan Steam here."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

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
            more = ("  - CodeAque found games in a folder it does not know: see Settings."
                    if self._lib.unknown and not self._demo else "")
            self.show_toast(f"Library updated: {n} game" + ("" if n == 1 else "s") + more)
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
            hint = ("".join(gamesroot.hint_text(self.cfg, u) + "\n\n" for u in self._lib.unknown[:3])
                    if self._lib.unknown else "")
            return ("No games yet!\n\n" + hint + "Choose \"Add Games\" to copy games from a USB stick, or open Settings "
                    "to add your Steam library and ROM folders.\n\n"
                    "Games you put in ~/Games/Atari/<system> (for example ~/Games/Atari/xbox) are found automatically "
                    "when you press Rescan.\n\n"
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
            for u in self._lib.unknown:
                if u.guess == sc.id:
                    folder += "\n\n" + gamesroot.hint_text(self.cfg, u) + "\n"
            return (f"No {sc.name} games yet.\n\nUse \"Add Games\" to import some, or put them in {folder}.\n\n"
                    f"Emulator: {label}" + ("" if _ready else "\n" + hint))
        return "No games here."

    # ----- actions ---------------------------------------------------------
    # ----- delete a game ------------------------------------------------------------
    @Slot(int, result=bool)
    def openDeleteGame(self, row: int) -> bool:
        """The Delete game page for this game. Returns False (with a toast) when it is not something CodeAque can delete."""
        g = self.model.game_at(row)
        if g is None:
            return False
        if gamedelete.kind_of(g) == "none":
            self.show_toast("CodeAque can only delete games from your games folders (and Windows games you added). "
                            "Use the other program to remove this one.", 6000)
            return False
        self._del_plan = gamedelete.plan_for(g, self.cfg)
        self._del_saves = False                      # saves are kept unless asked
        self._del_cover = False
        self._del_busy = False
        self._del_result = None
        return True

    def _about_rows(self) -> list:
        logo = branding.logo_file()
        row = {"kind": "item", "id": "aboutlogo", "title": f"{branding.NAME} {__version__}",
               "detail": branding.TAGLINE[0].upper() + branding.TAGLINE[1:]}
        if logo.is_file():
            row["image"] = QUrl.fromLocalFile(str(logo)).toString()
        return [row,
                self._info(f"{branding.NAME} is free and open source (MIT licence). It is a personal project and is not affiliated with any company."),
                self._info("It was called Code before. Nothing you set up is lost: the commands codeaque, code, atari and code-launcher all start it, "
                           "and your settings (~/.config/atari), data (~/.local/share/atari) and games (~/Games/Atari, ~/Games/Code, ~/Games/CodeAque) stay where they are."),
                self._info("The logo is original artwork by the project owner, made with AI tools. The picture CodeAque ships is 1254 pixels wide at most: sharp on a TV, "
                           "too small for large prints or metal stickers."),
                self._info("CodeAque never includes or downloads BIOS files, firmware, keys or games."),
                {"kind": "item", "id": "aboutsupport", "title": donate.TITLE, "detail": "Optional. Opens the donate page in a web browser."},
                {"kind": "item", "id": "back", "title": "Back"}]

    def _delete_rows(self) -> list:
        pl = self._del_plan
        if pl is None:
            return [self._info("Nothing to delete."), {"kind": "item", "id": "back", "title": "Back"}]
        if self._del_busy:
            return [self._info(f"Deleting {pl.title} ... please wait. Large games take a moment.")]
        if self._del_result is not None:
            r = self._del_result
            return [self._info(("DONE:  " if r.ok else "PROBLEM:  ") + r.text), {"kind": "done", "id": "back", "title": "Back to my games"}]
        rows: list = []
        if pl.kind == "steam":
            rows += [self._info(f"\"{pl.title}\" is a Steam game."), self._info(pl.message),
                     {"kind": "item", "id": "delno", "title": "No, go back", "detail": "Nothing is changed."},
                     {"kind": "done", "id": "delsteam", "title": "Open Steam to uninstall it",
                      "detail": "Opens Steam's own uninstall window (starts Steam if needed). CodeAque deletes nothing."}]
            return rows
        if not pl.removable:
            return [self._info(f"\"{pl.title}\" cannot be deleted from here."), self._info(pl.message),
                    {"kind": "item", "id": "back", "title": "Back"}]
        rows.append(self._info(f"Delete \"{pl.title}\" ({pl.system})?"))
        if pl.deletable:
            what = "folder" if pl.folder else "file"
            rows.append(self._info(f"The game {what}: {pl.where}"))
            rows.append(self._info(f"Size: {pl.size_text()}.  This cannot be undone."
                                   + ("  Everything inside the folder goes, including any saves kept in it." if pl.folder else "")))
        else:
            rows.append(self._info(pl.message))
        rows.append({"kind": "item", "id": "delno", "title": "No, keep it", "detail": "Nothing is changed."})
        if pl.saves:
            rows.append({"kind": "item", "id": "delsaves", "title": "Its save files next to the game: " + ("DELETE them too" if self._del_saves else "KEEP them"),
                         "detail": f"{len(pl.saves)} file{'s' if len(pl.saves) != 1 else ''}, {importer.human_size(pl.saves_size)}. Press to change. "
                                   "Saves an emulator keeps in its own folders are never touched."})
        if pl.cover is not None and pl.deletable:
            rows.append({"kind": "item", "id": "delcover", "title": "Its cover picture: " + ("DELETE it too" if self._del_cover else "KEEP it"),
                         "detail": f"{pl.cover.name}, {importer.human_size(pl.cover_size)}. Press to change."})
        rows.append({"kind": "done", "id": "delyes", "title": "Yes, delete it" if pl.deletable else "Yes, remove it from CodeAque",
                     "detail": "Only files inside your games folders are deleted." if pl.deletable else "Its files stay where they are."})
        return rows

    def _delete_activate(self, rid: str) -> str:
        pl = self._del_plan
        if self._del_busy:
            return ""
        if rid == "back":
            return "close"
        if pl is None or rid == "delno":
            return "close"
        if rid == "delsaves":
            self._del_saves = not self._del_saves
            return "refresh"
        if rid == "delcover":
            self._del_cover = not self._del_cover
            return "refresh"
        if rid == "delsteam" and pl.kind == "steam":
            try:
                big = self._shell_mode()
            except Exception:
                big = False
            ok, text = gamedelete.open_steam_uninstall(self.cfg, pl.appid, big_picture=big) if not os.environ.get("ATARI_NO_STEAM_SPAWN") \
                else (True, "(Steam start skipped)")
            self.show_toast(text, 9000)
            self._del_result = gamedelete.Result(ok, text)
            return "refresh"
        if rid == "delyes" and pl.removable:
            self._del_busy = True
            cfg, saves, cover = self.cfg, self._del_saves, self._del_cover

            def work():
                try:
                    res = gamedelete.delete(pl, cfg, saves, cover)
                except Exception as exc:  # pragma: no cover - never leave the page stuck on "Deleting"
                    res = gamedelete.Result(False, f"Something went wrong: {exc}")
                self.deleteFinished.emit(res)
            threading.Thread(target=work, daemon=True, name="atari-delete").start()
            return "refresh"
        return ""

    @Slot(object)
    def _on_delete_finished(self, res) -> None:
        pl = self._del_plan
        self._del_busy = False
        self._del_result = res
        if pl is not None and (res.deleted or res.ok):
            self.store.games.pop(pl.gid, None)           # forget favourite / recent / play time of a game that is gone
            self.store.save()
        self.rescan(toast=False)
        self.show_toast(res.text, 9000)
        self.pageChanged.emit()

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
        if g.gid == "tool:recordings":
            self.pageRequested.emit("recordings")
            return
        if g.gid == "tool:record" and not g.missing:
            self.toggleRecording()
            return
        if self._demo:
            self.show_toast("Demo mode: nothing to launch.")
            return
        if g.missing:                      # the program is not installed: offer to install it (one press)
            self.begin_install([g.missing], for_gid=g.gid, what=g.title)
            return
        self._launch_game(g)

    @Slot()
    def supportCode(self) -> None:
        """Settings / Options > Support CodeAque: open the donate page (donate.DONATE_URL) in the web browser. Only ever on a button press."""
        if self._running:
            return
        ok, _text = webapps.status(self.cfg, webapps.SUPPORT)
        if not ok:
            self.show_toast("Support CodeAque opens a web page, and no web browser is installed yet. Install one in Options > Emulators > "
                            "Install emulators and apps, then try again. (Page: " + donate.DONATE_URL + ")", 12000)
            return
        self._launch_game(Game(gid=webapps.SUPPORT.gid, title=webapps.SUPPORT.title, platform=webapps.STREAMING,
                               platform_name=webapps.STREAMING_NAME, note=webapps.SUPPORT.note))

    def _launch_game(self, g) -> None:
        self.playSound("launch")
        if self.cfg.music and self._snd_enabled():
            self._snd_write("music off")        # the game gets the speakers
        self._running = True
        self._minimized_for_game = False       # never carry "CodeAque was minimised" over from an earlier launch (the window may have been
        self._run_playing = False              # brought back by hand); a stale flag kept CodeAque in front of the second launch
        self._running_appid = getattr(g, "steam_appid", "") or ""
        self._running_title = g.title
        self._running_gid = g.gid
        self._launch_cancel = threading.Event()
        self._run_status = ""
        self._run_cancelable = False
        self.runningStatusChanged.emit()
        self._running_is_rom = g.platform != "steam"
        if g.gid == "app:steam" or g.platform == "steam":
            if g.gid == "app:steam" and getattr(self, "_steam_guard", None) is not None:
                self._steam_guard.handled_by_code()
            if self._shell_mode() and not os.environ.get("ATARI_NO_STEAMFIX"):
                self._steam_prepare()
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
                cancel = self._launch_cancel
                secs, err = launcher.run_game(cfg, g, on_started=started, cancel=cancel,
                                              status=lambda phase, text: self.launchStatus.emit(phase, text))
            except launcher.LaunchError as exc:
                err = str(exc)
            except Exception as exc:  # pragma: no cover - safety net
                err = f"Something went wrong: {exc}"
            self.sessionEnded.emit(g.gid, g.title, secs, err)

        threading.Thread(target=worker, daemon=True).start()

    @Property(str, notify=runningHintChanged)
    def runningHint(self):
        return self._running_hint

    @Property(str, notify=runningStatusChanged)
    def runningStatus(self):
        return self._run_status

    @Property(bool, notify=runningStatusChanged)
    def runningCancelable(self):
        return self._run_cancelable and self._running

    @Slot(str, str)
    def _on_launch_status(self, phase: str, text: str) -> None:
        """Live progress of a Steam game start (Steam starting, asking, waiting, playing). In CodeAque-only mode CodeAque steps aside as soon as
        Steam's own windows may need to be seen (reveal) or the game is up (playing)."""
        if not self._running:
            return
        self._run_status = text
        self._run_cancelable = phase in ("starting", "launching", "waiting", "reveal")
        self._run_playing = phase == "playing"
        self.runningStatusChanged.emit()
        guard = getattr(self, "_steam_guard", None)
        if guard is not None and phase in ("starting", "launching"):
            guard.handled_by_code()                       # CodeAque itself is starting Steam: the watcher must not interfere
        if phase in ("reveal", "playing") and self._shell_mode() and self._window is not None and not os.environ.get("ATARI_NO_MINIMIZE"):
            self._hide_for_game()

    @Property(bool, notify=runningStatusChanged)
    def runningPlaying(self):
        """A Steam game is up (or was already running): the Now Playing screen offers 'Back to the game' and 'Stop waiting'."""
        return self._run_playing and self._running

    @Slot()
    def showGame(self) -> None:
        """Bring the running Steam game's window to the front (X11 only); says so when it cannot."""
        if not (self._running and self._run_playing and self._running_appid):
            return
        appid, title = self._running_appid, self._running_title

        def work():
            ok = launcher.bring_to_front(launcher.find_steam_pids(appid))
            kiosk.log_event(f"steam: bring {title} to the front: {'done' if ok else 'not possible'}")
            self.launchStatus.emit("playing", f"Playing {title}" + ("" if ok else
                                   "\nCodeAque could not bring the game to the front by itself (it needs xdotool or wmctrl, and X11). Use Alt+Tab."))
            if ok and self._shell_mode():
                QTimer.singleShot(0, self._hide_for_game)
        threading.Thread(target=work, daemon=True).start()

    @Property(bool, notify=runningStatusChanged)
    def runningSteam(self):
        return bool(self._running and getattr(self, "_running_appid", ""))

    @Slot(result=str)
    def copySteamLog(self) -> str:
        """Now Playing > Copy Steam log: CodeAque's Steam steps plus Steam's own log, to the clipboard and ~/CodeAque-steam-log.txt."""
        from . import steam as steam_mod
        text = steam_mod.steam_log_report(session_lines=kiosk.log_tail(2000))
        path = Path.home() / "CodeAque-steam-log.txt"
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            path = None
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
        except Exception:  # pragma: no cover
            pass
        kiosk.log_event("steam launch: Steam log copied" + (f" (saved to {path})" if path else ""))
        self.show_toast("Steam log copied - paste it in a message, or send the file " + (str(path) if path else "(could not save the file)") + ".", 9000)
        return str(path or "")

    @Slot()
    def cancelLaunch(self) -> None:
        """Esc / B / the Cancel button while a Steam game is starting: stop waiting and come back to CodeAque (Steam keeps running)."""
        if self._running and (self._run_cancelable or self._run_playing):
            kiosk.log_event("steam launch: cancel pressed on the Now Playing screen" + (" (game running: stop waiting for it)" if self._run_playing else ""))
            self._launch_cancel.set()
            self._run_status = "Cancelling..."
            self._run_cancelable = False
            self._run_playing = False
            self.runningStatusChanged.emit()

    @Slot()
    def _on_session_started(self) -> None:
        """The emulator process is up. CodeAque's own (full screen) window must not sit between the keyboard and the
        emulator, so after a moment it is minimised; it comes back when the game ends."""
        steam_here = self._shell_mode() and getattr(self, "_running_gid", "") == "app:steam"
        if (getattr(self, "_running_is_rom", False) or steam_here) and not os.environ.get("ATARI_NO_MINIMIZE") and self._window is not None:
            self._hide_timer.start()               # (Steam: its dialogs - Properties, Settings - must not open behind CodeAque's full screen window)

    def _hide_for_game(self) -> None:
        if self._running and self._window is not None and self._window.visibility() != QWindow.Minimized:
            self._minimized_for_game = True
            self._window.showMinimized()

    # ----- in-app text / password dialog (no pkexec window: there is no desktop in CodeAque-only mode) ---------------------
    def ask_text(self, title: str, prompt: str, secret: bool, initial: str, error: str, callback) -> None:
        """Show CodeAque's on-screen-keyboard dialog. callback(text | None) runs on the GUI thread; None = cancelled. Safe from any thread."""
        self._input_queue.append([title, prompt, bool(secret), initial, error, callback])
        self.inputRequested.emit()

    def ask_text_blocking(self, title: str, prompt: str, secret: bool = False, initial: str = "", error: str = "", timeout: float = 600.0):
        """For worker threads: waits for the dialog. Returns the text, or None when cancelled / nobody answered."""
        done = threading.Event()
        box: list = [None]

        def cb(text):
            box[0] = text
            done.set()
        self.ask_text(title, prompt, secret, initial, error, cb)
        if not done.wait(timeout):
            self._input_timeout(cb)
        return box[0]

    def _input_timeout(self, cb) -> None:
        self._input_queue = [r for r in self._input_queue if r[5] is not cb]
        if self._input_cur is not None and self._input_cur[5] is cb:
            self._input_cur = None
            self.inputChanged.emit()

    @Slot()
    def _input_next(self) -> None:
        if self._input_cur is None and self._input_queue:
            self._input_cur = self._input_queue.pop(0)
            self.inputChanged.emit()

    @Property(bool, notify=inputChanged)
    def inputActive(self):
        return self._input_cur is not None

    @Property(str, notify=inputChanged)
    def inputTitle(self):
        return self._input_cur[0] if self._input_cur else ""

    @Property(str, notify=inputChanged)
    def inputPrompt(self):
        return self._input_cur[1] if self._input_cur else ""

    @Property(bool, notify=inputChanged)
    def inputSecret(self):
        return bool(self._input_cur and self._input_cur[2])

    @Property(str, notify=inputChanged)
    def inputInitial(self):
        return self._input_cur[3] if self._input_cur else ""

    @Property(str, notify=inputChanged)
    def inputError(self):
        return self._input_cur[4] if self._input_cur else ""

    @Slot(str)
    def submitInput(self, text: str) -> None:
        self._input_finish(text)

    @Slot()
    def cancelInput(self) -> None:
        self._input_finish(None)

    def _input_finish(self, text) -> None:
        cur, self._input_cur = self._input_cur, None
        self.inputChanged.emit()
        if cur is not None:
            try:
                cur[5](text)                          # (a password is handed over here and nowhere else: never logged, never stored)
            except Exception as exc:  # pragma: no cover - a broken callback must not freeze the dialog queue
                kiosk.log_event(f"input dialog callback failed: {type(exc).__name__}")
        if self._input_queue:
            self._input_next()


    # ----- file viewer: ~/Downloads, ~/Games, ~/Videos -------------------------------------
    def _fm_home(self) -> Path:
        return Path.home()

    def _fm_set_msg(self, ok: bool, text: str) -> None:
        self._fm_ok, self._fm_msg = ok, text
        kiosk.log_event(f"files: {'OK' if ok else 'FAILED'} - {text}")

    @Slot()
    def filesReset(self) -> None:
        self._fm_dir, self._fm_pick, self._fm_msg = None, None, ""

    def _fm_busy_rows(self) -> list:
        """While an unpack runs in the background: what it is doing, a percentage bar with the current file, and a Cancel button."""
        pr = self._fm_prog
        frac = pr.fraction if pr is not None else None
        rows = [self._info(self._fm_busy)]
        rows.append({"kind": "progress", "title": (pr.name if pr is not None and pr.name else "Getting ready ..."),
                     "fraction": -1.0 if frac is None else float(frac), "value": (pr.percent_text if pr is not None else "") or "",
                     "detail": (pr.detail if pr is not None else "")})
        rows.append({"kind": "item", "id": "fmcancel", "title": "Cancel  (Esc / B)", "detail": "Stops unpacking and removes the half-made folder."})
        return rows

    def _files_rows(self) -> list:
        rows: list = []
        if self._fm_busy:
            return self._fm_busy_rows()
        if self._fm_msg:
            rows.append(self._info(("DONE:  " if self._fm_ok else "NOTE:  ") + self._fm_msg))
        home = self._fm_home()
        if self._fm_dir is None:
            places = files.places(home)
            self._fm_places = places
            rows.append(self._info("Your files: pick a place, then open any folder in it. Press Back (Esc / B) to go up one folder at a time. "
                                   "Downloads, Games and Videos can be changed here; the BIOS / emulator folders are look-only."))
            heads = {"main": "Main places", "games": "Games folders", "system": "Console folders inside your games folders", "look": "BIOS, emulator and CodeAque folders (look only)"}
            last = ""
            for i, pl in enumerate(places):
                if pl.group != last:
                    rows.append(self._info(heads[pl.group] + ":"))
                    last = pl.group
                rows.append({"kind": "item", "id": f"fmroot:{i}", "title": pl.label, "value": f"{pl.count} item" + ("" if pl.count == 1 else "s"),
                             "detail": f"{pl.path}" + ("" if pl.group == "look" else f"   -   {files.free_text(pl.path)}")})
            if not any(pl.group == "main" for pl in places):
                rows.append(self._info("None of ~/Downloads, ~/Games or ~/Videos exists yet. Download or add something first."))
            rows.append({"kind": "item", "id": "back", "title": "Back"})
            return rows
        d = self._fm_dir
        entries, more = files.list_dir(d)
        self._fm_items = entries
        look = files.is_look_only(d, home)
        top = files.is_top(d, home)
        rows.append(self._info("You are here:  " + files.breadcrumb(d, home)))
        rows.append(self._info(f"{d}   -   {files.free_text(d)}" + ("   -   look only: nothing here is changed by CodeAque" if look else "")))
        rows.append({"kind": "item", "id": "fmup", "title": "..  Up  (one folder)" if not top else "..  Up  (to the list of places)",
                     "detail": "Go back one folder." if not top else "Shows Downloads, Games, the games folders and the BIOS / emulator folders."})
        rows.append({"kind": "item", "id": "fmplaces", "title": "All places  (Downloads, Games, Videos, BIOS folders ...)",
                     "detail": "Jump to the list of every place you can open."})
        if not top and not look:
            rows.append({"kind": "item", "id": "fmhere", "title": "Actions for THIS folder (rename, delete, add to games)",
                         "detail": f"{d.name}"})
        if not entries:
            rows.append(self._info("This folder is empty."))
        for i, e in enumerate(entries):
            tag = "  (link)" if e.link else ""
            if e.is_dir:
                rows.append({"kind": "item", "id": f"fm:{i}", "title": e.name + "/" + tag, "value": f"{e.count} item" + ("" if e.count == 1 else "s"),
                             "detail": "Folder - press to open it."})
            else:
                what = {"zip": "Archive (zip)", "tar": "Archive (tar)", "7z": "Archive (7z)", "rar": "Archive (rar)", "video": "Video"}.get(e.kind, "File")
                if look:
                    extra = " - look only (press to see where it is)."
                else:
                    extra = " - press, then Extract here to unpack it." if e.kind in ("zip", "tar", "7z", "rar") else " - press for Open, Rename, Delete, Add to my games."
                rows.append({"kind": "item", "id": f"fm:{i}", "title": e.name + tag, "value": importer.human_size(e.size),
                             "detail": what + ", " + downloads.human_age(e.mtime) + extra})
        if more:
            rows.append(self._info(f"Only the first {files.LIST_CAP} items are shown."))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _files_activate(self, rid: str) -> str:
        home = self._fm_home()
        if self._fm_busy:
            if rid == "fmcancel":
                self._fm_cancel.set()
            return ""
        self._fm_msg = ""
        self._fm_pending_delete = False
        if rid.startswith("fmroot:"):
            try:
                self._fm_dir = self._fm_places[int(rid[7:])].path
            except (ValueError, IndexError, AttributeError):
                return "refresh"
            return "page:files"
        if rid == "fmplaces":
            self._fm_dir = None
            return "page:files"
        if rid == "fmup":
            d = self._fm_dir
            self._fm_dir = None if (d is None or files.is_top(d, home)) else d.parent
            return "page:files"
        if rid == "fmhere" and self._fm_dir is not None:
            self._fm_pick = self._fm_dir
            return "page:fileact"
        if rid.startswith("fm:"):
            try:
                e = self._fm_items[int(rid[3:])]
            except (ValueError, IndexError):
                return "refresh"
            if e.is_dir:
                self._fm_dir = e.path
                return "page:files"
            if files.is_look_only(e.path, home):
                self.show_toast(f"{e.path}  ({importer.human_size(e.size)}). This folder is look-only: CodeAque shows where the file is but does not change it.", 9000)
                return ""
            self._fm_pick = e.path
            return "page:fileact"
        return ""

    def _fileact_rows(self) -> list:
        p = self._fm_pick
        if p is None or not (p.exists() or p.is_symlink()):
            return [self._info("That file or folder is gone."), {"kind": "item", "id": "back", "title": "Back"}]
        rows: list = []
        if self._fm_msg:
            rows.append(self._info(("DONE:  " if self._fm_ok else "NOTE:  ") + self._fm_msg))
        if self._fm_busy:
            return rows + self._fm_busy_rows()
        isdir = p.is_dir()
        kind = "folder" if isdir else (files.archive_kind(p) or "file")
        size = files.folder_size(p) if isdir else p.stat().st_size
        rows.append(self._info(f"{p.name}   -   {importer.human_size(size)}   -   {p.parent}"))
        if self._fm_pending_delete:
            rows.append(self._info(f"Delete \"{p.name}\" for good?" + (" Everything inside it goes too." if isdir else "") + " This cannot be undone."))
            rows.append({"kind": "item", "id": "fmno", "title": "No, keep it"})
            rows.append({"kind": "item", "id": "fmyes", "title": "Yes, delete it"})
            return rows
        if kind in ("zip", "tar", "7z", "rar"):
            tool = files.missing_tool(kind)
            if tool:
                name = "7-Zip" if tool == "7zip" else "unrar"
                rows.append(self._info(f"Unpacking .{kind} files needs {name}. It is free and installs in one press (CodeAque asks for your password on this screen)."))
                rows.append({"kind": "done", "id": f"fminstall:{tool}", "title": f"Install {name}", "detail": "Then come back and press Extract here."})
            rows.append({"kind": "done", "id": "fmextract", "title": "Extract here  (unzip into a new folder)",
                         "detail": f"Makes the folder \"{files.archive_stem(p)}\" next to it. A password-protected archive asks for the password on this screen."})
        if isdir:
            rows.append({"kind": "item", "id": "fmopen", "title": "Open this folder", "detail": "Look inside."})
        else:
            rows.append({"kind": "item", "id": "fmopen", "title": "Open", "detail": "With the program set up for this kind of file (videos play full screen)."})
        if kind in ("zip", "tar", "7z", "rar"):
            rows.append({"kind": "item", "id": "fmbios", "title": "Use as BIOS pack",
                         "detail": "Unpacks it here with a progress bar, finds the BIOS / firmware files (including Xbox: BIOS, boot ROM, hard-disk image) "
                                   "and copies them to the right emulator folders. Only for files from your own consoles."})
        rows.append({"kind": "item", "id": "fmadd", "title": "Add to my games", "detail": "Pick the system; the file moves into that games folder."})
        rows.append({"kind": "item", "id": "fmrename", "title": "Rename", "detail": "Type a new name on this screen."})
        rows.append({"kind": "item", "id": "fmdelete", "title": "Delete", "detail": "Asks you to confirm first."})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _fileact_activate(self, rid: str) -> str:
        p = self._fm_pick
        if self._fm_busy:
            if rid == "fmcancel":
                self._fm_cancel.set()
            return ""
        if p is None:
            return "page:files"
        home = self._fm_home()
        if rid == "fmno":
            self._fm_pending_delete = False
            return "page:fileact"
        self._fm_msg = ""
        if rid == "fmopen":
            if p.is_dir():
                self._fm_dir, self._fm_pick = p, None
                return "page:files"
            ok, text = files.open_file(p, home=home)
            self._fm_set_msg(ok, text)
            self.show_toast(text, 6000)
            return "refresh"
        if rid == "fmadd":
            it = downloads.item_for(self.cfg, p)
            if it is None:
                self._fm_set_msg(False, "That file is gone.")
                return "refresh"
            self._dl_pick = it
            self._dl_from_files = True
            return "page:dlsystem"
        if rid == "fmrename":
            def done(text):
                if text is None:
                    return
                ok, msg = files.rename(p, text, home)
                if ok:
                    self._fm_pick = p.parent / text.strip()
                self._fm_set_msg(ok, msg)
                self.pageChanged.emit()
            self.ask_text("RENAME", f"New name for \"{p.name}\":", False, p.name, "", done)
            return ""
        if rid == "fmdelete":
            self._fm_pending_delete = True
            return "page:fileact"
        if rid == "fmyes":
            self._fm_pending_delete = False
            ok, text = files.delete(p, home)
            self._fm_set_msg(ok, text)
            if ok:
                self._fm_pick = None
                return "page:files"
            return "page:fileact"
        if rid.startswith("fminstall:"):
            tool = rid[10:]
            known = {a.id: a for a in list(apps.APP_DEFS) + list(apps.HELPERS)}
            if tool in known:
                self.begin_install([tool], for_gid=f"app:{tool}", what=known[tool].title)
            return ""
        if rid == "fmextract":
            self._fm_extract(p)
            return "refresh"
        if rid == "fmbios":
            return "import:biospick"
        return ""

    def _fm_extract(self, p: Path) -> None:
        self._fm_cancel = threading.Event()
        self._fm_busy = f"Unpacking {p.name} ..."
        self._fm_progress = ""
        self._fm_prog = None
        cancel = self._fm_cancel
        home = self._fm_home()
        last = [0.0]

        def progress(pr):
            now = time.monotonic()
            done = pr.fraction is not None and pr.fraction >= 1.0
            if now - last[0] < 0.15 and not done:             # the screen is redrawn at most ~7 times a second
                return
            last[0] = now
            self._fm_prog = dataclasses.replace(pr)             # a snapshot: the worker keeps changing its own
            self.filesEvent.emit("progress", True, "")

        def work():
            password, err = "", ""
            for _attempt in range(4):
                res = files.extract(p, password, progress, cancel, home=home)
                if res.needs_password:
                    err = "That password did not work. Try again." if password else ""       # a password was tried and failed
                    password = self.ask_text_blocking("ARCHIVE PASSWORD", f"{p.name} is protected. Type its password:", True, "", err) or ""
                    if not password:
                        self.filesEvent.emit("done", False, "No password was entered, so nothing was unpacked.")
                        return
                    continue
                self._fm_tool = res.needs_tool
                self.filesEvent.emit("done", res.ok, res.text)
                return
            self.filesEvent.emit("done", False, "The password did not work after several tries. Nothing was unpacked.")
        threading.Thread(target=work, daemon=True, name="atari-files").start()

    @Slot(str, bool, str)
    def _files_event(self, kind: str, ok: bool, text: str) -> None:
        if kind == "progress":
            pass                                            # the worker already stored self._fm_prog; just redraw
        else:
            self._fm_busy = ""
            self._fm_progress = ""
            self._fm_prog = None
            self._fm_set_msg(ok, text)
            self.show_toast(("Done: " if ok else "") + text, 9000)
            if ok:
                self.rescan(toast=False)
        self.pageChanged.emit()

    @Slot(str, result=str)
    def pageEscape(self, name: str) -> str:
        """Esc / B on a page: what to do. Most pages just close; the file viewer goes up one level."""
        if name == "deletegame" and self._del_busy:
            return ""
        if name == "fileact":
            if self._fm_busy:
                self._fm_cancel.set()
                return ""
            self._fm_pending_delete = False
            return "page:files"
        if name == "files":
            if self._fm_busy:
                self._fm_cancel.set()
                return ""
            if self._fm_dir is not None:
                self._fm_dir = None if files.is_top(self._fm_dir, self._fm_home()) else self._fm_dir.parent
                self._fm_msg = ""
                return "page:files"
        return "back"

    # ----- Steam in CodeAque-only mode: always Big Picture --------------------------------
    def _start_steam_guard(self) -> None:
        """CodeAque-only mode: a `steam` wrapper first in PATH, Steam's own start-up setting, Steam Play for all games, and a watcher that
        opens Big Picture on a Steam client that was started some other way."""
        self._steam_guard = steamfix.Guard()
        steamfix.put_shim_first(os.environ)
        threading.Thread(target=self._steam_prepare, daemon=True, name="atari-steamfix").start()
        self._steam_timer = QTimer(self, interval=3000)
        self._steam_timer.timeout.connect(self._steam_tick)
        self._steam_timer.start()

    def _steam_prepare(self) -> None:
        try:
            for line in steamfix.apply(self.cfg, bigpicture_start=not self._steam_autostart_on()):
                kiosk.log_event("steam: " + line)
        except Exception as exc:  # pragma: no cover - never let this touch CodeAque
            kiosk.log_event(f"steam: setup problem: {exc}")

    def _steam_tick(self) -> None:
        from . import steam as steam_mod
        guard = getattr(self, "_steam_guard", None)
        if guard is None or self._steam_busy:
            return
        try:
            running = steam_mod.steam_running()
        except Exception:
            return
        if self._running_gid == "app:steam" and running:
            guard.handled_by_code()
        if guard.tick(running, time.monotonic()):
            self._steam_busy = True
            threading.Thread(target=self._steam_nudge, daemon=True, name="atari-steamnudge").start()

    def _steam_nudge(self) -> None:
        try:
            cmd, how = apps.app_command(self.cfg, apps.BY_ID["steam"])
            if how and cmd:
                kiosk.log_event("steam: a Steam client CodeAque did not start is open - asking it for Big Picture")
                self._steam_run(cmd + ["steam://open/bigpicture"], env=launcher.clean_env(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=20)
        except Exception as exc:
            kiosk.log_event(f"steam: could not ask Steam for Big Picture: {exc}")
        finally:
            self._steam_busy = False

    def _shell_mode(self) -> bool:
        """CodeAque-only session, or CodeAque-only mode installed but this copy was started from the desktop (see kiosk.shell_mode)."""
        try:
            return kiosk.shell_mode(self._kiosk_layout)
        except Exception:  # pragma: no cover - never let a file check break the window logic
            return kiosk.in_session()

    def _log_window(self, why: str) -> None:
        win = self._window
        try:
            kiosk.log_event(f"{why}: window visible={win.isVisible()} active={win.isActive()} "
                            f"state={int(win.visibility())} shell_mode={self._shell_mode()} in_session={kiosk.in_session()}")
        except Exception:
            pass

    def _restore_window(self) -> None:
        win = self._window
        if win is None:
            return
        if self._minimized_for_game:
            self._minimized_for_game = False
            if self.cfg.fullscreen or self._shell_mode():
                win.showFullScreen()
            else:
                win.showNormal()
        elif self._shell_mode():
            win.showFullScreen()            # CodeAque-only: always take the whole screen back, whatever the app did to the window
        win.raise_()
        win.requestActivate()
        if not self._demo:
            kiosk.log_event(f"an app closed ({self._running_title or 'app'}): CodeAque takes the screen back")
            QTimer.singleShot(2000, lambda: self._log_window("2 s after the app closed"))
        # window managers sometimes ignore the first focus request right after a full-screen app closed: ask again
        for ms in ((300, 1000, 2500, 5000) if self._shell_mode() else (300, 1000)):       # CodeAque-only: nothing else may keep the screen
            QTimer.singleShot(ms, self._reactivate)

    def _reactivate(self) -> None:
        win = self._window
        if win is None or self._running:
            return
        try:
            if not win.isActive():
                win.raise_()
                win.requestActivate()
        except RuntimeError:       # the window is already gone (CodeAque is closing)
            pass

    @Slot(str, str, float, str)
    def _on_session_ended(self, gid: str, title: str, secs: float, err: str) -> None:
        if secs >= MIN_PLAYTIME_SEC:
            self.store.add_playtime(gid, secs)
        self._hide_timer.stop()
        self._running = False
        self._run_status = ""
        self._run_cancelable = False
        self._run_playing = False
        self.runningStatusChanged.emit()
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
        if gid == "app:roblox" and err and ("APK bundle" in err or "Permission Update Required" in err):      # Sober fell back to its file screen: show the step-by-step fix
            self._rbx_state = "idle"
            self.pageRequested.emit("robloxfix")

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
        rows = [{"kind": "info", "title": "Emulators are separate programs. CodeAque finds them automatically "
                                          "(installed programs and Flatpaks).", "value": "", "detail": ""},
                {"kind": "info", "title": "Press Enter on a console to switch between its emulators. "
                                          "CodeAque never includes BIOS, firmware, keys or games - bring your own.",
                 "value": "", "detail": ""},
                {"kind": "install", "title": "Install emulators and apps",
                 "value": "",
                 "detail": "Opens a window that installs every emulator and PC app CodeAque knows (safe to run again). "
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
            if ready and bstate == "missing":
                rows.append({"kind": "biosfindpage", "title": f"{sc.name}: Find my BIOS files", "value": "",
                             "detail": "Looks in Downloads (also inside archives) for this console's BIOS and copies it into place."})
            if sc.id == "xbox":
                rows.append({"kind": "xemupage", "title": "Xbox: check and repair xemu settings", "value": "",
                             "detail": "Shows exactly which BIOS, boot ROM and disk files xemu will use, fixes empty paths "
                                       "(\"Failed to open flash file ''\"), and can make an empty disk image."})
            if sc.id == "xbox" and bstate != "ok":
                for line in bios.xbox_guide():
                    rows.append({"kind": "info", "title": line, "value": "", "detail": ""})
        for app in apps.APP_DEFS:
            ready, text = apps.app_status(self.cfg, app)
            rows.append({"kind": "app", "title": app.title + "  (PC Apps)", "value": "Ready" if ready else "Not installed",
                         "detail": app.note if ready else text})
        b, how = webapps.find_browser(self.cfg)
        rows.append({"kind": "app", "title": "Streaming web apps  (browser)", "value": "Ready" if b else "Not installed",
                     "detail": (f"Open in {b.name}. " + ("Netflix & co. work." if b.drm else "Netflix & co. may not play (no Widevine) - use Chrome.")
                                if b else webapps.HELP_TEXT)})
        wok, wlabel = windows.runner_status(self.cfg)
        rows.append({"kind": "app", "title": "PC Games support", "value": "Ready" if wok else "Not installed",
                     "detail": ("Advanced: PC games run with " + wlabel + " (a Windows compatibility layer), each game in its own private folder.")
                               if wok else wlabel})
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
        self._cleanup_unpacked()
        self._imp_kind = "bios" if kind == "bios" else "games"
        self._imp_state = "drives"
        self._imp_msg = ""
        self._imp_source = ""
        self._imp_left, self._imp_groups, self._imp_group = [], [], []
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
        if self._imp_kind == "bios":
            rows.append({"kind": "pack", "title": "Choose a zipped BIOS pack...",
                         "detail": "A .zip, .7z, .rar or .tar file you made from your own consoles (also from a USB stick). CodeAque unpacks it "
                                   "here with a progress bar, copies the files each emulator needs and deletes the unpacked copy. "
                                   "You can also open the file in My files and choose \"Use as BIOS pack\".", "value": ""})
        rows.append({"kind": "close", "title": "Back", "detail": "", "value": ""})
        return rows

    @Slot(str)
    def startImportScan(self, path: str) -> None:
        if not path:
            return
        if self._imp_kind == "bios" and Path(path).is_file():
            self._start_bios_pack(Path(path))
            return
        self._imp_pack = ""
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

    # ----- BIOS packs (zip / 7z / rar / tar) -------------------------------------
    def _unpack_dir(self) -> Path:
        return paths.data_dir() / "bios-unpack"

    def _cleanup_unpacked(self) -> None:
        """Delete the unpacked copy of a BIOS pack (the files that mattered were copied to the emulators already)."""
        tmp, self._imp_tmp = self._imp_tmp, None
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        try:
            self._unpack_dir().rmdir()                            # CodeAque's own work folder, removed when empty
        except OSError:
            pass

    @Slot(str)
    def importBiosFromPick(self, path: str = "") -> None:
        """"Use as BIOS pack" in the My files viewer: opens the Add BIOS screen and unpacks that file."""
        p = Path(path) if path else self._fm_pick
        if p is None:
            return
        self._imp_kind = "bios"
        self.startImportScan(str(p))

    def _start_bios_pack(self, archive: Path) -> None:
        self._cleanup_unpacked()
        kind = files.archive_kind(archive)
        self._imp_source = str(archive)
        self._imp_pack = archive.name
        if not kind:
            self._imp_state = "drives"
            self._imp_msg = (f"\"{archive.name}\" is not a folder or a BIOS pack CodeAque can open (zip, tar, 7z, rar). "
                             "Pick the folder it is in instead, or unpack it first in My files.")
            self.importChanged.emit()
            return
        shutil.rmtree(self._unpack_dir(), ignore_errors=True)       # leftovers of an earlier run (CodeAque's own folder)
        dest = self._unpack_dir() / f"pack-{time.monotonic_ns()}"
        self._imp_tmp = dest
        self._imp_state = "unpacking"
        self._imp_progress = 0.0
        self._imp_file = ""
        self._imp_msg = f"Unpacking {archive.name} ..."
        self._imp_cancel = threading.Event()
        self.importChanged.emit()
        self.importProgressChanged.emit()
        cancel = self._imp_cancel
        last = [0.0]

        def progress(pr):
            now = time.monotonic()
            f = pr.fraction
            if now - last[0] < 0.12 and not (f is not None and f >= 1.0):
                return
            last[0] = now
            self.importProgressed.emit(0.0 if f is None else f, (pr.name or archive.name)
                                       + (f"   ({pr.detail})" if pr.detail else ""))

        def work():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                password = ""
                for _attempt in range(4):
                    ex = files.extract(archive, password, progress, cancel, into=dest)
                    if ex.needs_password:
                        err = "That password did not work. Try again." if password else ""
                        password = self.ask_text_blocking("PACK PASSWORD", f"{archive.name} is protected. Type its password:", True, "", err) or ""
                        if not password:
                            self.importUnpacked.emit(files.Extraction(False, "No password was entered, so the pack was not opened."))
                            return
                        continue
                    break
                else:
                    self.importUnpacked.emit(files.Extraction(False, "The password did not work after several tries."))
                    return
                if cancel.is_set():
                    shutil.rmtree(dest, ignore_errors=True)
                    return
                if not ex.ok:
                    self.importUnpacked.emit(ex)
                    return
                res = bios.scan_for_bios(dest, cancel)
            except Exception as exc:  # pragma: no cover - safety net
                self.importUnpacked.emit(files.Extraction(False, f"Something went wrong opening the pack: {exc}"))
                return
            self.importScanned.emit(res)

        threading.Thread(target=work, daemon=True, name="atari-biospack").start()

    @Slot(object)
    def _on_import_unpacked(self, ex) -> None:
        if self._imp_state != "unpacking":
            return
        self._cleanup_unpacked()
        self._imp_state = "drives"
        self._imp_msg = ex.text + (" Open the Emulators page and install 7-Zip (or unrar) first." if ex.needs_tool else "")
        self.importChanged.emit()

    @Slot(object)
    def _on_import_scanned(self, res) -> None:
        if self._imp_state not in ("scanning", "unpacking"):  # cancelled meanwhile
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
            where = f"in the pack {self._imp_pack}" if self._imp_pack else f"on {self._imp_source}"
            self._imp_msg = (f"Found {n} BIOS / firmware file{'s' if n != 1 else ''} {where}. "
                             "Tick the ones to copy - they go to each emulator's own folder. "
                             if n else f"No known BIOS files found {where}. ") + bios.LEGAL
            if n:
                try:
                    self._imp_msg += "\n" + "\n".join(bios.pack_summary(res.items))
                except Exception as exc:  # pragma: no cover - a summary must never hide the list
                    print(f"[atari] BIOS summary failed: {exc}")
            if self._imp_pack and not n:
                self._cleanup_unpacked()
            self.importChanged.emit()
            return
        self.import_model.set_items(res.items, names)
        self._imp_left = list(res.ambiguous)
        self._imp_seen = res.seen_text()
        self._imp_truncated = res.truncated
        self._imp_failed_scan = res.unclear < 0
        self._imp_nfiles = res.files_seen
        self._imp_items_found = len(res.items)
        self.askImportSystems()

    def _list_message(self) -> str:
        """What the checklist page says: how many games, what was seen, and every skipped file with its reason."""
        n = self.import_model.rowCount()
        src = self._imp_source
        if self._imp_failed_scan:
            return "Something went wrong while reading this folder."
        msg = (f"Found {n} game{'s' if n != 1 else ''} on {src}." if n else f"No games added yet from {src}.")
        if not n and not self._imp_left:
            msg = f"No games found on {src}."
        if not n or self._imp_left:
            msg += f" I looked at {self._imp_nfiles} file{'s' if self._imp_nfiles != 1 else ''}: {self._imp_seen}."
        if self._imp_left:
            lines = [f"  - {k.name}: {k.reason}" for k in self._imp_left[:4]]
            more = len(self._imp_left) - 4
            msg += "  Skipped " + str(len(self._imp_left)) + " file" + ("s" if len(self._imp_left) != 1 else "") + \
                   " (the console is unclear):\n" + "\n".join(lines) + (f"\n  ...and {more} more." if more > 0 else "") + \
                   "\n  Press CHOOSE SYSTEM to tell me which console they are for."
        elif not n:
            msg += " CodeAque looks for game files such as .iso, .zip, .cue, .nes and folders with a default.xbe (Xbox) or PS3_GAME (PS3)."
        if self._imp_truncated:
            msg += " Only the first files are shown (very large folder)."
        return msg

    @Property(int, notify=importChanged)
    def importPendingCount(self):
        return len(self._imp_left)

    @Slot()
    def askImportSystems(self) -> None:
        """Start (or restart) asking "Which system is this?" for the files whose console is unknown."""
        groups: dict = {}
        for k in self._imp_left:
            ext = k.path.suffix.lower().lstrip(".")
            groups.setdefault((ext, tuple(k.candidates)), []).append(k)
        self._imp_groups = list(groups.values())
        self._next_choice()

    def _next_choice(self) -> None:
        if self._imp_groups:
            self._imp_group = self._imp_groups.pop(0)
            self._imp_state = "choose"
        else:
            self._imp_group = []
            self._imp_state = "list"
            self._imp_msg = self._list_message()
        self.importChanged.emit()

    @Property(str, notify=importChanged)
    def importChoiceTitle(self):
        n = len(self._imp_group)
        return "Which system is this?" if n <= 1 else f"Which system are these {n} files?"

    @Property(str, notify=importChanged)
    def importChoiceFiles(self):
        names = [k.name for k in self._imp_group[:5]]
        more = len(self._imp_group) - len(names)
        return "\n".join(names) + (f"\n...and {more} more" if more > 0 else "")

    @Slot(result="QVariantList")
    def importChoiceRows(self):
        rows = []
        cands = self._imp_group[0].candidates if self._imp_group else []
        for sid in cands:
            sc = self.cfg.systems.get(sid)
            if sc is not None:
                rows.append({"kind": "system", "title": sc.name, "detail": "", "value": "", "sid": sid})
        rows.append({"kind": "skip", "title": "Not now - skip these files", "detail": "You can choose later with the "
                     "CHOOSE SYSTEM button", "value": "", "sid": ""})
        return rows

    @Slot(str)
    def chooseImportSystem(self, sid: str) -> None:
        group, self._imp_group = self._imp_group, []
        if sid and group and sid in self.cfg.systems:
            self.import_model.add_items([k.to_item(sid) for k in group])
            ids = {id(k) for k in group}
            self._imp_left = [k for k in self._imp_left if id(k) not in ids]
        self._next_choice()

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
        self._imp_done_items = list(items)
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
            msg = f"Done - {res.copied} game{'s' if res.copied != 1 else ''} added ({importer.human_size(res.bytes_copied)})."
            if res.skipped_duplicates:
                msg += f" {res.skipped_duplicates} already in your library (skipped)."
            if res.failed:
                msg += f" {len(res.failed)} could not be copied: " + "; ".join(res.failed[:3])
            if res.cancelled:
                msg = "Cancelled. " + msg
            elif res.copied:
                msg += " Your USB stick can be removed safely."
        self._imp_msg = msg
        if not res.error:
            self._add_result = msg
        self._imp_state = "done"
        self._imp_progress = 1.0
        self.importChanged.emit()
        self.importProgressChanged.emit()
        self.rescan(toast=False)

    def _on_bios_finished(self, res) -> None:
        self._cleanup_unpacked()
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
            if res.copied and not self._imp_pack:
                msg += "  Your USB stick can be removed safely."
            if self._imp_pack:
                msg += f"  The unpacked copy of {self._imp_pack} was deleted."
            try:
                left = []
                for sid in {it.system for it in self._imp_done_items}:
                    miss = bios.missing_detail(sid)
                    if miss:
                        left.append(f"{self.cfg.systems[sid].name if sid in self.cfg.systems else sid} still needs " + ", ".join(miss))
                msg += ("  Still missing: " + "; ".join(left) + ".") if left else "  Nothing else is missing for those consoles."
            except Exception as exc:  # pragma: no cover
                print(f"[atari] BIOS missing list failed: {exc}")
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
        if self._imp_state in ("scanning", "unpacking"):
            self._cleanup_unpacked()
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
    def toggleEscExit(self) -> None:
        self.cfg.esc_exit = not self.cfg.esc_exit
        self._save_prefs()

    @Slot()
    def toggleSteamBigPicture(self) -> None:
        self.cfg.steam_bigpicture = not self.cfg.steam_bigpicture
        self._save_prefs()

    @Slot()
    def toggleAnimations(self) -> None:
        self.cfg.reduce_animations = not self.cfg.reduce_animations
        self._save_prefs()

    @Property(QObject, constant=True)
    def wifi(self):
        """The WiFi screen's controller (nmcli). Created on first use; tests may set `_wifi_run` to a mocked nmcli."""
        if self._wifi is None:
            from .wifi_ui import WifiController
            self._wifi = WifiController(self, run=getattr(self, "_wifi_run", None))
        return self._wifi

    @Property(bool, constant=True)
    def kioskSession(self):
        """CodeAque is the whole session (CodeAque-only mode): quitting only restarts it."""
        return kiosk.in_session()

    @Property(QObject, constant=True)
    def media(self):
        """The top bar's play / pause / skip control (playerctl, MPRIS). Tests may pass fakes through `_media_fns`."""
        if self._media is None:
            from .media_ui import MediaController
            now, send = getattr(self, "_media_fns", (None, None))
            self._media = MediaController(self, now=now, send=send)
        return self._media

    def _media_poll(self) -> None:
        if self._demo or os.environ.get("ATARI_NO_MEDIA"):
            return
        self.media.refresh()
        QTimer.singleShot(4000, self._media_poll)

    def _wifi_poll(self) -> None:
        """The home screen's one-line WiFi status, refreshed now and every minute (never in demo / test runs)."""
        if self._demo or os.environ.get("ATARI_NO_WIFI"):
            return
        self.wifi.updateSummary()
        QTimer.singleShot(60000, self._wifi_poll)

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
            self._set_update("available", f"CodeAque {rel.version} is available (you have {__version__}).")
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
            self._set_update("available", f"CodeAque {self._upd_release.version} is available (you have {__version__}).")
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
                self.updateEvent.emit("done", f"CodeAque {rel.version} is installed. Restart CodeAque to use it.", 1.0)
            except updater.Cancelled:
                self.updateEvent.emit("available", f"Cancelled. CodeAque {rel.version} is still available.", -1.0)
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
        """Start the new CodeAque a moment after this one has quit."""
        root = Path(os.environ.get("ATARI_UPDATE_ROOT") or updater.app_dir())
        cmd = updater.restart_command(root, sys.argv[1:])
        try:
            self._restart_spawn(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.show_toast(f"Could not restart: {exc}. Please start CodeAque again yourself.", 8000)
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
        self.startIcons(force=True)

    def startIcons(self, force: bool = False) -> None:
        """Fetch the missing tile icons (web apps, PC apps, free games) once, in the background. Quiet: no screen text."""
        if not self._covers_allowed() or self._icon_busy:
            return
        specs = [s for s in (icons.spec_for(g.gid) for g in self._all
                             if g.gid.partition(":")[0] in ("web", "app", "free") and not g.rom_path) if s is not None]
        if not specs:
            return
        self._icon_busy = True
        fast = bool(os.environ.get("ATARI_COVERS_FAST"))
        flathub = os.environ.get("ATARI_ICONS_FLATHUB_URL") or icons.FLATHUB_ICONS
        steam_base = os.environ.get("ATARI_COVERS_STEAM_URL") or covers.STEAM_URL
        root = Path(os.environ["ATARI_ICONS_DIR"]) if os.environ.get("ATARI_ICONS_DIR") else None

        def worker():
            try:
                http = covers.Http(pause=0.0 if fast else 0.2, backoff=0.01 if fast else 1.0, timeout=5 if fast else 12)
                f = icons.IconFetcher(http, root, flathub, steam_base, force=force)
                f.run(specs, on_icon=lambda s, p: self.iconArrived.emit(s.gid, p, s.kind != "free" or not s.steam_appid))
            except Exception as exc:  # pragma: no cover - safety net
                print(f"[atari] icon download failed: {exc}")
            self.iconsDone.emit()

        threading.Thread(target=worker, daemon=True, name="atari-icons").start()

    @Slot()
    def _icons_finished(self) -> None:
        self._icon_busy = False

    @Slot(str, str, bool)
    def _on_icon_arrived(self, gid: str, path: str, fit: bool) -> None:
        for g in self._all:
            if g.gid == gid and (not g.cover or g.cover != path):
                if g.cover and not g.fit and gid.partition(":")[0] != "free":
                    return                       # it already has real art of its own
                g.cover = g.header = path
                g.fit = fit
                self.model.cover_updated(gid)
                return

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
        rows.append({"kind": "themepage", "title": "Theme: " + themes.get(self.store.get_pref("theme", themes.DEFAULT)).name,
                     "detail": "CodeAque Gold, Midnight, Neon, Light, Hoodlum Asylum - colours, background and buttons."})
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
        rows.append({"kind": "update", "title": "Update CodeAque",
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
        rows.append({"kind": "brightnesspage", "title": "Brightness", "value": f"{self._br_level}%" if self._br_level >= 0 else "",
                     "detail": "Screen brightness, for when the laptop's brightness keys do nothing. Also on the home screen (the sun)."})
        rows.append({"kind": "volume", "title": "Volume", "value": f"{int(round(self.cfg.volume * 100))}%",
                     "detail": "Press Enter to step through 20 / 40 / 60 / 80 / 100 %."})
        rows.append({"kind": "anim", "title": "Reduce animations",
                     "value": "ON" if self.cfg.reduce_animations else "OFF",
                     "detail": "Turns off the moving background, bobbing icons and fades. Choose ON on a slow computer."})
        rows += self._rec_rows()
        rows.append({"kind": "sgdbkey", "title": "SteamGridDB key (optional, for more covers)",
                     "value": "Set" if self.cfg.steamgriddb_key else "Not set",
                     "detail": "Free at steamgriddb.com > Preferences > API. Type it here with the keyboard, or put it in config.toml under [covers]. Leave empty to skip."})
        rows.append({"kind": "installmenu", "title": "Install emulators and apps", "value": "",
                     "detail": "One press: essentials only, or everything. Missing programs also show INSTALL on their own tile."})
        rows.append({"kind": "steampage", "title": "Steam: install, rescan, drives",
                     "value": "Installed" if self.steam_installed() else "Not installed",
                     "detail": "Installs Steam for you, rescans your Steam games, and says where to keep them."})
        rows += self._intro_rows()
        rows.append({"kind": "wifipage", "title": "WiFi", "value": self.wifi.summary or "",
                     "detail": "Find a network, type its password with the on-screen keyboard, see if it connected, or forget a network. "
                               "Works in CodeAque-only mode too."})
        _mode = kiosk.read_mode(self._kiosk_layout)["next"]
        rows.append({"kind": "bootpage", "title": "Boot screen", "detail": "The CodeAque start-up menu (CodeAque / Windows) and splash. Install or restore."})
        rows.append({"kind": "steamboot", "title": "Start Steam at boot (hidden): " + ("ON" if self._steam_autostart_on() else "OFF"),
                     "detail": "Starts Steam quietly in the background when CodeAque starts, with Steam's own saved login, so games open faster. "
                               "CodeAque never sees or stores your Steam password." + ("" if self._steam_installed() else " (Steam is not installed.)")})
        rows.append({"kind": "findgamespage", "title": "Find my games",
                     "detail": "Your own games and backups from Downloads, Desktop, Documents and drives, sorted by console."})
        rows.append({"kind": "biosfindpage", "title": "Find my BIOS files",
                     "detail": "Looks in Downloads (also inside .zip / .7z / .rar) and copies them where the emulators look."})
        rows.append({"kind": "screentvpage", "title": "Screen to TV: show CodeAque on your TV",
                     "detail": "HDMI cable steps, same picture / TV only, and wireless (Miracast, Chromecast) if your TV supports it."})
        rows.append({"kind": "controllerspage", "title": "Controllers: see your gamepads, test buttons, set up for xemu",
                     "detail": "Shows the gamepads found, a live button test, and writes player 1 into xemu's settings."})
        rows.append({"kind": "startmodepage", "title": "Start mode: Linux desktop or CodeAque only",
                     "value": {"console": "CODEAQUE ONLY", "desktop": "LINUX DESKTOP"}.get(_mode, "CHECK"),
                     "detail": "Choose whether the computer starts into the normal Linux Mint desktop or straight into CodeAque like a console. "
                               "Shows the current setting, read back from the computer."})
        rows.append({"kind": "kioskpage", "title": ("CodeAque-only mode: details, update and repair (ON)" if kiosk.enabled(self._kiosk_layout)
                                          else "CodeAque-only mode: details (OFF)"),
                     "value": "ON" if kiosk.enabled(self._kiosk_layout) else "OFF",
                     "detail": "Makes the computer boot into CodeAque with no Mint desktop. Asks you to confirm first, and there is always a way back."})
        rows.append({"kind": "quietbootpage", "title": "Quiet boot: hide the Mint logo and menus",
                     "value": "ON" if quietboot.enabled(self._qb_layout) else "OFF",
                     "detail": "Boot menu hidden, CodeAque logo on black instead of the Mint logo, start-up text off. Reversible; the boot menu stays one key away."})
        rows.append({"kind": "bootreport", "title": "Copy boot report (to send for help)", "value": "",
                     "detail": "Saves ~/Downloads/code-boot-report.txt with the boot menu / GRUB / firmware boot list settings. No passwords."})
        rows.append({"kind": "info", "title": "About the Dell logo at power-on", "value": "", "detail": quietboot.BIOS_LOGO_NOTE})
        if kiosk.enabled(self._kiosk_layout):
            old = kiosk.session_outdated(self._kiosk_layout)
            rows.append({"kind": "kioskupdate", "title": "Update CodeAque-only mode", "value": "UPDATE NEEDED" if old else "Up to date",
                         "detail": "One press (password once) rewrites the CodeAque-only session file so closing an app or a crash never drops you to the "
                                   "Mint desktop. Needed once after an update from 0.3.x / 0.4.0."})
        rows.append({"kind": "bigpicture", "title": "Open Steam in Big Picture (full screen)",
                     "value": "ON" if self.cfg.steam_bigpicture else "OFF",
                     "detail": "The Steam tile opens Steam full screen with big buttons for a controller. Press Esc twice (or hold Guide and press B) "
                               "to leave it and come back to CodeAque - Steam keeps running. OFF = Steam opens in a normal window (CodeAque-only mode always uses Big Picture). "
                               "Steam's desktop dialogs (Properties) are not made for a TV: use Big Picture's own menus."})
        rows.append({"kind": "escexit", "title": "Esc twice returns to CodeAque (Netflix, YouTube, Kodi...)",
                     "value": "ON" if self.cfg.esc_exit else "OFF",
                     "detail": "Press Esc twice quickly, or hold Esc for 1 second (or Ctrl+Esc; on a controller hold Guide and press B) "
                               "to close a streaming app and come back here. One Esc still leaves video full screen as usual."})
        rows.append({"kind": "support", "title": donate.TITLE, "value": "", "detail": donate.DETAIL})
        rows.append({"kind": "emulators", "title": "Emulators", "value": "",
                        "detail": "See what is installed, install emulators, and which consoles still need BIOS files."})
        for u in self._lib.unknown:
            rows.append({"kind": "fixfolder", "id": u.path, "title": "Not recognised: " + u.name,
                         "value": "Fix" if u.guess in self.cfg.systems else "",
                         "detail": gamesroot.hint_text(self.cfg, u)
                                   + ("  Press Enter to do it for you." if u.guess in self.cfg.systems else "")})
        for sc in self.cfg.systems.values():
            n = self._lib.rom_counts.get(sc.id, 0)
            auto = self._lib.auto_folders.get(sc.id, [])
            have = [*sc.roms, *auto]
            folder = ", ".join(have) if have else "Not set - press Enter to choose a folder"
            if not have and not n and sc.id not in self._setup_shown():
                continue
            rows.append({"kind": "system", "id": sc.id, "title": sc.name,
                         "value": (f"{n} game" + ("" if n == 1 else "s")) if have else "",
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

    @Slot(str)
    def fixGamesFolder(self, path: str) -> None:
        """Rename an unrecognised ~/Games/Atari folder (or move a loose game file) to the system it looks like."""
        ok, msg = gamesroot.fix(self.cfg, path)
        self.rescan(toast=False)
        self.show_toast(msg, 9000)

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
            media = os.environ.get("ATARI_MEDIA_ROOTS")
            bases = ([Path(x) for x in media.split(os.pathsep) if x] if media else
                     [Path("/media") / os.environ.get("USER", ""), Path("/run/media") / os.environ.get("USER", ""), Path("/mnt")])
            for base in bases:
                try:
                    places += [(f"USB / drive: {p.name}", p) for p in sorted(base.iterdir()) if p.is_dir()]
                except OSError:
                    pass
            for label, sub_ in (("Downloads", "Downloads"), ("Videos", "Videos"), ("Documents", "Documents"), ("Desktop", "Desktop"), ("My games (Games/Atari)", "Games/Atari")):
                if (home / sub_).is_dir():
                    places.append((label, home / sub_))
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
        return {"help": "HELP & GETTING STARTED", "fix": "FIX MY GAME", "winform": "PC GAMES INSTALLER",
                "winchoose": "WHICH PROGRAM STARTS THE GAME?", "winwork": "OPENING THE ARCHIVE",
                "install": "INSTALL", "installmenu": "INSTALL EMULATORS & APPS", "steam": "STEAM",
                "recordings": "RECORDINGS", "coverpick": "PICK A COVER", "nocovers": "COVERS NOT FOUND",
                "addgames": "ADD GAMES", "kiosk": "CODEAQUE-ONLY MODE", "startmode": "START MODE", "xemusetup": "XBOX (XEMU) SETTINGS", "controllers": "CONTROLLERS", "brightness": "BRIGHTNESS", "btpair": "PAIR A BLUETOOTH CONTROLLER", "biosfind": "FIND MY BIOS FILES", "theme": "THEME", "simtycoon": "SIM & TYCOON", "create": "CREATE", "worldgames": "WORLD GAMES", "boot": "BOOT SCREEN", "simpick": "ADD TO SIM & TYCOON", "findgames": "FIND MY GAMES", "screentv": "SCREEN TO TV", "quietboot": "QUIET BOOT", "power": "POWER", "downloads": "DOWNLOADS", "golive": "GO LIVE", "robloxfix": "FIX ROBLOX",
                "dlsystem": "WHICH SYSTEM IS THIS FILE FOR?", "files": "MY FILES", "fileact": "WHAT TO DO WITH IT", "deletegame": "DELETE GAME", "about": "ABOUT CODEAQUE"}.get(name, name.upper())

    @Slot(str, result=str)
    def pageSub(self, name: str) -> str:
        return {"help": "Up/Down to choose, Enter / A to press.  Esc / B = back.",
                "simtycoon": "Your simulation and management games. Enter / A to play or install.  Esc / B = back.",
                "golive": "Enter / A to press.  Esc / B = back.",
                "robloxfix": "Enter / A on Run fix.  Esc / B = back.",
                "downloads": "Enter / A on a finished file adds it to your games.  Esc / B = back.",
                "files": "Downloads, Games, Videos.  Enter / A opens;  Esc / B goes up.",
                "fileact": "Enter / A on the button you want.  Esc / B = back to the list.",
                "about": "Esc / B = back.",
                "deletegame": "Nothing is deleted until you press Yes.  Esc / B = no, go back.",
                "dlsystem": "Enter / A picks the system - the file moves into that games folder.  Esc / B = back.",
                "fix": "CodeAque checked everything it can.  Esc / B = back.",
                "winform": "Check the details, then choose \"Add this game\".  Esc / B = cancel.",
                "winchoose": "Pick the main program (the biggest .exe is usually it).  Esc / B = cancel.",
                "winwork": "Please wait - big games take a minute.  Esc / B = cancel.",
                "install": "One press, no terminal.  Esc / B = back.",
                "installmenu": "Up/Down to choose, Enter / A to press.  Esc / B = back.",
                "steam": "Install Steam, rescan your games, and where to keep them.  Esc / B = back.",
                "recordings": "Enter / A plays a recording.  Esc / B = back.",
                "coverpick": "Enter / A uses the highlighted picture.  Esc / B = back.",
                "nocovers": "Games that no cover was found for.  Esc / B = back.",
                "addgames": "Up/Down to choose, Enter / A or a click to press.  Esc / B = back.",
                "startmode": "Choose one. Esc / B = back.",
                "xemusetup": "Esc / B = back. Your own Xbox files only - nothing is bundled.",
                "controllers": "Up/Down to choose, Enter / A to press.  Esc / B = back.",
                "btpair": "Pairing mode on the pad first, then Search.  Esc / B = back.",
                "biosfind": "Your own BIOS files only - nothing is downloaded.  Esc / B = back.",
                "findgames": "Your own games and backups only - nothing is downloaded.  Esc / B = back.",
                "screentv": "Cable first (easiest), wireless if your TV supports it.  Esc / B = back.",
                "kiosk": "Read this, then choose.  Esc / B = back - nothing changes until you press Yes.",
                "power": "Up/Down to choose, Enter / A to press.  Restart and shut down ask first.  Esc / B = back.",
                "quietboot": "Read this, then choose.  Esc / B = back - nothing changes until you press Yes."}.get(name, "")

    # ----- Go Live: OBS + the Twitch / TikTok / YouTube dashboards -------------------------------
    def _golive_rows(self) -> list:
        ok, text = apps.app_status(self.cfg, apps.BY_ID["obs"])
        rows = [self._info("Stream your games: OBS (free) sends your screen and sound to Twitch, TikTok or YouTube. Step 1: get OBS. "
                           "Step 2: open your service's page and copy your stream key. Step 3: Open OBS, paste the key, Start Streaming."),
                {"kind": "item", "id": "obsopen" if ok else "obsinstall",
                 "title": "Open OBS with the Go Live scene" if ok else "Install OBS Studio",
                 "detail": ("Starts OBS with a ready \"Code Go Live\" scene that captures your whole screen." if ok else
                            "Not installed yet. One button, free, open source."), "value": "" if ok else "Install"}]
        for gid, title in (("web:twitchlive", "Twitch: open the Creator Dashboard"), ("web:tiktoklive", "TikTok LIVE: open the web LIVE page"),
                           ("web:youtubelive", "YouTube Live: open YouTube Studio")):
            rows.append({"kind": "item", "id": "go:" + gid, "title": title, "detail": "Opens in the web browser window. Esc twice returns to CodeAque."})
        rows += [self._info(golive.TWITCH_TEXT), self._info(golive.YOUTUBE_TEXT), self._info("TikTok on Linux: " + golive.TIKTOK_TEXT),
                 self._info(golive.SECRET_TEXT),
                 self._info("Linux has no OBS \"Game Capture\": the scene captures the whole screen (on Wayland a system window asks which screen). "
                            "To only record, not stream, press F9 for CodeAque's own screen recorder."),
                 {"kind": "item", "id": "recordings", "title": "My recordings", "detail": "Videos made with the screen recorder (F9)."},
                 {"kind": "item", "id": "back", "title": "Back"}]
        return rows

    def _golive_activate(self, rid: str) -> str:
        if rid == "obsinstall":
            self.begin_install(["obs"], for_gid="app:obs", what="OBS Studio")
            return ""
        if rid == "obsopen":
            ok, text = golive.start_obs(self.cfg)
            self.show_toast(text, 12000)
            return ""
        if rid == "recordings":
            return "page:recordings"
        if rid.startswith("go:"):
            g = next((x for x in self._all if x.gid == rid[3:]), None)
            if g is None or g.missing:
                self.show_toast(webapps.HELP_TEXT, 9000)
                return ""
            self._launch_game(g)
            return "close"
        return ""

    # ----- Downloads: the web browser's files -> my games ---------------------------------
    def _downloads_rows(self) -> list:
        items = downloads.scan(self.cfg)
        self._dl_items = items
        ok, text = webapps.status(self.cfg, webapps.BY_ID["browser"])
        tok, _t = apps.app_status(self.cfg, apps.BY_ID["transmission"])
        rows = [self._info("Browse the web yourself, download a file you own or may use, then come back here. Files land in ~/Downloads. "
                           "CodeAque does not recommend or link any download site."),
                {"kind": "done", "id": "dlfiles", "title": "OPEN THE FILE VIEWER  (unzip, rename, delete, add to my games)",
                 "detail": "Browse Downloads, Games and Videos with sizes and free space. One button unzips a .zip / .7z / .rar / .tar."},
                {"kind": "item", "id": "dlbrowser", "title": "Open the web browser", "detail": text,
                 "value": "" if ok else "No browser"},
                {"kind": "item", "id": "dltorrent", "title": "Torrent client (Transmission)",
                 "detail": ("Opens it - add your own .torrent file or magnet link there." if tok else
                            "Not installed yet. Press to install it (one button, free, open source)."),
                 "value": "" if tok else "Install"},
                {"kind": "item", "id": "dlrefresh", "title": "Refresh the list", "detail": "Shows files that arrived since you opened this page."}]
        if not items:
            rows.append(self._info("Nothing in your Downloads folder yet."))
        for i, it in enumerate(items):
            if it.is_torrent:
                rows.append({"kind": "item", "id": f"dl:{i}", "title": it.name, "value": "Torrent",
                             "detail": "A .torrent file - press to open it with the torrent client (it saves to ~/Downloads)."})
            elif it.partial:
                rows.append({"kind": "item", "id": f"dl:{i}", "title": it.shown_name, "value": "Downloading...",
                             "detail": f"{importer.human_size(it.size)} so far - press Refresh to see the progress. (The browser shows the speed.)"})
            else:
                guess = ""
                if it.guess:
                    guess = "Looks like: " + ", ".join(self.cfg.systems[s].name for s in it.guess[:2] if s in self.cfg.systems) + ".  "
                kind = "Folder: " if it.is_dir else ""
                rows.append({"kind": "item", "id": f"dl:{i}", "title": it.name, "value": importer.human_size(it.size),
                             "detail": kind + guess + downloads.human_age(it.mtime) + " - press to add it to my games."})
        if self._dl_msg:
            rows.insert(1, self._info("Last result:  " + self._dl_msg))
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _downloads_activate(self, rid: str) -> str:
        if rid == "dlbrowser":
            g = next((x for x in self._all if x.gid == "web:browser"), None)
            if g is None or g.missing:
                self.show_toast(webapps.HELP_TEXT, 9000)
                return ""
            self._launch_game(g)
            return "close"
        if rid == "dltorrent":
            g = next((x for x in self._all if x.gid == "app:transmission"), None)
            if g is None or g.missing:
                self.begin_install(["transmission"], for_gid="app:transmission", what="Transmission")
                return ""
            ok, text = downloads.open_torrent(self.cfg)
            self.show_toast(text, 6000)
            return ""
        if rid == "dlrefresh":
            return "refresh"
        if rid == "dlfiles":
            self.filesReset()
            self._fm_dir = files.roots(self._fm_home())[0][1] if files.roots(self._fm_home()) else None
            return "page:files"
        if rid.startswith("dl:"):
            try:
                it = self._dl_items[int(rid[3:])]
            except (ValueError, IndexError):
                return "refresh"
            if it.is_torrent:
                ok, text = downloads.open_torrent(self.cfg, it.path)
                if not ok and "not installed" in text:
                    self.begin_install(["transmission"], for_gid="app:transmission", what="Transmission")
                    return ""
                self.show_toast(text, 7000)
                return ""
            if it.partial:
                self.show_toast("That is still downloading. Press Refresh in a moment.", 5000)
                return "refresh"
            self._dl_pick = it
            return "page:dlsystem"
        return ""

    def _dlsystem_rows(self) -> list:
        it = self._dl_pick
        if it is None:
            return [self._info("Pick a file first."), {"kind": "item", "id": "back", "title": "Back"}]
        rows = [self._info(f"{it.name} ({importer.human_size(it.size)}) - which system is it for?  Only add files you own or may use.")]
        likely = set(it.guess or [])
        for sid, name in downloads.candidates(self.cfg, it):
            rows.append({"kind": "item", "id": f"dlsys:{sid}", "title": name, "value": "Likely" if sid in likely else "",
                         "detail": f"Moves the file to {importer.destination_for(self.cfg, sid)}"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    def _dlsystem_activate(self, rid: str) -> str:
        if rid.startswith("dlsys:") and self._dl_pick is not None:
            ok, text, _t = downloads.add_to_games(self.cfg, self._dl_pick.path, rid[6:])
            self._dl_msg = text
            self.show_toast(text, 9000)
            if ok:
                self._dl_pick = None
                self.rescan(toast=False)
            if self._dl_from_files:
                self._dl_from_files = False
                self._fm_pick = None
                self._fm_set_msg(ok, text)
                return "page:files"
            return "page:downloads"
        return ""

    def _addgames_rows(self) -> list:
        try:
            drives = importer.detect_drives()
        except Exception:
            drives = []
        usb = (f"Found: {drives[0].label}" + (f" (+{len(drives) - 1} more)" if len(drives) > 1 else "")) if drives else "Plug the USB stick in first, then press this."
        rows = [self._info("Step 1 of 2 - where are the games?  Pick one. CodeAque only reads from your stick or folder; nothing there is changed.")]
        rows += [
            {"kind": "item", "id": "usb", "title": "From a USB stick", "detail": usb, "value": "USB" if drives else ""},
            {"kind": "item", "id": "folder", "title": "From a folder on this computer",
             "detail": "Starts at your USB sticks, Downloads and Home. Pick the folder that holds the games."},
            {"kind": "done", "id": "findgames", "title": "Find my games (one press)",
             "detail": "Looks in Downloads, Desktop, Documents and drives for your own games and backups, and sorts them by console."},
            {"kind": "item", "id": "biosfind", "title": "Find my BIOS files (one press)",
             "detail": "Looks in Downloads (also inside archives) for BIOS files from your own consoles."},
            {"kind": "item", "id": "windows", "title": "PC Games Installer (a PC game: .exe, setup.exe or .zip)",
             "detail": "A PC game you own or downloaded yourself. CodeAque sets it up to run on this computer."},
            {"kind": "item", "id": "bios", "title": "BIOS files (for PlayStation, Saturn, Dreamcast ...)",
             "detail": "Files from your own console; some emulators need them."},
            {"kind": "item", "id": "downloads", "title": "Files I downloaded from the web (Downloads)",
             "detail": "Move a finished download from ~/Downloads into your games, or open the web browser."},
        ]
        if self._add_result:
            rows.append(self._info("Last result:  " + self._add_result))
        rows.append({"kind": "done", "id": "finish", "title": "Finished - show my games"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    @Slot(str, result="QVariantList")
    def pageRows(self, name: str):
        if name == "addgames":
            return self._addgames_rows()
        if name == "robloxfix":
            return self._roblox_fix_rows()
        if name == "golive":
            return self._golive_rows()
        if name == "downloads":
            return self._downloads_rows()
        if name == "files":
            return self._files_rows()
        if name == "fileact":
            return self._fileact_rows()
        if name == "deletegame":
            return self._delete_rows()
        if name == "about":
            return self._about_rows()
        if name == "dlsystem":
            return self._dlsystem_rows()
        if name == "help":
            return self._help_rows()
        if name == "fix":
            return self._fix_rows()
        if name == "winform":
            return self._winform_rows()
        if name == "winchoose":
            return self._winchoose_rows()
        if name == "recordings":
            return self._recordings_rows()
        if name == "coverpick":
            return self._coverpick_rows()
        if name == "nocovers":
            return self._nocovers_rows()
        if name == "install":
            return self._install_rows()
        if name == "installmenu":
            return self._installmenu_rows()
        if name == "steam":
            return self._steam_rows()
        if name == "kiosk":
            return self._kiosk_rows()
        if name == "startmode":
            return self._startmode_rows()
        if name == "xemusetup":
            return self._xemu_rows()
        if name == "brightness":
            return self._br_rows()
        if name == "controllers":
            return self._controllers_rows()
        if name == "btpair":
            return self._bt_rows()
        if name == "biosfind":
            return self._bf_rows()
        if name == "theme":
            return self._theme_rows()
        if name == "simtycoon":
            return self._sim_rows()
        if name == "create":
            return self._create_rows()
        if name == "boot":
            return self._boot_rows()
        if name == "worldgames":
            return self._wg_rows()
        if name == "simpick":
            return self._simpick_rows()
        if name == "findgames":
            return self._fg_rows()
        if name == "screentv":
            return self._tv_rows()
        if name == "quietboot":
            return self._quietboot_rows()
        if name == "power":
            return self._power_rows()
        if name == "winwork":
            return [{"kind": "info", "title": self._win_text or "Working..."},
                    {"kind": "item", "id": "cancel", "title": "Cancel"}]
        return []

    def _info(self, text: str) -> dict:
        return {"kind": "info", "title": text}

    def _help_rows(self) -> list:
        n_games = self._real_count()
        rows = [self._info(diagnose.controller_text())]
        rows.append({"kind": "item", "id": "about", "title": f"About {branding.NAME}  (version {__version__})",
                     "detail": "The logo, the version, where things are kept, and the old names that still work."})
        rows.append(self._info("Getting started - press each step in order (you can skip steps you do not need):"))
        for step in diagnose.checklist(self.cfg, n_games > 0):
            done = step["done"] and not (step["id"] == "covers")
            rows.append({"kind": "item", "id": "ck_" + step["id"], "title": step["title"],
                         "value": "Done" if done else "", "tone": "ok" if done else "",
                         "detail": step["detail"]})
        rows += [
            {"kind": "item", "id": "winadd", "title": "PC Games Installer (.exe, setup.exe or .zip)",
             "detail": "For PC games you own or downloaded yourself."},
            {"kind": "item", "id": "nocovers", "title": "Covers not found (and re-download covers)",
             "detail": "Lists games no cover was found for; pick one yourself or search again."},
            {"kind": "item", "id": "steampage", "title": "Steam: install, rescan, where to keep games",
             "detail": "Installs Steam for you, opens it for the first sign-in, rescans your games, and warns about Windows (NTFS) drives."},
            {"kind": "item", "id": "controls", "title": "Controls (keyboard keys)",
             "detail": "Which keys to press inside each emulator."},
            self._info("Q: Make music?  A: Options > Studio (or the Studio tile). Make a beat, record your voice over it, then mix and save a WAV or MP3 "
                       "in ~/Music/Atari Studio. Use headphones when you record."),
            self._info("Q: Netflix, YouTube, Instagram...?  A: open the Streaming tile (Systems row). Each opens in its own browser window - "
                       "sign in once per app (it remembers you). You may need a mouse or touch screen inside web pages; "
                       "AntiMicroX can make a controller act as a mouse. Netflix, Prime and Disney+ stream at about 720p on Linux."),
            self._info("Q: Fortnite / Call of Duty / Warzone?  A: they do not work on Linux - their anti-cheat blocks it and the makers do not support it. "
                       "The Free Games tile lists free games that do work (checked on ProtonDB). Minecraft Java: Prism Launcher in PC Apps (needs your own licence)."),
            self._info("Q: Roblox says \"Invalid Bundle\" / I downloaded a .flatpak file.  A: " + sober.INVALID_BUNDLE_TEXT),
            self._info("Q: Roblox asks for an \"application bundle (APK)\" / \"Install Roblox\".  A: " + sober.BUNDLE_HELP),
            {"kind": "item", "id": "soberfix", "title": "Roblox asks for an application bundle? Open the step-by-step fix",
             "detail": "Checks Flathub, updates Sober, tests the internet, DNS and clock, and names the cause. Needs internet."},
            self._info("Q: Can I get games from the web?  A: Options > Downloads opens a web browser (it starts at a neutral search engine; "
                       "CodeAque recommends no sites) and lists what you downloaded. Press a finished file, choose its system, and it moves into "
                       "~/Games/Atari/<system>. Only add games you own or may legally use. A torrent client (Transmission) installs with one "
                       "button on the same screen; it is not set up with any torrents or sites."),
            self._info("Q: How do I stream to Twitch / TikTok / YouTube?  A: Options > Go Live. OBS installs with one button and opens with a "
                       "ready scene; you paste your own stream key into OBS. TikTok LIVE Studio is Windows-only, so on Linux TikTok works through "
                       "OBS with the key from TikTok's web LIVE page (only for accounts TikTok allows)."),
            self._info("Q: A game does not start.  A: highlight it, press the Options button (F10 / Start), choose \"Fix my game\"."),
            self._info("Q: The game has no picture.  A: step 4 above downloads covers (needs internet). Names must look like the real game title."),
            self._info("Q: A console says it needs a BIOS.  A: those are files from your own console. CodeAque cannot download them - use step 3 with a USB stick or folder."),
            self._info("Q: Where are my games?  A: ~/Games/Atari/<console>/ . Your favourites and play time are kept when you update CodeAque."),
            self._info("Q: How do I quit a game?  A: use the emulator's own exit (see Controls). CodeAque comes back by itself."),
            self._info("Q: How do I get back from Netflix / YouTube / Kodi?  A: press Esc twice quickly (or hold Esc for 1 second, or Ctrl+Esc). "
                       "CodeAque closes the app and comes back. One Esc still leaves video full screen as normal. On a controller: hold Guide / Home and press B. "
                       "(Needs the normal Linux Mint X11 desktop; turn it off in Settings.)"),
            self._info("Q: Can I have my own start-up video?  A: CodeAque comes with a 10-second intro. To use your own instead: Settings > Choose intro video (mp4, webm, mkv or mov). It plays before the home screen; "
                       "any key, click or controller button skips it. Remove it any time in Settings. Needs mpv, ffplay or VLC to be installed."),
            self._info("Q: How do I connect to WiFi?  A: press the WiFi button next to the clock (or Settings > WiFi). Pick your network, type the password with "
                       "the on-screen keyboard (controller: D-pad + A, L1 = delete, R1 = switch letters / capitals / symbols), then CONNECT. "
                       "It works in CodeAque-only mode too. \"Forget\" removes a saved network."),
            self._info("Q: How do I make the computer start straight into CodeAque, like a console?  A: Settings > CodeAque-only mode. "
                       "To get the normal desktop back: Settings > Start mode > Use Linux desktop (or pick the Cinnamon session on the login screen)."),
            {"kind": "item", "id": "inputfix", "title": "Steam says \"Missing permissions for input devices\"? Fix controller permissions",
             "detail": "Installs Valve's controller rules (steam-devices) so Steam and CodeAque can use your gamepad. Asks for your password once."},
            {"kind": "item", "id": "studiofix", "title": "Studio does not work? Fix Studio",
             "detail": "Checks numpy, the recording tools and the microphone, and installs what is missing (needs internet)."},
            {"kind": "item", "id": "copylog", "title": "Copy log (to send to someone who is helping you)",
             "detail": "Copies CodeAque's recent messages and your setup to the clipboard. It contains no passwords."},
            {"kind": "item", "id": "reset",
             "title": "Press again to reset my settings" if self._reset_armed else "Safe mode: reset my settings",
             "detail": "Puts CodeAque's settings back to normal if something looks wrong. Your games, favourites and "
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
            rows.append({"kind": "item", "id": "biosfind", "title": "Find my BIOS files (looks in Downloads for you)",
                         "detail": "Finds the files by name and size, also inside .zip / .7z / .rar, and shows where they go before copying."})
            rows.append({"kind": "item", "id": "bios", "title": "Add BIOS files",
                         "detail": "From your own console, via USB stick or folder."})
        if g.platform == "steam" or g.gid == "app:steam":
            rows.append({"kind": "item", "id": "inputfix", "title": "Fix Steam controller / gamepad permissions",
                         "detail": "For \"Missing permissions for input devices\" in Steam."})
        if g.gid.endswith(":roblox") and g.platform == apps.APPS:
            rows.append({"kind": "item", "id": "soberfix", "title": "Fix Roblox (step by step)",
                         "detail": "For Roblox asking for an \"application bundle (APK)\": updates Sober and checks Sober's server and Google Play can be reached."})
        rows.append({"kind": "item", "id": "copylog", "title": "Copy log"})
        if g.platform == windows.PLATFORM:
            rows.append({"kind": "item", "id": "remove",
                         "title": "Press again to remove this game from CodeAque" if self._remove_armed
                         else "Remove this game from CodeAque",
                         "detail": "Only CodeAque's entry goes - the game's files stay on your disk."})
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
        head = [f"CodeAque {__version__}  python {sys.version.split()[0]}  {os.environ.get('XDG_CURRENT_DESKTOP', '')}",
                diagnose.controller_text(), "Studio: " + studio_fix.summary(studio_fix.problems(studio_fix.numpy_ok()))
                if hasattr(studio_fix, "numpy_ok") else diagnose.controller_text(), ""]
        slog = studio_fix.read_log(40)
        text = "\n".join(head + (lines or ["(the log is empty)"]) + (["", "--- Studio log ---"] + slog if slog else []))
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
        self.show_toast("Copied CodeAque's log to the clipboard - paste it into a message to whoever is helping you.", 7000)
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
        if name == "brightness":
            return self._br_activate(rid)
        if rid == "biosfind" and name != "biosfind":
            return "page:biosfind"
        if rid == "findgames" and name != "findgames":
            return "page:findgames"
        if name == "help":
            return self._help_activate(rid)
        if name == "robloxfix":
            return self._roblox_fix_activate(rid)
        if name == "golive":
            return self._golive_activate(rid)
        if name == "downloads":
            return self._downloads_activate(rid)
        if name == "files":
            return self._files_activate(rid)
        if name == "fileact":
            return self._fileact_activate(rid)
        if name == "deletegame":
            return self._delete_activate(rid)
        if name == "about":
            if rid == "aboutsupport":
                self.supportCode()
            return ""
        if name == "dlsystem":
            return self._dlsystem_activate(rid)
        if name == "addgames":
            return {"usb": "import:games", "folder": "browse:importfolder", "windows": "browse:winaddwizard",
                    "bios": "import:bios", "downloads": "page:downloads", "finish": "close"}.get(rid, "")
        if name == "install":
            return self._install_activate(rid)
        if name == "recordings":
            return self._recordings_activate(rid)
        if name == "coverpick":
            return self._coverpick_activate(rid)
        if name == "nocovers":
            return self._nocovers_activate(rid)
        if name == "installmenu":
            if rid == "inst_essentials":
                self.installEssentials()
            elif rid == "inst_all":
                self.installAll()
            elif rid == "inst_terminal":
                self.installInTerminal()
            return ""
        if name == "kiosk":
            return self._kiosk_activate(rid)
        if name == "startmode":
            return self._startmode_activate(rid)
        if name == "xemusetup":
            return self._xemu_activate(rid)
        if name == "controllers":
            return self._controllers_activate(rid)
        if name == "btpair":
            return self._bt_activate(rid)
        if name == "biosfind":
            return self._bf_activate(rid)
        if name == "theme":
            return self._theme_activate(rid)
        if name == "simtycoon":
            return self._sim_activate(rid)
        if name == "create":
            return self._create_activate(rid)
        if name == "boot":
            return self._boot_activate(rid)
        if name == "worldgames":
            return self._wg_activate(rid)
        if name == "simpick":
            return self._simpick_activate(rid)
        if name == "findgames":
            return self._fg_activate(rid)
        if name == "screentv":
            return self._tv_activate(rid)
        if name == "quietboot":
            return self._quietboot_activate(rid)
        if name == "power":
            return self._power_activate(rid)
        if name == "steam":
            if rid == "steaminstall":
                self.installSteam()
            elif rid == "steamopen":
                g = next((x for x in self._all if x.gid == "app:steam"), None)
                if g is not None and not g.missing:
                    self._launch_game(g)
                    return "close"
            elif rid == "steamrescan":
                self.rescanSteam()
                return "refresh"
            elif rid == "steamproton":
                ok, msg = steamfix.set_default_proton(cfg_root=self.cfg.steam_root)
                kiosk.log_event("steam: " + msg)
                self.show_toast(msg, 9000)
            elif rid == "inputfix":
                self.fixInputPermissions()
            return ""
        if name == "fix":
            if rid == "inputfix":
                self.fixInputPermissions()
                return ""
            if rid == "soberfix":
                self._rbx_state = "idle"
                return "page:robloxfix"
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
                self.show_toast("Removed from CodeAque. The game's files are still on your disk.")
                return "close"
        if name == "winform":
            if rid == "name":
                return "osk:winname"
            if rid == "cover":
                return "browse:wincover"
            if rid == "add":
                return self.winFinish()
            if rid == "runinstaller":
                self._win_run_installer()
                return "refresh"
            if rid == "pcsupport":
                self.begin_install(list(windows.SUPPORT_SPECS), what="PC game support")
                return ""
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

    def _install_activate(self, rid: str) -> str:
        if rid == "install" or rid == "retry":
            self._inst_state = "ask"
            self._install_start()
            return "refresh"
        if rid == "cancel":
            if self._inst_job is not None:
                self._inst_job.cancel()
            return ""
        if rid == "launch":
            g = next((x for x in self._all if x.gid == self._inst_for_gid), None)
            self._inst_state = "idle"
            if g is not None and not g.missing and not self._running:
                self._launch_game(g)
            return "close"
        if rid == "copylog":
            self.copyLog()
            return ""
        return ""

    def _help_activate(self, rid: str) -> str:
        if rid != "reset":
            self._reset_armed = False
        if rid == "inputfix":
            self.fixInputPermissions()
            return ""
        if rid == "soberfix":
            self._rbx_state = "idle"
            return "page:robloxfix"
        if rid == "studiofix":
            st = self.studio
            if st.available and not studio_fix.problems(True):
                self.show_toast("The Studio looks fine. If it still fails, press Copy log and send it to whoever is helping you.", 7000)
            else:
                st.fix()
                self.show_toast("Fixing the Studio - CodeAque adds what is missing. This can take a minute.", 7000)
            return ""
        if rid == "about":
            return "page:about"
        if rid == "ck_emus":
            return "page:installmenu"
        if rid == "ck_steam" or rid == "steampage":
            return "page:steam"
        if rid == "nocovers":
            return "page:nocovers"
        if rid == "ck_games":
            return "page:addgames"
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
        exts = {"exe": (".exe",) + windows.ARCHIVE_EXT, "image": windows.IMAGE_EXT, "video": intro.VIDEO_EXT,
                "archive": tuple(files.ARCHIVE_SUFFIXES), "unreal": ("unrealeditor", "ue4editor")}.get(kind, ())
        found = []
        if path and exts:
            try:
                for child in sorted(Path(path).iterdir(), key=lambda c: c.name.lower()):
                    if (not child.name.startswith(".") and child.name.lower().endswith(exts) and child.is_file()):
                        found.append({"name": child.name, "path": str(child)})
            except OSError:
                pass
        data["files"] = found
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
            self.show_toast("CodeAque could not find a Windows program (.exe) inside that archive. "
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
        self._page_seen("winform")
        rows = []
        if self._win_msg:
            rows.append(self._info(("Working:  " if self._win_busy else "Result:  ") + self._win_msg))
        rows.append(self._info("PC games run on this computer through CodeAque's PC game support." if ok else windows.UMU_HINT))
        if not ok:
            rows.append({"kind": "item", "id": "pcsupport", "title": "Install PC game support",
                         "detail": "Downloads umu-launcher from its official page (it fetches the rest the first time a game starts). Only when you press Install."})
        rows.append(self._info(windows.ANTICHEAT_NOTE))
        rows.append(self._info("Program: " + self._win_exe))
        if self._win_exe and windows.is_installer(self._win_exe):
            rows.append({"kind": "done", "id": "runinstaller", "title": "This is an installer: run it with the PC Games Installer",
                         "detail": "The game's own setup opens; click through it as usual. When it closes, CodeAque finds the installed game and adds it."})
        return rows + [
            {"kind": "item", "id": "name", "title": "Name", "value": self._win_name or "(none)",
             "detail": "Press Enter to change the name."},
            {"kind": "item", "id": "cover", "title": "Cover picture (optional)",
             "value": Path(self._win_cover).name if self._win_cover else "None",
             "detail": "A .png or .jpg. Skip it for now if you do not have one."},
            {"kind": "done", "id": "add", "title": "Add this game"},
            {"kind": "item", "id": "back", "title": "Cancel"},
        ]

    def _win_run_installer(self) -> None:
        if getattr(self, "_win_busy", False):
            return
        setup, name = Path(self._win_exe), (self._win_name.strip() or windows.clean_name(Path(self._win_exe).parent.name))
        self._win_busy, self._win_msg = True, "The installer is open - finish it, then CodeAque adds the game..."

        def work():
            try:
                g, self._win_msg = windows.run_installer(self.cfg, setup, name)
                kiosk.log_event(f"pc games installer: {setup} -> {g.exe if g else 'nothing'}")
            except Exception as exc:  # pragma: no cover
                self._win_msg = f"Something went wrong: {exc}"
            finally:
                self._win_busy = False
                self._bgDone.emit()
                QTimer.singleShot(0, lambda: self.rescan(toast=False))
        threading.Thread(target=work, daemon=True, name="atari-pcinstaller").start()

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
        name = self._win_name.strip() or "PC game"
        windows.add_game(name, self._win_exe, self._win_cover)
        self._win_reset()
        self.rescan(toast=False)
        self._filter = windows.PLATFORM
        self.currentFilterChanged.emit()
        self._apply()
        ok, label = windows.runner_status(self.cfg)
        self.show_toast(f"Added {name} to PC Games." + ("" if ok else "  " + windows.UMU_HINT), 10000)
        return "close"

    @Slot(result=str)
    def homeDir(self) -> str:
        return str(Path.home())
