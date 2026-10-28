"""Screen recorder: the commands it builds, the start/stop wrapper, and one real recording of an Xvfb screen."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from atarilauncher import config, recorder

X11 = {"DISPLAY": ":7", "XDG_SESSION_TYPE": "x11"}
WAY = {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}
SRC = ("alsa_output.pci.analog-stereo.monitor", "alsa_input.pci.analog-stereo")


def has(*names):
    return lambda n: ("/usr/bin/" + n) if n in names else None


def cmd(cfg, which=has("ffmpeg"), env=X11, out=Path("/tmp/x.mp4")):
    return recorder.build_command(cfg, out, size=(1920, 1080), env=env, which=which, sources=SRC,
                                  run=lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=""))


def test_ffmpeg_x11grab_with_desktop_audio_and_ultrafast_x264():
    cfg = config.default_config()
    c = cmd(cfg)
    assert c[0] == "/usr/bin/ffmpeg" and "x11grab" in c and "1920x1080" in c and ":7+0,0" in c
    assert c[c.index("-framerate") + 1] == "30"
    assert c[c.index("-i", c.index("pulse")) - 0 + 1] == SRC[0]
    assert "libx264" in c and c[c.index("-preset") + 1] == "ultrafast" and c[c.index("-crf") + 1] == "28"
    assert c[-1] == "/tmp/x.mp4" and "+frag_keyframe+empty_moov+default_base_moof" in c


@pytest.mark.parametrize("mode,inputs", [("none", 0), ("desktop", 1), ("mic", 1), ("both", 2)])
def test_audio_modes(mode, inputs):
    cfg = config.default_config()
    cfg.rec_audio = mode
    c = cmd(cfg)
    assert c.count("pulse") == inputs
    assert ("amix=inputs=2" in " ".join(c)) == (mode == "both")
    assert ("-c:a" in c) == (inputs > 0)
    if mode == "mic":
        assert SRC[1] in c and SRC[0] not in c


def test_quality_and_fps_settings():
    cfg = config.default_config()
    cfg.rec_quality, cfg.rec_fps = "high", 60
    c = cmd(cfg)
    assert c[c.index("-crf") + 1] == "23" and c[c.index("-framerate") + 1] == "60"
    cfg.rec_quality = "low"
    assert cmd(cfg)[cmd(cfg).index("-crf") + 1] == "33"


def test_wayland_uses_wf_recorder_and_explains_when_missing():
    cfg = config.default_config()
    c = cmd(cfg, which=has("wf-recorder", "ffmpeg"), env=WAY)
    assert c[0] == "wf-recorder" and "-f" in c
    assert recorder.why_not(cfg, WAY, has("ffmpeg")).startswith("This is a Wayland session")
    assert recorder.why_not(cfg, X11, has()) .startswith("ffmpeg is not installed")
    assert recorder.why_not(cfg, X11, has("ffmpeg")) == "" and "no display" in recorder.why_not(cfg, {}, has("ffmpeg")).lower()
    assert cmd(cfg, which=has(), env=X11) == []


def test_vaapi_only_when_asked_and_available(monkeypatch):
    cfg = config.default_config()
    assert "h264_vaapi" not in cmd(cfg)
    cfg.rec_encoder = "vaapi"
    monkeypatch.setattr(recorder, "has_encoder", lambda *a, **k: True)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    c = cmd(cfg)
    assert "h264_vaapi" in c and "-vaapi_device" in c and "libx264" not in c


def test_names_folder_and_listing(tmp_path):
    cfg = config.default_config()
    assert recorder.out_dir(cfg, tmp_path) == tmp_path / "Videos" / "Atari Recordings"
    cfg.rec_dir = str(tmp_path / "mine")
    assert recorder.out_dir(cfg, tmp_path) == tmp_path / "mine"
    assert recorder.new_filename(0).startswith("Atari-1970-") or recorder.new_filename(0).startswith("Atari-1969-")
    d = tmp_path / "mine"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"1" * 10)
    time.sleep(0.02)
    (d / "b.mp4").write_bytes(b"2" * 10)
    (d / "notes.txt").write_text("x")
    assert [r["name"] for r in recorder.list_recordings(cfg, tmp_path)] == ["b.mp4", "a.mp4"]


def test_player_prefers_mpv_full_screen_then_xdg_open():
    assert recorder.player_command("/v/a.mp4", None, has("mpv", "xdg-open")) == ["mpv", "--fs", "/v/a.mp4"]
    assert recorder.player_command("/v/a.mp4", None, has("xdg-open")) == ["xdg-open", "/v/a.mp4"]
    assert recorder.player_command("/v/a.mp4", None, has()) == []


class FakeProc:
    def __init__(self, alive=True, stderr=b""):
        self.pid, self._alive, self.signals = 999999, alive, []
        self.stderr = type("S", (), {"read": lambda s: stderr})()

    def poll(self):
        return None if self._alive else 1

    def wait(self, t=None):
        self._alive = False

    def send_signal(self, s):
        self.signals.append(s)
        self._alive = False

    terminate = kill = lambda self: None


def test_recorder_wrapper_start_stop_and_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    cfg = config.default_config()
    cfg.rec_dir = str(tmp_path / "rec")
    r = recorder.Recorder(popen=lambda *a, **k: FakeProc())
    p = r.start(cfg, size=(640, 480), env=X11, which=has("ffmpeg"), sources=SRC)
    assert p is not None and p.parent == tmp_path / "rec" and r.active
    p.write_bytes(b"data")
    assert r.stop() == p and not r.active

    r2 = recorder.Recorder(popen=lambda *a, **k: FakeProc(alive=False, stderr=b"boom\nDevice busy"))
    assert r2.start(cfg, size=(640, 480), env=X11, which=has("ffmpeg"), sources=SRC) is None and "Device busy" in r2.error

    r3 = recorder.Recorder(popen=lambda *a, **k: FakeProc())
    assert r3.start(cfg, size=(640, 480), env=X11, which=has(), sources=SRC) is None and "ffmpeg is not installed" in r3.error


def test_config_round_trip_for_new_0_3_1_settings(tmp_path):
    cfg = config.default_config()
    cfg.rec_audio, cfg.rec_quality, cfg.rec_fps, cfg.rec_dir = "both", "high", 60, "/tmp/rr"
    cfg.steamgriddb_key, cfg.cover_wikipedia, cfg.esc_exit = "abc123", False, False
    path = tmp_path / "config.toml"
    config.save_config(cfg, path)
    back = config.load_config(path)
    assert (back.rec_audio, back.rec_quality, back.rec_fps, back.rec_dir) == ("both", "high", 60, "/tmp/rr")
    assert back.steamgriddb_key == "abc123" and back.cover_wikipedia is False and back.esc_exit is False
    path.write_text('[recording]\naudio = "bogus"\nfps = 12\n')
    bad = config.load_config(path)
    assert bad.rec_audio == "desktop" and bad.rec_fps == 30


@pytest.mark.skipif(not (shutil.which("Xvfb") and shutil.which("ffmpeg")), reason="needs Xvfb and ffmpeg")
def test_real_recording_of_an_xvfb_screen(tmp_path, monkeypatch):
    for n in range(120, 150):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
    xv = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "320x240x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        cfg = config.default_config()
        cfg.rec_audio, cfg.rec_dir = "none", str(tmp_path / "rec")
        r = recorder.Recorder()
        env = {"DISPLAY": f":{n}", "XDG_SESSION_TYPE": "x11"}
        p = r.start(cfg, size=(320, 240), env=env)
        assert p is not None, r.error
        time.sleep(1.5)
        assert r.elapsed() > 1
        out = r.stop()
        assert out == p and out.stat().st_size > 1000
        if shutil.which("ffprobe"):
            info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-of", "csv=p=0", str(out)],
                                  capture_output=True, text=True).stdout
            assert "h264" in info and "320,240" in info
    finally:
        xv.terminate()
        xv.wait(5)
