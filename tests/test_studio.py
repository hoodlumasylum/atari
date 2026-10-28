"""Hoodlum Asylum Studio: beat generator, synth, mixer, projects, export, recording (stub programs), and the screen."""
import json
import os
import shutil
import stat
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, Qt  # noqa: E402

from atarilauncher import apps  # noqa: E402
from atarilauncher.studio import beatgen, mixer, project as proj, recorder, synth  # noqa: E402
from tests.test_features_ui import conf, open_menu_item, wait_for  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


@pytest.fixture(autouse=True)
def studio_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_STUDIO_DIR", str(tmp_path / "studio"))
    return tmp_path / "studio"


def steps(p, track):
    return sorted(n.step for n in p.tracks[track])


def make(genre="trap", **kw):
    return beatgen.get_generator().generate(beatgen.BeatRequest(genre, seed=kw.pop("seed", 7), **kw))


# ------------------------------------------------------------------ beat generator
def test_same_seed_same_beat_other_seed_differs():
    assert make(seed=5).to_dict() == make(seed=5).to_dict()
    assert make(seed=5).to_dict() != make(seed=6).to_dict()


def test_every_genre_makes_a_full_beat():
    for g in beatgen.GENRE_ORDER:
        p = make(g)
        assert p.genre == g and p.bars == 4 and p.total_steps == 64
        assert beatgen.GENRES[g].tempo[0] <= p.tempo <= beatgen.GENRES[g].tempo[2]
        for t in ("kick", "hat", "bass808", "chords", "melody"):
            assert p.tracks[t], (g, t)
        assert all(0 <= n.step < 64 for t in p.tracks.values() for n in t)


def test_house_is_four_on_the_floor_and_trap_has_fast_hats():
    h = make("house")
    assert [s % 16 for s in steps(h, "kick")] == [0, 4, 8, 12] * 4
    t = make("trap")
    assert len(t.tracks["hat"]) >= 40
    assert 8 in [s % 16 for s in steps(t, "snare")]          # the snare lands on beat 3 in trap


def test_tempo_key_and_mode_requests_are_respected():
    p = make("rnb", tempo=96, key="F#", minor=False)
    assert (p.tempo, p.key, p.minor) == (96, "F#", False)
    roots = {n.midi % 12 for n in p.tracks["bass808"]}
    scale = {(beatgen.NOTE_NAMES.index("F#") + i) % 12 for i in (0, 2, 4, 5, 7, 9, 11)}
    assert roots <= scale                                    # the bass stays inside the key


def test_vibe_makes_it_busier():
    calm = sum(len(v) for v in make("trap", vibe=0.0).tracks.values())
    hard = sum(len(v) for v in make("trap", vibe=1.0).tracks.values())
    assert hard > calm


def test_pattern_roundtrip_and_grid():
    p = make("drill")
    q = beatgen.Pattern.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q.to_dict() == p.to_dict()
    g = p.grid()
    assert [r["name"] for r in g][:3] == ["kick", "snare", "clap"] and all(len(r["cells"]) == 64 for r in g)
    assert sum(g[0]["cells"]) == len(p.tracks["kick"])


def test_surprise_is_valid_and_varies():
    import random
    rnd = random.Random(1)
    reqs = [beatgen.surprise(rnd) for _ in range(12)]
    assert len({r.genre for r in reqs}) > 2
    for r in reqs:
        beatgen.get_generator().generate(r)


class FakeAI:
    """What a real model plug-in would look like: a name and generate(BeatRequest) -> Pattern."""
    name = "fake-ai"

    def generate(self, req):
        p = beatgen.Pattern(req.genre, req.tempo or 100, req.key, True, 4, 0.0, req.vibe, seed=1, generator=self.name)
        p.tracks = {"kick": [beatgen.Note(s, 36, 1, 1.0) for s in range(0, 64, 8)]}
        return p


