"""Plays Atari's UI sounds. Runs as a separate process (python -m atarilauncher.sound_helper) so audio trouble can
never freeze or crash the launcher and SDL's audio settings never leak into emulators.

Atari writes one command per line to its input:   tick | select | back | fav | launch | error | start
                                                  file <path.wav> | stopfile        (the Studio's preview)
                                                  volume 0.6 | music on | music off | quit
It answers with one status line first:            ready pygame | ready paplay | ready aplay | unavailable
Uses pygame's mixer when pygame is installed (it comes with the gamepad support), otherwise an audio command-line
player (paplay / pw-play / aplay). With neither, it says "unavailable" and Atari carries on silently.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SFX = Path(__file__).resolve().parent / "assets" / "sfx"
NAMES = ("tick", "select", "back", "fav", "launch", "error", "start")
MUSIC_LEVEL = 0.35         # the ambient loop is always quieter than the effects
MIN_GAP = 0.03             # seconds: a held-down key cannot machine-gun the speakers


class PygameMixer:
    kind = "pygame"

    def __init__(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame.mixer as mixer                       # ImportError -> the caller tries the next player
        mixer.pre_init(44100, -16, 2, 512)
        mixer.init()
        self.mixer = mixer
        self.sounds = {}
        self.volume = 0.6
        self.music_ch = None
        for n in NAMES + ("ambient",):
            f = SFX / f"{n}.wav"
            if f.is_file():
                try:
                    self.sounds[n] = mixer.Sound(str(f))
                except Exception:
                    pass
        self.set_volume(self.volume)

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, v))
        for n, s in self.sounds.items():
            s.set_volume(self.volume * (MUSIC_LEVEL if n == "ambient" else 1.0))

    def play(self, name: str) -> None:
        s = self.sounds.get(name)
        if s is not None:
            s.play()

    def play_file(self, path: str) -> None:
        """The Studio's preview: a whole mix as one WAV (replaces the one before it)."""
        self.stop_file()
        try:
            self.file_sound = self.mixer.Sound(path)
            self.file_sound.set_volume(min(1.0, 0.4 + self.volume))
            self.file_ch = self.file_sound.play()
        except Exception:
            self.file_ch = None

    def stop_file(self) -> None:
        ch = getattr(self, "file_ch", None)
        if ch is not None:
            ch.stop()
        self.file_ch = None

    def music(self, on: bool) -> None:
        s = self.sounds.get("ambient")
        if s is None:
            return
        if on:
            if self.music_ch is None or not self.music_ch.get_busy():
                self.music_ch = s.play(loops=-1, fade_ms=1500)
        elif self.music_ch is not None:
            s.fadeout(800)
            self.music_ch = None

    def close(self) -> None:
        self.stop_file()
        try:
            self.mixer.quit()
        except Exception:
            pass


class CommandPlayer:
    """paplay / pw-play / aplay: one short process per sound. No music loop (it would need a process that never ends)."""

    def __init__(self, which=shutil.which):
        self.cmd = None
        self.kind = ""
        for prog, kind in (("paplay", "paplay"), ("pw-play", "pw-play"), ("aplay", "aplay")):
            p = which(prog)
            if p:
                self.cmd, self.kind = p, kind
                break
        if not self.cmd:
            raise RuntimeError("no audio player found")
        self.volume = 0.6

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, v))

    def play(self, name: str) -> None:
        f = SFX / f"{name}.wav"
        if not f.is_file() or self.volume <= 0:
            return
        if self.kind == "paplay":
            args = [self.cmd, f"--volume={int(65536 * self.volume)}", str(f)]
        elif self.kind == "pw-play":
            args = [self.cmd, f"--volume={self.volume:.2f}", str(f)]
        else:
            args = [self.cmd, "-q", str(f)]
        try:
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def music(self, on: bool) -> None:
        pass

    def play_file(self, path: str) -> None:
        self.stop_file()
        try:
            self.file_proc = subprocess.Popen([self.cmd, path] if self.kind != "aplay" else [self.cmd, "-q", path],
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.file_proc = None

    def stop_file(self) -> None:
        p = getattr(self, "file_proc", None)
        if p is not None and p.poll() is None:
            p.terminate()
        self.file_proc = None

    def close(self) -> None:
        self.stop_file()


def open_player(prefer_commands: bool = False):
    order = [CommandPlayer, PygameMixer] if prefer_commands else [PygameMixer, CommandPlayer]
    for cls in order:
        try:
            return cls()
        except Exception:
            continue
    return None


def serve(stdin=None, stdout=None, player=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    player = player if player is not None else open_player()
    if player is None:
        print("unavailable", file=stdout, flush=True)
        return 0
    print("ready " + player.kind, file=stdout, flush=True)
    last = 0.0
    for line in stdin:
        parts = line.split()
        if not parts:
            continue
        cmd = parts[0]
        if cmd == "quit":
            break
        if cmd == "file":                                   # file <path>  (the path may contain spaces)
            path = line.strip()[5:].strip()
            if path and hasattr(player, "play_file"):
                player.play_file(path)
            continue
        if cmd == "stopfile":
            if hasattr(player, "stop_file"):
                player.stop_file()
            continue
        if cmd == "volume" and len(parts) > 1:
            try:
                player.set_volume(float(parts[1]))
            except ValueError:
                pass
        elif cmd == "music" and len(parts) > 1:
            player.music(parts[1] == "on")
        elif cmd in NAMES:
            now = time.monotonic()
            if cmd == "tick" and now - last < MIN_GAP:
                continue
            last = now
            player.play(cmd)
    player.close()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
