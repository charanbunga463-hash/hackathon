"""Developer harness: run every demo's tests and report the seeded failure.

Not a pytest module — run it directly:

    python tests/run_demo_matrix.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEMOS = Path(__file__).resolve().parents[2] / "demo-projects"


def main() -> int:
    for directory in sorted(DEMOS.iterdir()):
        if not directory.is_dir():
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--color=no", "-rf"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=180,
        )
        summary = [
            line for line in result.stdout.splitlines()
            if line.strip().startswith(("FAILED", "ERROR")) or " passed" in line or " failed" in line
        ]
        print(f"\n=== {directory.name} (exit {result.returncode}) ===")
        for line in summary[-6:]:
            print("  ", line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
