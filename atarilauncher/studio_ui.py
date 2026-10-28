"""The Studio screen's brain (a QObject the QML talks to): pages, rows, actions. The audio work is in atarilauncher/studio/."""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import paths
from . import studio_fix
from .studio import beatgen, numpy_available, recorder

try:                                           # numpy is optional: without it the Studio only shows how to add it
    from .studio import mixer, project as proj, synth
except ImportError:                            # pragma: no cover - exercised by test_studio (numpy blocked in a subprocess)
    mixer = proj = synth = None

KEYS = beatgen.NOTE_NAMES
LOUD_ORDER = ["quiet", "normal", "loud"]
STUDIO_HELP = ("The Studio needs one extra library (numpy). Press \"Fix Studio\" below and Code adds it for you "
               "(needs internet). Or run ./install.sh again in the Code folder.")


class StudioController(QObject):
    changed = Signal()                 # rows / grid / state changed: the screen redraws
    playingChanged = Signal()
    toastRequested = Signal(str)
    availableChanged = Signal()
    fixDone = Signal(bool, str)        # worker thread -> main thread: (worked, plain-English text)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.page = "home"
        self.project = proj.Project() if proj else None
        self.genre = "trap"
        self.generator_name = "algorithmic"      # which registered BeatGenerator makes the beats
        self.tempo = beatgen.GENRES["trap"].tempo[1]
        self.key = "C"
        self.minor = True
        self.vibe = 5
        self.seed = random.randrange(1, 2**31)
        self.rnd = random.Random()
        self.playing = False
        self.what = ""                    # what is playing: "beat" | "mix" | "take"
        self.sources: list[dict] = []
        self.source_i = 0
        self.monitor = False
        self.count_in = True
        self.take_i = 0
        self.track_i = 0
        self.rec = recorder.Recorder()
        self.recording = False
        self._rec_take: proj.Take | None = None
        self._busy = ""
        self._play_timer = QTimer(self, singleShot=True)
        self._play_timer.timeout.connect(self._play_ended)
        self._rec_timer = QTimer(self, singleShot=True)
        self._rec_timer.timeout.connect(lambda: self.stop_record(auto=True))
        self._confirm = ""
        self.last_export = ""
        self._fixing = False
        self._fix_text = ""
        self.fixDone.connect(self._fix_finished)

    # ------------------------------------------------------------------ helpers
    @Property(bool, notify=availableChanged)
    def available(self) -> bool:
        return numpy_available() and mixer is not None

    @Property(bool, notify=changed)
    def fixing(self) -> bool:
        return self._fixing

    @Property(str, notify=availableChanged)
    def fixText(self) -> str:
        return self._fix_text

    @Property(str, constant=True)
    def helpText(self) -> str:
        return STUDIO_HELP

    @Property(str, notify=changed)
    def pageName(self) -> str:
        return self.page

    @Property(bool, notify=playingChanged)
    def isPlaying(self) -> bool:
        return self.playing

    @Property(bool, notify=changed)
    def isRecordingNow(self) -> bool:
        return self.recording

    @Property(float, notify=changed)
    def loopSeconds(self) -> float:
        p = self.project.pattern if self.project else None
        return p.total_steps * 60.0 / p.tempo / 4 if p else 8.0

    @Property(str, notify=changed)
    def projectName(self) -> str:
        return self.project.name if self.project else ""

    def _say(self, text: str, ms: int = 6000) -> None:
        self.backend.show_toast(text, ms)

    def _pattern(self) -> beatgen.Pattern:
        if self.project.pattern is None:
            self._generate()
        return self.project.pattern

    def _generate(self, new_seed: bool = False) -> None:
        if new_seed:
            self.seed = random.randrange(1, 2**31)
        req = beatgen.BeatRequest(self.genre, self.tempo, self.key, self.minor, self.vibe / 10.0, 4, self.seed)
        self.project.pattern = beatgen.get_generator(self.generator_name).generate(req)
        self.changed.emit()

    def _sound(self, line: str) -> None:
        if self.backend._snd_enabled():
            self.backend._snd_write(line)

    # ------------------------------------------------------------------ playback
    def _play_wav(self, stereo, what: str, extra_seconds: float = 0.0) -> bool:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        f = paths.data_dir() / "studio_preview.wav"
        proj.write_wav(f, stereo)
        self.stop_play(silent=True)
        self._sound(f"file {f}")
        self.playing, self.what = True, what
        self._play_timer.start(int((len(stereo) / synth.SR + 0.3) * 1000))
        self.playingChanged.emit()
        self.changed.emit()
        return True

    def stop_play(self, silent: bool = False) -> None:
        if self.playing or not silent:
            self._sound("stopfile")
        self._play_timer.stop()
        was, self.playing, self.what = self.playing, False, ""
        if was:
            self.playingChanged.emit()
            self.changed.emit()

    def _play_ended(self) -> None:
        self.playing, self.what = False, ""
        self.playingChanged.emit()
        self.changed.emit()

    def toggle_beat(self) -> None:
        if self.playing:
            self.stop_play()
            return
        p = self._pattern()
        chans = [c for c in self.project.channels(with_voice=False)]
        self._play_wav(mixer.mixdown(chans, p.tempo, self.project.loudness), "beat")

    def toggle_mix(self) -> None:
        if self.playing:
            self.stop_play()
            return
        if not self.project.pattern and not self.project.takes:
            self._say("Make a beat first (Studio > Make a beat).")
            return
        self._play_wav(self.project.render(), "mix")

    # ------------------------------------------------------------------ rows
    @Slot(result="QVariantList")
    def homeCards(self):
        return [
            {"id": "beat", "title": "Make a beat", "sub": "Pick a style, press a button, hear it. Trap, Drill, R&B, Afrobeats, Boom bap, Lo-fi, House."},
            {"id": "record", "title": "Record your voice", "sub": "Count-in, rap or sing over your beat, keep the best take."},
            {"id": "mix", "title": "Mix & share", "sub": "Balance the sounds, add reverb or echo, save a WAV or MP3."},
            {"id": "new", "title": "New project", "sub": ""},
            {"id": "open", "title": "Open: " + self._next_project_label(), "sub": ""},
        ]

    def _next_project_label(self) -> str:
        if not proj:
            return "(needs numpy)"
        ps = proj.list_projects()
        return ps[0].name if ps else "(none saved yet)"

    @Slot(str, result="QVariantList")
    def rows(self, page: str):
        if not self.available:
            return self._fix_rows()
        return {"beat": self._beat_rows, "record": self._record_rows, "mix": self._mix_rows}.get(page, lambda: [])()

    def _fix_rows(self) -> list:
        ps = studio_fix.problems(numpy_available())
        rows = [{"kind": "info", "title": "The Studio cannot start yet.  " + studio_fix.summary(ps)}]
        if self._fix_text:
            rows.append({"kind": "info", "title": self._fix_text})
        rows.append({"kind": "done", "id": "fix", "title": "Working on it..." if self._fixing else "Fix Studio (install what is missing)"})
        rows.append({"kind": "item", "id": "back", "title": "Back"})
        return rows

    @Slot()
    def fix(self) -> None:
        """One press: install what the Studio is missing (numpy, recording tools), then switch it on - no restart needed."""
        if self._fixing:
            return
        ps = studio_fix.problems(numpy_available(), sources=None)
        if not any(p.fixable for p in ps):
            self._fix_text = "Nothing can be fixed from here. " + studio_fix.summary(ps) + " Run ./install.sh again in the Code folder."
            self.availableChanged.emit()
            self.changed.emit()
            return
        self._fixing, self._fix_text = True, "Installing - this can take a minute..."
        studio_fix.log("Fix Studio pressed: " + ", ".join(p.id for p in ps))
        self.availableChanged.emit()
        self.changed.emit()

        def work():
            lines: list[str] = []

            def out(line: str) -> None:
                lines.append(line)
                studio_fix.log("fix: " + line)
            try:
                ok, text = studio_fix.fix(ps, out)
            except Exception as exc:       # never take Code down
                ok, text = False, f"The fix hit a problem: {exc}"
                studio_fix.log(text)
            self.fixDone.emit(ok, text)

        import threading
        threading.Thread(target=work, daemon=True, name="atari-studio-fix").start()

    @Slot(bool, str)
    def _fix_finished(self, ok: bool, text: str) -> None:
        self._fixing = False
        self._fix_text = text
        if ok and numpy_available():
            self._reload_modules()
        studio_fix.log(f"Fix Studio finished ok={ok}: {text}")
        self._say(text, 9000)
        self.availableChanged.emit()
        self.changed.emit()

    def _reload_modules(self) -> None:
        """numpy was installed while Code was running: load the Studio's numpy parts now."""
        global mixer, proj, synth
        import importlib
        importlib.invalidate_caches()
        try:
            from .studio import mixer as _m, project as _p, synth as _s
        except Exception as exc:
            studio_fix.log(f"reload failed: {exc!r}")
            self._fix_text = f"numpy was added but the Studio still could not load ({exc}). Restart Code once."
            return
        mixer, proj, synth = _m, _p, _s
        if self.project is None:
            self.project = proj.Project()

    def _row(self, rid, title, value="", detail="", kind="item", tone=""):
        r = {"kind": kind, "id": rid, "title": title, "value": value, "detail": detail}
        if tone:
            r["tone"] = tone
        return r

    def _beat_rows(self) -> list:
        g = beatgen.GENRES[self.genre]
        p = self.project.pattern
        playing = self.playing and self.what == "beat"
        return [
            {"kind": "info", "title": f"{g.name}: {g.description}  Left / Right changes the highlighted setting."},
            self._row("genre", "Style", g.name, "Left / Right to change."),
            self._row("tempo", "Speed (BPM)", f"{self.tempo}", f"Usual for {g.name}: {g.tempo[0]}-{g.tempo[2]}."),
            self._row("key", "Key", f"{self.key} {'minor' if self.minor else 'major'}", "Left / Right = note.  Enter = major / minor."),
            self._row("vibe", "Vibe", "Chill " + "\u25a0" * self.vibe + "\u25a1" * (10 - self.vibe) + " Hard", "How busy and hard-hitting it is."),
            self._row("surprise", "Surprise me!", "", "Picks everything for you and plays it.", tone=""),
            self._row("make", "Make a new variation", "", "Same settings, fresh drums, chords and tune."),
            self._row("play", "Stop" if playing else "Play my beat", "", "Press again to stop."),
            self._row("record", "Next: record your voice over it", "", ""),
            self._row("save", "Save project", self.project.name, "Saves in " + str(proj.studio_dir())),
            self._row("back", "Back to Studio"),
        ]

    def _sources_label(self) -> str:
        if not self.sources:
            return "Default microphone (none found)"
        return self.sources[self.source_i % len(self.sources)]["name"]

    def _record_rows(self) -> list:
        rows = []
        if self.project.pattern is None:
            rows.append({"kind": "info", "title": "Tip: make a beat first, then record over it. (You can also record without a beat.)"})
        ps = studio_fix.problems(True, sources=self.sources)
        for pr in ps:
            rows.append({"kind": "info", "title": pr.text})
        if any(pr.id == "audio-tools" and pr.fixable for pr in ps):
            rows.append(self._row("fix", "Fix recording (install the recording tools)", "", "Asks for your password once."))
        if self._fix_text and ps:
            rows.append({"kind": "info", "title": self._fix_text})
        rows += [
            self._row("input", "Microphone", self._sources_label(), "Left / Right to choose.  Plug it in first."),
            self._row("monitor", "Hear myself in headphones", "ON" if self.monitor else "OFF",
                      "Use HEADPHONES - with speakers you will get a loud squeal."),
            self._row("countin", "Count-in (4 clicks)", "ON" if self.count_in else "OFF", ""),
            self._row("rec", "Stop recording" if self.recording else "Record", "",
                      "It stops by itself at the end of the beat. Press again to stop sooner.", tone=""),
        ]
        ts = self.project.takes
        if ts:
            i = self.take_i % len(ts)
            t = ts[i]
            rows += [
                self._row("take", "Take", f"{t.name}  ({i + 1} of {len(ts)})", "Left / Right to choose a take."),
                self._row("takeplay", "Stop" if self.playing and self.what == "take" else "Play this take", ""),
                self._row("trimstart", "Cut from the start", f"{t.trim_start:.2f} s", "Left / Right = 0.05 s."),
                self._row("trimend", "Cut from the end", f"{t.trim_end:.2f} s", "Left / Right = 0.05 s."),
                self._row("autotrim", "Auto-trim silence", "", "Removes the quiet bit before and after you."),
                self._row("takedel", "Press again to delete this take" if self._confirm == "take" else "Delete this take", ""),
            ]
        rows += [self._row("mix", "Next: mix & share"), self._row("back", "Back to Studio")]
        return rows

    def _tracks(self) -> list[str]:
        return list(self.project.buses) + [t.name for t in self.project.takes]

    def _track_ref(self):
        names = self._tracks()
        n = names[self.track_i % len(names)]
        if n in self.project.buses:
            return n, self.project.buses[n], True
        t = next(t for t in self.project.takes if t.name == n)
        return n, t, False

    @staticmethod
    def _get(ref, key):
        return ref[key] if isinstance(ref, dict) else getattr(ref, key)

    @staticmethod
    def _set(ref, key, value):
        if isinstance(ref, dict):
            ref[key] = value
        else:
            setattr(ref, key, value)

    def _mix_rows(self) -> list:
        name, ref, _bus = self._track_ref()
        g = lambda k: self._get(ref, k)        # noqa: E731
        enc = proj.mp3_encoder()
        rows = [
            {"kind": "info", "title": "Left / Right changes the highlighted setting. Your changes are heard in the next Play."},
            self._row("track", "Track", name, "Left / Right to pick: the beat's parts and your takes."),
            self._row("volume", "Volume", f"{int(round(g('volume') * 100))}%", ""),
            self._row("pan", "Pan (left - right)", "Centre" if abs(g("pan")) < 0.05 else f"{'Left' if g('pan') < 0 else 'Right'} {int(abs(g('pan')) * 100)}%", ""),
            self._row("mute", "Mute", "MUTED" if g("mute") else "off", "Enter to switch.", tone="warn" if g("mute") else ""),
            self._row("preset", "Effect", mixer.PRESETS[g("preset")].split(" (")[0], mixer.PRESETS[g("preset")]),
        ]
        if self.project.advanced:
            rows += [self._row("eq_low", "Bass (EQ)", f"{g('eq_low'):+.0f} dB"), self._row("eq_mid", "Mids (EQ)", f"{g('eq_mid'):+.0f} dB"),
                     self._row("eq_high", "Treble (EQ)", f"{g('eq_high'):+.0f} dB"),
                     self._row("comp", "Compressor", f"{int(g('comp') * 100)}%", "Evens out loud and quiet bits.")]
        rows += [
            self._row("loud", "Master loudness", self.project.loudness.capitalize(), "Quiet / Normal / Loud. A limiter keeps it from distorting."),
            self._row("advanced", "Advanced (EQ + compressor)", "ON" if self.project.advanced else "OFF", "Enter to switch."),
            self._row("play", "Stop" if self.playing and self.what == "mix" else "Play the mix", ""),
            self._row("wav", "Save as WAV", "", "Best quality."),
            self._row("mp3", "Save as MP3", "" if enc else "needs ffmpeg", "Small files for sharing." if enc else "sudo apt install ffmpeg"),
            self._row("save", "Save project", self.project.name, ""),
            self._row("folder", "Open my Studio folder", "", str(proj.studio_dir())),
            self._row("back", "Back to Studio"),
        ]
        return rows

    # ------------------------------------------------------------------ the beat grid
    @Slot(result="QVariantList")
    def grid(self):
        if not numpy_available() or not self.project:
            return []
        p = self.project.pattern
        if p is None:
            p = self._pattern() if numpy_available() else None
        return p.grid() if p else []

    # ------------------------------------------------------------------ pressing and adjusting
    @Slot(str)
    def openPage(self, page: str) -> None:
        self.page = page
        self._confirm = ""
        if page == "record":
            self.sources = recorder.list_sources()
        if page == "beat" and numpy_available() and self.project.pattern is None:
            self._generate()
        self.changed.emit()

    @Slot()
    def leave(self) -> None:
        """Esc / B: back to the Studio home, or out of the Studio."""
        self.stop_play()
        if self.recording:
            self.stop_record()
        self.page = "home"
        self.changed.emit()

    @Slot(str, str, int)
    def adjust(self, page: str, rid: str, d: int) -> None:
        if not numpy_available():
            return
        self._confirm = ""
        if page == "beat":
            self._adjust_beat(rid, d)
        elif page == "record":
            if rid == "input" and self.sources:
                self.source_i = (self.source_i + d) % len(self.sources)
            elif rid == "take" and self.project.takes:
                self.take_i = (self.take_i + d) % len(self.project.takes)
            elif rid in ("trimstart", "trimend") and self.project.takes:
                t = self.project.takes[self.take_i % len(self.project.takes)]
                attr = "trim_start" if rid == "trimstart" else "trim_end"
                setattr(t, attr, max(0.0, round(getattr(t, attr) + 0.05 * d, 2)))
        elif page == "mix":
            self._adjust_mix(rid, d)
        self.changed.emit()

    def _adjust_beat(self, rid: str, d: int) -> None:
        if rid == "genre":
            i = (beatgen.GENRE_ORDER.index(self.genre) + d) % len(beatgen.GENRE_ORDER)
            self.genre = beatgen.GENRE_ORDER[i]
            self.tempo = beatgen.GENRES[self.genre].tempo[1]
            self.minor = beatgen.GENRES[self.genre].minor
        elif rid == "tempo":
            self.tempo = max(60, min(180, self.tempo + 2 * d))
        elif rid == "key":
            self.key = KEYS[(KEYS.index(self.key) + d) % 12]
        elif rid == "vibe":
            self.vibe = max(0, min(10, self.vibe + d))
        else:
            return
        self.stop_play(silent=True)
        self._generate()

    def _adjust_mix(self, rid: str, d: int) -> None:
        name, ref, _ = self._track_ref()
        if rid == "track":
            self.track_i = (self.track_i + d) % len(self._tracks())
        elif rid == "volume":
            self._set(ref, "volume", max(0.0, min(1.5, round(self._get(ref, "volume") + 0.05 * d, 2))))
        elif rid == "pan":
            self._set(ref, "pan", max(-1.0, min(1.0, round(self._get(ref, "pan") + 0.1 * d, 1))))
        elif rid == "preset":
            order = mixer.PRESET_ORDER
            self._set(ref, "preset", order[(order.index(self._get(ref, "preset")) + d) % len(order)])
        elif rid in ("eq_low", "eq_mid", "eq_high"):
            self._set(ref, rid, max(-12, min(12, self._get(ref, rid) + d)))
        elif rid == "comp":
            self._set(ref, "comp", max(0.0, min(1.0, round(self._get(ref, "comp") + 0.1 * d, 1))))
        elif rid == "loud":
            self.project.loudness = LOUD_ORDER[(LOUD_ORDER.index(self.project.loudness) + d) % len(LOUD_ORDER)]

    @Slot(str, str, result=str)
    def activate(self, page: str, rid: str) -> str:
        """Enter on a row. Returns '' | 'back' | 'page:<name>' (the screen follows it)."""
        if rid == "back":
            self.stop_play()
            return "back"
        if rid == "fix":
            self.fix()
            return ""
        if not self.available:
            return ""
        keep = self._confirm
        self._confirm = ""
        try:
            if page == "home":
                return self._home(rid)
            if page == "beat":
                return self._act_beat(rid)
            if page == "record":
                return self._act_record(rid, keep)
            if page == "mix":
                return self._act_mix(rid)
        except Exception as exc:                   # the Studio must never take Code down with it
            import traceback
            studio_fix.log(f"{page}/{rid} failed: {exc!r} " + traceback.format_exc().replace("\n", " | "))
            self._say(f"The Studio hit a problem: {exc}. Help > Copy log has the details.", 9000)
        return ""

    def _home(self, rid: str) -> str:
        if rid in ("beat", "record", "mix"):
            self.openPage(rid)
            return ""
        if rid == "new":
            self.stop_play()
            self.project = proj.Project(self._fresh_name())
            self.take_i = self.track_i = 0
            self._generate()
            self._say("New project: " + self.project.name)
        elif rid == "open":
            ps = proj.list_projects()
            if not ps:
                self._say("No saved projects yet. Make a beat and press Save project.")
            else:
                self.stop_play()
                self.project = proj.Project.load(ps[0])
                if self.project.pattern:
                    pt = self.project.pattern
                    self.genre, self.tempo, self.key, self.minor = pt.genre, pt.tempo, pt.key, pt.minor
                    self.vibe, self.seed = int(round(pt.vibe * 10)), pt.seed
                self._say("Opened " + self.project.name)
        self.changed.emit()
        return ""

    def _fresh_name(self) -> str:
        n, taken = 1, {p.name for p in proj.list_projects()}
        while f"My beat {n}" in taken:
            n += 1
        return f"My beat {n}"

    def _act_beat(self, rid: str) -> str:
        if rid == "surprise":
            r = beatgen.surprise(self.rnd)
            self.genre, self.tempo, self.key, self.vibe, self.seed = r.genre, r.tempo, r.key, int(round(r.vibe * 10)), r.seed
            self.minor = beatgen.GENRES[self.genre].minor
            self.stop_play(silent=True)
            self._generate()
            self.toggle_beat()
            self._say(f"Surprise! {beatgen.GENRES[self.genre].name} at {self.tempo} BPM in {self.key}.", 4000)
        elif rid == "make":
            self.stop_play(silent=True)
            self._generate(new_seed=True)
            self.toggle_beat()
        elif rid == "play":
            self.toggle_beat()
        elif rid == "key":
            self.minor = not self.minor
            self.stop_play(silent=True)
            self._generate()
        elif rid == "record":
            self.openPage("record")
        elif rid == "save":
            self._save()
        return ""

    def _save(self) -> None:
        f = self.project.save()
        self._say("Saved: " + str(f.parent))

    def _act_record(self, rid: str, keep: str) -> str:
        if rid == "monitor":
            self.monitor = not self.monitor
        elif rid == "countin":
            self.count_in = not self.count_in
        elif rid == "rec":
            self.stop_record() if self.recording else self.start_record()
        elif rid == "takeplay":
            self._play_take()
        elif rid == "autotrim":
            t = self.project.takes[self.take_i % len(self.project.takes)]
            a, b = proj.auto_trim_silence(proj.read_wav(self.project.folder / t.file))
            t.trim_start, t.trim_end = round(a, 2), round(b, 2)
            self._say(f"Trimmed {a:.2f} s from the start and {b:.2f} s from the end.", 4000)
        elif rid == "takedel":
            if keep != "take":
                self._confirm = "take"
            else:
                t = self.project.takes.pop(self.take_i % len(self.project.takes))
                try:
                    (self.project.folder / t.file).unlink()
                except OSError:
                    pass
                self.take_i = 0
        elif rid == "mix":
            self.openPage("mix")
        self.changed.emit()
        return ""

    def _act_mix(self, rid: str) -> str:
        if rid in ("mute",):
            _n, ref, _ = self._track_ref()
            self._set(ref, "mute", not self._get(ref, "mute"))
        elif rid == "advanced":
            self.project.advanced = not self.project.advanced
        elif rid == "play":
            self.toggle_mix()
        elif rid in ("wav", "mp3"):
            self._export(rid)
        elif rid == "save":
            self._save()
        elif rid == "folder":
            self.project.folder.mkdir(parents=True, exist_ok=True)
            opener = shutil.which("xdg-open")
            if opener and not os.environ.get("ATARI_NO_SOUND"):
                subprocess.Popen([opener, str(proj.studio_dir())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            self._say("Your Studio folder: " + str(proj.studio_dir()))
        self.changed.emit()
        return ""

    def _export(self, fmt: str) -> None:
        try:
            self.project.save()
            out = self.project.export(fmt)
            self.last_export = str(out)
            self._say(f"Saved {out.name} in {out.parent}", 9000)
        except RuntimeError as exc:
            self._say(str(exc), 10000)

    # ------------------------------------------------------------------ recording
    def _play_take(self) -> None:
        if self.playing:
            self.stop_play()
            return
        t = self.project.takes[self.take_i % len(self.project.takes)]
        x = self.project.take_audio(t)
        self._play_wav(proj.np.stack([x, x], axis=1) * 0.9, "take")

    def start_record(self) -> None:
        if self.recording:
            return
        self.stop_play(silent=True)
        p = self.project
        n = 1 + max([int(t.name.split()[-1]) for t in p.takes if t.name.split()[-1].isdigit()] or [0])
        path = p.folder / "takes" / f"take-{n}.wav"
        lead = synth.countin(p.pattern.tempo if p.pattern else 100) if self.count_in else proj.np.zeros(0)
        beat = [c for c in p.channels(with_voice=False)]
        tempo = p.pattern.tempo if p.pattern else 100
        backing = mixer.mixdown(beat, tempo, p.loudness) if beat else proj.np.zeros((int(synth.SR * 20), 2), dtype="float32")
        stereo = proj.np.concatenate([proj.np.stack([lead, lead], axis=1) if len(lead) else proj.np.zeros((0, 2)), backing])
        src = self.sources[self.source_i % len(self.sources)]["id"] if self.sources else ""
        try:
            self.rec.start(path, src, self.monitor)
        except RuntimeError as exc:
            studio_fix.log("record start failed: " + str(exc))
            self._say(str(exc), 10000)
            return
        time.sleep(0.15)
        problem = self.rec.failed_early()
        if problem:
            self.rec.stop()
            studio_fix.log("microphone failed: " + problem)
            self._say("Could not use the microphone: " + problem, 10000)
            return
        self.recording = True
        self._rec_take = proj.Take(f"takes/take-{n}.wav", f"Take {n}")
        self._rec_lead = len(lead) / synth.SR
        self._play_wav(stereo, "rec")
        self._rec_timer.start(int((len(stereo) / synth.SR + 0.4) * 1000))
        self._say("Recording! Rap or sing now." + (" Wait for the 4 clicks." if self.count_in else ""), 4000)

    def stop_record(self, auto: bool = False) -> None:
        if not self.recording:
            return
        self.recording = False
        self._rec_timer.stop()
        self.stop_play(silent=True)
        f = self.rec.stop()
        take, self._rec_take = self._rec_take, None
        if f is None or take is None:
            studio_fix.log("nothing was recorded")
            self._say("Nothing was recorded. Is the microphone plugged in and chosen?", 9000)
        else:
            # the count-in and the microphone's delay are cut from the start so the voice lines up with the beat
            take.trim_start = round(self._rec_lead + self.project.latency_ms / 1000.0, 2)
            try:
                _a, b = proj.auto_trim_silence(proj.read_wav(f))
                take.trim_end = round(b, 2)
            except (OSError, ValueError, Exception):
                pass
            self.project.takes.append(take)
            self.take_i = len(self.project.takes) - 1
            self.project.save()
            self._say(f"Saved {take.name}. Press Play this take to listen, or record another.", 7000)
        self.changed.emit()
