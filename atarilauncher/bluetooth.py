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
        # a proper bond: adapter powered + pairable + bondable, an agent in the same session, pair, then trust before it closes
        out = session([("power on", 0.5), ("pairable on", 0.3), ("agent NoInputNoOutput", 0.3), ("default-agent", 0.3),
                       ("scan on", 4.0), (f"pair {mac}", 12.0), ("scan off", 0.5), (f"trust {mac}", 1.0)], popen)
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
            set_values(input_text, "General", {"ClassicBondedOnly": "false", "IdleTimeout": "0"}, "="))


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
    # 0.5.6: NO outgoing "connect" for controllers. A DS4 / DualSense connects IN when PS is pressed; our own connect attempts
    # ("Host is down (112)") made bluetoothd refuse the pad's incoming connection ("Operation already in progress (114)").
    # So: adapter on, pad trusted, and let the pad come in.
    done = []
    for d in devices(runner):
        if d.is_pad and d.paired and not d.connected and not d.trusted:
            _run(["trust", d.mac], runner, 10)
            done.append(d.name)
    return done


# ---- 0.5.4: Bluetooth at boot, a pairing agent that is always there, plain boot status ------------------------------------------
BOOT_UNIT = "/etc/systemd/system/codeaque-bluetooth-on.service"
MODULES_CONF = "/etc/modules-load.d/codeaque-bluetooth.conf"
MODULES_TEXT = "# CodeAque: kernel parts a Bluetooth PlayStation pad needs\nuhid\nhidp\nhid_playstation\n"
BOOT_UNIT_TEXT = """[Unit]
Description=CodeAque: keep Bluetooth on and connectable so paired controllers can reconnect (also after sleep)
After=bluetooth.service
Wants=bluetooth.service

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=-/usr/sbin/rfkill unblock bluetooth
ExecStartPre=-/sbin/modprobe -a uhid hidp hid_playstation
ExecStart=/bin/sh -c 'while true; do bluetoothctl power on >/dev/null 2>&1; for m in $(bluetoothctl devices Paired 2>/dev/null | cut -d" " -f2); do bluetoothctl info "$m" 2>/dev/null | grep -q "Trusted: yes" || bluetoothctl trust "$m" >/dev/null 2>&1; done; s=$(btmgmt info 2>/dev/null | grep -i "current settings"); case "$s" in *connectable*) ;; *) btmgmt connectable on >/dev/null 2>&1; btmgmt bondable on >/dev/null 2>&1;; esac; case "$s" in *page-scan*|*connectable*) ;; *) hciconfig hci0 pscan >/dev/null 2>&1;; esac; sleep 20; done'

[Install]
WantedBy=bluetooth.target multi-user.target
"""
# helper marker for boot_status: connectable on



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
            "helper": _P(unit).is_file() and "Restart=always" in (_P(unit).read_text(errors="replace") if _P(unit).is_file() else ""),
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
           f"printf %s {q(MODULES_TEXT)} > {q(MODULES_CONF)}",
           "modprobe -a uhid hidp hid_playstation 2>/dev/null || true",
           "btmgmt connectable on >/dev/null 2>&1 || true",
           "btmgmt bondable on >/dev/null 2>&1 || true",
           "systemctl daemon-reload || true",
           f"systemctl enable {q(__import__('pathlib').Path(unit).name)} >/dev/null 2>&1 || true",
           f"systemctl restart {q(__import__('pathlib').Path(unit).name)} >/dev/null 2>&1 || true"]
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
        self.last_mac = ""
        self.on_seen: Callable[[str], None] | None = None   # a known pad showed up (PS pressed) -> quick connect tries

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
        known = {a.upper() for a in self._allowed()} | {a.upper() for a in self.extra}
        m = re.search(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})", line.upper())
        if "(yes/no)" not in line:
            if m and not line.lstrip().startswith("[agent]"):
                self.last_mac = m.group(1)
                if m.group(1) in known and self.on_seen and ("Connected:" in line or "[NEW]" in line or "[CHG]" in line):
                    try:
                        self.on_seen(m.group(1))
                    except Exception:
                        pass
            return None
        # bluetoothctl's agent prompts ("Authorize service <uuid> (yes/no)", "Confirm passkey ...") often carry no address:
        # then the device is the one bluetoothctl reported just before
        mac = m.group(1) if m else self.last_mac
        hid = "1124" in line and "authorize" in line.lower()
        ans = "yes" if (mac and mac in known) or (hid and not mac and known) else "no"
        self.answers.append((mac, ans))
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


