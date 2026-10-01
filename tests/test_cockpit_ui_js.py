"""Regression test for the served Cockpit dashboard inline script.

A prior defect turned literal backslash-n (``\\n``) inside JS single-quoted strings in
``DASHBOARD_HTML`` into real newlines (the constant is a non-raw Python triple-quoted
string). That produced ``SyntaxError: Invalid or unexpected token`` at parse time, which
silently blanked the dashboard in the browser. This test extracts the served ``<script>``
block and runs ``node --check`` on it, so the failure is caught at test time instead of in
a user's browser.

The test is skipped when ``node`` is not on ``PATH`` (e.g. a CI image without Node), so it
never hard-fails an environment that cannot run it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from blue_waves.cockpit_ui import DASHBOARD_HTML

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node not installed")


def _extract_script(html: str) -> str:
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if not match:
        pytest.fail("no <script> block found in dashboard HTML")
    return match.group(1)


def test_dashboard_inline_script_is_valid_js() -> None:
    script = _extract_script(DASHBOARD_HTML)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            [_NODE, "--check", str(path)],
            capture_output=True,
            text=True,
        )
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, (
        "node --check failed on the served cockpit script:\n" + result.stderr
    )
