"""Pairing Bluetooth controllers from CodeAque, with BlueZ's own tool `bluetoothctl` (the same thing the desktop's Bluetooth settings use).

Steps: make sure the Bluetooth adapter is on (only if it is blocked or the service is stopped does this need the administrator password -
asked in CodeAque's own dialog through rootauth), search for 15 seconds, list what was found (controllers first), then pair, trust (so it
reconnects by itself next time) and connect the one you pick. Every function returns plain-English text and never raises."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

from . import rootauth

SCAN_SECONDS = 20
MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)

PAIRING_STEPS = [
    "Put the controller into pairing mode first (the light flashes quickly when it is ready):",
    "Xbox-style pads: switch the pad on, then hold the small pairing button on the top edge (next to the charging port) until the logo flashes fast.",
    "PlayStation-style pads - PS4 DualShock 4 (shows up as \"Wireless Controller\"): hold SHARE and the PS button together for about 3 seconds, until the light bar "
    "flashes white in quick double blinks. Then press Search. (PS5 DualSense: hold Create + PS the same way.)",
    "Switch-style Pro pads: hold the small sync button on the top edge until the lights move from side to side.",
    "Other pads: look for a button marked with the Bluetooth sign, \"pair\" or \"sync\" (often held together with Start or Home). The pad's leaflet says which.",
    "Keep the pad close to the computer, then press Search below.",
]


@dataclass
class Device:
    mac: str
    name: str
    icon: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    battery: int | None = None
    bonded: bool | None = None       # None = this BlueZ does not say (older than 5.66)

    @property
    def is_pad(self) -> bool:
        n = self.name.lower()
        return self.icon == "input-gaming" or any(w in n for w in ("controller", "gamepad", "joy-con", "pro controller", "xbox", "dualshock",
                                                                     "dualsense", "8bitdo", "pad"))


def available(which: Callable = shutil.which) -> bool:
    return bool(which("bluetoothctl"))


def _run(args: list[str], runner: Callable | None = None, timeout: float = 20.0) -> tuple[int, str]:
    runner = runner or subprocess.run
    try:
        p = runner(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return 124, out.decode(errors="replace") if isinstance(out, bytes) else out
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")


def parse_devices(text: str) -> list[tuple[str, str]]:
    """(MAC, name) once per device. Scan output also has "[CHG] Device <mac> RSSI: -60" lines - those are not names."""
    names: dict[str, str] = {}
    gone: set[str] = set()
    for line in ANSI.sub("", text).splitlines():
        m = re.search(r"Device\s+(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(.*)$", line)
        if not m:
            continue
        mac, name = m.group(1).upper(), m.group(3).strip()
        if "[DEL]" in line:
            gone.add(mac)
            continue
        if "[CHG]" in line or re.match(r"^[A-Za-z]+:\s", name):
            names.setdefault(mac, "")
            continue
        gone.discard(mac)
        if name and (not names.get(mac) or names[mac].replace(":", "-") == mac.replace(":", "-")):
            names[mac] = name
        else:
            names.setdefault(mac, name)
    return [(m, n) for m, n in names.items() if m not in gone]


def parse_info(mac: str, name: str, text: str) -> Device:
    def field(k):
        m = re.search(r"^\s*" + re.escape(k) + r":\s*(.*)$", text, re.M)
        return m.group(1).strip() if m else ""
    d = Device(mac, field("Name") or field("Alias") or name or mac)
    d.icon = field("Icon")
    d.paired, d.trusted, d.connected = (field(k) == "yes" for k in ("Paired", "Trusted", "Connected"))
    d.bonded = None if field("Bonded") == "" else field("Bonded") == "yes"
    m = re.search(r"Battery Percentage:\s*0x[0-9a-fA-F]+\s*\((\d+)\)", text)
    d.battery = int(m.group(1)) if m else None
    return d


def rfkill_state(runner: Callable | None = None, which: Callable = shutil.which) -> dict:
    """{'soft': bool, 'hard': bool} for Bluetooth radios (from `rfkill list bluetooth`)."""
    if not which("rfkill"):
        return {"soft": False, "hard": False}
    try:
        p = (runner or subprocess.run)(["rfkill", "list", "bluetooth"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        out = p.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return {"soft": False, "hard": False}
    return {"soft": bool(re.search(r"Soft blocked:\s*yes", out)), "hard": bool(re.search(r"Hard blocked:\s*yes", out))}


def adapter(runner: Callable | None = None) -> dict:
    """{'present': bool, 'powered': bool, 'blocked': bool}"""
    rc, out = _run(["show"], runner, 10)
    present = rc == 0 and "Controller" in out and "No default controller" not in out
    blocked = "off-blocked" in out or "org.bluez.Error.Blocked" in out
    return {"present": present, "powered": bool(re.search(r"^\s*Powered:\s*yes", out, re.M)), "blocked": blocked}


def _admin(cmd: list[str], runner: Callable | None, which: Callable) -> tuple[bool, str]:
    runner = runner or subprocess.run
    full, secret, early = rootauth.prepare(["pkexec", *cmd], which)
    if early is not None:
        return False, "The password window was closed, so nothing was changed."
    try:
        p = runner(full, capture_output=True, text=True, timeout=30, **({"input": secret.decode()} if secret else {"stdin": subprocess.DEVNULL}))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return p.returncode == 0, ((p.stderr or p.stdout or "").strip().splitlines() or [""])[0]


def ensure_on(runner: Callable | None = None, which: Callable = shutil.which) -> tuple[bool, str]:
    """Bluetooth on. Asks for the administrator password only when the service is stopped or the radio is blocked."""
    if not available(which):
        return False, "The Bluetooth tools are not installed. In a Terminal:  sudo apt install bluez   (then restart the computer)."
    st = adapter(runner)
    if not st["present"]:
        _admin(["systemctl", "start", "bluetooth"], runner, which)
        st = adapter(runner)
        if not st["present"]:
            return False, "No Bluetooth adapter found. This computer may not have Bluetooth (a small USB Bluetooth adapter adds it)."
    rf = rfkill_state(runner, which)
    if rf["hard"]:
        return False, ("Bluetooth is switched off by the laptop's own switch or key (rfkill: hard blocked). Press the wireless / "
                       "airplane key (often Fn + a key with an aerial) or flip the switch, then search again.")
    if (st["blocked"] or rf["soft"]) and which("rfkill"):
        try:
            p = (runner or subprocess.run)(["rfkill", "unblock", "bluetooth"], capture_output=True, text=True, timeout=10,
                                           stdin=subprocess.DEVNULL)
            plain_ok = p.returncode == 0
        except (OSError, subprocess.SubprocessError):
            plain_ok = False
        if not plain_ok or rfkill_state(runner, which)["soft"] or adapter(runner)["blocked"]:
            _admin(["rfkill", "unblock", "bluetooth"], runner, which)
        st["blocked"] = True
    if not st["powered"] or st["blocked"]:
        rc, out = _run(["power", "on"], runner, 10)
        if "succeeded" not in out and not adapter(runner)["powered"]:
            return False, "Bluetooth is switched off and could not be switched on (" + (out.strip().splitlines() or ["no answer"])[-1] + ")."
    return True, "Bluetooth is on."


def devices(runner: Callable | None = None, extra: str = "") -> list[Device]:
    _rc, out = _run(["devices"], runner, 10)
    found = []
    for mac, name in parse_devices(out + "\n" + extra):
        _rc, info = _run(["info", mac], runner, 10)
        found.append(parse_info(mac, name, info))
    found.sort(key=lambda d: (not d.is_pad, not d.connected, d.name.lower()))
    return found


def session(steps: list[tuple[str, float]], popen: Callable | None = None, say: Callable[[str], None] | None = None) -> str:
    """One interactive bluetoothctl kept open for the whole job: BlueZ stops a search (and forgets the pairing agent) the moment
    the program that asked for it exits, so `bluetoothctl scan on` run on its own (0.5.0/0.5.1, stdin closed) searched for ~0 s.
    steps = [(command, seconds to wait after it)]. Returns everything bluetoothctl printed."""
    import threading
    import time
    popen = popen or subprocess.Popen
    try:
        p = popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        return str(exc)
    chunks: list[str] = []

    def reader():
        try:
            for line in p.stdout:
                chunks.append(line)
        except (OSError, ValueError):
            pass
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for cmd, wait in steps:
            p.stdin.write(cmd + "\n")
            p.stdin.flush()
            if say and cmd.startswith("scan on"):
                say(f"Searching for {int(wait)} seconds...")
            time.sleep(wait)
        p.stdin.write("quit\n")
        p.stdin.flush()
    except (OSError, ValueError):
        pass
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()
    t.join(timeout=2)
    return "".join(chunks)


def scan(runner: Callable | None = None, seconds: int = SCAN_SECONDS, popen: Callable | None = None,
         say: Callable[[str], None] | None = None) -> list[Device]:
    """Search for `seconds` with discovery held open in one bluetoothctl session (with a pairing agent), then list everything
    Bluetooth knows of. `runner` (tests / old path): the one-shot `--timeout` form."""
    if runner is not None and popen is None:
        _rc, out = _run(["--timeout", str(seconds), "scan", "on"], runner, seconds + 10)
        return devices(runner, extra=out)
    out = session([("power on", 0.5), ("agent NoInputNoOutput", 0.3), ("default-agent", 0.3), ("pairable on", 0.3),
                   ("scan on", float(seconds)), ("devices", 1.0), ("scan off", 0.3)], popen, say)
    return devices(runner, extra=out)


def connect_pad(mac: str, runner: Callable | None = None, say: Callable[[str], None] | None = None,
                popen=None) -> tuple[bool, str]:
    """Pair, trust and connect. Returns (worked, plain text)."""
    say = say or (lambda t: None)
    if not MAC.match(mac or ""):
        return False, "That is not a Bluetooth address."
    say("Pairing... (keep the pad in pairing mode)")
    if runner is None and (popen is not None or shutil.which("bluetoothctl")):
        # pair inside one session with an agent, and with discovery on (BlueZ often only pairs a device it can currently see)
        out = session([("agent NoInputNoOutput", 0.3), ("default-agent", 0.3), ("scan on", 4.0), (f"pair {mac}", 12.0)], popen)
        rc = 0 if ("Pairing successful" in out or "AlreadyExists" in out) else 1
    else:
        rc, out = _run(["pair", mac], runner, 40)
    if "Pairing successful" not in out and "AlreadyExists" not in out and rc != 0:
        why = "the pad stopped searching - put it in pairing mode again and retry" if ("not available" in out or "AuthenticationTimeout" in out
                                                                                       or "ConnectionAttemptFailed" in out or rc == 124) else \
              "it asked for a code this screen cannot type - pair it once in the desktop's Bluetooth settings" if "AuthenticationRejected" in out else \
              (out.strip().splitlines() or ["no answer"])[-1]
        return False, "Pairing did not work: " + why + "."
    say("Paired. Trusting it so it reconnects by itself next time...")
    _run(["trust", mac], runner, 15)
    say("Connecting...")
    rc, out = _run(["connect", mac], runner, 30)
    if "Connection successful" in out or "AlreadyConnected" in out or rc == 0:
        return True, "Connected. Press a button on the pad - it should now show on the Controllers page."
    return False, "Paired, but it did not connect yet. Press the Home button on the pad (it reconnects by itself), or press it again here."


def forget(mac: str, runner: Callable | None = None) -> tuple[bool, str]:
    if not MAC.match(mac or ""):
        return False, "That is not a Bluetooth address."
    rc, out = _run(["remove", mac], runner, 15)
    return ("removed" in out or rc == 0), ("Removed. Pair it again any time." if ("removed" in out or rc == 0) else "Could not remove it.")


# ---- reconnect without pairing again --------------------------------------------------------------------------------------------
MAIN_CONF = "/etc/bluetooth/main.conf"
INPUT_CONF = "/etc/bluetooth/input.conf"


def reconnect_conf(main_text: str, input_text: str) -> tuple[str, str]:
    """main.conf: [Policy] AutoEnable=true (the adapter is on after every start / resume, so a pad can reconnect by itself).
    input.conf: [General] ClassicBondedOnly=false - with true (BlueZ 5.6x default), a DualShock 4 whose bond BlueZ does not fully
    trust is refused at reconnect and has to be paired again. UserspaceHID is left as the distro set it."""
    from .inifile import set_values
    main_text = set_values(main_text, "General", {"FastConnectable": "true", "JustWorksRepairing": "always"}, "=")
    return (set_values(main_text, "Policy", {"AutoEnable": "true", "ReconnectAttempts": "7"}, "="),
            set_values(input_text, "General", {"ClassicBondedOnly": "false"}, "="))


def reconnect_ok(main_text: str, input_text: str) -> bool:
    from .inifile import get_value
    return (get_value(main_text, "Policy", "AutoEnable") or "").lower() == "true" and \
        (get_value(main_text, "General", "FastConnectable") or "").lower() == "true" and \
        (get_value(input_text, "General", "ClassicBondedOnly") or "true").lower() == "false"


def reconnect_script(new_main: str, new_input: str, main: str = MAIN_CONF, inp: str = INPUT_CONF, restart: str = "systemctl restart bluetooth") -> str:
    import shlex
    q = shlex.quote
    out = ["set -e"]
    for path, text in ((main, new_main), (inp, new_input)):
        out.append(f"mkdir -p {q(str(__import__('pathlib').Path(path).parent))}")
        out.append(f"[ -f {q(path)} ] && [ ! -f {q(path + '.codeaque.bak')} ] && cp -a {q(path)} {q(path + '.codeaque.bak')} || true")
        out.append(f"printf %s {q(text)} > {q(path)}")
    out += boot_fix_lines()
    out.append(restart)
    return "\n".join(out) + "\n"


def trust_paired_pads(runner: Callable | None = None) -> list[str]:
    """Mark every paired controller Trusted (so it may reconnect by itself). Returns the names changed."""
    done = []
    for d in devices(runner):
        if d.paired and d.is_pad and not d.trusted:
            _rc, out = _run(["trust", d.mac], runner, 15)
            done.append(d.name)
    return done


DUALBOOT_NOTE = ("Why a pad can forget this computer after Windows: a Bluetooth pad keeps one secret key per computer, and Linux and "
                 "Windows on the same laptop use the same Bluetooth adapter - so to the pad they are ONE computer. Pairing it in "
                 "Windows gives it a new key, and Linux's saved key stops working (and the other way round). Honest fixes: pair "
                 "the pad only in CodeAque (use a cable or a second pad in Windows), or copy the key from Windows to Linux with "
                 "the free tool bt-dualboot (advanced; CodeAque does not do this for you).")


def check_report(devs: list[Device], main_text: str, input_text: str, dual_boot: bool, service_on: bool = True) -> list[str]:
    """Plain lines for Controllers > Controller check."""
    from .inifile import get_value
    out = []
    pads_ = [d for d in devs if d.is_pad]
    if not pads_:
        out.append("No controller is paired with this computer yet.")
    for d in pads_:
        bond = "unknown (older Bluetooth software)" if d.bonded is None else ("yes" if d.bonded else "NO")
        line = (f"{d.name} ({d.mac}): paired {'yes' if d.paired else 'NO'}, trusted {'yes' if d.trusted else 'NO'}, "
                f"bonded {bond}, connected {'yes' if d.connected else 'no'}.")
        if d.paired and d.bonded is False:
            line += " Not bonded = no key was saved, so it can never reconnect by itself: Forget it and pair it again here."
        elif d.paired and not d.trusted:
            line += " Not trusted: press Fix controller reconnect."
        out.append(line)
    ae = (get_value(main_text, "Policy", "AutoEnable") or "not set")
    fc = (get_value(main_text, "General", "FastConnectable") or "not set")
    cb = (get_value(input_text, "General", "ClassicBondedOnly") or "not set (BlueZ default: true)")
    uh = (get_value(input_text, "General", "UserspaceHID") or "not set (BlueZ default)")
    out.append(f"Bluetooth settings: AutoEnable={ae}, FastConnectable={fc}, ClassicBondedOnly={cb}, UserspaceHID={uh}."
               + ("" if reconnect_ok(main_text, input_text) else "  -> press Fix controller reconnect."))
    if not service_on:
        out.append("The Bluetooth service is not running.")
    if any(d.paired and not d.connected for d in pads_):
        out.append("A pad that shows Paired but does not connect when you press its PS / Home button usually has a stale pairing: "
                   "press \"Remove and re-pair\" next to it (one tap; hold SHARE + PS while it searches).")
    if dual_boot:
        out.append("(Less likely here, only if the pad was ever paired in Windows:) " + DUALBOOT_NOTE)
    return out


def repair_pad(mac: str, runner: Callable | None = None, popen=None, say: Callable[[str], None] | None = None,
               seconds: int = SCAN_SECONDS) -> tuple[bool, str]:
    """One tap for a pad that shows Paired but will not connect (a stale pairing): remove it, search, pair, trust, connect -
    then read it back and make sure Trusted (and Bonded, where BlueZ reports it) stuck."""
    say = say or (lambda t: None)
    if not MAC.match(mac or ""):
        return False, "That is not a Bluetooth address."
    say("Removing the old pairing...")
    _run(["remove", mac], runner, 15)
    say("Searching - hold SHARE + PS on the pad now until the light double-blinks...")
    found = scan(runner, seconds, popen=popen, say=say) if (runner is None or popen is not None) else scan(runner, seconds)
    if not any(d.mac == mac for d in found):
        return False, ("The pad was not found. Hold SHARE + PS until the light bar double-blinks, keep it close, "
                       "then press Remove and re-pair again.")
    ok, text = connect_pad(mac, runner, say, popen=popen)
    if not ok:
        return False, text
    _rc, info = _run(["info", mac], runner, 10)
    d = parse_info(mac, "", info)
    if not d.trusted:
        _run(["trust", mac], runner, 15)
        _rc, info = _run(["info", mac], runner, 10)
        d = parse_info(mac, "", info)
    if d.bonded is False:
        return False, "It connected, but Bluetooth did not save a key (Bonded: no), so it will not reconnect after a restart."
    return True, ("Done: removed, paired again, trusted" + (" and bonded" if d.bonded else "") + ", connected. "
                  "After a restart, press the PS button and it should come back by itself.")


def auto_reconnect(runner: Callable | None = None, which: Callable = shutil.which) -> list[str]:
    """Background helper (every few seconds): Bluetooth on (no password: power on / rfkill unblock as the user), then ask every
    paired + trusted pad that is not connected to connect. A pad that is switched off simply does not answer. -> names connected."""
    if not available(which):
        return []
    st = adapter(runner)
    if not st["present"]:
        return []
    if not st["powered"]:
        if which("rfkill"):
            try:
                (runner or subprocess.run)(["rfkill", "unblock", "bluetooth"], capture_output=True, text=True, timeout=10,
                                           stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass
        _run(["power", "on"], runner, 10)
    done = []
    for d in devices(runner):
        if d.is_pad and d.paired and not d.connected:
            if not d.trusted:
                _run(["trust", d.mac], runner, 10)
            _rc, out = _run(["connect", d.mac], runner, 12)
            if "Connection successful" in out or "AlreadyConnected" in out:
                done.append(d.name)
    return done


# ---- 0.5.4: Bluetooth at boot, a pairing agent that is always there, plain boot status ------------------------------------------
BOOT_UNIT = "/etc/systemd/system/codeaque-bluetooth-on.service"
BOOT_UNIT_TEXT = """[Unit]
Description=CodeAque: switch Bluetooth on at every start so paired controllers can reconnect
After=bluetooth.service
Wants=bluetooth.service

