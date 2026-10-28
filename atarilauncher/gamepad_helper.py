"""Gamepad reader. Runs as a separate process (python -m atarilauncher.gamepad_helper).

It uses SDL2 (bundled with the `pygame` package) which understands practically every
controller (Xbox, PlayStation, Switch Pro, 8BitDo...). It prints one word per line:
up down left right accept back favorite options system search prev next quitapp record
(`quitapp` = Guide/Home held + B: closes a running web app or Kodi and returns to Code;
`record` = Guide/Home held + X: start / stop the screen recorder)

Running it in its own process keeps SDL's settings out of the emulators we launch,
and a controller problem can never crash the launcher.
"""
from __future__ import annotations

import sys
import time

REPEAT_DELAY = 0.35
REPEAT_RATE = 0.11
STICK_DEADZONE = 0.55

# SDL "game controller" button names -> launcher actions (Xbox-style layout)
# A = select/launch, B = back, X = favourite, Y = options/sort menu, Start/Menu = change system,
# Select/View = search, LB/RB = previous/next system, d-pad and left stick = move.
BUTTON_MAP = {
    "a": "accept", "b": "back", "x": "favorite", "y": "options",
    "start": "system", "back": "search",
    "leftshoulder": "prev", "rightshoulder": "next",
    "dpad_up": "up", "dpad_down": "down", "dpad_left": "left", "dpad_right": "right",
}
DIRECTIONS = {"up", "down", "left", "right"}


def stick_direction(x: float, y: float, deadzone: float = STICK_DEADZONE) -> str | None:
    """Dominant stick direction, or None inside the dead zone."""
    if max(abs(x), abs(y)) < deadzone:
        return None
    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "down" if y > 0 else "up"


class Repeater:
    """Turns 'held' directions into press events with key-repeat."""

    def __init__(self, delay=REPEAT_DELAY, rate=REPEAT_RATE):
        self.delay, self.rate = delay, rate
        self.held: dict[str, float] = {}

    def press(self, d: str, now: float) -> list[str]:
        self.held[d] = now + self.delay
        return [d]

    def release(self, d: str) -> None:
        self.held.pop(d, None)

    def tick(self, now: float) -> list[str]:
        out = []
        for d, due in list(self.held.items()):
            if now >= due:
                out.append(d)
                self.held[d] = now + self.rate
        return out


class GuideChord:
    """Guide/Home held + B  ->  'quitapp'. Guide alone does nothing; B alone is the normal 'back'."""

    def __init__(self):
        self.guide = 0                      # how many pads hold Guide down (usually 0 or 1)

    def button(self, name: str, down: bool) -> str | None:
        """Returns 'quitapp' when B is pressed with Guide held, 'swallow' for B/Guide events that must not
        also act as plain 'back', else None."""
        if name == "guide":
            self.guide = max(0, self.guide + (1 if down else -1))
            return "swallow"
        if name == "b" and down and self.guide:
            return "quitapp"
        if name == "x" and down and self.guide:
            return "record"
        return None


def main() -> int:
    import os

    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    try:
        import pygame
        from pygame._sdl2 import controller
    except Exception as exc:  # pygame missing: keyboard-only mode
        print(f"#unavailable {exc}", flush=True)
        return 0

    pygame.display.init()
    controller.init()
    pads: dict[int, "controller.Controller"] = {}
    rep = Repeater()
    stick_dir: dict[int, str | None] = {}
    axes: dict[tuple[int, int], float] = {}

    def open_pad(index: int):
        try:
            if controller.is_controller(index):
                c = controller.Controller(index)
                pads[c.as_joystick().get_instance_id()] = c
                print(f"#pad {c.name}", flush=True)
        except Exception as exc:
            print(f"#error {exc}", flush=True)

    for i in range(controller.get_count()):
        open_pad(i)

    chord = GuideChord()
    parent = os.getppid()
    btn_names = {getattr(pygame, n): n[len("CONTROLLER_BUTTON_"):].lower()
                 for n in dir(pygame) if n.startswith("CONTROLLER_BUTTON_")}
    while True:
        for ev in pygame.event.get():
            t = ev.type
            if t == pygame.QUIT:  # SDL turns SIGTERM into this event
                return 0
            if t == pygame.CONTROLLERDEVICEADDED:
                open_pad(ev.device_index)
            elif t == pygame.CONTROLLERDEVICEREMOVED:
                pads.pop(ev.instance_id, None)
                print("#pad-removed", flush=True)
            elif t == pygame.CONTROLLERBUTTONDOWN:
                bname = btn_names.get(ev.button, "")
                special = chord.button(bname, True)
                if special:
                    if special in ("quitapp", "record"):
                        print(special, flush=True)
                    continue
                action = BUTTON_MAP.get(bname)
                if action in DIRECTIONS:
                    for a in rep.press(action, time.monotonic()):
                        print(a, flush=True)
                elif action:
                    print(action, flush=True)
            elif t == pygame.CONTROLLERBUTTONUP:
                bname = btn_names.get(ev.button, "")
                if chord.button(bname, False):
                    continue
                action = BUTTON_MAP.get(bname)
                if action in DIRECTIONS:
                    rep.release(action)
            elif t == pygame.CONTROLLERAXISMOTION:
                axes[(ev.instance_id, ev.axis)] = ev.value / 32767.0
                x = axes.get((ev.instance_id, pygame.CONTROLLER_AXIS_LEFTX), 0.0)
                y = axes.get((ev.instance_id, pygame.CONTROLLER_AXIS_LEFTY), 0.0)
                new = stick_direction(x, y)
                old = stick_dir.get(ev.instance_id)
                if new != old:
                    if old:
                        rep.release(old)
                    if new:
                        print(new, flush=True)
                        rep.press(new, time.monotonic())
                    stick_dir[ev.instance_id] = new
        for a in rep.tick(time.monotonic()):
            print(a, flush=True)
        if os.getppid() != parent:  # the launcher went away
            return 0
        time.sleep(0.016)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(0)