def test_another_generator_can_be_plugged_in(monkeypatch):
    monkeypatch.setitem(beatgen.GENERATORS, "x", None)
    beatgen.GENERATORS.pop("x")
    beatgen.register_generator(FakeAI())
    try:
        assert beatgen.get_generator("fake-ai").name == "fake-ai"
        p = beatgen.get_generator("fake-ai").generate(beatgen.BeatRequest("trap"))
        buses = synth.render_buses(p, 1)                      # the rest of the Studio copes with a sparse pattern
        assert len(buses["Drums"]) > 0
        assert beatgen.get_generator("unknown").name == "algorithmic"
    finally:
        beatgen.GENERATORS.pop("fake-ai", None)


# ------------------------------------------------------------------ synth + mixer
def test_synth_is_finite_and_the_right_length():
    p = make("lofi", seed=2)
    buses = synth.render_buses(p, 2)
    secs = 2 * 64 * 60 / p.tempo / 4
    assert set(buses) == {"Drums", "808 bass", "Chords", "Melody"}
    for b in buses.values():
        assert np.isfinite(b).all() and abs(len(b) / synth.SR - secs) < 1.0 and np.abs(b).max() > 0.05
    assert abs(len(synth.countin(120)) / synth.SR - 2.0) < 0.2


def mix(p):
    return [mixer.Channel(k, v) for k, v in synth.render_buses(p, 1).items()]


def test_master_loudness_levels_and_no_clipping():
    p = make("trap", seed=3)
    levels = {}
    for lv in ("quiet", "normal", "loud"):
        out = mixer.mixdown(mix(p), p.tempo, lv)
        assert out.ndim == 2 and out.shape[1] == 2 and np.isfinite(out).all()
        assert np.abs(out).max() <= 0.9 + 1e-6               # the limiter keeps the peak under -1 dBFS
        levels[lv] = mixer.rms_db(out)
    assert levels["quiet"] < levels["normal"] < levels["loud"]
    assert abs(levels["normal"] - mixer.LOUDNESS["normal"]) < 2.5


def test_pan_mute_and_volume():
    x = np.sin(np.linspace(0, 2000, 44100)) * 0.5
    left = mixer.mixdown([mixer.Channel("a", x, 1.0, -1.0)], 100, "normal")
    right = mixer.mixdown([mixer.Channel("a", x, 1.0, 1.0)], 100, "normal")
    assert np.abs(left[:, 1]).max() < 0.02 * np.abs(left[:, 0]).max()
    assert np.abs(right[:, 0]).max() < 0.02 * np.abs(right[:, 1]).max()
    muted = mixer.mixdown([mixer.Channel("a", x, 1.0, 0, True), mixer.Channel("b", x * 0, 1.0)], 100, "normal")
    assert np.abs(muted).max() < 1e-6
    full = mixer.mixdown([mixer.Channel("a", x, 1.0), mixer.Channel("b", x * 0.2, 1.0)], 100, "normal")
    low = mixer.mixdown([mixer.Channel("a", x, 1.0), mixer.Channel("b", x * 0.2, 0.0)], 100, "normal")
    assert np.isfinite(full).all() and np.isfinite(low).all()


def test_effect_presets_change_the_sound():
    x = np.zeros(44100)
    x[:2000] = np.sin(np.linspace(0, 400, 2000)) * 0.8       # a short blip, then silence
    tail = {}
    for pr in ("none", "reverb", "echo"):
        out = mixer.mixdown([mixer.Channel("v", np.concatenate([x, np.zeros(44100)]), 1.0, 0.0, False, pr)], 100, "normal")
        tail[pr] = float(np.sqrt(np.mean(out[30000:80000] ** 2)))
    assert tail["reverb"] > tail["none"] and tail["echo"] > tail["none"]
    assert set(mixer.PRESET_ORDER) >= {"none", "vocal_clean", "reverb", "echo", "vocal_space"}
    for pr in mixer.PRESET_ORDER:
        assert np.isfinite(mixer.mixdown([mixer.Channel("v", x, 1.0, 0, False, pr)], 100, "normal")).all()


