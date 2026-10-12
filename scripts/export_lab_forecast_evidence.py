"""Summarize one completed synthetic forecast backtest without a customer claim."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export(lineage_path: Path, metadata_path: Path, fixture_path: Path, source_commit: str) -> dict:
    with lineage_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not rows or {row["product_id"] for row in rows} != set(metadata):
        raise ValueError("Forecast lineage and metadata product sets disagree")
    if len({row["product_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate product in forecast lineage")
    run_ids = {row["run_id"] for row in rows}
    versions = {row["model_version"] for row in rows}
    if len(run_ids) != 1 or len(versions) != 1:
        raise ValueError("Forecast evidence must describe one run and one model version")

    products = []
    fold_counts = set()
    uncertainty_methods = set()
    for row in sorted(rows, key=lambda item: item["product_id"]):
        product = row["product_id"]
        chosen = row["selected_model"]
        competitors = json.loads(row["competing_models"])
        if chosen not in competitors or "Naive" not in competitors:
            raise ValueError(f"Missing selected or simple baseline model for {product}")
        if metadata[product]["selected_model"] != chosen or metadata[product]["model_version"] != row["model_version"]:
            raise ValueError(f"Metadata and lineage disagree for {product}")
        selected = competitors[chosen]
        wape = float(row["backtest_wape"]) if row["backtest_wape"] else None
        if wape != selected["backtest_wape"]:
            raise ValueError(f"Selected WAPE and lineage disagree for {product}")
        fold_counts.add(len(selected["fold_metrics"]))
        uncertainty_methods.add(metadata[product]["uncertainty_method"])
        products.append(
            {
                "product_id": product,
                "selected_model": chosen,
                "selection_metric": "WAPE" if wape is not None else "RMSE",
                "backtest_start": row["backtest_start"],
                "backtest_end": row["backtest_end"],
                "selected_wape": wape,
                "selected_rmse": float(row["backtest_rmse"]),
                "selected_bias": float(row["backtest_bias"]),
                "naive_wape": competitors["Naive"]["backtest_wape"],
                "naive_rmse": competitors["Naive"]["backtest_rmse"],
                "selected_fold_metrics": selected["fold_metrics"],
                "naive_fold_metrics": competitors["Naive"]["fold_metrics"],
            }
        )

    if len(fold_counts) != 1 or len(uncertainty_methods) != 1:
        raise ValueError("Forecast folds or uncertainty methods disagree across products")
    code = (ROOT / "src/forecasting/train_forecast.py").read_bytes().replace(b"\r\n", b"\n")
    committed_code = subprocess.check_output(
        ["git", "show", f"{source_commit}:src/forecasting/train_forecast.py"], cwd=ROOT
    ).replace(b"\r\n", b"\n")
    if code != committed_code:
        raise ValueError("Current forecast code differs from declared source commit")
    fixture = fixture_path.read_bytes().replace(b"\r\n", b"\n")
    return {
        "status": "PASS",
        "scope": "SYNTHETIC_ROLLING_ORIGIN_BACKTEST_NO_CUSTOMER_ACCURACY",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "code_commit": source_commit,
        "forecast_code_sha256_normalized_lf": _sha256(code),
        "fixture_sha256_normalized_lf": _sha256(fixture),
        "lineage_sha256": _sha256(lineage_path.read_bytes()),
        "metadata_sha256": _sha256(metadata_path.read_bytes()),
        "run_id": next(iter(run_ids)),
        "model_version": next(iter(versions)),
        "data_class": "SYNTHETIC",
        "fold_count": next(iter(fold_counts)),
        "uncertainty_method": next(iter(uncertainty_methods)),
        "products": products,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export compact synthetic forecast evidence")
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = export(args.lineage, args.metadata, args.fixture, args.source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Forecast evidence exported: {len(report['products'])} synthetic products, {report['fold_count']} folds")


if __name__ == "__main__":
    main()
