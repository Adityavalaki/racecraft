"""
The interface's stylesheet holds together (BUG-006).

A merge once left "padding: 6px; min-height: 0; }" between two rules. The stray
brace made the browser read the next rule's selector as part of that text, drop
`.workspace { display: flex }` without a word, and stack the replay's columns.
The replay is now the `.pitwall` grid (D-024); the same guard holds for it.
Here, not in vitest: vitest hands CSS to tests as empty text.
"""

from __future__ import annotations

import re
from pathlib import Path

STYLES = Path(__file__).resolve().parents[1] / "web" / "src" / "styles.css"
CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def test_every_brace_closes_a_block():
    depth = 0
    for number, line in enumerate(CSS.splitlines(), start=1):
        for ch in line:
            depth += (ch == "{") - (ch == "}")
            assert depth >= 0, f'a "}}" with nothing to close, near line {number}'
    assert depth == 0


def test_the_replay_is_a_grid():
    # The replay's pit wall (D-024): the rule a stray brace would drop, as one once dropped `.workspace`.
    rule = re.search(r"\n\.pitwall \{([^}]*)\}", CSS)
    assert rule and "display: grid;" in rule.group(1)
    assert '"tower map dashA" "rc tel dashB"' in rule.group(1)
