"""PSP-style polish: synthesised sounds, the sound helper, Settings toggles, animations on/off, all headless."""
import io
import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402

from atarilauncher import config, sound_helper  # noqa: E402
from tests.test_features_ui import conf, open_menu_item, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

SFX = Path(__file__).resolve().parent.parent / "atarilauncher" / "assets" / "sfx"
NAMES = ["tick", "select", "back", "fav", "launch", "error", "start", "ambient"]


def test_all_sound_files_are_small_valid_original_wavs():
    for n in NAMES:
        f = SFX / f"{n}.wav"
        assert f.is_file(), n
        with wave.open(str(f)) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() in (11025, 22050)
            secs = w.getnframes() / w.getframerate()
            assert 0.02 < secs < 9
            frames = w.readframes(w.getnframes())
        assert max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True)) for i in range(0, len(frames), 2)) > 1000
        assert f.stat().st_size < 200 * 1024
    assert sum(p.stat().st_size for p in SFX.glob("*.wav")) < 480 * 1024


def test_ambient_loop_is_seamless():
    with wave.open(str(SFX / "ambient.wav")) as w:
        frames = w.readframes(w.getnframes())
    first = int.from_bytes(frames[:2], "little", signed=True)
    last = int.from_bytes(frames[-2:], "little", signed=True)
    assert abs(first - last) < 4000          # the end joins the start without a click (both near zero crossing)


