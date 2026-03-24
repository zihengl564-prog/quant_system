from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "outputs" / "research" / "experiment_registry.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "research" / "feature_stability"


def read_csv_auto(path: Path) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            df = pd.read_csv(path, encoding=encoding)
            df.columns = [str(c).replace("\ufeff", "") for c in df.columns]
            return df
        except Exception as e:
            last_error = e
    raise RuntimeError(f"failed to read csv: {path}, last_error={last_error}")


def load_metrics(metrics_path: str) -> dict:
    path = Path(metrics_path)
    if not path.exists():
        raise FileNotFoundError(f"metrics file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"registry not found: {REGISTRY_PATH}")

    registry_df = read_csv_auto(REGISTRY_PATH)

    if "run_id" not in registry_df.columns:
        raise ValueError(f"run_id column not found in registry columns={registry_df.columns.tolist()}")
    if "metrics_path" not in registry_df.columns:
        raise ValueError(f"metrics_path column not found in registry columns={registry_df.columns.tolist()}")

    registry_df = registry_df.drop_duplicates(subset=["run_id"], keep="last").copy()

    baseline_df = registry_df[registry_df["run_id"].astype(str).str.startswith("baseline_")].copy()
    wf_df = registry_df[registry_df["run_id"].astype(str).str.startswith("wf_")].copy()

    if baseline_df.empty:
        raise ValueError("no baseline runs found in experiment_registry.csv")
    if wf_df.empty:
        raise ValueError("no walk-forward runs found in experiment_registry.csv")

    baseline_df = baseline_df.sort_values(["train_end_date", "valid_end_date", "run_id"])
    baseline_row = baseline_df.iloc[-1]

    baseline_metrics = load_metrics(str(baseline_row["metrics_path"]))
    baseline_features = list(baseline_metrics.get("feature_columns", []))
    baseline_feature_set = set(baseline_features)

    run_feature_rows = []
    wf_feature_sets: dict[str, set[str]] = {}

    for _, row in wf_df.iterrows():
        run_id = str(row["run_id"])
        metrics = load_metrics(str(row["metrics_path"]))
        feature_columns = list(metrics.get("feature_columns", []))
        wf_feature_sets[run_id] = set(feature_columns)

        run_feature_rows.append(
            {
                "run_id": run_id,
                "feature_count": len(feature_columns),
                "train_start_date": metrics.get("train_start_date"),
                "train_end_date": metrics.get("train_end_date"),
                "valid_start_date": metrics.get("valid_start_date"),
                "valid_end_date": metrics.get("valid_end_date"),
                "mean_spearman_ic": metrics.get("metrics", {}).get("mean_spearman_ic"),
                "ic_ir": metrics.get("metrics", {}).get("ic_ir"),
                "mean_top_bottom_spread": metrics.get("metrics", {}).get("mean_top_bottom_spread"),
            }
        )

    run_feature_summary_df = pd.DataFrame(run_feature_rows).sort_values("run_id").reset_index(drop=True)

    all_features: set[str] = set(baseline_feature_set)
    for feature_set in wf_feature_sets.values():
        all_features |= feature_set
    all_features = sorted(all_features)

    wf_window_count = len(wf_feature_sets)
    majority_threshold = max(2, math.ceil(wf_window_count * 2 / 3))

    occurrence_rows = []
    for feature in all_features:
        wf_count = sum(feature in feature_set for feature_set in wf_feature_sets.values())
        baseline_used = feature in baseline_feature_set

        selected_for_core = int(baseline_used and wf_count == wf_window_count)
        selected_for_majority = int(baseline_used and wf_count >= majority_threshold)

        occurrence_rows.append(
            {
                "feature": feature,
                "baseline_used": int(baseline_used),
                "wf_window_count": wf_count,
                "wf_window_ratio": wf_count / wf_window_count if wf_window_count > 0 else 0.0,
                "is_all_wf_windows": int(wf_count == wf_window_count),
                "is_majority_wf_windows": int(wf_count >= majority_threshold),
                "selected_for_core": selected_for_core,
                "selected_for_majority": selected_for_majority,
            }
        )

    occurrence_df = pd.DataFrame(occurrence_rows).sort_values(
        ["selected_for_core", "selected_for_majority", "wf_window_count", "baseline_used", "feature"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)

    core_features = occurrence_df.loc[
        occurrence_df["selected_for_core"] == 1, "feature"
    ].tolist()

    majority_features = occurrence_df.loc[
        occurrence_df["selected_for_majority"] == 1, "feature"
    ].tolist()

    summary = {
        "registry_path": str(REGISTRY_PATH),
        "baseline_run_id": str(baseline_row["run_id"]),
        "baseline_feature_count": len(baseline_features),
        "walkforward_window_count": wf_window_count,
        "majority_threshold": majority_threshold,
        "core_feature_count": len(core_features),
        "majority_feature_count": len(majority_features),
        "core_feature_list_path": str(OUTPUT_DIR / "v11_feature_list_core.json"),
        "majority_feature_list_path": str(OUTPUT_DIR / "v11_feature_list_majority.json"),
    }

    occurrence_path = OUTPUT_DIR / "feature_occurrence.csv"
    run_summary_path = OUTPUT_DIR / "run_feature_summary.csv"
    summary_path = OUTPUT_DIR / "feature_stability_summary.json"
    core_path = OUTPUT_DIR / "v11_feature_list_core.json"
    majority_path = OUTPUT_DIR / "v11_feature_list_majority.json"

    occurrence_df.to_csv(occurrence_path, index=False, encoding="utf-8")
    run_feature_summary_df.to_csv(run_summary_path, index=False, encoding="utf-8")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(core_path, "w", encoding="utf-8") as f:
        json.dump(core_features, f, ensure_ascii=False, indent=2)

    with open(majority_path, "w", encoding="utf-8") as f:
        json.dump(majority_features, f, ensure_ascii=False, indent=2)

    print("feature stability audit completed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nCore V1.1 candidate features (all walk-forward windows):")
    for feature in core_features:
        print(feature)

    print("\nMajority V1.1 candidate features (majority walk-forward windows):")
    for feature in majority_features:
        print(feature)

    print("\nTop occurrence table:")
    print(occurrence_df.head(25).to_string(index=False))


if __name__ == "__main__":
    main()