"""The start-up intro: your own video (played by an external player, skippable, never longer than the clip), Code's own
animation, the Settings rows + file picker, and real playback on a headless X server with a generated test clip."""
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atarilauncher import config, exitwatch, intro
from tests.test_exitwatch import X, tap, xdo, xvfb  # noqa: F401  (real Xvfb fixture + xdotool helpers)

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """A 2-second generated test clip (colour bars + a tone). Nothing third-party."""
    if not HAVE_FFMPEG:
        pytest.skip("needs ffmpeg")
    f = tmp_path_factory.mktemp("clip") / "test-intro.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=15",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(f)], check=True)
    return f


def script(tmp_path, body, name="player"):
    f = tmp_path / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f


# ------------------------------------------------------------------ files
def test_custom_file_picks_the_first_known_extension(tmp_path):
    assert intro.custom_file(tmp_path) is None
    (tmp_path / "intro.txt").write_text("x")
    (tmp_path / "intro.mkv").write_bytes(b"v")
    assert intro.custom_file(tmp_path) == tmp_path / "intro.mkv"
    (tmp_path / "intro.mp4").write_bytes(b"v")
    assert intro.custom_file(tmp_path) == tmp_path / "intro.mp4"
    (tmp_path / "intro.mp4").write_bytes(b"")                      # an empty file is not a video
    assert intro.custom_file(tmp_path) == tmp_path / "intro.mkv"
    for ext in (".webm", ".mov"):
        (tmp_path / ("intro" + ext)).write_bytes(b"v")
    assert {p.suffix for p in tmp_path.glob("intro.*")} >= {".webm", ".mov"}


def test_install_copies_replaces_and_refuses_the_wrong_things(tmp_path):
    data = tmp_path / "data"
    src = tmp_path / "Downloads" / "My Intro (final).WEBM"
    src.parent.mkdir()
    src.write_bytes(b"webm-bytes")
    (data).mkdir()
    (data / "intro.mp4").write_bytes(b"old")
    ok, text = intro.install(src, data)
    assert ok and (data / "intro.webm").read_bytes() == b"webm-bytes" and not (data / "intro.mp4").exists()
    assert src.read_bytes() == b"webm-bytes"                       # the original is only read
    assert not list(data.glob("*.part"))
    assert intro.custom_file(data) == data / "intro.webm"
    ok, text = intro.install(tmp_path / "notes.txt", data)
    assert not ok and ".mp4" in text
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert not intro.install(empty, data)[0] and not intro.install(tmp_path / "missing.mp4", data)[0]
    assert (data / "intro.webm").is_file()                         # failures change nothing
    assert intro.remove(data) == 1 and intro.custom_file(data) is None and intro.remove(data) == 0


def test_plan_follows_the_two_switches_and_the_env(tmp_path):
    cfg = config.default_config()
    nop = lambda n: None
    assert intro.plan(cfg, tmp_path, {}, which=nop).mode == "default"          # nothing chosen, no player: Code's own animation
    b = intro.plan(cfg, tmp_path, {}, which=lambda n: "/usr/bin/" + n)
    assert b.mode == "builtin" and b.file == intro.bundled_file()              # nothing chosen, a player exists: the shipped video
    (tmp_path / "intro.mp4").write_bytes(b"v")
    p = intro.plan(cfg, tmp_path, {})
    assert p.mode == "custom" and p.file == tmp_path / "intro.mp4"             # ON by default as soon as a file exists
    cfg.intro_enabled = False
    assert intro.plan(cfg, tmp_path, {}).mode == ""                            # your video is off: no intro at all
    cfg.intro_enabled = True
    assert intro.plan(cfg, tmp_path, {"ATARI_NO_INTRO": "1"}).mode == ""
    (tmp_path / "intro.mp4").unlink()
    cfg.intro_default = False
    assert intro.plan(cfg, tmp_path, {}).mode == ""


