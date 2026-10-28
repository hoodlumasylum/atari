"""Sober's "Install Roblox - application bundle (APK) required" screen: detection, the one retry, the honest message."""
import os
import subprocess

import pytest

from atarilauncher import apps, diagnose, launcher, library, sober
from atarilauncher.config import default_config

FAIL_LOG = """info: app: lifecycle: logging_started
info: state: starting onboarding flow UI...
info: state: downloading Roblox from update service...
ERROR: state: couldn't download Roblox from update service, trying again...
ERROR: state: couldn't install Roblox using update service, falling back to manual install
"""
OK_LOG = "info: state: downloading Roblox from update service...\ninfo: app: Roblox started\n"
LOGDIR = ".var/app/org.vinegarhq.Sober/data/sober/sober_logs"


def logdir(home):
    d = home / LOGDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_detects_the_manual_bundle_fallback_in_a_real_looking_log():
    assert sober.needs_bundle(FAIL_LOG)
    assert not sober.needs_bundle(OK_LOG)
    assert not sober.needs_bundle("")


def test_bundle_state_reads_only_the_newest_log(tmp_path):
    d = logdir(tmp_path)
    (d / "old.log").write_text(FAIL_LOG)
    os.utime(d / "old.log", (1000, 1000))
    assert sober.bundle_state(0, home=str(tmp_path)) is True              # newest is the failed one
    (d / "new.log").write_text(OK_LOG)
    assert sober.bundle_state(0, home=str(tmp_path)) is False             # the newer start worked
    assert sober.bundle_state(0, home=str(tmp_path / "nothing")) is False


def test_service_checks_and_plain_english_cause():
    ok = sober.service_checks(lambda u: 200 if "vinegar" in u else 404)
    assert all(c.ok for c in ok)
    assert "probably down" in sober.explain(ok)
    blocked = sober.service_checks(lambda u: 0)
    assert not any(c.ok for c in blocked)
    assert "1.1.1.1" in sober.explain(blocked)
    server = sober.service_checks(lambda u: 500 if "vinegar" in u else 404)
    assert "its side" in sober.explain(server)


def test_update_command_is_the_documented_flatpak_update():
    assert sober.update_command()[:2] == ["flatpak", "update"] and sober.FLATPAK_ID in sober.update_command()
    seen = []
    ok, _ = sober.update_sober(run=lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "done", ""))
    assert ok and seen == [sober.update_command()]


def test_help_text_is_honest_and_never_points_at_an_apk_download():
    t = sober.BUNDLE_HELP
    assert "cannot download Roblox" in t and "1.1.1.1" in t and "unofficial" in t
    assert "apkmirror" not in t.lower() and "http" not in t.lower()


def roblox_game(tmp_path, script_body):
    script = tmp_path / "sober.sh"
    script.write_text("#!/bin/sh\n" + script_body)
    script.chmod(0o755)
    cfg = default_config()
    cfg.emulator_commands["roblox"] = str(script)
    g = next(g for g in library.build_library(cfg, home=tmp_path, metadata={}).games if g.title == "Roblox")
    return cfg, g


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_launch_with_the_bundle_screen_updates_sober_and_retries_once_then_succeeds(env, monkeypatch):
    d = logdir(env)
    counter = env / "count"
    # first start writes the failing log, second start writes a good one
    cfg, g = roblox_game(env, f"""n=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {counter}
if [ $n = 1 ]; then cat > {d}/a.log <<'EOF'
{FAIL_LOG}EOF
else sleep 0.3; echo ok > {d}/b.log; fi
""")
    real = sober.service_checks
    monkeypatch.setattr(sober, "service_checks", lambda probe=None: real(lambda u: 200))
    calls = []
    monkeypatch.setattr(sober, "update_sober", lambda *a, **k: calls.append("update") or (True, ""))
    secs, err = launcher.run_game(cfg, g, lambda: None)
    assert err == "" and calls == ["update"] and counter.read_text().strip() == "2"


def test_launch_that_keeps_failing_gives_an_honest_message_and_retries_only_once(env, monkeypatch):
    d = logdir(env)
    counter = env / "count"
    cfg, g = roblox_game(env, f"""n=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {counter}
cat > {d}/log$n.log <<'EOF'
{FAIL_LOG}EOF
""")
    real = sober.service_checks
    monkeypatch.setattr(sober, "service_checks", lambda probe=None: real(lambda u: 200))
    calls = []
    monkeypatch.setattr(sober, "update_sober", lambda *a, **k: calls.append("update") or (True, ""))
    secs, err = launcher.run_game(cfg, g, lambda: None)
    assert counter.read_text().strip() == "2" and calls == ["update"]
    assert err.startswith(launcher.INFO) and "updated Sober and tried again" in err and "Cloudflare" not in err
    assert "download service is probably down" in err


def test_blocked_network_skips_the_pointless_retry_and_says_so(env, monkeypatch):
    d = logdir(env)
    counter = env / "count"
    cfg, g = roblox_game(env, f"echo x >> {counter}\ncat > {d}/a.log <<'EOF'\n{FAIL_LOG}EOF\n")
    real = sober.service_checks
    monkeypatch.setattr(sober, "service_checks", lambda probe=None: real(lambda u: 0))
    monkeypatch.setattr(sober, "update_sober", lambda *a, **k: pytest.fail("must not update when offline"))
    secs, err = launcher.run_game(cfg, g, lambda: None)
    assert len(counter.read_text().split()) == 1
    assert "1.1.1.1" in err and "tried again" not in err


def test_a_normal_roblox_start_is_untouched(env, monkeypatch):
    cfg, g = roblox_game(env, "sleep 0.2\n")
    monkeypatch.setattr(sober, "update_sober", lambda *a, **k: pytest.fail("no update needed"))
    secs, err = launcher.run_game(cfg, g, lambda: None)
    assert err == ""


def test_fix_my_game_flags_the_download_problem(env):
    d = logdir(env)
    (d / "a.log").write_text(FAIL_LOG)
    cfg = default_config()
    g = next(g for g in library.build_library(cfg, home=env, metadata={}).games if g.title == "Roblox")
    rows = diagnose.check_game(cfg, g)
    row = next(r for r in rows if r["title"] == "Roblox download")
    assert row["state"] == diagnose.BAD and "cannot download Roblox" in row["advice"]
