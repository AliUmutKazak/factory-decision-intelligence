"""The dependency gate has no vulnerability allowlist after the Pillow fix."""

from copy import deepcopy

import pytest

from scripts.audit_dependency_advisories import check_audit_report, pinned_lock_dependencies


def clean_report():
    return {
        "dependencies": [
            {"name": "pillow", "version": "13.0.0", "vulns": []},
            {"name": "streamlit", "version": "1.66.1", "vulns": []},
        ]
    }


EXPECTED = {("pillow", "13.0.0"), ("streamlit", "1.66.1")}


def test_clean_pinned_pillow_report_is_accepted():
    assert check_audit_report(clean_report(), EXPECTED) == 2


@pytest.mark.parametrize("name", ["pillow", "streamlit"])
def test_any_known_advisory_fails_the_gate(name):
    report = deepcopy(clean_report())
    dependency = next(item for item in report["dependencies"] if item["name"] == name)
    dependency["vulns"] = [{"id": "CVE-2026-EXAMPLE", "fix_versions": []}]
    with pytest.raises(ValueError, match="Known advisories"):
        check_audit_report(report, EXPECTED)


@pytest.mark.parametrize("version", ["12.3.0", "13.0.1"])
def test_pillow_version_drift_requires_review(version):
    report = clean_report()
    report["dependencies"][0]["version"] = version
    with pytest.raises(ValueError, match="Expected pillow==13.0.0"):
        check_audit_report(report, EXPECTED)


def test_missing_pillow_fails_the_gate():
    report = clean_report()
    report["dependencies"].pop(0)
    with pytest.raises(ValueError, match="Expected pillow==13.0.0"):
        check_audit_report(report, EXPECTED)


def test_missing_audited_dependency_fails_the_gate():
    report = clean_report()
    report["dependencies"].pop()
    with pytest.raises(ValueError, match="Audit inventory differs"):
        check_audit_report(report, EXPECTED)


def test_lock_requires_exact_pins(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("pillow==13.0.0\nstreamlit>=1.66.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unpinned"):
        pinned_lock_dependencies(lock)
