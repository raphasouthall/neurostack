# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""The dashboard's static files reference only files that ship (issue #244)."""

import re
from pathlib import Path

import neurostack

STATIC = Path(neurostack.__file__).parent / "ui" / "static"
# Pages another builder lands; the router shows an error card until then.
PENDING = {"pages/graph.js", "pages/memories.js"}


def test_index_and_routes_reference_existing_files():
    html = (STATIC / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="([^"#:]+)"', html)
    app = (STATIC / "app.js").read_text()
    refs += [r.removeprefix("./") for r in re.findall(r"'(\./pages/[^']+\.js)'", app)]
    assert "app.js" in refs and "pages/overview.js" in refs
    missing = [r for r in refs if not (STATIC / r).is_file() and r not in PENDING]
    assert missing == []
