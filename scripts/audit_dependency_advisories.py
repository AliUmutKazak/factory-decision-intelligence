"""Audit both reproducible locks with one short-lived upstream Pillow exception."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

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


def check_audit_report(report: object) -> int:
    """Accept only the documented Pillow 12.3.0 findings; reject all others."""
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("pip-audit returned an invalid dependency report")

    accepted_ids = []
    pillow_found = False
    for dependency in report["dependencies"]:
        if not isinstance(dependency, dict):
            raise ValueError("pip-audit returned an invalid dependency")
        name, version, vulns = (
            dependency.get("name"),
            dependency.get("version"),
            dependency.get("vulns"),
        )
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(vulns, list):
            raise ValueError("pip-audit returned an incomplete dependency")
        if name.lower() == "pillow":
            pillow_found = True
            if version != "12.3.0":
                raise ValueError(f"Pillow version changed to {version}; reassess the exception")
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                raise ValueError(f"pip-audit returned an invalid advisory for {name}")
            advisory = vuln["id"]
            if name.lower() != "pillow" or version != "12.3.0" or advisory not in PILLOW_ADVISORIES:
                raise ValueError(f"Unaccepted advisory: {name}=={version} {advisory}")
            if "13.0.0" not in vuln.get("fix_versions", []):
                raise ValueError(f"Pillow fix version changed for {advisory}; reassess the exception")
            accepted_ids.append(advisory)
    if not pillow_found:
        raise ValueError("Pillow is absent from the audit report; reassess the exception")
    if set(accepted_ids) != set(PILLOW_ADVISORIES) or len(accepted_ids) != len(PILLOW_ADVISORIES):
        raise ValueError("Pillow advisory set changed; reassess the exception")
    return len(accepted_ids)


def main() -> int:
    today = datetime.now(UTC).date()
    if today > PILLOW_EXCEPTION_EXPIRES:
        raise RuntimeError("Pillow advisory exception expired; update Streamlit/Pillow before release")
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements-linux.lock", "requirements-windows.lock"):
        with TemporaryDirectory(prefix="fdi-audit-") as directory:
            report_path = Path(directory) / "audit.json"
            command = [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(root / name),
                "--strict",
                "--format",
                "json",
                "--desc",
                "off",
                "--aliases",
                "off",
                "--output",
                str(report_path),
            ]
            print(f"Auditing {name}; Pillow exceptions expire {PILLOW_EXCEPTION_EXPIRES}", flush=True)
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode not in (0, 1) or not report_path.is_file():
                print(result.stderr or result.stdout or "pip-audit failed", file=sys.stderr)
                return 1
            try:
                accepted = check_audit_report(json.loads(report_path.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                return 1
            if result.returncode == 1 and accepted == 0:
                print(f"{name}: pip-audit failed without a documented finding", file=sys.stderr)
                return 1
            print(f"{name}: {accepted} documented Pillow advisories; no other known findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