def test_the_shipped_intro_video_is_there_and_is_a_real_clip():
    f = intro.bundled_file()
    assert f is not None and f.name == "code-intro.mp4" and 6_000_000 < f.stat().st_size < 9_000_000
    assert f.read_bytes()[4:8] == b"ftyp"                                    # an MP4 container
    # the ORIGINAL video, not a re-compressed copy: the source is 1280x720 at about 6 Mbit/s (it is not 1080p; nothing is upscaled)
    if shutil.which("ffprobe"):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,bit_rate",
                              "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.strip().split(",")
        assert int(out[0]) == 1280 and int(out[1]) == 720 and int(out[2]) > 5_000_000


def test_players_fill_the_whole_screen_borderless_keep_the_whole_picture_and_hide_the_pointer():
    mpv = intro.player_command("mpv", "mpv", "/x.mp4", muted=False)
    for flag in ("--fs", "--no-border", "--ontop", "--keepaspect", "--panscan=0", "--cursor-autohide=always"):
        assert flag in mpv, flag                                              # full screen, no frame, black bars not cropping, no pointer
    assert not any(a.startswith("--panscan=") and a != "--panscan=0" for a in mpv) and "--video-zoom" not in " ".join(mpv)
    ff = intro.player_command("ffplay", "ffplay", "/x.mp4", muted=False)
    assert "-fs" in ff and "-noborder" in ff and "-x" not in ff and "-vf" not in ff     # ffplay keeps the aspect: black bars
    vlc = intro.player_command("cvlc", "cvlc", "/x.mp4", muted=False)
    assert "--fullscreen" in vlc and "--no-video-deco" in vlc and "--video-on-top" in vlc and "--mouse-hide-timeout=1" in vlc


def test_the_intro_screen_and_window_are_full_screen_with_no_pointer_even_in_windowed_mode():
    from pathlib import Path
    qml = Path(intro.__file__).parent / "qml"
    main = (qml / "Main.qml").read_text()
    assert 'mode === "intro" && Qt.platform.pluginName !== "offscreen")) ? Window.FullScreen' in main                     # full screen during the intro, desktop or Code-only mode
    assert "Qt.BlankCursor" in (qml / "Intro.qml").read_text()


def test_settings_are_saved_and_default_on(tmp_path):
    cfg = config.default_config()
    assert cfg.intro_enabled and cfg.intro_default
    cfg.intro_enabled = cfg.intro_default = False
    f = tmp_path / "config.toml"
    config.save_config(cfg, f)
    back = config.load_config(f)
    assert back.intro_enabled is False and back.intro_default is False
    f.write_text("[ui]\nvolume = 0.5\n")
    old = config.load_config(f)
    assert old.intro_enabled and old.intro_default


# ------------------------------------------------------------------ the player command lines
def test_player_commands():
    mpv = intro.player_command("mpv", "/usr/bin/mpv", "/d/intro.mp4", muted=False, input_conf="/d/in.conf")
    assert mpv[0] == "/usr/bin/mpv" and "--fs" in mpv and "--no-audio" not in mpv and "--input-conf=/d/in.conf" in mpv
    assert mpv[-2:] == ["--", "/d/intro.mp4"] and "--keep-open=no" in mpv
    assert "--no-audio" in intro.player_command("mpv", "mpv", "/x.mp4", muted=True)
    ff = intro.player_command("ffplay", "ffplay", "/x.mp4", muted=True)
    assert "-autoexit" in ff and "-fs" in ff and "-an" in ff and ff[-1] == "/x.mp4"
    assert "-an" not in intro.player_command("ffplay", "ffplay", "/x.mp4", muted=False)
    vlc = intro.player_command("cvlc", "cvlc", "/x.mp4", muted=True)
    assert "--play-and-exit" in vlc and "--no-audio" in vlc and vlc[-1] == "vlc://quit"
    assert intro.find_player(lambda n: {"ffplay": "/u/ffplay", "cvlc": "/u/cvlc"}.get(n)) == ("ffplay", "/u/ffplay")
    assert intro.find_player(lambda n: None) == ("", "")