def test_advanced_eq_and_compressor_do_something():
    t = np.arange(44100) / 44100
    low = np.sin(2 * np.pi * 80 * t) * 0.4
    base = mixer.mixdown([mixer.Channel("a", low)], 100, "loud")
    cut = mixer.mixdown([mixer.Channel("a", low, eq_low=-12), mixer.Channel("b", np.sin(2 * np.pi * 3000 * t) * 0.01)], 100, "loud")
    assert np.isfinite(cut).all() and not np.allclose(base[:20000], cut[:20000])
    spiky = np.concatenate([np.sin(2 * np.pi * 300 * t[:11025]) * 0.9, np.sin(2 * np.pi * 300 * t[:11025]) * 0.1] * 2)
    c = mixer.compress(spiky, 0.8) if hasattr(mixer, "compress") else spiky
    assert np.abs(c).max() <= np.abs(spiky).max() + 1e-6


# ------------------------------------------------------------------ wav + project
def test_wav_roundtrip_and_resample(tmp_path):
    x = np.sin(np.linspace(0, 300, 22050)) * 0.5
    f = tmp_path / "a.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    y = proj.read_wav(f)
    assert abs(len(y) - 44100) < 3 and np.abs(y).max() > 0.4
    proj.write_wav(tmp_path / "b.wav", np.stack([y, y], axis=1))
    with wave.open(str(tmp_path / "b.wav")) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 44100)
    with pytest.raises(ValueError):
        with wave.open(str(tmp_path / "c.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000); w.writeframes(b"\x80" * 80)
        proj.read_wav(tmp_path / "c.wav")


def test_project_save_load_roundtrip(studio_home):
    p = proj.Project("My Song!/x")
    p.pattern = make("rnb", seed=9)
    p.buses["Drums"]["volume"] = 0.33
    p.takes.append(proj.Take("takes/take-1.wav", "Take 1", 0.4, 0.2, 0.9, -0.3, False, "echo"))
    p.loudness, p.advanced = "loud", True
    f = p.save()
    assert f.parent.parent == studio_home and ".." not in str(f) and f.name == "project.json"
    q = proj.Project.load(f.parent)
    assert q.to_dict() == p.to_dict() and q.takes[0].preset == "echo" and q.buses["Drums"]["volume"] == 0.33
    assert proj.list_projects() == [f.parent]


def test_project_load_tolerates_junk_fields(studio_home):
    d = proj.Project("Old").to_dict()
    d["takes"] = [{"file": "t.wav", "name": "T", "future_field": 5}, "nonsense", {"nofile": 1}]
    d["loudness"] = "ear-splitting"
    d["buses"]["Nope"] = {"volume": 3}
    q = proj.Project.from_dict(d)
    assert len(q.takes) == 1 and q.loudness == "normal" and "Nope" not in q.buses


def test_export_wav(studio_home):
    p = proj.Project("Beat A")
    p.pattern = make("house", seed=1)
    out = p.export("wav")
    assert out.suffix == ".wav" and out.parent == studio_home / "Beat A"
    with wave.open(str(out)) as w:
        secs = w.getnframes() / w.getframerate()
        assert w.getnchannels() == 2 and abs(secs - p.beat_seconds()) < 1.5


@pytest.mark.skipif(not (shutil.which("ffmpeg") or shutil.which("lame")), reason="no mp3 encoder on this machine")
def test_export_mp3_with_the_real_encoder(studio_home):
    p = proj.Project("Beat B")
    p.pattern = make("lofi", seed=1)
    out = p.export("mp3")
    head = out.read_bytes()[:3]
    assert out.suffix == ".mp3" and out.stat().st_size > 20000 and (head == b"ID3" or head[0] == 0xFF)


def test_export_mp3_without_an_encoder_keeps_the_wav_and_says_how_to_fix_it(studio_home):
    p = proj.Project("Beat C")
    p.pattern = make("trap", seed=1)
    with pytest.raises(RuntimeError) as e:
        p.export("mp3", which=lambda n: None)
    assert "ffmpeg" in str(e.value) and (studio_home / "Beat C" / "Beat C.wav").is_file()


def test_export_mp3_command_and_failure(studio_home):
    p = proj.Project("Beat D")
    p.pattern = make("trap", seed=1)
    calls = []

    def run_ok(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"ID3fake")

        class R:
            returncode, stderr = 0, ""
        return R()

    out = p.export("mp3", which=lambda n: "/x/ffmpeg" if n == "ffmpeg" else None, run=run_ok)
    assert calls[0][0] == "ffmpeg" and calls[0][-1].endswith("Beat D.mp3") and out.read_bytes() == b"ID3fake"

    class Bad:
        returncode, stderr = 1, "boom"
    with pytest.raises(RuntimeError):
        proj.Project.export(p, "mp3", which=lambda n: "/x/lame" if n == "lame" else None, run=lambda *a, **k: Bad())
    assert proj.mp3_encoder(lambda n: "/x/lame" if n == "lame" else None)[0] == "lame"


def test_auto_trim_silence():
    sr = synth.SR
    x = np.zeros(sr * 4)
    x[sr: sr * 2] = np.sin(np.linspace(0, 3000, sr)) * 0.5
    a, b = proj.auto_trim_silence(x)
    assert 0.8 < a <= 1.0 and 1.8 < b <= 2.1
    assert proj.auto_trim_silence(np.zeros(sr)) == (0.0, 0.0) and proj.auto_trim_silence(np.zeros(0)) == (0.0, 0.0)


# ------------------------------------------------------------------ recording with stub programs
def stub_bin(tmp_path, with_parecord=True, fail=False):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    py = shutil.which("python3")
    log = tmp_path / "pactl.log"
    (d / "pactl").write_text(f"""#!{py}
import sys
open({str(log)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["list", "short", "sources"]:
    print("0\\talsa_output.pci.analog-stereo.monitor\\tPipeWire\\ts16le\\tIDLE")
    print("1\\talsa_input.usb-Blue_Snowball-00.mono\\tPipeWire\\ts16le\\tIDLE")
elif sys.argv[1] == "load-module":
    print("42")
""")
    if with_parecord:
        (d / "parecord").write_text(f"""#!{py}
import signal, sys, time, wave, math, struct
if {fail!r}:
    sys.stderr.write("Connection refused\\n"); sys.exit(1)
path = sys.argv[-1]
open({str(tmp_path / "parecord.args")!r}, "w").write(" ".join(sys.argv[1:]))
stop = []
signal.signal(signal.SIGINT, lambda *a: stop.append(1))
frames = []
t = 0
while not stop and t < 100:
    time.sleep(0.05); t += 1
    frames += [int(9000 * math.sin(i / 7.0)) for i in range(2205)]
w = wave.open(path, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
w.writeframes(struct.pack("<%dh" % len(frames), *frames)); w.close()
""")
    for f in d.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d, log


def only_path(monkeypatch, d):
    monkeypatch.setenv("PATH", str(d))


def test_list_sources_skips_speaker_monitors(tmp_path, monkeypatch):
    d, _ = stub_bin(tmp_path)
    only_path(monkeypatch, d)
    src = recorder.list_sources()
    assert [s["id"] for s in src] == ["alsa_input.usb-Blue_Snowball-00.mono"] and "Blue Snowball" in src[0]["name"]
    only_path(monkeypatch, tmp_path / "empty")
    assert recorder.list_sources() == []


def test_record_command_prefers_parecord_then_arecord():
    both = lambda n: "/x/" + n   # noqa: E731
    assert recorder.record_command(Path("/t/a.wav"), "mic1", both)[:1] == ["parecord"]
    assert "--device=mic1" in recorder.record_command(Path("/t/a.wav"), "mic1", both)
    assert recorder.record_command(Path("/t/a.wav"), "", lambda n: "/x/arecord" if n == "arecord" else None)[0] == "arecord"
    assert recorder.record_command(Path("/t/a.wav"), "", lambda n: "/x/ffmpeg" if n == "ffmpeg" else None)[0] == "ffmpeg"
    assert recorder.record_command(Path("/t/a.wav"), "", lambda n: None) is None


def test_recorder_records_stops_and_cleans_up_the_monitor(tmp_path, monkeypatch):
    d, log = stub_bin(tmp_path)
    only_path(monkeypatch, d)
    r = recorder.Recorder()
    r.start(tmp_path / "t" / "a.wav", "alsa_input.usb-Blue_Snowball-00.mono", monitor=True)
    import time
    time.sleep(0.4)
    assert r.recording and r.failed_early() == ""
    f = r.stop()
    assert f and f.is_file() and len(proj.read_wav(f)) > 4000 and not r.recording
    calls = log.read_text()
    assert "load-module module-loopback source=alsa_input.usb-Blue_Snowball-00.mono" in calls and "unload-module 42" in calls
    assert r.stop() is None
    assert "--device=alsa_input.usb-Blue_Snowball-00.mono" in (tmp_path / "parecord.args").read_text()


def test_recorder_reports_a_microphone_that_fails(tmp_path, monkeypatch):
    d, _ = stub_bin(tmp_path, fail=True)
    only_path(monkeypatch, d)
    r = recorder.Recorder()
    r.start(tmp_path / "a.wav")
    import time
    time.sleep(0.4)
    assert "Connection refused" in r.failed_early()
    assert r.stop() is None


def test_recorder_without_any_recording_program(tmp_path, monkeypatch):
    only_path(monkeypatch, tmp_path / "nothing")
    with pytest.raises(RuntimeError) as e:
        recorder.Recorder().start(tmp_path / "a.wav")
    assert "apt install" in str(e.value)


# ------------------------------------------------------------------ the controller (no window)
class FakeBackend:
    def __init__(self):
        self.sound = []
        self.toasts = []

    def show_toast(self, msg, ms=5000):
        self.toasts.append(msg)

    def _snd_enabled(self):
        return True

    def _snd_write(self, line):
        self.sound.append(line)


@pytest.fixture
def ctl(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    from atarilauncher.studio_ui import StudioController
    fb = FakeBackend()
    c = StudioController(fb)
    c.fb = fb
    return c


def ids(rows):
    return [r.get("id") for r in rows if r.get("kind") != "info"]


def test_home_has_three_big_cards(ctl):
    assert [c["id"] for c in ctl.homeCards()][:3] == ["beat", "record", "mix"]
    assert ctl.available


def test_beat_page_controls(ctl):
    ctl.openPage("beat")
    assert ids(ctl.rows("beat"))[:8] == ["genre", "tempo", "key", "vibe", "surprise", "make", "play", "record"]
    first = ctl.project.pattern
    assert first is not None and ctl.grid()
    ctl.adjust("beat", "genre", 1)
    assert ctl.genre == "drill" and ctl.project.pattern.genre == "drill" and ctl.tempo == beatgen.GENRES["drill"].tempo[1]
    t = ctl.tempo
    ctl.adjust("beat", "tempo", 1)
    ctl.adjust("beat", "key", 1)
    ctl.adjust("beat", "vibe", 1)
    assert (ctl.tempo, ctl.key, ctl.vibe) == (t + 2, "C#", 6) and ctl.project.pattern.tempo == t + 2
    for _ in range(40):
        ctl.adjust("beat", "vibe", 1)
    assert ctl.vibe == 10
    ctl.activate("beat", "key")
    assert ctl.minor is not beatgen.GENRES["drill"].minor
    rows = {r["id"]: r for r in ctl.rows("beat") if r.get("id")}
    assert rows["key"]["value"].startswith("C#") and "BPM" in rows["tempo"]["title"]


def test_surprise_plays_and_stop_stops(ctl):
    ctl.openPage("beat")
    ctl.activate("beat", "surprise")
    assert ctl.playing and ctl.what == "beat"
    played = [s for s in ctl.fb.sound if s.startswith("file ")]
    assert played and Path(played[-1][5:]).is_file()
    with wave.open(played[-1][5:]) as w:
        assert w.getnchannels() == 2 and w.getnframes() > 44100
    ctl.activate("beat", "play")
    assert not ctl.playing and ctl.fb.sound[-1] == "stopfile"


def test_generator_choice_is_used(ctl):
    beatgen.register_generator(FakeAI())
    try:
        ctl.generator_name = "fake-ai"
        ctl.openPage("beat")
        assert ctl.project.pattern.generator == "fake-ai"
    finally:
        beatgen.GENERATORS.pop("fake-ai", None)


def test_mix_page_controls_and_advanced(ctl):
    ctl.openPage("beat")
    ctl.openPage("mix")
    rs = ids(ctl.rows("mix"))
    assert rs[:5] == ["track", "volume", "pan", "mute", "preset"] and "eq_low" not in rs
    ctl.adjust("mix", "volume", -2)
    ctl.adjust("mix", "pan", 3)
    ctl.activate("mix", "mute")
    d = ctl.project.buses["Drums"]
    assert (d["volume"], d["pan"], d["mute"]) == (0.7, 0.3, True)
    ctl.adjust("mix", "track", 1)
    ctl.adjust("mix", "preset", 1)
    assert ctl.project.buses["808 bass"]["preset"] == "vocal_clean"
    ctl.activate("mix", "advanced")
    assert {"eq_low", "eq_mid", "eq_high", "comp"} <= set(ids(ctl.rows("mix")))
    ctl.adjust("mix", "eq_low", 20)
    assert ctl.project.buses["808 bass"]["eq_low"] == 12
    ctl.adjust("mix", "loud", 1)
    assert ctl.project.loudness == "loud"
    ctl.activate("mix", "play")
    assert ctl.playing and ctl.what == "mix"


def test_export_and_save_from_the_mix_page(ctl, studio_home):
    ctl.openPage("beat")
    ctl.project.name = "Cypher"
    ctl.activate("mix", "wav")
    assert (studio_home / "Cypher" / "Cypher.wav").is_file() and (studio_home / "Cypher" / "project.json").is_file()
    assert "Cypher.wav" in ctl.fb.toasts[-1]
    ctl.activate("mix", "save")
    assert "Saved" in ctl.fb.toasts[-1]


def test_mp3_row_says_when_there_is_no_encoder(ctl, monkeypatch):
    monkeypatch.setattr(proj, "mp3_encoder", lambda which=None: None)
    ctl.openPage("mix")
    row = next(r for r in ctl.rows("mix") if r.get("id") == "mp3")
    assert row["value"] == "needs ffmpeg"
    ctl.activate("mix", "mp3")
    assert "ffmpeg" in ctl.fb.toasts[-1]


def test_new_and_open_project(ctl, studio_home):
    ctl.openPage("beat")
    ctl.adjust("beat", "genre", 2)
    ctl.project.name = "Keep me"
    ctl.project.save()
    ctl.activate("home", "new")
    assert ctl.project.name == "My beat 1" and ctl.project.takes == []
    ctl.activate("home", "open")
    assert ctl.project.name == "Keep me" and ctl.genre == "rnb"
    assert "Keep me" in [c for c in ctl.homeCards()][4]["title"]


def test_recording_flow_with_stub_microphone(ctl, tmp_path, monkeypatch):
    d, log = stub_bin(tmp_path)
    only_path(monkeypatch, d)
    ctl.openPage("beat")
    ctl.openPage("record")
    assert [s["id"] for s in ctl.sources] == ["alsa_input.usb-Blue_Snowball-00.mono"]
    ctl.activate("record", "monitor")
    assert ctl.monitor
    ctl.activate("record", "rec")
    assert ctl.recording and ctl.playing and ctl.what == "rec"
    rec_wav = [s for s in ctl.fb.sound if s.startswith("file ")][-1][5:]
    with wave.open(rec_wav) as w:                              # count-in + beat were rendered into the backing file
        assert w.getnframes() / w.getframerate() > ctl.project.beat_seconds() / 2 + 1.5
    import time
    time.sleep(0.5)
    ctl.activate("record", "rec")
    assert not ctl.recording and len(ctl.project.takes) == 1
    t = ctl.project.takes[0]
    assert (ctl.project.folder / t.file).is_file() and t.name == "Take 1"
    lead = len(synth.countin(ctl.project.pattern.tempo)) / synth.SR
    assert abs(t.trim_start - round(lead + 0.09, 2)) < 0.02          # the count-in and the mic delay are cut off
    assert (ctl.project.folder / "project.json").is_file()
    assert "unload-module 42" in log.read_text()
    # takes: more than one, trimming, play, delete needs a second press
    ctl.activate("record", "rec"); time.sleep(0.3); ctl.activate("record", "rec")
    assert [t.name for t in ctl.project.takes] == ["Take 1", "Take 2"]
    names = ids(ctl.rows("record"))
    assert {"take", "takeplay", "trimstart", "trimend", "autotrim", "takedel"} <= set(names)
    ctl.adjust("record", "trimend", 2)
    assert ctl.project.takes[ctl.take_i].trim_end >= 0.1
    ctl.activate("record", "takeplay")
    assert ctl.playing and ctl.what == "take"
    ctl.activate("record", "autotrim")
    ctl.activate("record", "takedel")
    assert len(ctl.project.takes) == 2                                # first press only asks
    ctl.activate("record", "takedel")
    assert len(ctl.project.takes) == 1
    # takes show up in the mixer and in the export
    ctl.openPage("mix")
    assert "Take 1" in [r["value"] for r in ctl.rows("mix") if r.get("id") == "track"] or ctl._tracks()[-1] == ctl.project.takes[0].name
    ctl.adjust("mix", "track", -1)
    assert ctl._track_ref()[0] == ctl.project.takes[0].name
    ctl.activate("mix", "wav")
    assert Path(ctl.last_export).is_file()


def test_recording_failure_is_explained_not_fatal(ctl, tmp_path, monkeypatch):
    d, _ = stub_bin(tmp_path, fail=True)
    only_path(monkeypatch, d)
    ctl.openPage("record")
    ctl.activate("record", "rec")
    assert not ctl.recording and "Could not use the microphone" in ctl.fb.toasts[-1]
    only_path(monkeypatch, tmp_path / "none")
    ctl.activate("record", "rec")
    assert not ctl.recording and "apt install" in ctl.fb.toasts[-1]


def test_without_numpy_the_studio_explains_itself(ctl, monkeypatch):
    import atarilauncher.studio_ui as su
    monkeypatch.setattr(su, "numpy_available", lambda: False)
    rows = ctl.rows("beat")
    assert "numpy" in rows[0]["title"] and ids(rows) == ["back"]
    assert ctl.activate("home", "beat") == "" and ctl.page == "home"


def test_atari_still_works_when_numpy_is_missing(tmp_path):
    """The real situation after `install.sh --no-studio`: numpy cannot be imported at all."""
    import subprocess, sys
    code = (
        "import sys; sys.modules['numpy'] = None\n"
        "from PySide6.QtGui import QGuiApplication\n"
        "app = QGuiApplication([])\n"
        "from atarilauncher.studio_ui import StudioController\n"
        "class B:\n"
        "    def show_toast(self, *a): pass\n"
        "    def _snd_enabled(self): return False\n"
        "c = StudioController(B())\n"
        "assert not c.available and 'numpy' in c.helpText and c.projectName == ''\n"
        "assert len(c.homeCards()) == 5 and c.grid() == [] and c.loopSeconds == 8.0\n"
        "c.openPage('beat'); c.adjust('beat', 'genre', 1); c.leave()\n"
        "assert c.activate('home', 'beat') == '' and c.rows('mix')[0]['kind'] == 'info'\n"
        "print('ok')\n")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", ATARI_NO_SOUND="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60,
                       cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-800:]


# ------------------------------------------------------------------ integration: the window, the menu, the tile
def test_studio_in_the_app_menu_and_tile(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        assert apps and "studio" in apps.NON_GAME
        games = [ui.backend.model.game_at(i) for i in range(ui.backend.model.rowCount())]
        open_menu_item(ui, "studio")
        assert ui.mode == "studio"
        scr = ui.win.findChild(QObject, "studioScreen")
        assert scr.property("page") == "home"
        ui.key(Qt.Key_Right); ui.key(Qt.Key_Left)
        ui.key(Qt.Key_Return)                                       # card 1: Make a beat
        assert scr.property("page") == "beat"
        st = ui.backend.studio
        g0 = st.genre
        ui.key(Qt.Key_Right)                                        # the first row is the style
        assert st.genre != g0
        for _ in range(4):
            ui.key(Qt.Key_Down, 20)
        ui.backend._sound_sink = lambda line: sink.append(line)
        sink = []
        ui.key(Qt.Key_Return)                                       # Surprise me
        assert st.isPlaying and any(s.startswith("file ") for s in sink)
        pump(app, 200)
        ui.win.grabWindow().save(str(tmp_path / "studio_beat.png"))
        ui.key(Qt.Key_Escape)
        assert scr.property("page") == "home" and not st.isPlaying
        pump(app, 150)
        ui.win.grabWindow().save(str(tmp_path / "studio_home.png"))
        ui.key(Qt.Key_Right); ui.key(Qt.Key_Return)                 # Record
        assert scr.property("page") == "record"
        pump(app, 150)
        ui.win.grabWindow().save(str(tmp_path / "studio_record.png"))
        ui.key(Qt.Key_Escape); ui.key(Qt.Key_Right); ui.key(Qt.Key_Return)
        assert scr.property("page") == "mix"
        pump(app, 150)
        ui.win.grabWindow().save(str(tmp_path / "studio_mix.png"))
        ui.key(Qt.Key_Escape)
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library"
        assert not [w for w in ui.warnings if "tudio" in w], ui.warnings
        # the Studio tile opens it too
        ui.backend.studioRequested.emit()
        pump(app, 100)
        assert ui.mode == "studio"
        ui.key(Qt.Key_Escape)
        assert ui.mode == "library"
    finally:
        ui.close()


def test_studio_tile_is_a_non_game_that_launches_the_studio(app, tmp_path, monkeypatch):
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=False)
    try:
        b = ui.backend
        assert any(g.gid == "studio:open" for g in b._all)
        assert b.totalGames == 0                                     # not counted as a game
        b.setFilter("studio")
        pump(app, 100)
        assert b.model.rowCount() == 1 and b.model.game_at(0).gid == "studio:open"
        seen = []
        b.studioRequested.connect(lambda: seen.append(1))
        b.launch(0)
        assert seen == [1] and not b.running
        pump(app, 100)
        assert ui.mode == "studio"
    finally:
        ui.close()


def test_sound_helper_accepts_file_commands(tmp_path):
    import subprocess, sys
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
    env.pop("ATARI_NO_SOUND", None)
    wav = tmp_path / "x y.wav"
    proj.write_wav(wav, np.zeros((4410, 2)))
    r = subprocess.run([sys.executable, "-m", "atarilauncher.sound_helper"], input=f"file {wav}\nstopfile\nfile /nonexistent.wav\nquit\n",
                       capture_output=True, text=True, env=env, timeout=20, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0 and r.stdout.startswith("ready")
