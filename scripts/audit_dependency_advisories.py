"""Audit both reproducible dependency locks without vulnerability exceptions."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def pinned_lock_dependencies(path: Path) -> set[tuple[str, str]]:
    """Read every exact package pin; reject syntax the audit cannot verify."""
    pinned = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith(("#", " ")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if match is None:
            raise ValueError(f"Unpinned or unsupported requirement in {path.name}: {line}")
        pinned.add((match.group(1).lower(), match.group(2)))
    if not pinned:
        raise ValueError(f"No pinned dependencies in {path.name}")
    return pinned


def check_audit_report(report: object, expected: set[tuple[str, str]]) -> int:
    """Require Pillow 13 and reject every advisory in a complete pip-audit report."""
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("pip-audit returned an invalid dependency report")

    dependencies = report["dependencies"]
    if not dependencies:
        raise ValueError("pip-audit returned an empty dependency report")
    pillow_versions = set()
    audited = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise ValueError("pip-audit returned an invalid dependency")
        name, version, vulns = (
            dependency.get("name"),
            dependency.get("version"),
            dependency.get("vulns"),
        )
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(vulns, list):
            raise ValueError("pip-audit returned an incomplete dependency")
        audited.add((name.lower(), version))
        if name.lower() == "pillow":
            pillow_versions.add(version)
        if vulns:
            ids = [item.get("id", "unknown") for item in vulns if isinstance(item, dict)]
            raise ValueError(f"Known advisories in {name}=={version}: {', '.join(ids) or 'unknown'}")
    if pillow_versions != {"13.0.0"}:
        raise ValueError(f"Expected pillow==13.0.0 in audit report; found {sorted(pillow_versions)}")
    if audited != expected or len(dependencies) != len(expected):
        raise ValueError(
            f"Audit inventory differs from lock: missing={sorted(expected - audited)}, extra={sorted(audited - expected)}"
        )
    return len(dependencies)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements-linux.lock", "requirements-windows.lock"):
        lock_path = root / name
        expected = pinned_lock_dependencies(lock_path)
        with TemporaryDirectory(prefix="fdi-audit-") as directory:
            report_path = Path(directory) / "audit.json"
            command = [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(lock_path),
                "--strict",
                "--no-deps",
                "--disable-pip",
                "--format",
                "json",
                "--desc",
                "off",
                "--aliases",
                "off",
                "--output",
                str(report_path),
            ]
            print(f"Auditing {name} without exceptions", flush=True)
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if not report_path.is_file():
                print(result.stderr or result.stdout or "pip-audit failed", file=sys.stderr)
                return 1
            try:
                count = check_audit_report(json.loads(report_path.read_text(encoding="utf-8")), expected)
            except (ValueError, OSError) as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                return 1
            if result.returncode:
                print(result.stderr or result.stdout or "pip-audit failed", file=sys.stderr)
                return 1
            print(f"{name}: {count} dependencies audited; no known advisories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