def test_input_conf_makes_any_key_and_click_quit(tmp_path):
    f = Path(intro.write_input_conf(tmp_path))
    lines = f.read_text().split("\n")
    for k in ("ESC quit", "ENTER quit", "ANY_UNICODE quit", "MBTN_LEFT quit", "SPACE quit"):
        assert k in lines


def test_length_limit_is_the_clip_plus_a_second_or_two():
    assert intro.time_limit(10.0) == 10.0 + intro.GRACE and intro.time_limit(None) == intro.UNKNOWN_CAP
    assert intro.probe_seconds("/x.mp4", which=lambda n: None) is None
    fake = lambda cmd, **kw: type("R", (), {"stdout": "10.016000\n"})()
    assert intro.probe_seconds("/x.mp4", which=lambda n: "/u/ffprobe", run=fake) == pytest.approx(10.016)
    assert intro.probe_seconds("/x.mp4", which=lambda n: "/u/ffprobe", run=lambda *a, **k: type("R", (), {"stdout": ""})()) is None


@pytest.mark.skipif(not (HAVE_FFMPEG and shutil.which("ffprobe")), reason="needs ffprobe")
def test_probe_reads_a_real_clip_length(clip):
    assert intro.probe_seconds(clip) == pytest.approx(2.0, abs=0.2)


# ------------------------------------------------------------------ Playback (the safety rules)
def run_playback(cmd, limit, **kw):
    ended = []
    pb = intro.Playback(cmd, limit, ended.append, **kw).start()
    pb.done.wait(15)
    return pb, ended


def test_a_clip_that_ends_by_itself_is_finished(tmp_path):
    pb, ended = run_playback([str(script(tmp_path, "sleep 0.4"))], 10)
    assert ended == ["finished"] and pb.proc.poll() == 0


def test_skip_stops_the_player_quickly(tmp_path):
    p = script(tmp_path, "exec sleep 60")
    ended = []
    pb = intro.Playback([str(p)], 100, ended.append).start()
    time.sleep(0.3)
    t0 = time.time()
    pb.skip()
    pb.done.wait(5)
    assert ended == ["skipped"] and time.time() - t0 < 3 and pb.proc.poll() is not None


def test_it_never_waits_longer_than_the_limit(tmp_path):
    t0 = time.time()
    pb, ended = run_playback([str(script(tmp_path, "exec sleep 60"))], 0.5)
    assert ended == ["timeout"] and time.time() - t0 < 5 and pb.proc.poll() is not None


def test_a_player_that_cannot_run_is_skipped_quietly(tmp_path):
    assert run_playback([str(tmp_path / "nope")], 10)[1] == ["failed"]
    assert run_playback([str(script(tmp_path, "exit 3"))], 10)[1] == ["failed"]       # died at once with an error


def test_a_player_that_ignores_sigterm_is_still_stopped(tmp_path):
    p = script(tmp_path, "trap '' TERM; while true; do sleep 0.1; done")
    ended = []
    pb = intro.Playback([str(p)], 100, ended.append).start()
    time.sleep(0.3)
    pb.skip()
    pb.done.wait(8)
    assert ended == ["skipped"] and pb.proc.poll() is not None


# ------------------------------------------------------------------ real keys on a real (headless) X server
@X
def test_any_new_key_skips_but_a_key_already_held_does_not(xvfb, tmp_path):
    p = script(tmp_path, "exec sleep 60")
    xdo("keydown", "shift")                                         # held down before the clip starts
    time.sleep(0.1)
    ended = []
    pb = intro.Playback([str(p)], 100, ended.append, keys=exitwatch.X11Keys).start()
    time.sleep(0.6)
    assert ended == []
    tap("a")                                                        # a NEW key = skip
    pb.done.wait(5)
    xdo("keyup", "shift")
    assert ended == ["skipped"]


