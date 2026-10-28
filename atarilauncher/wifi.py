"""WiFi through NetworkManager's `nmcli` (what Linux Mint uses). No root is needed for a normal logged-in desktop or
CodeAque-only session: NetworkManager lets the person at the console manage WiFi, and `nmcli dev wifi connect SSID password PW`
stores the password with the connection itself, so no desktop applet / password-agent is required (that is why this works
in CodeAque-only mode where there is no panel).

Everything runs through an injectable `run(args, timeout)` -> (returncode, stdout, stderr), so tests use a mocked nmcli.
Nothing here ever raises: a missing nmcli, a stopped NetworkManager or a missing adapter come back as plain-English states."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

Run = Callable[..., tuple]

NO_NMCLI = ("This computer has no NetworkManager (the nmcli tool), so CodeAque cannot manage WiFi. On Linux Mint it is installed "
            "by default - connect with the network icon on the Mint desktop instead (Settings > Start mode > Use Linux desktop).")
NO_NM = ("NetworkManager is not running, so WiFi cannot be managed here. Restart the computer; if it is still off, "
         "connect with the Mint desktop's network settings.")
NO_ADAPTER = ("No WiFi adapter was found in this computer. If it should have one, check that it is not switched off by a key or "
              "switch on the laptop, or plug in a USB WiFi stick and press Scan again. A network cable works without any setup.")
RADIO_OFF = "WiFi is switched off. Press the button to turn it on."


def run_nmcli(args: list[str], timeout: float = 20.0) -> tuple:
    """Real runner: (returncode, stdout, stderr). 127 = nmcli missing, 124 = timed out."""
    env = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        r = subprocess.run(["nmcli"] + list(args), capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return 127, "", "nmcli: command not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 126, "", str(exc)


def split_terse(line: str) -> list[str]:
    """Split one `nmcli -t` line: fields are separated by ':'; a literal ':' or '\\' inside a field is written '\\:' / '\\\\'."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


@dataclass
class Network:
    ssid: str
    signal: int = 0            # 0-100
    security: str = ""         # "" / "--" = open
    in_use: bool = False       # connected right now
    known: bool = False        # a saved profile exists ("Forget" is possible)

    @property
    def secure(self) -> bool:
        return self.security not in ("", "--")

    @property
    def bars(self) -> int:     # 1-4
        return 1 if self.signal < 25 else 2 if self.signal < 50 else 3 if self.signal < 75 else 4

    def as_dict(self) -> dict:
        return {"ssid": self.ssid, "signal": self.signal, "bars": self.bars, "secure": self.secure,
                "security": "Open" if not self.secure else self.security.replace("WPA2 WPA3", "WPA3").strip() or "Secured",
                "inUse": self.in_use, "known": self.known}


@dataclass
class Adapter:
    state: str = "ok"          # ok | nonmcli | nm_off | noadapter | radio_off
    device: str = ""
    text: str = ""

    @property
    def usable(self) -> bool:
        return self.state == "ok"


@dataclass
class Status:
    ssid: str = ""             # connected WiFi network, if any
    wired: bool = False        # connected by cable
    text: str = "Not connected"

    @property
    def online(self) -> bool:
        return bool(self.ssid) or self.wired


def adapter(run: Run = run_nmcli, which: Callable = shutil.which) -> Adapter:
    if run is run_nmcli and not which("nmcli"):
        return Adapter("nonmcli", "", NO_NMCLI)
    rc, out, err = run(["-t", "-f", "DEVICE,TYPE,STATE", "device"], 10)
    if rc == 127:
        return Adapter("nonmcli", "", NO_NMCLI)
    if rc != 0:
        return Adapter("nm_off", "", NO_NM)
    dev = ""
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[1] == "wifi":
            dev = f[0]
            break
    if not dev:
        return Adapter("noadapter", "", NO_ADAPTER)
    rc, out, _ = run(["radio", "wifi"], 10)
    if rc == 0 and out.strip().lower().startswith("disabled"):
        return Adapter("radio_off", dev, RADIO_OFF)
    return Adapter("ok", dev, "")


def status(run: Run = run_nmcli) -> Status:
    rc, out, _ = run(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], 10)
    if rc != 0:
        return Status()
    ssid, wired = "", False
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or f[2] != "connected":
            continue
        if f[1] == "wifi":
            ssid = f[3]
        elif f[1] == "ethernet":
            wired = True
    if ssid:
        return Status(ssid, wired, "Connected to " + ssid)
    if wired:
        return Status("", True, "Connected by cable")
    return Status()


def saved(run: Run = run_nmcli) -> set[str]:
    rc, out, _ = run(["-t", "-f", "NAME,TYPE", "connection", "show"], 10)
    names: set[str] = set()
    if rc == 0:
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) >= 2 and f[1] in ("802-11-wireless", "wifi"):
                names.add(f[0])
    return names


