"""Tiny INI editor that keeps everything else in the file as it is (comments, order, other sections)."""
from __future__ import annotations

import re


def set_values(text: str, section: str, values: dict, sep: str = " = ") -> str:
    """Set key=value pairs in [section] (added at its end; the section is added at the end of the file if missing).
    A commented-out '#Key = x' line is left alone and the real key is added."""
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if l.strip() == f"[{section}]":
            start = i
            break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        lines += [f"{k}{sep}{v}" for k, v in values.items()]
        return "\n".join(lines) + "\n"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*\[.*\]\s*$", lines[j]):
            end = j
            break
    todo = dict(values)
    for j in range(start + 1, end):
        m = re.match(r"^\s*([^#;=][^=]*?)\s*=", lines[j])
        if m and m.group(1) in todo:
            lines[j] = f"{m.group(1)}{sep}{todo.pop(m.group(1))}"
    ins = end
    while ins > start + 1 and not lines[ins - 1].strip():
        ins -= 1
    lines[ins:ins] = [f"{k}{sep}{v}" for k, v in todo.items()]
    return "\n".join(lines) + "\n"


def get_value(text: str, section: str, key: str) -> str | None:
    cur = None
    for l in text.splitlines():
        s = l.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
        elif cur == section:
            m = re.match(r"^([^#;=][^=]*?)\s*=\s*(.*)$", s)
            if m and m.group(1) == key:
                return m.group(2)
    return None
