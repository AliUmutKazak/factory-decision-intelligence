"""Audit both reproducible locks with one short-lived upstream Pillow exception."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# Streamlit 1.64.0 requires Pillow <13 while these 24 advisories are fixed
# in Pillow 13.0.0. Lab-only exception; keep it explicit and time-limited.
PILLOW_EXCEPTION_EXPIRES = date(2026, 11, 20)
PILLOW_ADVISORIES = (
    "CVE-2026-112895",
    "CVE-2026-112400",
    "CVE-2026-112397",
    "CVE-2026-112896",
    "CVE-2026-112897",
    "CVE-2026-112395",
    "CVE-2026-112404",
    "CVE-2026-112899",
    "CVE-2026-112402",
    "CVE-2026-112900",
    "CVE-2026-112893",
    "CVE-2026-112392",
    "CVE-2026-112891",
    "CVE-2026-112405",
    "CVE-2026-112390",
    "CVE-2026-112401",
    "CVE-2026-112901",
    "CVE-2026-112391",
    "CVE-2026-112894",
    "CVE-2026-112406",
    "CVE-2026-112399",
    "CVE-2026-112892",
    "CVE-2026-112393",
    "CVE-2026-112396",
)


def main() -> int:
    today = datetime.now(UTC).date()
    if today > PILLOW_EXCEPTION_EXPIRES:
        raise RuntimeError("Pillow advisory exception expired; update Streamlit/Pillow before release")
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements-linux.lock", "requirements-windows.lock"):
        command = [sys.executable, "-m", "pip_audit", "-r", str(root / name), "--strict"]
        for advisory in PILLOW_ADVISORIES:
            command.extend(("--ignore-vuln", advisory))
        print(f"Auditing {name}; Pillow exceptions expire {PILLOW_EXCEPTION_EXPIRES}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
