from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"


@dataclass(frozen=True)
class TurtleV1Config:
    """A-Turtle V1 parameters."""

    min_list_days: int = 120
    # Tushare daily.amount is normally in thousand RMB: 50,000 = 50 million RMB.
    min_avg_amount_20: float = 50_000.0

    fast_ma_window: int = 20
    slow_ma_window: int = 60

    entry_window: int = 20
    exit_window: int = 10
    atr_window: int = 20

    top_n: int = 15

    risk_per_trade: float = 0.005
    max_stock_weight: float = 0.08
    stop_atr_multiple: float = 2.0

    lookback_calendar_days: int = 180


def normalize_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return pd.to_datetime(value).strftime("%Y-%m-%d")


class TurtleV1SignalBuilder:
    """Build A-Turtle V1 daily signals from standardized A-share data."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        config: Optional[TurtleV1Config] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.config = config or TurtleV1Config()

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"research database not found: {self.db_path}")
        return sqlite3.connect(self.db_path)

    def load_market_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        start_date = normalize_date(start_date)
        end_date = normalize_date(end_date)

        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required")
        if start_date > end_date:
            raise ValueError(f"start_date > end_date: {start_date} > {end_date}")

        query_start = (
            pd.Timestamp(start_date)
            - pd.Timedelta(days=self.config.lookback_calendar_days)
        ).strftime("%Y-%m-%d")

        sql = """
        SELECT
            d.*,
            m.name AS security_name,
            m.list_date,
            m.delist_date,
            m.list_status
        FROM std_equity_daily d
        LEFT JOIN std_security_master m
            ON d.ts_code = m.ts_code
        WHERE d.trade_date BETWEEN ? AND ?
        ORDER BY d.ts_code, d.trade_date
        """

        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(query_start, end_date))

        if df.empty:
            raise ValueError(
                "std_equity_daily returned no data "
                f"for {query_start} ~ {end_date}"
            )

        return df

    @staticmethod
    def _prepare_prices(df: pd.DataFrame) -> pd.DataFrame:
        """Prefer adjusted OHLC fields and fall back to raw prices if needed."""
        data = df.copy()

        for raw_col, adj_col in (
            ("open", "open_adj"),
            ("high", "high_adj"),
            ("low", "low_adj"),
            ("close", "close_adj"),
        ):
            if raw_col not in data.columns:
                raise ValueError(f"missing required column: {raw_col}")

            if adj_col not in data.columns:
                data[adj_col] = data[raw_col]
            else:
                data[adj_col] = data[adj_col].fillna(data[raw_col])

        return data

    def build(self, start_date: str, end_date: str) -> pd.DataFrame:
        config = self.config
        start_date = normalize_date(start_date)
        end_date = normalize_date(end_date)

        data = self.load_market_data(start_date=start_date, end_date=end_date)
        data = self._prepare_prices(data)

        data["trade_date"] = pd.to_datetime(data["trade_date"])
        data["list_date_dt"] = pd.to_datetime(data["list_date"], errors="coerce")
        data["delist_date_dt"] = pd.to_datetime(data["delist_date"], errors="coerce")
        data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        g = data.groupby("ts_code", group_keys=False)

        data["ma20"] = g["close_adj"].transform(
            lambda s: s.rolling(
                config.fast_ma_window,
                min_periods=config.fast_ma_window,
            ).mean()
        )
        data["ma60"] = g["close_adj"].transform(
            lambda s: s.rolling(
                config.slow_ma_window,
                min_periods=config.slow_ma_window,
            ).mean()
        )

        # Use only information available before the current close.
        data["entry_high_20"] = g["high_adj"].transform(
            lambda s: s.shift(1)
            .rolling(config.entry_window, min_periods=config.entry_window)
            .max()
        )
        data["exit_low_10"] = g["low_adj"].transform(
            lambda s: s.shift(1)
            .rolling(config.exit_window, min_periods=config.exit_window)
            .min()
        )

        prev_close = g["close_adj"].shift(1)
        true_range = pd.concat(
            [
                (data["high_adj"] - data["low_adj"]).abs(),
                (data["high_adj"] - prev_close).abs(),
                (data["low_adj"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        data["true_range"] = true_range

        data["atr20"] = true_range.groupby(data["ts_code"]).transform(
            lambda s: s.ewm(
                alpha=1.0 / config.atr_window,
                adjust=False,
                min_periods=config.atr_window,
            ).mean()
        )
        data["atr_pct"] = np.where(
            data["close_adj"].notna() & (data["close_adj"] != 0),
            data["atr20"] / data["close_adj"],
            np.nan,
        )

        data["avg_amount_20"] = g["amount"].transform(
            lambda s: s.rolling(20, min_periods=20).mean()
        )
        data["return_20"] = g["close_adj"].pct_change(periods=20, fill_method=None)
        data["list_days"] = (data["trade_date"] - data["list_date_dt"]).dt.days

        market_ok = data["ts_code"].astype(str).str.endswith((".SH", ".SZ"))
        name_series = data["security_name"].fillna("").astype(str).str.upper()
        not_st = ~name_series.str.contains("ST", regex=False)
        list_age_ok = data["list_days"] >= config.min_list_days
        liquidity_ok = data["avg_amount_20"] >= config.min_avg_amount_20
        delist_ok = data["delist_date_dt"].isna() | (
            data["trade_date"] <= data["delist_date_dt"]
        )
        valid_price = (
            data["close_adj"].notna()
            & data["high_adj"].notna()
            & data["low_adj"].notna()
            & (data["close_adj"] > 0)
        )

        data["universe_pass"] = (
            market_ok
            & not_st
            & list_age_ok
            & liquidity_ok
            & delist_ok
            & valid_price
        )

        data["trend_pass"] = (
            (data["close_adj"] > data["ma60"])
            & (data["ma20"] > data["ma60"])
        )
        data["breakout_pass"] = data["close_adj"] > data["entry_high_20"]

        data["breakout_strength"] = np.where(
            data["atr20"].notna() & (data["atr20"] > 0),
            (data["close_adj"] - data["entry_high_20"]) / data["atr20"],
            np.nan,
        )

        data["entry_signal_raw"] = (
            data["universe_pass"]
            & data["trend_pass"]
            & data["breakout_pass"]
            & data["atr20"].notna()
        )

        data["entry_rank"] = np.nan
        signal_mask = data["entry_signal_raw"]
        if signal_mask.any():
            ranks = (
                data.loc[signal_mask]
                .groupby("trade_date")["breakout_strength"]
                .rank(method="first", ascending=False)
            )
            data.loc[signal_mask, "entry_rank"] = ranks

        data["entry_selected"] = data["entry_signal_raw"] & (
            data["entry_rank"] <= config.top_n
        )
        data["initial_stop_distance_pct"] = (
            config.stop_atr_multiple * data["atr_pct"]
        )

        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        result = data[
            (data["trade_date"] >= start_ts)
            & (data["trade_date"] <= end_ts)
        ].copy()

        numeric_cols = result.select_dtypes(include=[np.number]).columns
        result[numeric_cols] = result[numeric_cols].replace([np.inf, -np.inf], np.nan)
        result["trade_date"] = result["trade_date"].dt.strftime("%Y-%m-%d")

        return result.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
