"""Is this a weak graphics chip? Used by Settings > Reduce effects = AUTO (blur and soft shadows off on weak chips).

The renderer name is read once from OpenGL (an off-screen context, nothing is shown). Software drawing (llvmpipe and
friends), virtual-machine adapters and older Intel / Atom / small ARM chips count as weak. If it cannot be read, the
chip is treated as NOT weak, but CODEAQUE_WEAK_GPU=1 / 0 always wins."""
from __future__ import annotations

import os
import re

_WEAK = [
    r"llvmpipe", r"softpipe", r"swrast", r"software", r"svga3d", r"virgl", r"virtio", r"vmware", r"virtualbox",
    r"microsoft basic", r"gdi generic",
    r"intel.*\bhd graphics(\s+[2-5]\d{3}\b|\s+50[05]\b|\s*\(|\s*$)",   # older Intel HD: 2000-5xxx, 500/505, or no number (Bay Trail)
    r"\bgma\b", r"atom", r"bay ?trail", r"cherry ?trail", r"ironlake", r"sandy ?bridge", r"ivy ?bridge", r"haswell",
    r"mali-[47]\d\d", r"videocore", r"v3d", r"vc4", r"adreno.?[1-4]\d\d",
]
_cache: str | None = None


def is_weak(renderer: str) -> bool:
    r = (renderer or "").lower()
    return bool(r) and any(re.search(p, r) for p in _WEAK)


def renderer() -> str:
    """The OpenGL renderer string, or "" (needs a QGuiApplication)."""
    global _cache
    if _cache is not None:
        return _cache
    _cache = ""
    if os.environ.get("QT_QPA_PLATFORM", "") in ("offscreen", "minimal"):
        return _cache
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        ctx = QOpenGLContext()
        if not ctx.create():
            return _cache
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        if ctx.makeCurrent(surf):
            GL_RENDERER = 0x1F01
            _cache = str(ctx.functions().glGetString(GL_RENDERER) or "")
            ctx.doneCurrent()
    except Exception:
        _cache = ""
    return _cache


def weak_gpu() -> bool:
    env = os.environ.get("CODEAQUE_WEAK_GPU", "")
    if env in ("0", "1"):
        return env == "1"
    return is_weak(renderer())