def loaded_modules(path: str = "/proc/modules") -> set:
    try:
        return {l.split()[0] for l in open(path) if l.strip()}
    except OSError:
        return set()


def diagnostics(mac: str = "", runner: Callable | None = None, journal: Callable | None = None, modules: set | None = None) -> list[str]:
    """Plain lines to photograph and send: this pad's paired / trusted / bonded / connected, the adapter state, the kernel parts a
    PlayStation pad needs, and the last 20 lines of the Bluetooth service log. Never raises; needs no password."""
    out = ["DIAGNOSTICS (take a photo of this page and send it)"]
    try:
        devs = [d for d in devices(runner) if d.is_pad and d.paired]
        if mac:
            devs = [d for d in devs if d.mac == mac] or devs
        if not devs:
            out.append("No paired controller.")
        yn = lambda b: "?" if b is None else ("yes" if b else "NO")
        for d in devs:
            out.append(f"{d.name} {d.mac}: paired {yn(d.paired)}, trusted {yn(d.trusted)}, bonded {yn(d.bonded)}, connected {yn(d.connected)}")
        _rc, a = _run(["show"], runner, 10)
        keep = [l.strip() for l in a.splitlines() if re.match(r"\s*(Controller|Powered|Discoverable|Pairable|Connectable|PowerState)\b", l)]
        out.append("Adapter (bluetoothctl show): " + "; ".join(keep) if keep else "Adapter: no answer from bluetoothctl show")
        out += mgmt_lines(runner)
        mods = loaded_modules() if modules is None else modules
        out.append("Kernel parts: " + ", ".join(f"{m} {'yes' if m in mods else 'NO'}" for m in ("bluetooth", "hidp", "uhid", "hid_playstation")))
    except Exception as exc:  # pragma: no cover
        out.append(f"(could not read Bluetooth: {exc})")
    try:
        if journal is not None:
            text = journal()
        else:
            p = subprocess.run(["journalctl", "-b", "-u", "bluetooth", "-n", "2000", "--no-pager", "-o", "short"],
                               capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            text = (p.stdout or "") + (p.stderr or "")
        lines = journal_filter(text, mac)
        out.append("Bluetooth log - only lines about input / HID / connecting / pairing" + (f" / {mac}" if mac else "") + " (last 20):"
                   if lines else "Bluetooth log: no input / HID / connect lines since this start (or the log is not readable by this user).")
        out += ["  " + l[-160:] for l in lines]
    except (OSError, subprocess.SubprocessError):
        out.append("Bluetooth service log: journalctl not available.")
    return out


def mgmt_lines(runner: Callable | None = None) -> list[str]:
    """`btmgmt info`: the adapter's address and current settings straight from the kernel - 'connectable' must be there, or
    a pad pressing PS never even reaches bluetoothd."""
    if runner is not None:
        return []
    try:
        p = subprocess.run(["btmgmt", "info"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        text = (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ["Kernel adapter settings (btmgmt info): btmgmt not available."]
    return mgmt_summary(text)


def mgmt_summary(text: str) -> list[str]:
    addr = re.search(r"addr ([0-9A-F:]{17})", text, re.I)
    cur = re.search(r"current settings:\s*(.*)", text, re.I)
    if not cur:
        return ["Kernel adapter settings (btmgmt info): could not read (" + ((text.strip().splitlines() or ["no answer"])[-1])[:80] + ")."]
    c = cur.group(1).strip()
    out = [f"Kernel adapter {addr.group(1) if addr else '?'} current settings: {c}"]
    if "connectable" not in c.split():
        out.append("  -> NOT connectable: the pad's PS press cannot reach this computer. Press Fix controller reconnect "
                   "(CodeAque's helper then keeps it connectable, also after sleep).")
    return out


LOG_PATTERN = r"input|hid|connect|auth|pair|bond|key|refus|agent"


def journal_filter(text: str, mac: str = "", n: int = 20) -> list[str]:
    """Only the lines that matter for a controller (not the audio 'Endpoint registered' start-up lines)."""
    pat = LOG_PATTERN + ("|" + re.escape(mac[:5]) if mac else "")
    keep = [l for l in text.splitlines() if l.strip() and re.search(pat, l, re.I) and "Endpoint registered" not in l]
    return keep[-n:]


def quick_connect(mac: str, seconds: float = 10.0, runner: Callable | None = None, sleep: Callable = None) -> bool:
    """Right after the pad's PS button: ask it to connect again and again for ~10 s (the DS4 only listens briefly)."""
    import time as _t
    sleep = sleep or _t.sleep
    end = _t.monotonic() + seconds
    while True:
        _rc, out = _run(["connect", mac], runner, 5)
        if "Connection successful" in out or "AlreadyConnected" in out:
            return True
        if _t.monotonic() >= end:
            return False
        sleep(0.7)


def link_key_script(mac: str, root: str = "/var/lib/bluetooth") -> str:
    """Run as root: for each adapter, is there a saved pairing key for this pad? Prints a short fingerprint of the key (never the
    key itself), so two checks can tell whether the key was replaced in between (for example by pairing in Windows)."""
    return ("for d in " + root + "/*/; do [ -d \"$d\" ] || continue; a=$(basename \"$d\"); f=\"${d}" + mac.upper() + "/info\"; "
            "if [ -f \"$f\" ]; then k=$(sed -n '/^\\[LinkKey\\]/,/^\\[/s/^Key=//p' \"$f\" | head -n1); "
            "if [ -n \"$k\" ]; then echo \"adapter $a key yes $(printf %s \"$k\" | sha256sum | cut -c1-8)\"; "
            "else echo \"adapter $a key no\"; fi; else echo \"adapter $a nofile\"; fi; done\n")


def parse_link_key(out: str) -> dict:
    """-> {'adapters': [..], 'saved': bool|None, 'fingerprint': str}"""
    ad, saved, fp = [], None, ""
    for l in out.splitlines():
        m = re.match(r"adapter (\S+) (key yes (\w+)|key no|nofile)", l.strip())
        if not m:
            continue
        ad.append(m.group(1))
        if m.group(3):
            saved, fp = True, m.group(3)
        elif saved is None:
            saved = False
    return {"adapters": ad, "saved": saved, "fingerprint": fp}


def link_key_lines(info: dict, previous: str = "") -> list[str]:
    if info["saved"] is None:
        return ["Saved pairing key: could not check (no Bluetooth folder found, or the password box was closed)."]
    if not info["saved"]:
        return ["Saved pairing key: NO - this computer did not keep a key for the pad, so it must be paired again each time. "
                "Press Remove and re-pair once more; if it still says NO, send these diagnostics."]
    out = [f"Saved pairing key: yes (fingerprint {info['fingerprint']}; adapter {', '.join(info['adapters'])})."]
    if previous and previous != info["fingerprint"]:
        out.append(f"The key CHANGED since the last check (was {previous}). Something paired the pad again in between - most often "
                   "Windows on the same computer, or a PS4 console. " + "The pad keeps only one key per computer.")
    if len(info["adapters"]) > 1:
        out.append("More than one Bluetooth adapter address is stored - if the adapter's address changes between starts, the pad "
                   "cannot find it again.")
    return out


DUALBOOT_SHORT = ("Dual boot: if you pair this pad in Windows (or with a PS4) it gets a new key and Linux's saved key stops working - "
                  "then only SHARE + PS (pairing again) works here. Pair it in only one place.")