@X
def test_real_ffplay_plays_a_generated_clip_to_the_end(xvfb, clip, monkeypatch):
    if not shutil.which("ffplay"):
        pytest.skip("needs ffplay")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    cmd = intro.player_command("ffplay", shutil.which("ffplay"), clip, muted=False)
    t0 = time.time()
    pb, ended = run_playback(cmd, 15)
    if ended == ["failed"]:
        pytest.skip("ffplay cannot open a window on this Xvfb")
    assert ended == ["finished"] and 1.0 < time.time() - t0 < 10


@X
def test_real_ffplay_is_skipped_by_a_key_press(xvfb, clip, monkeypatch):
    if not shutil.which("ffplay"):
        pytest.skip("needs ffplay")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    cmd = intro.player_command("ffplay", shutil.which("ffplay"), clip, muted=True)
    ended = []
    pb = intro.Playback(cmd, 15, ended.append, keys=exitwatch.X11Keys).start()
    time.sleep(0.8)
    if ended == ["failed"]:
        pytest.skip("ffplay cannot open a window on this Xvfb")
    t0 = time.time()
    tap("space")
    pb.done.wait(6)
    assert ended == ["skipped"] and time.time() - t0 < 4 and pb.proc.poll() is not None


# ------------------------------------------------------------------ the whole app: intro screen, skip, Settings
pytest.importorskip("PySide6")
from PySide6.QtCore import QMetaObject, Qt  # noqa: E402

from tests.test_features_ui import conf, wait_for  # noqa: E402
from tests.test_studio_click import click_text, texts  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


@pytest.fixture
def intro_on(monkeypatch):
    monkeypatch.delenv("ATARI_NO_INTRO", raising=False)
    monkeypatch.setattr(intro, "DEFAULT_SECONDS", 0.8)
    # most tests are about the short animation: pretend no video player is installed for the *default* choice only
    monkeypatch.setattr(intro, "default_plan", lambda which=None: intro.Plan("default"))


def make_ui(app, tmp_path, monkeypatch, sink=None):
    conf(tmp_path, "[steam]\nenabled = false\n")
    return Ui(app, tmp_path, monkeypatch, config_exists=False)


def be_mod():
    from atarilauncher import backend
    return backend


def start_with_sink(app, tmp_path, monkeypatch):
    """Ui whose backend records sound commands (the sink is installed before the window asks for the intro sound)."""
    sent = []
    orig = be_mod().Backend.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self._sound_sink = sent.append
    monkeypatch.setattr(be_mod().Backend, "__init__", init)
    return make_ui(app, tmp_path, monkeypatch), sent


def test_atari_own_intro_shows_the_wordmark_plays_its_sound_and_ends(app, tmp_path, monkeypatch, intro_on):
    monkeypatch.setattr(intro, "DEFAULT_SECONDS", 2.5)
    monkeypatch.setattr(intro, "find_player", lambda which=None: ("", ""))       # no player: the animation instead of the video
    ui, sent = start_with_sink(app, tmp_path, monkeypatch)
    try:
        assert ui.mode == "intro" and ui.backend.introActive and ui.backend.introMode == "default"
        assert "intro" in sent and "start" not in sent                       # its own sound replaces the start chime
        pump(app, 500)
        img = ui.win.grabWindow()
        gold = sum(1 for x in range(0, img.width(), 8) for y in range(0, img.height(), 8)
                   if (lambda c: c.red() > 150 and c.green() > 100 and c.blue() < 90)(img.pixelColor(x, y)))
        assert gold > 20                                                     # the gold Code logo is really drawn
        assert any(t == "Press any key to skip" for t, _ in texts(ui))
        assert wait_for(app, lambda: ui.mode == "library", 8), ui.mode      # it ends by itself after its length
        assert not ui.backend.introActive and not ui.warnings, ui.warnings
        ui.key(Qt.Key_Down)                                                  # the library works normally afterwards
        assert ui.mode == "library"
    finally:
        ui.close()