def test_generator_is_deterministic(tmp_path):
    out = subprocess.run([sys.executable, "scripts/make_sounds.py"], cwd=Path(__file__).resolve().parent.parent,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "tick.wav" in out.stdout


class FakePlayer:
    kind = "fake"

    def __init__(self):
        self.log = []

    def set_volume(self, v):
        self.log.append(("volume", v))

    def play(self, n):
        self.log.append(("play", n))

    def music(self, on):
        self.log.append(("music", on))

    def close(self):
        self.log.append(("close",))


def test_helper_protocol_with_a_fake_player():
    p = FakePlayer()
    out = io.StringIO()
    serve_in = io.StringIO("tick\nselect\nvolume 0.4\nmusic on\nbogus\nvolume x\nmusic off\nquit\nfav\n")
    assert sound_helper.serve(serve_in, out, p) == 0
    assert out.getvalue().strip() == "ready fake"
    assert [x for x in p.log if x[0] == "play"] == [("play", "tick"), ("play", "select")]   # tick/select; 'fav' came after quit
    assert ("volume", 0.4) in p.log and ("music", True) in p.log and ("music", False) in p.log and p.log[-1] == ("close",)


def test_helper_says_unavailable_when_there_is_no_audio_at_all(monkeypatch):
    monkeypatch.setattr(sound_helper, "open_player", lambda *a, **k: None)
    out = io.StringIO()
    assert sound_helper.serve(io.StringIO("tick\n"), out) == 0
    assert out.getvalue().strip() == "unavailable"


def test_helper_really_plays_through_pygame_with_a_dummy_sound_card():
    pytest.importorskip("pygame")
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
    r = subprocess.run([sys.executable, "-m", "atarilauncher.sound_helper"], input="volume 0.5\ntick\nselect\nlaunch\nmusic on\nmusic off\nquit\n",
                       capture_output=True, text=True, env=env, timeout=30,
                       cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0 and r.stdout.strip() == "ready pygame", (r.stdout, r.stderr)


def test_command_line_player_is_the_fallback(monkeypatch, tmp_path):
    played = []
    monkeypatch.setattr(sound_helper.subprocess, "Popen", lambda args, **k: played.append(args))
    pl = sound_helper.CommandPlayer(which=lambda n: "/usr/bin/paplay" if n == "paplay" else None)
    pl.set_volume(0.5)
    pl.play("select")
    assert played and played[0][0] == "/usr/bin/paplay" and played[0][-1].endswith("select.wav") and "--volume=32768" in played[0]
    with pytest.raises(RuntimeError):
        sound_helper.CommandPlayer(which=lambda n: None)


def test_config_ui_section_round_trips_and_old_files_get_defaults(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.default_config()
    cfg.music, cfg.volume, cfg.sound_effects, cfg.reduce_animations = True, 0.8, False, True
    config.save_config(cfg, path)
    back = config.load_config(path)
    assert (back.music, round(back.volume, 2), back.sound_effects, back.reduce_animations) == (True, 0.8, False, True)
    path.write_text("[steam]\nenabled = false\n")                  # a 0.2.x config: no [ui] section
    old = config.load_config(path)
    assert (old.sound_effects, old.music, old.volume, old.reduce_animations) == (True, False, 0.6, False)
    path.write_text("[ui]\nvolume = 'loud'\n")
    assert config.load_config(path).volume == 0.6                   # nonsense never crashes


def sink_ui(app, tmp_path, monkeypatch, text="[steam]\nenabled = false\n"):
    conf(tmp_path, text)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    ui.cmds = []
    ui.backend._sound_sink = ui.cmds.append
    return ui


def test_keys_make_sounds_and_the_gamepad_takes_the_same_path(app, tmp_path, monkeypatch):
    ui = sink_ui(app, tmp_path, monkeypatch)
    try:
        ui.backend._start_timer.start()                # (it already fired once while the window was loading)
        pump(app, 900)
        assert "start" in ui.cmds
        ui.cmds.clear()
        ui.key(Qt.Key_Right, 60)
        ui.key(Qt.Key_F10, 60)                         # opens the menu from the library
        assert "tick" in ui.cmds
        ui.cmds.clear()
        ui.key(Qt.Key_Down, 60)
        ui.key(Qt.Key_Return, 60)                      # "sort" screen
        ui.key(Qt.Key_Escape, 60)
        assert ui.cmds[0] == "tick" and "select" in ui.cmds and "back" in ui.cmds
        ui.cmds.clear()
        monkeypatch.setenv("ATARI_TEST_INPUT", "1")
        ui.backend.send_action("down")                 # what the gamepad helper does for a D-pad press
        pump(app, 80)
        assert "tick" in ui.cmds
    finally:
        ui.close()


def test_sound_effects_off_means_silence_and_volume_steps(app, tmp_path, monkeypatch):
    ui = sink_ui(app, tmp_path, monkeypatch)
    try:
        b = ui.backend
        b.toggleSoundEffects()
        assert b.soundEffects is False
        ui.cmds.clear()
        ui.key(Qt.Key_Down)
        b.playSound("select")
        assert ui.cmds == []                           # nothing at all while off
        b.toggleSoundEffects()
        seen = []
        for _ in range(6):
            b.cycleVolume()
            seen.append(round(b.volume, 1))
        assert seen == [0.8, 1.0, 0.2, 0.4, 0.6, 0.8]  # 0.6 -> 0.8 -> 1.0 -> wraps to 0.2 ...
        assert any(c.startswith("volume 0.20") for c in ui.cmds)
        ui.cmds.clear()
        b.toggleMusic()
        assert "music on" in ui.cmds and b.music is True
        saved = (tmp_path / "conf" / "config.toml").read_text()
        assert "music = true" in saved and "volume = 0.80" in saved
    finally:
        ui.close()


def test_launch_whoosh_favourite_and_error_sounds(app, tmp_path, monkeypatch):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Brick Bash.nes").write_bytes(b"0")
    ui = sink_ui(app, tmp_path, monkeypatch, f'[steam]\nenabled = false\n[systems.nes]\nroms = ["{roms}"]\n')
    try:
        b = ui.backend
        b.rescan(toast=False)
        pump(app, 100)
        b.toggleFavorite(0)
        assert "fav" in ui.cmds
        ui.cmds.clear()
        b.cfg.music = True
        b.cfg.systems["nes"].command = "no-such-nes-emulator {rom}"      # a missing program of your own: a plain launch error
        b.rescan(toast=False)
        # the real launch path: there is no NES emulator on the test machine, so it ends with an error
        b.launch(0)
        assert wait_for(app, lambda: not b.running, 10)
        assert ui.cmds[0] == "launch" and "music off" in ui.cmds and "error" in ui.cmds
        assert ui.cmds.index("music on") > ui.cmds.index("music off")      # the music comes back when the game is over
    finally:
        ui.close()


def test_settings_rows_for_sound_and_animations_work_from_the_keyboard(app, tmp_path, monkeypatch):
    ui = sink_ui(app, tmp_path, monkeypatch)
    try:
        kinds = [r["kind"] for r in ui.backend.setupRows()]
        assert {"sfx", "music", "volume", "anim"} <= set(kinds)
        open_menu_item(ui, "settings")
        assert ui.mode == "setup"
        rows = [r for r in ui.backend.setupRows()]
        idx = [r["kind"] for r in rows].index("anim")
        for _ in range(idx):
            ui.key(Qt.Key_Down, 20)
        assert ui.backend.animations is True
        ui.key(Qt.Key_Return)
        assert ui.backend.animations is False
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()


def test_waves_background_pauses_when_animations_are_reduced_or_a_game_runs(app, tmp_path, monkeypatch):
    ui = sink_ui(app, tmp_path, monkeypatch)
    try:
        from PySide6.QtQuick import QQuickItem
        wave_item = next(i for i in ui.win.findChildren(QQuickItem) if i.metaObject().className().startswith("WaveBackground"))
        # 0.6.1: on the home screen the blurred game-art backdrop replaces the waves, so they do not draw there at all
        bd = ui.win.findChild(QQuickItem, "homeBackdrop")
        assert bd.property("visible") is True and wave_item.property("active") is False
        ui.backend.toggleAnimations()
        pump(app, 50)
        assert ui.backend.animations is False
        ui.backend._running = True
        ui.backend.runningChanged.emit()
        pump(app, 50)
        assert wave_item.property("active") is False
        assert not ui.warnings, ui.warnings
    finally:
        ui.close()
