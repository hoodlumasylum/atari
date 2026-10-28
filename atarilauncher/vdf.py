"""Minimal parser for Valve's text KeyValues format (.vdf / .acf).

Keys are lower-cased because Steam treats them case-insensitively
(``appid`` vs ``appID`` both occur in the wild).
"""
from __future__ import annotations

from typing import Any

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


class VDFError(ValueError):
    pass


def _tokenize(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n\ufeff":
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append(_ESCAPES.get(nxt, "\\" + nxt))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise VDFError("unterminated string")
            i += 1
            yield ("s", "".join(buf))
        else:  # unquoted token
            j = i
            while j < n and text[j] not in " \t\r\n{}\"":
                j += 1
            yield ("s", text[i:j])
            i = j


def loads(text: str) -> dict[str, Any]:
    tokens = list(_tokenize(text))
    pos = 0

    def parse_block(top: bool) -> dict[str, Any]:
        nonlocal pos
        out: dict[str, Any] = {}
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "}":
                if top:
                    raise VDFError("unexpected '}'")
                pos += 1
                return out
            if tok == "{" or not isinstance(tok, tuple):
                raise VDFError("expected a key")
            key = tok[1].lower()
            pos += 1
            if pos >= len(tokens):
                raise VDFError("key without value")
            val = tokens[pos]
            if val == "{":
                pos += 1
                out[key] = parse_block(False)
            elif isinstance(val, tuple):
                out[key] = val[1]
                pos += 1
            else:
                raise VDFError("unexpected '}'")
        if not top:
            raise VDFError("missing '}'")
        return out

    return parse_block(True)


def load(path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return loads(fh.read())
