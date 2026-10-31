"""Gamepad reader. Runs as a separate process (python -m atarilauncher.gamepad_helper).

It uses SDL2 (bundled with the `pygame` package) which understands practically every
controller (Xbox, PlayStation, Switch Pro, 8BitDo...). It prints one word per line:
up down left right accept back favorite options system search prev next quitapp record
Lines that start with `#` are information for the Controllers page: `#pad <name>`, `#pad-removed`, `#btn <name>` (every button pressed, as SDL
names it), `#axis <name> <left|right|up|down|pulled>` (a stick or trigger moved past half way).
(`quitapp` = Guide/Home held + B: closes a running web app or Kodi and returns to CodeAque;
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

# Pads SDL does not know as a "game controller" (no mapping for this exact version - e.g. a DualShock 4 over Bluetooth with the
# newer hid_playstation driver) are read as plain joysticks. Linux drivers (hid_playstation, hid_sony, xpad, hid_nintendo) order
# the buttons by their evdev codes: SOUTH, EAST, NORTH, WEST, TL, TR, TL2, TR2, SELECT, START, MODE, THUMBL, THUMBR.
RAW_BUTTONS = ["a", "b", "y", "x", "leftshoulder", "rightshoulder", "lefttrigger", "righttrigger", "back", "start", "guide",
               "leftstick", "rightstick"]
PLAYSTATION_WORDS = ("wireless controller", "dualshock", "dualsense", "playstation", "sony")


def raw_button_name(index: int) -> str:
    """A plain joystick's button number -> the same name SDL gives a mapped pad (DS4: 0 Cross=a, 1 Circle=b, 2 Triangle=y,
    3 Square=x, 8 Share=back, 9 Options=start, 10 PS=guide)."""
    return RAW_BUTTONS[index] if 0 <= index < len(RAW_BUTTONS) else ""


def hat_directions(x: int, y: int) -> set[str]:
    out = set()
    if x < 0:
        out.add("left")
    elif x > 0:
        out.add("right")
    if y > 0:
        out.add("up")        # SDL hats: +1 = up
    elif y < 0:
        out.add("down")
    return out


def input_access(dev: str = "/dev/input") -> tuple[int, int]:
    """(event devices, of them readable by this user). 0 readable of several = no permission (see the Controllers page)."""
    import glob
    import os
    ev = glob.glob(os.path.join(dev, "event*"))
    return len(ev), sum(1 for e in ev if os.access(e, os.R_OK))


def hidraw_readable(dev: str = "/dev") -> bool:
    import glob
    import os
    return any(os.access(h, os.R_OK | os.W_OK) for h in glob.glob(os.path.join(dev, "hidraw*")))
AXIS_ON = 0.5


def axis_word(name: str, value: float) -> str:
    """Plain word for a stick / trigger pushed past half way."""
    if name.endswith("trigger"):
        return "pulled"
    if name.endswith("x"):
        return "right" if value > 0 else "left"
    return "down" if value > 0 else "up"


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
    if not hidraw_readable():
        # SDL's own PlayStation/Switch drivers talk to /dev/hidraw*, which a normal user usually cannot open: then a DualShock 4
        # can show up but send nothing. Use the kernel's driver (evdev) instead, which works with the normal seat permissions.
        os.environ.setdefault("SDL_JOYSTICK_HIDAPI", "0")
    n_ev, n_ok = input_access()
    if n_ev and not n_ok:
        print("#noperm", flush=True)
    try:
        import pygame
        from pygame._sdl2 import controller
    except Exception as exc:  # pygame missing: keyboard-only mode
        print(f"#unavailable {exc}", flush=True)
        return 0

    pygame.display.init()
    controller.init()
    pygame.joystick.init()
    pads: dict[int, "controller.Controller"] = {}
    raws: dict[int, object] = {}            # plain joysticks (no SDL mapping), by instance id
    hats: dict[int, set] = {}
    rep = Repeater()
    stick_dir: dict[int, str | None] = {}
    axes: dict[tuple[int, int], float] = {}

    def open_pad(index: int):
        try:
            if controller.is_controller(index):
                c = controller.Controller(index)
                iid = c.as_joystick().get_instance_id()
                if iid not in pads:
                    pads[iid] = c
                    print(f"#pad {c.name}", flush=True)
            else:
                j = pygame.joystick.Joystick(index)
                iid = j.get_instance_id()
                if iid not in raws and iid not in pads:
                    raws[iid] = j
                    print(f"#pad {j.get_name()} (basic)", flush=True)
        except Exception as exc:
            print(f"#error {exc}", flush=True)

    def press(bname: str) -> None:
        special = chord.button(bname, True)
        if special:
            if special in ("quitapp", "record"):
                print(special, flush=True)
            return
        action = BUTTON_MAP.get(bname)
        if action in DIRECTIONS:
            for a in rep.press(action, time.monotonic()):
                print(a, flush=True)
        elif action:
            print(action, flush=True)

    def release(bname: str) -> None:
        if chord.button(bname, False):
            return
        action = BUTTON_MAP.get(bname)
        if action in DIRECTIONS:
            rep.release(action)

    last_rescan = time.monotonic()
    last_used = [None]

    def used(iid) -> None:
        """'#use <name>' when a different pad than last time presses something (the hints switch to its button names)."""
        if iid == last_used[0]:
            return
        last_used[0] = iid
        dev = pads.get(iid) or raws.get(iid)
        if dev is not None:
            try:
                nm = dev.name if hasattr(dev, "name") and not callable(dev.name) else dev.get_name()
            except Exception:
                nm = ""
            print(f"#use {nm}", flush=True)

    for i in range(controller.get_count()):
        open_pad(i)

    chord = GuideChord()
    axis_names = {getattr(pygame, n): n[len("CONTROLLER_AXIS_"):].lower()
                  for n in dir(pygame) if n.startswith("CONTROLLER_AXIS_") and n != "CONTROLLER_AXIS_MAX"}
    axis_on: dict[tuple[int, int], bool] = {}
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
            elif t == getattr(pygame, "JOYDEVICEADDED", -1):
                open_pad(ev.device_index)
            elif t == getattr(pygame, "JOYDEVICEREMOVED", -1):
                if raws.pop(getattr(ev, "instance_id", -1), None) is not None:
                    print("#pad-removed", flush=True)
            elif t == pygame.JOYBUTTONDOWN and ev.instance_id in raws:
                used(ev.instance_id)
                bname = raw_button_name(ev.button)
                print(f"#btn {bname or ev.button}", flush=True)
                press(bname)
            elif t == pygame.JOYBUTTONUP and ev.instance_id in raws:
                release(raw_button_name(ev.button))
            elif t == pygame.JOYHATMOTION and ev.instance_id in raws:
                new = hat_directions(*ev.value)
                old = hats.get(ev.instance_id, set())
                for d in old - new:
                    release("dpad_" + d)
                for d in new - old:
                    press("dpad_" + d)
                hats[ev.instance_id] = new
            elif t == pygame.JOYAXISMOTION and ev.instance_id in raws and ev.axis in (0, 1):
                axes[(ev.instance_id, -1 - ev.axis)] = ev.value
                new = stick_direction(axes.get((ev.instance_id, -1), 0.0), axes.get((ev.instance_id, -2), 0.0))
                old = stick_dir.get(ev.instance_id)
                if new != old:
                    if old:
                        rep.release(old)
                    if new:
                        print(new, flush=True)
                        rep.press(new, time.monotonic())
                    stick_dir[ev.instance_id] = new
            elif t == pygame.CONTROLLERBUTTONDOWN:
                used(ev.instance_id)
                bname = btn_names.get(ev.button, "")
                print(f"#btn {bname or ev.button}", flush=True)
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
                aname = axis_names.get(ev.axis, str(ev.axis))
                was = axis_on.get((ev.instance_id, ev.axis), False)
                now_on = abs(axes[(ev.instance_id, ev.axis)]) >= AXIS_ON
                if now_on and not was:
                    print(f"#axis {aname} {axis_word(aname, ev.value)}", flush=True)
                axis_on[(ev.instance_id, ev.axis)] = now_on
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
        if time.monotonic() - last_rescan > 3.0:     # belt and braces: a pad that SDL never announced (no udev events in the session)
            last_rescan = time.monotonic()
            try:
                if pygame.joystick.get_count() > len(pads) + len(raws):
                    for i in range(pygame.joystick.get_count()):
                        open_pad(i)
            except Exception:
                pass
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