def scan(run: Run = run_nmcli, rescan: bool = True) -> tuple[list[Network], str]:
    """Nearby networks, strongest first, one row per name (hidden ones have no name and are skipped), and a message if it failed."""
    known = saved(run)
    rc, out, err = run(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes" if rescan else "no"], 30)
    if rc != 0 and rescan:                       # "Scanning not allowed immediately following previous scan": use the last result
        rc, out, err = run(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], 15)
    if rc != 0:
        return [], friendly_error(err) or "Could not look for networks."
    best: dict[str, Network] = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1].strip():
            continue
        try:
            sig = int(f[2])
        except ValueError:
            sig = 0
        n = Network(f[1], sig, f[3], f[0].strip() == "*", f[1] in known)
        old = best.get(n.ssid)
        if old is None or n.in_use or (not old.in_use and n.signal > old.signal):
            best[n.ssid] = n
    nets = sorted(best.values(), key=lambda n: (not n.in_use, -n.signal, n.ssid.lower()))
    return nets, ""


def friendly_error(err: str) -> str:
    e = (err or "").lower()
    if not e.strip():
        return ""
    if ("secrets were required" in e or "wrong password" in e or "4-way handshake" in e
            or ("(7)" in e and "secret" in e) or ("authentication" in e and "fail" in e)):
        return "The password was not accepted. Check it (capital letters count) and try again."
    if "no network with ssid" in e or "not found" in e and "ssid" in e:
        return "That network is not in range right now. Move closer to the router and scan again."
    if "not authorized" in e or "insufficient privileges" in e or "polkit" in e or "permission" in e:
        return ("This user is not allowed to change WiFi. Open the Mint desktop's network settings once, or ask the person who "
                "set the computer up.")
    if "timeout" in e or "timed out" in e:
        return "The router did not answer in time. Try again, or move closer."
    if "networkmanager is not running" in e or "couldn't connect to server" in e:
        return NO_NM
    if "rf-kill" in e or "rfkill" in e or "wifi is disabled" in e or "wireless is disabled" in e:
        return RADIO_OFF
    if "no suitable device" in e or "no wifi device" in e or "device not found" in e:
        return NO_ADAPTER
    first = (err or "").strip().splitlines()[0]
    return first[:160]


def connect(ssid: str, password: str = "", hidden: bool = False, run: Run = run_nmcli, known: bool | None = None) -> tuple[bool, str]:
    """Join a network. A saved network is simply brought up; otherwise `device wifi connect` (which saves it).
    A failed attempt removes the profile it just created, so a wrong password is not remembered."""
    ssid = ssid.strip()
    if not ssid:
        return False, "Type the network name first."
    was_known = (ssid in saved(run)) if known is None else known
    if was_known and not password:
        rc, out, err = run(["--wait", "30", "connection", "up", "id", ssid], 45)
    else:
        args = ["--wait", "30", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        if hidden:
            args += ["hidden", "yes"]
        rc, out, err = run(args, 45)
    if rc == 0:
        return True, "Connected to " + ssid + "."
    if not was_known:                                  # do not keep a half-made profile of a failed attempt
        run(["connection", "delete", "id", ssid], 10)
    msg = friendly_error(err or out)
    if rc == 124:
        msg = friendly_error("timeout")
    return False, msg or "Could not connect."


def forget(ssid: str, run: Run = run_nmcli) -> tuple[bool, str]:
    rc, out, err = run(["connection", "delete", "id", ssid], 15)
    if rc == 0:
        return True, "Forgot " + ssid + ". It will ask for the password next time."
    return False, friendly_error(err or out) or "Could not forget that network."


def radio_on(run: Run = run_nmcli) -> tuple[bool, str]:
    rc, out, err = run(["radio", "wifi", "on"], 10)
    if rc == 0:
        return True, "WiFi is on."
    return False, friendly_error(err or out) or "Could not switch WiFi on (a keyboard key or switch on the laptop may have turned it off)."


def disconnect(device: str, run: Run = run_nmcli) -> tuple[bool, str]:
    rc, out, err = run(["device", "disconnect", device], 15)
    return rc == 0, "Disconnected." if rc == 0 else (friendly_error(err or out) or "Could not disconnect.")


def summary(run: Run = run_nmcli, which: Callable = shutil.which) -> str:
    """One short line for the home screen: the network name, 'Cable', 'No WiFi', or 'Offline'."""
    ad = adapter(run, which)
    st = status(run) if ad.state in ("ok", "radio_off", "noadapter") else Status()
    if st.ssid:
        return st.ssid
    if st.wired:
        return "Cable"
    if ad.state in ("noadapter", "nonmcli", "nm_off"):
        return "No WiFi"
    if ad.state == "radio_off":
        return "WiFi off"
    return "Offline"
