from __future__ import annotations

import numpy as np
import pandas as pd


def _cross_section_rank_pct(series: pd.Series) -> pd.Series:
    """
    同一交易日横截面百分位排名，范围约 (0, 1]。
    """
    return series.rank(method="average", pct=True)


def _to_decile(rank_pct: pd.Series) -> pd.Series:
    """
    将横截面百分位映射到 0~9 十档标签，便于后续 ranking objective 使用。
    """
    decile = np.floor(rank_pct * 10).clip(0, 9)
    return decile.astype("Int64")


def build_return_labels(
    df: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 5),
) -> pd.DataFrame:
    """
    生成未来收益标签：
    - label_ret_{h}d_fwd
    - label_ret_{h}d_fwd_rank_pct
    - label_ret_{h}d_fwd_decile
    """
    required_cols = {"ts_code", "trade_date"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"build_return_labels missing columns: {missing}")

    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    close_col = "close_adj" if "close_adj" in data.columns else "close"
    g = data.groupby("ts_code", group_keys=False)

    label = data[["ts_code", "trade_date"]].copy()

    for h in horizons:
        future_close = g[close_col].shift(-h)
        raw_col = f"label_ret_{h}d_fwd"
        rank_col = f"label_ret_{h}d_fwd_rank_pct"
        decile_col = f"label_ret_{h}d_fwd_decile"

        label[raw_col] = np.where(
            data[close_col].notna() & (data[close_col] != 0) & future_close.notna(),
            future_close / data[close_col] - 1.0,
            np.nan,
        )

        label[rank_col] = label.groupby("trade_date")[raw_col].transform(_cross_section_rank_pct)
        label[decile_col] = _to_decile(label[rank_col])

    label["trade_date"] = label["trade_date"].dt.strftime("%Y-%m-%d")
    return label