@pytest.mark.parametrize("how", ["key", "esc", "click", "gamepad"])
def test_any_key_click_or_controller_button_skips_atari_own_intro(app, tmp_path, monkeypatch, intro_on, how):
    monkeypatch.setattr(intro, "DEFAULT_SECONDS", 30)
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert ui.mode == "intro"
        if how == "key":
            ui.key(Qt.Key_X)
        elif how == "esc":
            ui.key(Qt.Key_Escape)
        elif how == "click":
            ui.click(300, 300)
        else:
            ui.backend.send_action("accept")
            pump(app, 100)
        assert ui.mode == "library" and not ui.backend.introActive
    finally:
        ui.close()


def test_both_switches_off_means_no_intro(app, tmp_path, monkeypatch, intro_on):
    conf(tmp_path, "[steam]\nenabled = false\n[ui]\nintro_default = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        assert ui.mode == "library" and not ui.backend.introActive
    finally:
        ui.close()


@pytest.fixture
def your_video(tmp_path, monkeypatch, intro_on):
    """~/.local/share/atari/intro.mp4 exists, and the 'player' is a script that records how it was called."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "intro.mp4").write_bytes(b"not really a video")
    out = tmp_path / "player-args"
    state = {"body": f'echo "$@" > {out}\nexec sleep 30'}

    def make():
        return script(tmp_path, state["body"], "fakeplayer")
    monkeypatch.setattr(intro, "find_player", lambda which=None: ("mpv", str(make())))
    monkeypatch.setattr(intro, "probe_seconds", lambda *a, **k: 30.0)
    return out, state


def test_your_video_plays_full_screen_and_any_key_skips_it(app, tmp_path, monkeypatch, your_video):
    out, state = your_video
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert ui.mode == "intro" and ui.backend.introMode == "custom"
        assert wait_for(app, lambda: out.exists() and out.read_text().strip() != "", 5)
        args = out.read_text()
        assert "--fs" in args and str(tmp_path / "data" / "intro.mp4") in args and "--no-audio" in args   # ATARI_NO_SOUND = quiet
        pb = ui.backend._intro_play
        assert pb is not None and pb.active
        ui.key(Qt.Key_Return)
        assert wait_for(app, lambda: ui.mode == "library", 6), ui.mode
        assert pb.proc.poll() is not None                                    # the player was really stopped
    finally:
        ui.close()


def test_with_no_video_of_your_own_the_shipped_code_intro_video_plays_and_any_key_skips_it(app, tmp_path, monkeypatch, your_video):
    out, state = your_video
    (tmp_path / "data" / "intro.mp4").unlink()                               # nothing of your own
    monkeypatch.setattr(intro, "default_plan", lambda which=None: intro.Plan("builtin", intro.bundled_file()))
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert ui.mode == "intro" and ui.backend.introMode == "builtin"
        assert wait_for(app, lambda: out.exists() and out.read_text().strip() != "", 5)
        args = out.read_text()
        assert "--fs" in args and "assets/intro/code-intro.mp4" in args
        ui.key(Qt.Key_Return)
        assert wait_for(app, lambda: ui.mode == "library", 6), ui.mode
    finally:
        ui.close()


def test_sound_switch_controls_the_audio_of_your_video(app, tmp_path, monkeypatch, your_video):
    out, state = your_video
    monkeypatch.delenv("ATARI_NO_SOUND", raising=False)
    monkeypatch.setenv("ATARI_NO_SOUND", "")                                 # sound allowed by the environment
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert wait_for(app, lambda: out.exists() and out.read_text().strip() != "", 5)
        assert "--no-audio" not in out.read_text()                           # Sound effects ON -> the clip has sound
        ui.backend.skipIntro()
        assert wait_for(app, lambda: ui.mode == "library", 6)
    finally:
        ui.close()
    out.unlink()
    (tmp_path / "conf").mkdir(exist_ok=True)
    conf(tmp_path, "[steam]\nenabled = false\n[ui]\nsound_effects = false\n")
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        assert wait_for(app, lambda: out.exists() and out.read_text().strip() != "", 5)
        assert "--no-audio" in out.read_text()                               # Sound effects OFF -> muted
        ui.backend.skipIntro()
    finally:
        ui.close()


def test_a_clip_that_ends_by_itself_goes_to_the_library(app, tmp_path, monkeypatch, your_video):
    out, state = your_video
    state["body"] = "sleep 0.5"
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert ui.mode == "intro"
        assert wait_for(app, lambda: ui.mode == "library", 8), ui.mode
    finally:
        ui.close()


@pytest.mark.parametrize("player", ["missing", "broken"])
def test_playback_trouble_skips_the_intro_and_atari_starts(app, tmp_path, monkeypatch, your_video, player):
    out, state = your_video
    if player == "missing":
        monkeypatch.setattr(intro, "find_player", lambda which=None: ("", ""))
    else:
        state["body"] = "exit 1"
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert wait_for(app, lambda: ui.mode == "library", 6), ui.mode
        assert not ui.warnings and ui.backend.totalGames >= 0
    finally:
        ui.close()


def test_startup_never_waits_longer_than_the_clip(app, tmp_path, monkeypatch, your_video):
    out, state = your_video
    state["body"] = "trap '' TERM; while true; do sleep 0.1; done"           # a player that hangs and ignores SIGTERM
    monkeypatch.setattr(intro, "probe_seconds", lambda *a, **k: 0.3)
    monkeypatch.setattr(intro, "GRACE", 0.3)
    t0 = time.time()
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        assert wait_for(app, lambda: ui.mode == "library", 8), ui.mode
        assert time.time() - t0 < 8
    finally:
        ui.close()


def test_atari_key_handling_still_works_after_the_intro(app, tmp_path, monkeypatch, intro_on):
    """Esc / the Esc-twice watcher are unaffected: after the intro the normal Esc behaviour is back."""
    monkeypatch.setattr(intro, "DEFAULT_SECONDS", 30)
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        ui.key(Qt.Key_Escape)                                                # skips the intro, does nothing else
        assert ui.mode == "library"
        ui.key(Qt.Key_Escape)                                                # a plain Esc in the library keeps its old meaning
        assert ui.mode == "menu" and not ui.warnings                         # (it opens the options menu, as before)
        assert exitwatch.enabled(ui.backend.cfg)
    finally:
        ui.close()


# ------------------------------------------------------------------ Settings
def setup_rows(ui):
    return {r["kind"]: r for r in ui.backend.setupRows() if r["kind"].startswith("intro")}


def test_settings_rows_toggles_choose_and_remove(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Videos").mkdir()
    vid = home / "Downloads" / "my intro (final).mp4"
    vid.write_bytes(b"v" * 100)
    (home / "Downloads" / "notes.txt").write_text("x")
    (home / "Downloads" / "pic.png").write_bytes(b"p")
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        b = ui.backend
        rows = setup_rows(ui)
        assert rows["introvideo"]["value"] == "None" and "introremove" not in rows
        assert rows["introdefault"]["value"] == "ON" and {"introchoose", "intropreview"} <= set(rows)
        assert b.introBrowseStart() == str(home / "Downloads")
        listing = b.listFiles(str(home / "Downloads"), "video")
        assert [f["name"] for f in listing["files"]] == ["my intro (final).mp4"]          # only videos are offered
        assert any(d["name"] == "Videos" for d in b.listDir("")["dirs"])                  # Videos is one of the starting places
        assert b.introPicked(str(vid)) == "ok"
        data = tmp_path / "data"
        assert (data / "intro.mp4").read_bytes() == b"v" * 100 and vid.is_file()
        rows = setup_rows(ui)
        assert rows["introvideo"]["value"] == "ON" and "my intro" not in rows["introvideo"]["title"] and "intro.mp4" in rows["introvideo"]["detail"]
        assert "introremove" in rows
        b.toggleIntro()
        assert setup_rows(ui)["introvideo"]["value"] == "OFF" and b.cfg.intro_enabled is False
        b.toggleIntro()
        b.toggleIntroDefault()
        assert setup_rows(ui)["introdefault"]["value"] == "OFF"
        assert b.introPicked(str(home / "Downloads" / "notes.txt")) == "error" and "mp4" in b.toast
        b.removeIntro()
        assert not (data / "intro.mp4").exists() and "introremove" not in setup_rows(ui)
        assert vid.is_file()                                                              # the original stays
        (home / "Downloads").rename(home / "Dl")
        assert b.introBrowseStart() == str(home / "Videos")                                # no Downloads: Videos next
    finally:
        ui.close()


def test_choose_intro_video_with_the_big_button_picker(app, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    vid = home / "Downloads" / "clip.mkv"
    vid.write_bytes(b"v" * 50)
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(app, 200)
        assert ui.mode == "setup"
        rows = ui.backend.setupRows()
        target = next(i for i, r in enumerate(rows) if r["kind"] == "introchoose")
        for _ in range(sum(1 for r in rows[:target] if r["kind"] != "info")):         # walk down with the keyboard
            ui.key(Qt.Key_Down, 20)
        ui.key(Qt.Key_Return)
        assert ui.mode == "browse"
        shown = [t for t, _ in texts(ui)]
        assert "\u25c0  Back" in shown and "clip.mkv" in shown                          # a visible Back and the video
        click_text(ui, "clip.mkv")                                                      # ...picked with the mouse
        pump(app, 200)
        assert ui.mode == "setup"                                                       # back on the Settings screen
        assert (tmp_path / "data" / "intro.mkv").read_bytes() == b"v" * 50
        assert any("Intro video set" in ui.backend.toast for _ in [0])
    finally:
        ui.close()


def test_play_the_intro_now_from_settings_returns_to_settings(app, tmp_path, monkeypatch, intro_on):
    monkeypatch.setattr(intro, "DEFAULT_SECONDS", 30)
    monkeypatch.setattr(intro, "find_player", lambda which=None: ("", ""))                 # the animation (no real player in a test)
    monkeypatch.setenv("ATARI_NO_INTRO", "1")                                              # not at start-up, only on request
    ui = make_ui(app, tmp_path, monkeypatch)
    try:
        QMetaObject.invokeMethod(ui.win, "openSetup")
        pump(app, 200)
        assert ui.mode == "setup"
        ui.backend.previewIntro()
        pump(app, 200)
        assert ui.mode == "intro"
        ui.key(Qt.Key_A)
        assert ui.mode == "setup" and not ui.backend.introActive
    finally:
        ui.close()


def test_selftest_and_demo_never_wait_for_an_intro(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", ATARI_DATA_DIR=str(tmp_path / "d"), ATARI_CONFIG_DIR=str(tmp_path / "c"),
               HOME=str(tmp_path), ATARI_NO_SOUND="1", ATARI_NO_UPDATE_CHECK="1", ATARI_NO_COVERS="1")
    env.pop("ATARI_NO_INTRO", None)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "atarilauncher", "--selftest", "--windowed"], env=env,
                       cwd=str(Path(__file__).resolve().parent.parent), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert time.time() - t0 < 30


def test_no_third_party_logo_or_video_is_shipped():
    root = Path(__file__).resolve().parent.parent
    shipped = [p.relative_to(root).as_posix() for p in (root / "atarilauncher").rglob("*")
               if p.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov", ".avi")]
    assert shipped == ["atarilauncher/assets/intro/code-intro.mp4"]        # exactly one clip: the project owner's own Code intro
    assert (root / "atarilauncher" / "assets" / "sfx" / "intro.wav").is_file()

