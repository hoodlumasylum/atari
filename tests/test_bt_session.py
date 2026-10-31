"""Pairing a PS4 DualShock 4 ("Wireless Controller") with a pretend interactive bluetoothctl (mocked BlueZ)."""
import queue
import subprocess

from atarilauncher import bluetooth as bt

MAC = "1C:66:6D:AA:BB:01"


class FakeCtl:
    """Acts like an interactive bluetoothctl: answers commands written to stdin; the pad is only seen while a search is running."""
    def __init__(self, pairs=True):
        self.q, self.cmds, self.scanning, self.pairs = queue.Queue(), [], False, pairs
        outer = self

        class In:
            def write(self, s):
                for c in s.splitlines():
                    outer.cmd(c.strip())

            def flush(self):
                pass
        self.stdin = In()

    def cmd(self, c):
        self.cmds.append(c)
        say = self.q.put
        if c == "scan on":
            self.scanning = True
            say("Discovery started\n")
            say("[\x1b[0;92mNEW\x1b[0m] Device 11:22:33:44:55:66 11-22-33-44-55-66\n")
            say(f"[\x1b[0;92mNEW\x1b[0m] Device {MAC} Wireless Controller\n")
            say(f"[CHG] Device {MAC} RSSI: -48\n")
        elif c == "scan off":
            self.scanning = False
        elif c.startswith("pair "):
            say("Attempting to pair with " + MAC + "\n")
            say("Pairing successful\n" if self.scanning and self.pairs else "Failed to pair: org.bluez.Error.AuthenticationFailed\n")
        elif c == "quit":
            self.q.put(None)

    @property
    def stdout(self):
        while True:
            x = self.q.get(timeout=5)
            if x is None:
                return
            yield x

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_scan_keeps_one_session_open_with_agent_and_finds_the_ds4(monkeypatch):
    monkeypatch.setattr(bt, "_run", lambda args, runner=None, timeout=20: (0, ""))
    monkeypatch.setattr("time.sleep", lambda s: None)
    ctl = FakeCtl()
    found = bt.scan(seconds=20, popen=lambda *a, **k: ctl)
    assert ctl.cmds.index("default-agent") < ctl.cmds.index("scan on") < ctl.cmds.index("scan off") < ctl.cmds.index("quit")
    assert "power on" in ctl.cmds
    names = {d.mac: d.name for d in found}
    assert names[MAC] == "Wireless Controller"            # not "RSSI: -48"
    ds4 = next(d for d in found if d.mac == MAC)
    assert ds4.is_pad and found[0].mac == MAC              # controllers listed first


def test_pair_happens_in_a_session_with_discovery_on(monkeypatch):
    calls = []
    monkeypatch.setattr(bt, "_run", lambda args, runner=None, timeout=20: (calls.append(args) or 0, "Connection successful" if args[0] == "connect" else ""))
    monkeypatch.setattr("time.sleep", lambda s: None)
    ctl = FakeCtl()
    ok, text = bt.connect_pad(MAC, popen=lambda *a, **k: ctl)
    assert ok and "Connected" in text
    assert ctl.cmds.index("scan on") < ctl.cmds.index(f"pair {MAC}")
    assert ["trust", MAC] in calls and ["connect", MAC] in calls
    ok, text = bt.connect_pad(MAC, popen=lambda *a, **k: FakeCtl(pairs=False))
    assert not ok and "Pairing did not work" in text


class Done:
    def __init__(self, out="", rc=0):
        self.stdout, self.stderr, self.returncode = out, "", rc


def test_rfkill_soft_block_is_lifted_and_hard_block_explained(monkeypatch):
    state = {"soft": True}
    seen = []

    def runner(cmd, **k):
        seen.append(cmd)
        if cmd[:2] == ["rfkill", "list"]:
            return Done(f"0: hci0: Bluetooth\n\tSoft blocked: {'yes' if state['soft'] else 'no'}\n\tHard blocked: no\n")
        if cmd[:2] == ["rfkill", "unblock"]:
            state["soft"] = False
            return Done()
        if cmd[:2] == ["bluetoothctl", "show"]:
            return Done("Controller 00:11:22:33:44:55\n\tPowered: " + ("no" if state["soft"] else "yes") + "\n")
        return Done("Changing power on succeeded\n")
    ok, text = bt.ensure_on(runner=runner, which=lambda n: "/usr/bin/" + n)
    assert ok and ["rfkill", "unblock", "bluetooth"] in seen and not state["soft"]

    def hard(cmd, **k):
        if cmd[:2] == ["rfkill", "list"]:
            return Done("0: hci0: Bluetooth\n\tSoft blocked: no\n\tHard blocked: yes\n")
        return Done("Controller 00:11:22:33:44:55\n\tPowered: no\n")
    ok, text = bt.ensure_on(runner=hard, which=lambda n: "/usr/bin/" + n)
    assert not ok and "hard blocked" in text


def test_ds4_tip_is_on_the_page():
    tips = " ".join(bt.PAIRING_STEPS)
    assert "SHARE and the PS button" in tips and "Wireless Controller" in tips


def test_remove_and_repair_one_tap(monkeypatch):
    calls = []
    trusted = {"v": False}

    def run(args, runner=None, timeout=20):
        calls.append(args)
        if args[0] == "trust":
            trusted["v"] = True
        if args[0] == "connect":
            return 0, "Connection successful"
        if args[0] == "info":
            return 0, f"Name: Wireless Controller\nPaired: yes\nBonded: yes\nTrusted: {'yes' if trusted['v'] else 'no'}\nConnected: yes\n"
        return 0, ""
    monkeypatch.setattr(bt, "_run", run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    ctls = []

    def popen(*a, **k):
        ctls.append(FakeCtl())
        return ctls[-1]
    ok, text = bt.repair_pad(MAC, popen=popen)
    assert ok and "bonded" in text, text
    assert calls[0] == ["remove", MAC] and ["trust", MAC] in calls and ["connect", MAC] in calls
    assert any(f"pair {MAC}" in c.cmds for c in ctls)


def test_auto_reconnect_powers_on_and_trusts_but_never_connects_out(monkeypatch):
    calls = []

    def run(args, runner=None, timeout=20):
        calls.append(args)
        if args[0] == "show":
            return 0, "Controller 00:11:22:33:44:55\n\tPowered: no\n"
        if args[0] == "devices":
            return 0, f"Device {MAC} Wireless Controller\nDevice 11:22:33:44:55:66 Speaker\n"
        if args[0] == "info" and args[1] == MAC:
            return 0, "Name: Wireless Controller\nPaired: yes\nTrusted: no\nConnected: no\n"
        if args[0] == "info":
            return 0, "Name: Speaker\nPaired: yes\nConnected: no\n"
        if args[0] == "connect":
            return 0, "Connection successful"
        return 0, ""
    monkeypatch.setattr(bt, "_run", run)

    class P:
        returncode, stdout, stderr = 0, "", ""
    got = bt.auto_reconnect(runner=lambda *a, **k: P(), which=lambda n: "/usr/bin/" + n)
    assert got == ["Wireless Controller"]
    assert ["power", "on"] in calls and ["trust", MAC] in calls
    assert not any(c[0] == "connect" for c in calls)       # outgoing connects blocked the DS4's own incoming connection
