"""Ensure the temporary lab exception cannot hide an unrelated finding."""

from copy import deepcopy

import pytest

from scripts.audit_dependency_advisories import PILLOW_ADVISORIES, check_audit_report


def report_with_allowed_advisories():
    return {
        "dependencies": [
            {
                "name": "pillow",
                "version": "12.3.0",
                "vulns": [{"id": advisory, "fix_versions": ["13.0.0"]} for advisory in PILLOW_ADVISORIES],
            },
            {"name": "other", "version": "1.0", "vulns": []},
        ]
    }


def test_only_documented_pillow_version_is_accepted():
    assert check_audit_report(report_with_allowed_advisories()) == len(PILLOW_ADVISORIES)


@pytest.mark.parametrize(
    ("package", "version", "advisory"),
    [
        ("other", "1.0", PILLOW_ADVISORIES[0]),
        ("pillow", "12.4.0", PILLOW_ADVISORIES[0]),
        ("pillow", "12.3.0", "CVE-2026-NEW"),
    ],
)
def test_exception_cannot_hide_other_package_version_or_advisory(package, version, advisory):
    report = deepcopy(report_with_allowed_advisories())
    report["dependencies"][0]["name"] = package
    report["dependencies"][0]["version"] = version
    report["dependencies"][0]["vulns"][0]["id"] = advisory
    with pytest.raises(ValueError):
        check_audit_report(report)


def test_changed_fix_version_requires_review():
    report = report_with_allowed_advisories()
    report["dependencies"][0]["vulns"][0]["fix_versions"] = ["12.3.1"]
    with pytest.raises(ValueError, match="fix version changed"):
        check_audit_report(report)


def test_missing_known_advisory_requires_review():
    report = report_with_allowed_advisories()
    report["dependencies"][0]["vulns"].pop()
    with pytest.raises(ValueError, match="advisory set changed"):
        check_audit_report(report)
