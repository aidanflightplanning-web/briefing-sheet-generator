"""TAF layout used on the briefing sheet.

The base forecast stays on the first line and every change group starts a new
line: BECMG, FMddhhmm and PROBnn are indented two spaces, TEMPO four spaces.
A "PROB30 TEMPO" pair therefore becomes "  PROB30" followed by "    TEMPO ...",
while a US-style "PROB30 2709/2712 ..." stays on one line. Example::

    TAF TTPP 232200Z 2400/2424 09003KT 9999 FEW010CB SCT015
        TEMPO 2402/2409 5000 SHRA BKN015
      BECMG 2411/2413 11010KT
      PROB30
        TEMPO 2415/2418 3000 TSRA SCT010CB
"""

from __future__ import annotations

import re

_TEMPO = re.compile(r"^TEMPO$")
_CHANGE_GROUP = re.compile(r"^(?:BECMG|INTER|FM\d{4,6}|PROB\d{2})$")


def format_taf(report: str) -> list[str]:
    tokens = report.replace("=", " ").split()
    lines: list[tuple[int, list[str]]] = [(0, [])]
    for i, token in enumerate(tokens):
        if i and _TEMPO.match(token):
            lines.append((4, [token]))
        elif i and _CHANGE_GROUP.match(token):
            lines.append((2, [token]))
        else:
            lines[-1][1].append(token)
    return [" " * indent + " ".join(words) for indent, words in lines if words]
