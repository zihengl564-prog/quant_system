from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.features.liquidity_feature_generator import build_liquidity_features
from src.features.price_volume_feature_generator import build_price_volume_features
from src.labels.return_label_generator import build_return_labels


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    if date_str is None:
        return None
    ts = pd.to_datetime(date_str)
    return ts.strftime("%Y-%m-%d")


@dataclass
class BuildResult:
    feature_panel: pd.DataFrame
    label_panel: pd.DataFrame
    model_panel: pd.DataFrame


class FeaturePanelBuilder:
    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"db not found: {self.db_path}")
        conn = sqlite3.connect(self.db_path)
        return conn

    @staticmethod
    def _assert_unique_keys_df(df: pd.DataFrame, table_name: str) -> None:
        dup_mask = df.duplicated(subset=["trade_date", "ts_code"], keep=False)
        if dup_mask.any():
            dup_rows = df.loc[dup_mask, ["trade_date", "ts_code"]].head(10).to_dict("records")
            raise ValueError(
                f"{table_name} contains duplicate (trade_date, ts_code) keys, sample={dup_rows}"
            )

    @staticmethod
    def _assert_unique_keys_in_db(conn: sqlite3.Connection, table_name: str) -> None:
        sql = f"""
        SELECT COUNT(*)
        FROM (
            SELECT trade_date, ts_code, COUNT(*) AS c
            FROM {table_name}
            GROUP BY trade_date, ts_code
            HAVING COUNT(*) > 1
        ) t
        """
        duplicate_key_count = conn.execute(sql).fetchone()[0]
        if duplicate_key_count > 0:
            raise ValueError(
                f"{table_name} still has duplicate key groups after persist: {duplicate_key_count}"
            )

    @staticmethod
    def _create_unique_indexes(conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_feature_panel_v1_trade_date_ts_code "
            "ON feature_panel_v1(trade_date, ts_code)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_label_panel_v1_trade_date_ts_code "
            "ON label_panel_v1(trade_date, ts_code)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_panel_v1_trade_date_ts_code "
            "ON model_panel_v1(trade_date, ts_code)"
        )

    def load_std_equity_daily(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        lookback_days: int = 40,
        lookforward_days: int = 5,
    ) -> pd.DataFrame:
        start_date = normalize_date(start_date)
        end_date = normalize_date(end_date)

        query = "SELECT * FROM std_equity_daily"
        params: list[str] = []

        if start_date and end_date:
            query_start = (pd.Timestamp(start_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            query_end = (pd.Timestamp(end_date) + pd.Timedelta(days=lookforward_days)).strftime("%Y-%m-%d")
            query += " WHERE trade_date BETWEEN ? AND ?"
            params.extend([query_start, query_end])

        query += " ORDER BY trade_date, ts_code"

        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            raise ValueError("std_equity_daily query returned empty result")

        return df

    def build(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BuildResult:
        start_date = normalize_date(start_date)
        end_date = normalize_date(end_date)

        base = self.load_std_equity_daily(start_date=start_date, end_date=end_date)

        price_feat = build_price_volume_features(base)
        liq_feat = build_liquidity_features(base)
        label_panel = build_return_labels(base, horizons=(1, 5))

        dim_cols = ["ts_code", "trade_date"]
        carry_cols = [c for c in ["industry", "market"] if c in base.columns]
        feature_panel = base[dim_cols + carry_cols].copy()

        feature_panel = feature_panel.merge(price_feat, on=["ts_code", "trade_date"], how="left")
        feature_panel = feature_panel.merge(liq_feat, on=["ts_code", "trade_date"], how="left")

        feature_panel = feature_panel.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)
        label_panel = label_panel.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)

        model_panel = feature_panel.merge(label_panel, on=["ts_code", "trade_date"], how="left")
        model_panel = model_panel.drop_duplicates(subset=["ts_code", "trade_date"]).reset_index(drop=True)

        if start_date:
            feature_panel = feature_panel[feature_panel["trade_date"] >= start_date]
            label_panel = label_panel[label_panel["trade_date"] >= start_date]
            model_panel = model_panel[model_panel["trade_date"] >= start_date]

        if end_date:
            feature_panel = feature_panel[feature_panel["trade_date"] <= end_date]
            label_panel = label_panel[label_panel["trade_date"] <= end_date]
            model_panel = model_panel[model_panel["trade_date"] <= end_date]

        for df in (feature_panel, label_panel, model_panel):
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            if numeric_cols:
                df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)

        feature_panel = feature_panel.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        label_panel = label_panel.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        model_panel = model_panel.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

        self._assert_unique_keys_df(feature_panel, "feature_panel_v1")
        self._assert_unique_keys_df(label_panel, "label_panel_v1")
        self._assert_unique_keys_df(model_panel, "model_panel_v1")

        return BuildResult(
            feature_panel=feature_panel,
            label_panel=label_panel,
            model_panel=model_panel,
        )

    def _delete_date_range(self, conn: sqlite3.Connection, table_name: str, start_date: Optional[str], end_date: Optional[str]) -> None:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        exists = cursor.fetchone() is not None
        if not exists:
            return

        if start_date and end_date:
            cursor.execute(
                f"DELETE FROM {table_name} WHERE trade_date BETWEEN ? AND ?",
                (start_date, end_date),
            )
        elif start_date:
            cursor.execute(
                f"DELETE FROM {table_name} WHERE trade_date >= ?",
                (start_date,),
            )
        elif end_date:
            cursor.execute(
                f"DELETE FROM {table_name} WHERE trade_date <= ?",
                (end_date,),
            )
        else:
            cursor.execute(f"DELETE FROM {table_name}")

    def persist(
        self,
        result: BuildResult,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        start_date = normalize_date(start_date)
        end_date = normalize_date(end_date)

        self._assert_unique_keys_df(result.feature_panel, "feature_panel_v1")
        self._assert_unique_keys_df(result.label_panel, "label_panel_v1")
        self._assert_unique_keys_df(result.model_panel, "model_panel_v1")

        with self._connect() as conn:
            self._delete_date_range(conn, "feature_panel_v1", start_date, end_date)
            self._delete_date_range(conn, "label_panel_v1", start_date, end_date)
            self._delete_date_range(conn, "model_panel_v1", start_date, end_date)

            result.feature_panel.to_sql("feature_panel_v1", conn, if_exists="append", index=False)
            result.label_panel.to_sql("label_panel_v1", conn, if_exists="append", index=False)
            result.model_panel.to_sql("model_panel_v1", conn, if_exists="append", index=False)

            self._create_unique_indexes(conn)

            self._assert_unique_keys_in_db(conn, "feature_panel_v1")
            self._assert_unique_keys_in_db(conn, "label_panel_v1")
            self._assert_unique_keys_in_db(conn, "model_panel_v1")

            conn.commit()

        return {
            "feature_rows": len(result.feature_panel),
            "label_rows": len(result.label_panel),
            "model_rows": len(result.model_panel),
            "start_date": start_date,
            "end_date": end_date,
            "db_path": str(self.db_path),
        }

    def build_and_persist(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        result = self.build(start_date=start_date, end_date=end_date)
        summary = self.persist(result, start_date=start_date, end_date=end_date)
        summary["feature_columns"] = result.feature_panel.columns.tolist()
        summary["label_columns"] = result.label_panel.columns.tolist()
        return summary