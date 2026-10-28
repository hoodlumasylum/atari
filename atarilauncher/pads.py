"""Gamepads: which ones are plugged in, and the SDL "GUID" xemu uses to remember one.

Read from the kernel's list (/proc/bus/input/devices): every block that has a joystick handler (js0, js1 ...) is a pad. The GUID is built
the way SDL2 builds it for a Linux pad - bus, vendor, product and version as little-endian 16-bit words - which is what xemu stores in
`[input.bindings] port1 = '...'`. (xemu may be built with a newer SDL whose GUID has an extra byte or two at the end; that is why CodeAque
also leaves xemu's own automatic binding switched on - see xemuconfig.set_pad.) Pure Python, never raises, no SDL needed."""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

PROC_DEVICES = "/proc/bus/input/devices"
BUS_NAMES = {3: "USB", 5: "Bluetooth", 6: "Virtual", 17: "Host", 25: "Host", 1: "PCI", 2: "ISA", 24: "Host"}


@dataclass
class Pad:
    name: str
    bus: int
    vendor: int
    product: int
    version: int
    js: str = ""           # "js0"
    event: str = ""        # "event5"

    @property
    def guid(self) -> str:
        return sdl_guid(self.bus, self.vendor, self.product, self.version, self.name)

    @property
    def how(self) -> str:
        return BUS_NAMES.get(self.bus, "other")

    @property
    def ids(self) -> str:
        return f"{self.vendor:04x}:{self.product:04x}"


def sdl_guid(bus: int, vendor: int, product: int, version: int, name: str = "") -> str:
    """SDL2's GUID for a Linux joystick (32 hex characters)."""
    if vendor and product:
        raw = struct.pack("<8H", bus, 0, vendor, 0, product, 0, version, 0)
    else:                                   # no ids: SDL uses a checksum of the name and the name itself
        crc = _crc16(name.encode("utf-8", "replace"))
        raw = struct.pack("<HH", bus, crc) + name.encode("utf-8", "replace")[:12].ljust(12, b"\0")
    return raw.hex()


def _crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse(text: str) -> list[Pad]:
    pads: list[Pad] = []
    for block in re.split(r"\n\s*\n", text):
        ident = re.search(r"Bus=([0-9a-fA-F]+)\s+Vendor=([0-9a-fA-F]+)\s+Product=([0-9a-fA-F]+)\s+Version=([0-9a-fA-F]+)", block)
        name = re.search(r'^N: Name="(.*)"', block, re.M)
        hand = re.search(r"^H: Handlers=(.*)$", block, re.M)
        if not (ident and name and hand):
            continue
        handlers = hand.group(1).split()
        js = next((h for h in handlers if re.fullmatch(r"js\d+", h)), "")
        if not js:
            continue
        ev = next((h for h in handlers if re.fullmatch(r"event\d+", h)), "")
        bus, vendor, product, version = (int(x, 16) for x in ident.groups())
        pads.append(Pad(name.group(1), bus, vendor, product, version, js, ev))
    pads.sort(key=lambda p: int(p.js[2:]))
    return pads


def detect(path: str = PROC_DEVICES) -> list[Pad]:
    try:
        return parse(Path(path).read_text(errors="replace"))
    except OSError:
        return []
