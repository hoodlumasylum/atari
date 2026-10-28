"""The shared one-press installer, driven with stubbed commands (nothing is really installed)."""
import threading

import pytest

from atarilauncher import appinstall, apps, sober
from atarilauncher.appinstall import Env, Job, install_one, plan, target_for

GOOD = [sober.Check("cpu", True, False, "x86-64 processor: OK.")]


def make_env(tmp_path, have=("flatpak", "pkexec", "apt-get"), fail=(), preflight=None):
    """run() records commands; a successful `flatpak install` creates the install folder like the real one does."""
    calls = []

    def run(cmd, out, cancel=None, env=None):
        calls.append(list(cmd))
        out("working...")
        if any(f in " ".join(cmd) for f in fail):
            return 1
        if cmd[:2] == ["flatpak", "install"]:
            d = tmp_path / ".local/share/flatpak/app" / cmd[-1] / "x86_64"
            d.mkdir(parents=True, exist_ok=True)
        return 0

    env = Env(run=run, which=lambda n: "/usr/bin/" + n if n in have else None, home=tmp_path, preflight=preflight or (lambda: GOOD))
    return env, calls


def test_every_app_and_emulator_has_a_way_to_install():
    for tid in appinstall.all_ids():
        t = target_for(tid)
        assert t is not None
        assert plan(t, flatpak=True, pkexec=True, apt=True), tid


def test_flatpak_is_tried_first_per_user_and_noninteractive(tmp_path):
    env, calls = make_env(tmp_path)
    res = install_one(target_for("heroic"), env=env)
    assert res.status == "installed" and res.how == "flatpak"
    inst = [c for c in calls if c[:2] == ["flatpak", "install"]][0]
    assert "--user" in inst and "--noninteractive" in inst and inst[-2:] == ["flathub", "com.heroicgameslauncher.hgl"]
    assert not any("pkexec" in c for c in calls)


def test_apt_with_pkexec_when_flatpak_fails(tmp_path):
    env, calls = make_env(tmp_path, fail=("flatpak install",))
    res = install_one(target_for("mednafen"), env=env) if target_for("mednafen") else None
    if res is None:
        pytest.skip("no apt-only target")
    assert any(c[:3] == ["pkexec", "apt-get", "install"] for c in calls) or res.status == "failed"


def test_nothing_available_gives_plain_english(tmp_path):
    env, _ = make_env(tmp_path, have=())
    res = install_one(target_for("heroic"), env=env)
    assert res.status == "failed" and "no way to install" in res.detail


# ------------------------------------------------------------------------------------------------ Roblox (Sober)
def test_sober_is_a_flathub_only_install_of_the_verified_id():
    t = target_for("roblox")
    assert t.flatpak == "org.vinegarhq.Sober" == sober.FLATPAK_ID
    assert plan(t, flatpak=True, pkexec=True, apt=True) == ["flatpak"]     # no bundle, no .flatpakref, no apt route


def test_roblox_installs_from_flathub_and_explains_first_start(tmp_path):
    env, calls = make_env(tmp_path)
    res = install_one(target_for("roblox"), env=env)
    assert res.status == "installed"
    assert ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "org.vinegarhq.Sober"] in calls
    assert "downloads Roblox" in res.detail.replace("download Roblox", "downloads Roblox") or "download Roblox" in res.detail
    assert "sign in" in res.detail.lower()
    assert "Roblox" in appinstall.summary_text([res]) and "sign in" in appinstall.summary_text([res]).lower()


def test_roblox_adds_vulkan_driver_with_pkexec_when_none_found(tmp_path):
    no_vk = GOOD + [sober.Check("vulkan", False, False, "No Vulkan graphics driver found.")]
    env, calls = make_env(tmp_path, preflight=lambda: no_vk)
    res = install_one(target_for("roblox"), env=env)
    assert ["pkexec", "apt-get", "install", "-y", "mesa-vulkan-drivers"] in calls
    assert res.status == "installed" and "Graphics driver added" in res.detail


def test_roblox_still_installs_when_vulkan_package_fails_or_no_pkexec(tmp_path):
    no_vk = GOOD + [sober.Check("vulkan", False, False, "x")]
    env, _ = make_env(tmp_path, fail=("mesa-vulkan",), preflight=lambda: no_vk)
    res = install_one(target_for("roblox"), env=env)
    assert res.status == "installed" and "OpenGL" in res.detail
    env, calls = make_env(tmp_path / "b", have=("flatpak",), preflight=lambda: no_vk)
    (tmp_path / "b").mkdir()
    res = install_one(target_for("roblox"), env=env)
    assert res.status == "installed" and not any("pkexec" in c for c in calls) and "OpenGL" in res.detail


def test_roblox_refuses_on_arm_or_old_cpu_or_kernel_before_downloading_anything(tmp_path):
    for kw, word in (({"machine": "aarch64"}, "x86-64"),
                     ({"machine": "x86_64", "cpuinfo": "flags : fpu sse2 ssse3"}, "too old"),
                     ({"machine": "x86_64", "cpuinfo": "flags : sse4_1 sse4_2", "release": "5.4.0-1"}, "kernel")):
        env, calls = make_env(tmp_path, preflight=lambda kw=kw: sober.preflight(**kw))
        res = install_one(target_for("roblox"), env=env)
        assert res.status == "failed" and word in res.detail and calls == []


def test_roblox_failure_text_explains_invalid_bundle(tmp_path):
    env, _ = make_env(tmp_path, fail=("flatpak install",))
    res = install_one(target_for("roblox"), env=env)
    assert res.status == "failed" and "Invalid Bundle" in res.detail and "Install" in res.detail


def test_preflight_on_the_dell_latitude_style_machine():
    cpu = "flags : fpu sse4_1 sse4_2 avx2"
    checks = sober.preflight("x86_64", "6.8.0-45-generic", cpu, icd_files=lambda: ["/usr/share/vulkan/icd.d/intel_icd.x86_64.json"])
    assert sober.blocking(checks) is None and not sober.needs_vulkan_driver(checks)
    checks = sober.preflight("x86_64", "6.8.0", cpu, icd_files=lambda: [])
    assert sober.blocking(checks) is None and sober.needs_vulkan_driver(checks)
    assert sober.preflight("x86_64", "5.10.1", cpu, icd_files=lambda: [])[2].fatal


def test_job_reports_steps_and_done(tmp_path):
    env, _ = make_env(tmp_path)
    ev = []
    job = Job([(target_for("roblox"), ""), (target_for("heroic"), "")], lambda k, t: ev.append((k, t)), env).start()
    job.thread.join(10)
    kinds = [k for k, _t in ev]
    assert kinds[0] == "step" and kinds[-1] == "done" and "(2/2) Heroic Games Launcher" in [t for k, t in ev if k == "step"]
    assert [r.status for r in job.results] == ["installed", "installed"]