[Service]
Type=oneshot
ExecStartPre=-/usr/sbin/rfkill unblock bluetooth
ExecStart=/bin/sh -c 'for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do bluetoothctl power on 2>/dev/null | grep -q succeeded && exit 0; sleep 2; done; exit 0'

[Install]
WantedBy=bluetooth.target multi-user.target
"""


def boot_status(runner: Callable | None = None, which: Callable = shutil.which, unit: str = BOOT_UNIT) -> dict:
    """What decides whether a pad can come back after a restart, without CodeAque: is bluetoothd enabled at boot, running,
    is CodeAque's 'Bluetooth on at start' helper there, and is the desktop's Bluetooth applet (blueman) installed."""
    run = runner or subprocess.run

    def sc(*a):
        try:
            p = run(["systemctl", *a], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
            return (p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    from pathlib import Path as _P
    return {"enabled": sc("is-enabled", "bluetooth") in ("enabled", "static", "alias", "enabled-runtime"),
            "active": sc("is-active", "bluetooth") == "active",
            "helper": _P(unit).is_file(),
            "blueman": bool(which("blueman-applet"))}


def boot_ok(st: dict) -> bool:
    return st["enabled"] and st["active"] and st["helper"]


def boot_lines(st: dict) -> list[str]:
    yn = lambda b: "yes" if b else "NO"
    out = [f"Bluetooth at start: service switched on at boot {yn(st['enabled'])}, running now {yn(st['active'])}, "
           f"CodeAque's 'Bluetooth on at start' helper {yn(st['helper'])}, desktop Bluetooth icon (blueman) {yn(st['blueman'])}."]
    if not boot_ok(st):
        out.append("  -> press Fix controller reconnect (it switches these on; asks for the password once).")
    return out


def boot_fix_lines(unit: str = BOOT_UNIT, install_blueman: bool = True) -> list[str]:
    import shlex
    q = shlex.quote
    out = ["systemctl unmask bluetooth.service >/dev/null 2>&1 || true",
           "systemctl enable bluetooth.service >/dev/null 2>&1 || true",
           "rfkill unblock bluetooth 2>/dev/null || true",
           f"printf %s {q(BOOT_UNIT_TEXT)} > {q(unit)}",
           "systemctl daemon-reload || true",
           f"systemctl enable {q(__import__('pathlib').Path(unit).name)} >/dev/null 2>&1 || true"]
    if install_blueman:
        out.append("command -v blueman-applet >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y blueman >/dev/null 2>&1 || true")
    return out


class Agent:
    """A pairing agent that stays registered while CodeAque runs (CodeAque-only mode has no desktop, so no blueman agent: a pad
    asking to (re)connect could be refused for want of anyone to say yes). It says yes ONLY for controllers already paired here,
    or for the one address being re-paired right now; every other request is answered no."""

    def __init__(self, popen: Callable | None = None, allowed: Callable[[], set] | None = None):
        self._popen = popen or subprocess.Popen
        self._allowed = allowed or (lambda: set())
        self.extra: set = set()
        self.proc = None
        self.answers: list[tuple[str, str]] = []

    def start(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        try:
            self.proc = self._popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            self.proc.stdin.write("agent NoInputNoOutput\ndefault-agent\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.proc = None
            return False
        threading.Thread(target=self._read, daemon=True, name="atari-btagent").start()
        return True

    def handle(self, line: str) -> str | None:
        """'yes' / 'no' for a (yes/no) prompt, None for anything else."""
        if "(yes/no)" not in line:
            return None
        m = re.search(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})", line.upper())
        ok = bool(m) and (m.group(1) in {a.upper() for a in self._allowed()} or m.group(1) in {a.upper() for a in self.extra})
        ans = "yes" if ok else "no"
        self.answers.append((m.group(1) if m else "", ans))
        return ans

    def _read(self):
        p = self.proc
        try:
            for line in p.stdout:
                a = self.handle(line)
                if a:
                    p.stdin.write(a + "\n")
                    p.stdin.flush()
        except (OSError, ValueError):
            pass


PRESS_PS = "Press the PS button on the pad to connect it."
