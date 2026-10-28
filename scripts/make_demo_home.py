#!/usr/bin/env python3
"""Developer tool: build a pretend home folder (fake Steam library + fake ROMs + a fake USB stick) for
screenshots and testing. Usage:  python3 scripts/make_demo_home.py /tmp/atari-demo

Prints the environment variables to use, e.g.
  HOME=/tmp/atari-demo/home ATARI_MEDIA_ROOTS=/tmp/atari-demo/media/me ./run.sh --windowed
All game names and artwork are made up (no real titles, no third-party art).
"""
import colorsys
import json
import random
import sys
import time
from pathlib import Path

STEAM = [
    (9100001, "Cosmic Crawler"), (9100002, "Neon Pinball Deluxe"), (9100003, "Dungeon of Pixels"),
    (9100004, "Turbo Kart Rally"), (9100005, "Lantern Valley"), (9100006, "Orbital Defense"),
    (9100007, "Rust & Rails"), (9100008, "Echoes of Tomorrow"), (9100009, "Iron Harbor"),
    (9100010, "Midnight Courier"),
]
ROMS = {
    "atari2600": ("a26", ["Blocky Breakout", "Desert Raider", "Sky Gunner"]),
    "snes": ("sfc", ["Cloud Racers", "Dragon Tamer"]),
    "ps1": ("cue", ["Dino Dash", "Turbo Kart Zero"]),
    "ps2": ("iso", ["Midnight Racer"]),
    "dreamcast": ("gdi", ["Orbit Fighters"]),
    "gamecube": ("iso", ["Island Hoppers"]),
    "nes": ("nes", ["Castle Quest", "Plumber Panic"]),
    "xbox": ("xiso", ["Block Party"]),
}


def art(path: Path, w: int, h: int, seed: int, title: str):
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return
    rnd = random.Random(seed)
    hue = rnd.random()
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    c1 = tuple(int(x * 255) for x in colorsys.hls_to_rgb(hue, 0.42, 0.7))
    c2 = tuple(int(x * 255) for x in colorsys.hls_to_rgb((hue + 0.12) % 1, 0.10, 0.6))
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2)))
    for _ in range(7):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(w // 8, w // 3)
        col = tuple(int(x * 255) for x in colorsys.hls_to_rgb((hue + rnd.random() * 0.3) % 1, 0.6, 0.8))
        d.ellipse([x - r, y - r, x + r, y + r], outline=col, width=max(2, w // 60))
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.74), w, h], fill=(0, 0, 0))
    d.text((w * 0.06, h * 0.80), title.upper(), fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=88)


def main(root: Path):
    home = root / "home"
    steam = home / ".local/share/Steam"
    (steam / "steamapps").mkdir(parents=True, exist_ok=True)
    (home / ".steam").mkdir(exist_ok=True)
    link = home / ".steam/steam"
    if not link.exists():
        link.symlink_to(steam)
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % steam)
    for i, (appid, name) in enumerate(STEAM):
        (steam / f"steamapps/appmanifest_{appid}.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"%d"\n\t"name"\t\t"%s"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"%s"\n'
            '\t"SizeOnDisk"\t\t"1000000"\n}\n' % (appid, name, name))
        if i % 3 != 2:  # most have local library art, a few fall back to the generated tile
            cache = steam / "appcache/librarycache" / str(appid)
            art(cache / "library_600x900.jpg", 600, 900, appid, name)
            art(cache / "header.jpg", 460, 215, appid + 1, name)
    rom_cfg = []
    for sid, (ext, titles) in ROMS.items():
        folder = home / "Games/Atari" / sid
        folder.mkdir(parents=True, exist_ok=True)
        for t in titles:
            (folder / f"{t} (USA).{ext}").write_bytes(b"demo")
        rom_cfg.append(f'[systems.{sid}]\nroms = ["{folder}"]\n')
    covers = home / ".local/share/atari/covers"
    art(covers / "Cloud Racers.png", 600, 600, 77, "Cloud Racers")      # a user-supplied cover
    art(covers / "Blocky Breakout.jpg", 600, 600, 78, "Blocky Breakout")
    conf = home / ".config/atari"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "config.toml").write_text("[general]\nfullscreen = false\n[steam]\nenabled = true\n\n" + "\n".join(rom_cfg))
    # favourites and recently played
    now = time.time()
    st = {"version": 1, "games": {}}
    ids = [f"steam:{a}" for a, _ in STEAM]
    for n, gid in enumerate(ids[:4]):
        st["games"][gid] = {"last_played": now - n * 3600 * 5, "launches": 2, "playtime_sec": 3600 * (n + 1)}
    for gid in (ids[0], ids[3], ids[4]):
        st["games"].setdefault(gid, {})["favorite"] = True
    (home / ".local/share/atari").mkdir(parents=True, exist_ok=True)
    (home / ".local/share/atari/state.json").write_text(json.dumps(st))
    # a pretend USB stick
    media = root / "media/me"
    stick = media / "RETRO_USB"
    for rel, size in {"snes/Star Voyager.sfc": 3000000, "snes/Jungle Jump (EU).zip": 900000,
                      "gba/Pocket Racer.gba": 1500000, "Atari 2600/Space Duel Jr.a26": 4096,
                      "PS1/Cave Story Remix.cue": 100, "PS1/Cave Story Remix.bin": 6000000,
                      "PS3/Sky Fortress [BLUS00001]/PS3_GAME/USRDIR/EBOOT.BIN": 2000000,
                      "PS3/Sky Fortress [BLUS00001]/PS3_GAME/USRDIR/data.pak": 9000000,
                      "xbox/Hover Arena.xiso": 4000000, "readme.txt": 10}.items():
        p = stick / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    (stick / "PS1/Cave Story Remix.cue").write_text('FILE "Cave Story Remix.bin" BINARY\n')
    print(f"HOME={home} ATARI_MEDIA_ROOTS={media}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/atari-demo"))
