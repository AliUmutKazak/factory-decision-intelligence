"""Explicit input provenance for sealed runs and lab presentation."""

import hashlib
import json
from pathlib import Path

DATA_CLASSES = {"SYNTHETIC", "OPEN", "CUSTOMER", "UNCLASSIFIED"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_run_source(manifest_path: Path, run_id: str) -> tuple[str, str | None]:
    """Only trust a manifest that names the ACTIVE run and a known class."""
    try:
        manifest_path = Path(manifest_path)
        bundle_manifest = json.loads((manifest_path.parent.parent / "manifest.json").read_text(encoding="utf-8"))
        if bundle_manifest.get("run_id") != run_id:
            return "UNCLASSIFIED", None
        sealed = bundle_manifest["files"]["reports/run_manifest.json"]
        if sha256_file(manifest_path) != sealed["sha256"]:
            return "UNCLASSIFIED", None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_id") != run_id:
            return "UNCLASSIFIED", None
        source = manifest["inputs"]["input_dataset"]
        data_class = source.get("data_class")
        if data_class not in DATA_CLASSES or not source.get("path") or not source.get("sha256"):
            return "UNCLASSIFIED", None
        return data_class, source["path"]
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
        return "UNCLASSIFIED", None
