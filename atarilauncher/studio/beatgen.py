"""Beat generation behind an interface.

``BeatGenerator.generate(BeatRequest) -> Pattern`` is all a generator has to do. ``AlgorithmicGenerator`` below makes drums,
an 808 bass line, chords and a melody from per-genre rules. To plug in an AI model later, write a class with the same
two things (``name`` and ``generate``) that returns a ``Pattern`` (notes on a 16th-note grid) and call ``register_generator``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

STEPS = 16                                    # 16th notes per bar
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MINOR = [0, 2, 3, 5, 7, 8, 10]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
TRACKS = ("kick", "snare", "clap", "hat", "ohat", "bass808", "chords", "melody")
DRUM_TRACKS = ("kick", "snare", "clap", "hat", "ohat")
BUSES = {"Drums": DRUM_TRACKS, "808 bass": ("bass808",), "Chords": ("chords",), "Melody": ("melody",)}


@dataclass
class Note:
    step: int
    midi: int = 0
    length: int = 1
    vel: float = 0.8


@dataclass
class BeatRequest:
    genre: str = "trap"
    tempo: int = 0              # 0 = the genre's usual tempo
    key: str = "C"
    minor: bool | None = None   # None = the genre's usual mode
    vibe: float = 0.5           # 0 = chill, 1 = hard
    bars: int = 4
    seed: int | None = None


@dataclass
class Pattern:
    genre: str
    tempo: int
    key: str
    minor: bool
    bars: int
    swing: float
    vibe: float
    tracks: dict = field(default_factory=dict)       # name -> [Note]
    seed: int = 0
    generator: str = "algorithmic"

    @property
    def total_steps(self) -> int:
        return self.bars * STEPS

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("genre", "tempo", "key", "minor", "bars", "swing", "vibe", "seed", "generator")}
        d["tracks"] = {n: [[x.step, x.midi, x.length, round(x.vel, 3)] for x in notes] for n, notes in self.tracks.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        p = cls(str(d.get("genre", "trap")), int(d.get("tempo", 120)), str(d.get("key", "C")), bool(d.get("minor", True)),
                int(d.get("bars", 4)), float(d.get("swing", 0.0)), float(d.get("vibe", 0.5)))
        p.seed = int(d.get("seed", 0))
        p.generator = str(d.get("generator", "algorithmic"))
        for n, notes in (d.get("tracks") or {}).items():
            p.tracks[n] = [Note(int(a), int(b), int(c), float(v)) for a, b, c, v in notes]
        return p

    def grid(self, rows=("kick", "snare", "clap", "hat", "ohat", "bass808", "chords", "melody")) -> list[dict]:
        """For the step-sequencer view: [{name, cells:[0/1 per step]}]."""
        out = []
        for r in rows:
            cells = [0] * self.total_steps
            for n in self.tracks.get(r, []):
                if 0 <= n.step < self.total_steps:
                    cells[n.step] = 1
            out.append({"name": r, "cells": cells})
        return out


class BeatGenerator(Protocol):
    name: str

    def generate(self, req: BeatRequest) -> Pattern: ...


# --------------------------------------------------------------------------- genres
@dataclass(frozen=True)
class Genre:
    id: str
    name: str
    tempo: tuple              # (low, default, high)
    minor: bool
    swing: float
    kick: str                 # 16-step templates: x = hit, . = rest; lower-case 'o' = maybe (vibe decides)
    snare: str
    clap: str
    hat: str
    ohat: str
    bass_rhythm: str
    progressions: tuple       # scale degrees (1-7), one chord per bar (cycled)
    seventh: bool
    melody_density: float
    slide: bool = False       # 808 glides between notes (drill)
    description: str = ""


GENRES: dict[str, Genre] = {g.id: g for g in (
    Genre("trap", "Trap", (125, 140, 160), True, 0.0,
          "x.....o...o..o..", "........x.......", "........x.......", "x.xxx.xxx.xxx.xx", "......x.......x.", "x.....o...x..o..",
          ((1, 6, 3, 7), (1, 4, 6, 5), (6, 7, 1, 1)), False, 0.35, False, "Hard 808s, snappy snares, fast hi-hats."),
    Genre("drill", "Drill", (138, 142, 146), True, 0.0,
          "x.....o...o.o...", "........x.......", "........x.......", "x..x..x.x..x..x.", "..............x.", "x..o..x...x.o...",
          ((1, 6, 7, 5), (1, 1, 4, 5), (6, 5, 4, 5)), False, 0.3, True, "Dark, sliding 808s and skippy hi-hats."),
    Genre("rnb", "R&B", (78, 90, 102), True, 0.12,
          "x.....o...x.....", "....x.......x...", "....x.......x...", "x.x.x.x.x.x.x.x.", "......x.......x.", "x.....o...x.....",
          ((2, 5, 1, 6), (1, 6, 4, 5), (6, 2, 5, 1)), True, 0.4, False, "Smooth chords, slow groove, soft drums."),
    Genre("afrobeats", "Afrobeats", (96, 102, 110), False, 0.05,
          "x..x..x...x.x...", "....x.......x..o", "....x.......x...", "x.xxx.xxx.xxx.xx", "..x...x...x...x.", "x..x..x...x.x...",
          ((1, 5, 6, 4), (1, 4, 5, 4), (6, 4, 1, 5)), False, 0.55, False, "Bouncy, off-beat percussion and bright chords."),
    Genre("boombap", "Boom bap", (84, 90, 96), True, 0.2,
          "x.....x...x.....", "....x.......x...", "................", "x.x.x.x.x.x.x.x.", "..............x.", "x.....x...x.....",
          ((1, 4, 1, 5), (6, 7, 1, 1), (1, 6, 2, 5)), True, 0.3, False, "Classic head-nod drums with dusty chords."),
    Genre("lofi", "Lo-fi", (70, 78, 86), True, 0.18,
          "x.......x.x.....", "....x.......x...", "................", "x.x...x.x...x.x.", "..............x.", "x.......x.......",
          ((2, 5, 1, 6), (1, 6, 2, 5), (4, 3, 2, 1)), True, 0.25, False, "Sleepy, jazzy, relaxed. Great for studying."),
    Genre("house", "House", (120, 124, 128), True, 0.0,
          "x...x...x...x...", "................", "....x.......x...", "..x...x...x...x.", "..x...x...x...x.", "..x...x...x...x.",
          ((1, 1, 6, 7), (1, 4, 1, 5), (6, 5, 1, 4)), True, 0.35, False, "Four-on-the-floor kick and off-beat hats."),
)}
GENRE_ORDER = list(GENRES)


def midi_of(key: str, octave: int) -> int:
    return 12 * (octave + 1) + NOTE_NAMES.index(key)


def scale_note(key: str, minor: bool, degree: int, octave: int) -> int:
    """MIDI note of a scale degree (1-based, may be < 1 or > 7 to leave the octave)."""
    sc = MINOR if minor else MAJOR
    d = degree - 1
    return midi_of(key, octave) + sc[d % 7] + 12 * (d // 7)


def chord_notes(key: str, minor: bool, degree: int, seventh: bool, octave: int = 3) -> list[int]:
    notes = [scale_note(key, minor, degree + k, octave) for k in (0, 2, 4)]
    if seventh:
        notes.append(scale_note(key, minor, degree + 6, octave))
    return notes


class AlgorithmicGenerator:
    """Rule-based generator: genre templates + a seed + the 'vibe' slider. Same request + seed = same beat."""
    name = "algorithmic"

    def generate(self, req: BeatRequest) -> Pattern:
        g = GENRES.get(req.genre) or GENRES["trap"]
        seed = req.seed if req.seed is not None else random.randrange(1, 2**31)
        rnd = random.Random(seed)
        lo, default, hi = g.tempo
        tempo = req.tempo or default
        tempo = max(60, min(180, tempo))
        minor = g.minor if req.minor is None else req.minor
        key = req.key if req.key in NOTE_NAMES else "C"
        vibe = max(0.0, min(1.0, req.vibe))
        bars = max(1, min(8, req.bars))
        p = Pattern(g.id, tempo, key, minor, bars, g.swing, vibe, seed=seed, generator=self.name)
        for t in TRACKS:
            p.tracks[t] = []
        prog = rnd.choice(g.progressions)

        def place(track: str, tmpl: str, bar: int, vel: float, maybe: float):
            for i, ch in enumerate(tmpl):
                if ch == "x" or (ch == "o" and rnd.random() < maybe):
                    v = max(0.3, min(1.0, vel + rnd.uniform(-0.08, 0.08)))
                    p.tracks[track].append(Note(bar * STEPS + i, 0, 1, v))

        for bar in range(bars):
            last = bar % 4 == 3
            place("kick", g.kick, bar, 0.75 + 0.25 * vibe, 0.25 + 0.6 * vibe)
            place("snare", g.snare, bar, 0.85, 1)
            place("clap", g.clap, bar, 0.8, 1)
            hat_ok = 0.35 + 0.65 * vibe
            for i, ch in enumerate(g.hat):
                if ch == "x" and (i % 4 == 0 or rnd.random() < hat_ok):
                    accent = 0.9 if i % 4 == 0 else 0.55 + 0.25 * rnd.random()
                    p.tracks["hat"].append(Note(bar * STEPS + i, 0, 1, accent))
            if g.id in ("trap", "drill") and vibe > 0.4 and (last or rnd.random() < vibe * 0.4):
                for i in (13, 14, 15):                               # a little hi-hat roll
                    p.tracks["hat"].append(Note(bar * STEPS + i, 0, 1, 0.5 + 0.1 * i % 3))
            place("ohat", g.ohat, bar, 0.7, 0.5)
            if last and g.id != "house":                             # a fill on the last bar of four
                for i in rnd.sample(range(10, 16), 2):
                    p.tracks["snare"].append(Note(bar * STEPS + i, 0, 1, 0.6))
            # chords: one per bar, held; some genres re-hit halfway
            deg = prog[bar % len(prog)]
            notes = chord_notes(key, minor, deg, g.seventh, 3)
            hits = [0] if g.id not in ("house", "afrobeats") else [0, 6, 10]
            for h in hits:
                ln = 14 if len(hits) == 1 else 4
                for m in notes:
                    p.tracks["chords"].append(Note(bar * STEPS + h, m, ln, 0.5 + 0.1 * vibe))
            # 808 follows the chord root on the genre's bass rhythm
            root = scale_note(key, minor, deg, 1)
            prev = None
            for i, ch in enumerate(g.bass_rhythm):
                if ch == "x" or (ch == "o" and rnd.random() < 0.3 + 0.5 * vibe):
                    nxt = next((j for j in range(i + 1, STEPS) if g.bass_rhythm[j] in "xo"), STEPS)
                    note = root
                    if g.slide and prev is not None and rnd.random() < 0.5:
                        note = root + rnd.choice([0, 3 if minor else 4, 5, 7, -2])
                    p.tracks["bass808"].append(Note(bar * STEPS + i, note, max(1, min(nxt - i, 8)), 0.9))
                    prev = note
            # melody: a small random walk over the scale, landing on chord tones on strong beats
            density = min(0.9, g.melody_density * (0.5 + vibe))
            pos = rnd.choice([3, 5, 7])
            for i in range(STEPS):
                strong = i % 4 == 0
                if rnd.random() < (density if not strong else density * 1.3):
                    pos = max(1, min(11, pos + rnd.choice([-2, -1, -1, 0, 1, 1, 2])))
                    if strong:
                        pos = min((deg - 1, deg + 1, deg + 3, deg + 7, deg + 8), key=lambda x: abs(x - pos)) % 12 or deg
                        pos = max(1, min(11, pos))
                    p.tracks["melody"].append(Note(bar * STEPS + i, scale_note(key, minor, pos, 5),
                                                   rnd.choice([1, 2, 2, 3]), 0.55 + 0.25 * rnd.random()))
        for t in p.tracks:
            p.tracks[t].sort(key=lambda n: (n.step, n.midi))
        return p


GENERATORS: dict = {"algorithmic": AlgorithmicGenerator()}


def register_generator(gen) -> None:
    """Plug in another generator (an AI model, say). It needs a ``name`` and ``generate(BeatRequest) -> Pattern``."""
    GENERATORS[gen.name] = gen


def get_generator(name: str = "algorithmic"):
    return GENERATORS.get(name) or GENERATORS["algorithmic"]


def surprise(rnd: random.Random | None = None) -> BeatRequest:
    """'Surprise me': random genre, key and vibe (tempo within the genre's usual range)."""
    rnd = rnd or random.Random()
    g = GENRES[rnd.choice(GENRE_ORDER)]
    return BeatRequest(g.id, rnd.randint(g.tempo[0], g.tempo[2]), rnd.choice(NOTE_NAMES), None, round(rnd.random(), 2),
                       4, rnd.randrange(1, 2**31))
