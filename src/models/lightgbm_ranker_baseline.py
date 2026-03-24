from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError as e:
    raise SystemExit(
        "lightgbm is not installed in the current environment. "
        "Please install it first, e.g. pip install lightgbm"
    ) from e


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "research" / "experiments"
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "outputs" / "research" / "experiment_registry.csv"


@dataclass
class TrainOutput:
    metrics: dict
    feature_columns: list[str]
    train_rows: int
    valid_rows: int
    train_date_count: int
    valid_date_count: int
    run_id: str
    run_dir: str
    model_path: str
    prediction_path: str
    importance_path: str
    metrics_path: str
    selected_features_path: str
    daily_eval_path: str
    registry_path: str


class LightGBMRankerBaseline:
    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        output_root: Optional[str | Path] = None,
        registry_path: Optional[str | Path] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
        self.registry_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH

        self.output_root.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"db not found: {self.db_path}")
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _sanitize_token(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")

    @staticmethod
    def _threshold_token(missing_threshold: float) -> str:
        value = int(round(missing_threshold * 100))
        return f"mt{value:02d}"

    @staticmethod
    def _valid_days_token(valid_days: int) -> str:
        return f"vd{valid_days}"

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _auto_run_id(
        self,
        label_col: str,
        missing_threshold: float,
        valid_days: int,
        train_start_date: str,
        train_end_date: str,
        valid_start_date: str,
        valid_end_date: str,
        prefix: str = "baseline",
    ) -> str:
        return (
            f"{self._sanitize_token(prefix)}"
            f"_{self._sanitize_token(label_col)}"
            f"_{self._threshold_token(missing_threshold)}"
            f"_{self._valid_days_token(valid_days)}"
            f"_tr{train_start_date.replace('-', '')}_{train_end_date.replace('-', '')}"
            f"_va{valid_start_date.replace('-', '')}_{valid_end_date.replace('-', '')}"
        )

    def _ensure_unique_run_id(self, run_id: str) -> str:
        run_dir = self.output_root / run_id
        if not run_dir.exists():
            return run_id

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{run_id}_rerun_{ts}"

    def load_model_panel(self) -> pd.DataFrame:
        with self._connect() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM model_panel_v1 ORDER BY trade_date, ts_code",
                conn,
            )
        if df.empty:
            raise ValueError("model_panel_v1 is empty")
        return df

    @staticmethod
    def _ensure_supported_label(label_col: str) -> None:
        if not label_col.endswith("_decile"):
            raise ValueError(
                "current baseline only supports decile labels for lambdarank, "
                f"got label_col={label_col}"
            )

    @staticmethod
    def _select_feature_columns(
        train_df: pd.DataFrame,
        missing_threshold: float,
        feature_whitelist: Optional[list[str]] = None,
    ) -> list[str]:
        if feature_whitelist is not None:
            feature_whitelist = [str(x) for x in feature_whitelist]
            feature_whitelist = LightGBMRankerBaseline._dedupe_preserve_order(feature_whitelist)

            missing_in_df = [c for c in feature_whitelist if c not in train_df.columns]
            if missing_in_df:
                raise ValueError(
                    f"feature_whitelist contains columns not found in train_df: {missing_in_df}"
                )

            if not feature_whitelist:
                raise ValueError("feature_whitelist is empty")

            # 关键修改：
            # 一旦传入白名单，就严格使用这份固定特征集，
            # 不再按窗口内 missing_threshold 二次删列。
            return feature_whitelist

        candidate_cols = [c for c in train_df.columns if c.startswith("feat_")]
        selected = [
            c for c in candidate_cols
            if float(train_df[c].isna().mean()) <= missing_threshold
        ]
        if not selected:
            raise ValueError("no usable feature columns after missing-rate filtering")
        return selected

    @staticmethod
    def _build_group_sizes(df: pd.DataFrame) -> list[int]:
        grouped = (
            df.groupby("trade_date", sort=True)
            .size()
            .astype(int)
            .tolist()
        )
        if not grouped:
            raise ValueError("empty group sizes")
        return grouped

    @staticmethod
    def _split_train_valid_by_labeled_dates(
        df: pd.DataFrame,
        label_col: str,
        valid_days: int,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        labeled = df[df[label_col].notna()].copy()
        if labeled.empty:
            raise ValueError(f"no labeled rows available for {label_col}")

        labeled = labeled.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        labeled_dates = sorted(labeled["trade_date"].unique())

        if len(labeled_dates) <= valid_days + 1:
            raise ValueError(
                f"not enough labeled trade dates for split: labeled_dates={len(labeled_dates)}, valid_days={valid_days}"
            )

        train_dates = labeled_dates[:-valid_days]
        valid_dates = labeled_dates[-valid_days:]

        train_df = labeled[labeled["trade_date"].isin(train_dates)].copy()
        valid_df = labeled[labeled["trade_date"].isin(valid_dates)].copy()

        if train_df.empty or valid_df.empty:
            raise ValueError("train_df or valid_df is empty after split")

        return train_df, valid_df

    @staticmethod
    def _evaluate_predictions(valid_df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
        rows = []

        for trade_date, day_df in valid_df.groupby("trade_date", sort=True):
            day_df = day_df.dropna(subset=["pred_score", "label_ret_5d_fwd"]).copy()
            if day_df.empty:
                continue

            if day_df["pred_score"].nunique() > 1 and day_df["label_ret_5d_fwd"].nunique() > 1:
                ic = day_df["pred_score"].corr(day_df["label_ret_5d_fwd"], method="spearman")
            else:
                ic = np.nan

            n = max(1, int(len(day_df) * 0.2))
            ranked = day_df.sort_values("pred_score", ascending=False).reset_index(drop=True)

            top_ret = float(ranked.head(n)["label_ret_5d_fwd"].mean())
            bottom_ret = float(ranked.tail(n)["label_ret_5d_fwd"].mean())
            spread = top_ret - bottom_ret

            rows.append(
                {
                    "trade_date": trade_date,
                    "sample_count": int(len(day_df)),
                    "top_bucket_size": int(n),
                    "spearman_ic": None if pd.isna(ic) else float(ic),
                    "top20_ret_mean": top_ret,
                    "bottom20_ret_mean": bottom_ret,
                    "top_bottom_spread": spread,
                }
            )

        daily_eval = pd.DataFrame(rows)

        if daily_eval.empty:
            metrics = {
                "valid_day_count": 0,
                "mean_spearman_ic": None,
                "std_spearman_ic": None,
                "ic_ir": None,
                "mean_top20_ret": None,
                "mean_bottom20_ret": None,
                "mean_top_bottom_spread": None,
            }
            return metrics, daily_eval

        ic_series = pd.to_numeric(daily_eval["spearman_ic"], errors="coerce")

        ic_mean = float(ic_series.mean()) if ic_series.notna().any() else None
        ic_std = float(ic_series.std(ddof=1)) if ic_series.notna().sum() > 1 else None
        ic_ir = float(ic_mean / ic_std) if (ic_mean is not None and ic_std not in (None, 0.0)) else None

        metrics = {
            "valid_day_count": int(len(daily_eval)),
            "mean_spearman_ic": ic_mean,
            "std_spearman_ic": ic_std,
            "ic_ir": ic_ir,
            "mean_top20_ret": float(daily_eval["top20_ret_mean"].mean()),
            "mean_bottom20_ret": float(daily_eval["bottom20_ret_mean"].mean()),
            "mean_top_bottom_spread": float(daily_eval["top_bottom_spread"].mean()),
        }
        return metrics, daily_eval

    def _append_registry(self, row: dict) -> None:
        row_df = pd.DataFrame([row])

        if self.registry_path.exists():
            old_df = pd.read_csv(self.registry_path, encoding="utf-8-sig")
            old_df.columns = [str(c).replace("\ufeff", "") for c in old_df.columns]
            new_df = pd.concat([old_df, row_df], ignore_index=True)
        else:
            new_df = row_df

        new_df.to_csv(self.registry_path, index=False, encoding="utf-8")

    def _train_core(
        self,
        train_df: pd.DataFrame,
        valid_df: pd.DataFrame,
        label_col: str,
        missing_threshold: float,
        num_boost_round: int,
        valid_days: int,
        run_id: Optional[str] = None,
        run_prefix: str = "baseline",
        register_run: bool = True,
        feature_whitelist: Optional[list[str]] = None,
    ) -> TrainOutput:
        self._ensure_supported_label(label_col)

        train_df = train_df.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        valid_df = valid_df.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

        feature_cols = self._select_feature_columns(
            train_df=train_df,
            missing_threshold=missing_threshold,
            feature_whitelist=feature_whitelist,
        )

        X_train = train_df[feature_cols]
        y_train = train_df[label_col].astype(int)
        X_valid = valid_df[feature_cols]
        y_valid = valid_df[label_col].astype(int)

        train_group = self._build_group_sizes(train_df)
        valid_group = self._build_group_sizes(valid_df)

        lgb_train = lgb.Dataset(
            X_train,
            label=y_train,
            group=train_group,
            feature_name=feature_cols,
            free_raw_data=False,
        )
        lgb_valid = lgb.Dataset(
            X_valid,
            label=y_valid,
            group=valid_group,
            feature_name=feature_cols,
            reference=lgb_train,
            free_raw_data=False,
        )

        params = {
            "objective": "lambdarank",
            "metric": "ndcg",
            "ndcg_eval_at": [5, 10, 20],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 50,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "verbosity": -1,
            "seed": 42,
        }

        booster = lgb.train(
            params=params,
            train_set=lgb_train,
            num_boost_round=num_boost_round,
            valid_sets=[lgb_train, lgb_valid],
            valid_names=["train", "valid"],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=20),
            ],
        )

        valid_pred_df = valid_df.copy()
        valid_pred_df["pred_score"] = booster.predict(
            X_valid,
            num_iteration=booster.best_iteration,
        )

        metrics, daily_eval = self._evaluate_predictions(valid_pred_df)

        importance_df = pd.DataFrame(
            {
                "feature": feature_cols,
                "importance_gain": booster.feature_importance(importance_type="gain"),
                "importance_split": booster.feature_importance(importance_type="split"),
            }
        ).sort_values("importance_gain", ascending=False)

        train_start_date = str(train_df["trade_date"].min())
        train_end_date = str(train_df["trade_date"].max())
        valid_start_date = str(valid_df["trade_date"].min())
        valid_end_date = str(valid_df["trade_date"].max())

        if not run_id:
            run_id = self._auto_run_id(
                label_col=label_col,
                missing_threshold=missing_threshold,
                valid_days=valid_days,
                train_start_date=train_start_date,
                train_end_date=train_end_date,
                valid_start_date=valid_start_date,
                valid_end_date=valid_end_date,
                prefix=run_prefix,
            )

        run_id = self._ensure_unique_run_id(run_id)

        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        model_path = run_dir / "model.txt"
        prediction_path = run_dir / "valid_predictions.csv"
        importance_path = run_dir / "feature_importance.csv"
        metrics_path = run_dir / "metrics.json"
        selected_features_path = run_dir / "selected_features.json"
        daily_eval_path = run_dir / "daily_eval.csv"

        prediction_df = valid_pred_df[
            ["trade_date", "ts_code", "pred_score", "label_ret_5d_fwd", label_col]
        ].copy()

        booster.save_model(str(model_path))
        prediction_df.to_csv(prediction_path, index=False, encoding="utf-8-sig")
        importance_df.to_csv(importance_path, index=False, encoding="utf-8-sig")
        daily_eval.to_csv(daily_eval_path, index=False, encoding="utf-8-sig")

        with open(selected_features_path, "w", encoding="utf-8") as f:
            json.dump(feature_cols, f, ensure_ascii=False, indent=2)

        final_metrics = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "db_path": str(self.db_path),
            "label_col": label_col,
            "missing_threshold": missing_threshold,
            "num_boost_round": num_boost_round,
            "feature_count": int(len(feature_cols)),
            "feature_columns": feature_cols,
            "train_rows": int(len(train_df)),
            "valid_rows": int(len(valid_df)),
            "train_date_count": int(train_df["trade_date"].nunique()),
            "valid_date_count": int(valid_df["trade_date"].nunique()),
            "train_start_date": train_start_date,
            "train_end_date": train_end_date,
            "valid_start_date": valid_start_date,
            "valid_end_date": valid_end_date,
            "best_iteration": int(booster.best_iteration),
            "metrics": metrics,
            "model_path": str(model_path),
            "prediction_path": str(prediction_path),
            "importance_path": str(importance_path),
            "selected_features_path": str(selected_features_path),
            "daily_eval_path": str(daily_eval_path),
            "strict_feature_whitelist": feature_whitelist is not None,
        }

        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(final_metrics, f, ensure_ascii=False, indent=2)

        if register_run:
            registry_row = {
                "run_id": run_id,
                "label_col": label_col,
                "missing_threshold": missing_threshold,
                "num_boost_round": num_boost_round,
                "feature_count": int(len(feature_cols)),
                "train_rows": int(len(train_df)),
                "valid_rows": int(len(valid_df)),
                "train_date_count": int(train_df["trade_date"].nunique()),
                "valid_date_count": int(valid_df["trade_date"].nunique()),
                "train_start_date": train_start_date,
                "train_end_date": train_end_date,
                "valid_start_date": valid_start_date,
                "valid_end_date": valid_end_date,
                "best_iteration": int(booster.best_iteration),
                "mean_spearman_ic": final_metrics["metrics"]["mean_spearman_ic"],
                "ic_ir": final_metrics["metrics"]["ic_ir"],
                "mean_top_bottom_spread": final_metrics["metrics"]["mean_top_bottom_spread"],
                "run_dir": str(run_dir),
                "metrics_path": str(metrics_path),
            }
            self._append_registry(registry_row)

        return TrainOutput(
            metrics=final_metrics,
            feature_columns=feature_cols,
            train_rows=int(len(train_df)),
            valid_rows=int(len(valid_df)),
            train_date_count=int(train_df["trade_date"].nunique()),
            valid_date_count=int(valid_df["trade_date"].nunique()),
            run_id=run_id,
            run_dir=str(run_dir),
            model_path=str(model_path),
            prediction_path=str(prediction_path),
            importance_path=str(importance_path),
            metrics_path=str(metrics_path),
            selected_features_path=str(selected_features_path),
            daily_eval_path=str(daily_eval_path),
            registry_path=str(self.registry_path),
        )

    def train(
        self,
        label_col: str = "label_ret_5d_fwd_decile",
        valid_days: int = 5,
        missing_threshold: float = 0.8,
        num_boost_round: int = 300,
        run_id: Optional[str] = None,
        register_run: bool = True,
        feature_whitelist: Optional[list[str]] = None,
    ) -> TrainOutput:
        df = self.load_model_panel()
        train_df, valid_df = self._split_train_valid_by_labeled_dates(
            df=df,
            label_col=label_col,
            valid_days=valid_days,
        )
        return self._train_core(
            train_df=train_df,
            valid_df=valid_df,
            label_col=label_col,
            missing_threshold=missing_threshold,
            num_boost_round=num_boost_round,
            valid_days=valid_days,
            run_id=run_id,
            run_prefix="baseline",
            register_run=register_run,
            feature_whitelist=feature_whitelist,
        )

    def train_from_date_sets(
        self,
        train_dates: list[str],
        valid_dates: list[str],
        label_col: str = "label_ret_5d_fwd_decile",
        missing_threshold: float = 0.5,
        num_boost_round: int = 300,
        run_id: Optional[str] = None,
        register_run: bool = True,
        feature_whitelist: Optional[list[str]] = None,
    ) -> TrainOutput:
        df = self.load_model_panel()
        labeled = df[df[label_col].notna()].copy()

        train_df = labeled[labeled["trade_date"].isin(train_dates)].copy()
        valid_df = labeled[labeled["trade_date"].isin(valid_dates)].copy()

        if train_df.empty:
            raise ValueError("train_df is empty for the provided train_dates")
        if valid_df.empty:
            raise ValueError("valid_df is empty for the provided valid_dates")

        return self._train_core(
            train_df=train_df,
            valid_df=valid_df,
            label_col=label_col,
            missing_threshold=missing_threshold,
            num_boost_round=num_boost_round,
            valid_days=len(valid_dates),
            run_id=run_id,
            run_prefix="walkforward",
            register_run=register_run,
            feature_whitelist=feature_whitelist,
        )