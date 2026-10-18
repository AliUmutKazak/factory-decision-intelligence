"""Check the canonical gate inventory against local evidence and the roadmap view."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs/evidence-register.json"
ROADMAP = ROOT / "docs/fdi-roadmap-execution.md"
RELEASE_BOUNDARY = ROOT / "docs/release-evidence-and-field-boundary.md"
GATE_ROW = re.compile(r"^\| (G\d{1,2}) [^|]*\| ([^|]*)\|", re.MULTILINE)


def _repo_file(name: str) -> Path:
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"Missing or unsafe evidence path: {name}")
    return path


def _historical_code(name: str, commit: str) -> bytes:
    _repo_file(name)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"Invalid historical code commit: {commit}")
    return subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT).replace(b"\r\n", b"\n")


def verify() -> None:
    inventory = json.loads(REGISTER.read_text(encoding="utf-8"))
    if inventory["schema_version"] != 1:
        raise ValueError("Unsupported evidence-register schema")
    release = inventory["latest_verified_release"]
    tag_commit = subprocess.check_output(["git", "rev-list", "-n", "1", release["tag"]], cwd=ROOT, text=True).strip()
    if tag_commit != release["commit"]:
        raise ValueError("Release tag and commit disagree")
    if release["artifact_name"] != f"fdi-lab-candidate-{release['commit']}":
        raise ValueError("Release artifact name and commit disagree")
    if not re.fullmatch(r"[0-9a-f]{64}", release["artifact_sha256"]):
        raise ValueError("Invalid release artifact digest")

    for source_id, source in inventory["sources"].items():
        data = _repo_file(source["path"]).read_bytes()
        mode = source["sha256_mode"]
        if mode == "normalized_lf":
            data = data.replace(b"\r\n", b"\n")
        elif mode != "byte_exact":
            raise ValueError(f"Unknown hash mode for {source_id}: {mode}")
        actual = hashlib.sha256(data).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Source hash changed: {source_id}")

    for source_id in ("jsp_v012_30s", "jsp_v012_60s"):
        source = inventory["sources"][source_id]
        report = json.loads(_repo_file(source["path"]).read_text(encoding="utf-8"))
        if report["identity"]["solver_version"] != "9.15.6755":
            raise ValueError(f"Unexpected solver version in {source_id}")
        for name, expected in report["identity"]["code_hashes_normalized_lf"].items():
            normalized = _historical_code(name, source["code_commit"])
            if hashlib.sha256(normalized).hexdigest() != expected:
                raise ValueError(f"Historical benchmark code disagrees with {source_id}: {name}")
    forecast_source = inventory["sources"]["forecast_v012"]
    forecast = json.loads(_repo_file(forecast_source["path"]).read_text(encoding="utf-8"))
    if forecast["code_commit"] != forecast_source["code_commit"]:
        raise ValueError("Forecast evidence commit disagrees with register")
    forecast_code = _historical_code("src/forecasting/train_forecast.py", forecast_source["code_commit"])
    if hashlib.sha256(forecast_code).hexdigest() != forecast["forecast_code_sha256_normalized_lf"]:
        raise ValueError("Historical forecast code disagrees with forecast_v012")

    for source_id in (
        "g7_paired_reschedule_corrected_20261018",
        "g7_paired_reschedule_maintenance_audit_20261018",
        "g7_paired_reschedule_setup_audit_20261018",
    ):
        replay_source = inventory["sources"][source_id]
        replay = json.loads(_repo_file(replay_source["path"]).read_text(encoding="utf-8"))
        if replay["source_db_sha256"] != inventory["sources"]["reference_db"]["sha256"]:
            raise ValueError(f"G7 replay used a different reference database: {source_id}")
        if (replay["methods"], replay["attempted_trace_count"], replay["planned_event_pair_count"]) != (
            ["FULL", "EDD"],
            3,
            6,
        ):
            raise ValueError(f"G7 replay protocol changed: {source_id}")
        paired = [row for trace in replay["traces"] for row in trace["paired_events"]]
        if (
            len(paired) != 6
            or replay["paired_accepted_event_count"] != 6
            or not all(row["both_accepted"] for row in paired)
        ):
            raise ValueError(f"G7 replay count disagrees with event records: {source_id}")
        for name, expected in replay["code_sha256"].items():
            if hashlib.sha256(_historical_code(name, replay_source["code_commit"])).hexdigest() != expected:
                raise ValueError(f"G7 replay code disagrees: {source_id}/{name}")
        for trace in replay["traces"]:
            name = Path(trace["trace"]).name
            if (
                hashlib.sha256(_historical_code(f"examples/{name}", replay_source["code_commit"])).hexdigest()
                != trace["trace_sha256"]
            ):
                raise ValueError(f"G7 replay event trace disagrees: {source_id}/{name}")
            if len(trace["paired_events"]) != 2:
                raise ValueError(f"G7 replay event count disagrees: {source_id}/{name}")
            for method in replay["methods"]:
                outcome = trace["outcomes"][method]
                if (
                    not outcome["source_unchanged"]
                    or not outcome["completed_all_events"]
                    or outcome["final_active_run_ids"] != ["TRACE-02"]
                    or len(outcome["attempts"]) != 2
                    or not all(attempt["accepted"] for attempt in outcome["attempts"])
                ):
                    raise ValueError(f"G7 replay outcome disagrees: {source_id}/{name}/{method}")

    gates = inventory["gates"]
    expected_ids = {f"G{index}" for index in range(14)}
    if {item["id"] for item in gates} != expected_ids or len(gates) != len(expected_ids):
        raise ValueError("Gate IDs must be G0 through G13 exactly once")
    roadmap = ROADMAP.read_text(encoding="utf-8")
    matrix = roadmap.split("## G0-G13 kapı matrisi", 1)[1].split("## v1.1", 1)[0]
    rows = dict(GATE_ROW.findall(matrix))
    if set(rows) != expected_ids:
        raise ValueError("Roadmap matrix must contain G0 through G13 exactly once")
    for record in [*gates, *inventory["lab_packages"]]:
        for source_id in record["source_ids"]:
            if source_id not in inventory["sources"]:
                raise ValueError(f"Unknown source ID in {record['id']}: {source_id}")
        for evidence in record["evidence"]:
            _repo_file(evidence)
        if record["status"] == "Kabul edildi" and not record.get("accepted_by"):
            raise ValueError(f"Accepted gate has no approver: {record['id']}")
    for gate in gates:
        if rows[gate["id"]].strip() != gate["status"]:
            raise ValueError(f"Roadmap status disagrees with register: {gate['id']}")

    release_boundary = RELEASE_BOUNDARY.read_text(encoding="utf-8")
    for content, label in [(roadmap, "roadmap"), (release_boundary, "release boundary")]:
        if release["tag"] not in content or str(release["ci_run_id"]) not in content:
            raise ValueError(f"Current release evidence missing from {label}")
    if release["artifact_sha256"] not in roadmap:
        raise ValueError("Current artifact digest missing from roadmap")
    print(f"Evidence register verified: {len(gates)} gates, {len(inventory['lab_packages'])} lab packages")


if __name__ == "__main__":
    verify()
