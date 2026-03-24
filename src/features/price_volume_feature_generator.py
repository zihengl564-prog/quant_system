from __future__ import annotations

import numpy as np
import pandas as pd


def build_price_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    从标准化日线表生成价格/波动相关特征。
    约定：
    - 输入必须至少包含 ts_code, trade_date
    - 优先使用复权价字段 *_adj；若不存在则回退到原始价字段
    """
    required_cols = {"ts_code", "trade_date"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"build_price_volume_features missing columns: {missing}")

    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    close_col = "close_adj" if "close_adj" in data.columns else "close"
    open_col = "open_adj" if "open_adj" in data.columns else "open"
    high_col = "high_adj" if "high_adj" in data.columns else "high"
    low_col = "low_adj" if "low_adj" in data.columns else "low"

    g = data.groupby("ts_code", group_keys=False)

    prev_close = g[close_col].shift(1)

    feat = data[["ts_code", "trade_date"]].copy()

    # 价格收益类
    feat["feat_ret_1d"] = g[close_col].pct_change(1)
    feat["feat_ret_5d"] = g[close_col].pct_change(5)
    feat["feat_ret_10d"] = g[close_col].pct_change(10)
    feat["feat_ret_20d"] = g[close_col].pct_change(20)

    # 日内收益 / 跳空 / 波动区间
    feat["feat_intraday_ret"] = np.where(
        data[open_col].notna() & (data[open_col] != 0),
        data[close_col] / data[open_col] - 1.0,
        np.nan,
    )
    feat["feat_gap_ret"] = np.where(
        prev_close.notna() & (prev_close != 0),
        data[open_col] / prev_close - 1.0,
        np.nan,
    )
    feat["feat_high_low_range"] = np.where(
        data[low_col].notna() & (data[low_col] != 0),
        data[high_col] / data[low_col] - 1.0,
        np.nan,
    )

    # 滚动波动率（基于 1d 收益）
    ret_1d = feat["feat_ret_1d"]
    feat["feat_volatility_5d"] = (
        ret_1d.groupby(data["ts_code"]).rolling(5).std().reset_index(level=0, drop=True)
    )
    feat["feat_volatility_10d"] = (
        ret_1d.groupby(data["ts_code"]).rolling(10).std().reset_index(level=0, drop=True)
    )
    feat["feat_volatility_20d"] = (
        ret_1d.groupby(data["ts_code"]).rolling(20).std().reset_index(level=0, drop=True)
    )

    # 与中短期均线的偏离（动量/反转都能提供信号）
    ma_5 = g[close_col].transform(lambda s: s.rolling(5).mean())
    ma_10 = g[close_col].transform(lambda s: s.rolling(10).mean())
    ma_20 = g[close_col].transform(lambda s: s.rolling(20).mean())

    feat["feat_close_to_ma5"] = np.where(ma_5.notna() & (ma_5 != 0), data[close_col] / ma_5 - 1.0, np.nan)
    feat["feat_close_to_ma10"] = np.where(ma_10.notna() & (ma_10 != 0), data[close_col] / ma_10 - 1.0, np.nan)
    feat["feat_close_to_ma20"] = np.where(ma_20.notna() & (ma_20 != 0), data[close_col] / ma_20 - 1.0, np.nan)

    # 清理 inf
    numeric_cols = [c for c in feat.columns if c not in ("ts_code", "trade_date")]
    feat[numeric_cols] = feat[numeric_cols].replace([np.inf, -np.inf], np.nan)

    feat["trade_date"] = feat["trade_date"].dt.strftime("%Y-%m-%d")
    return feat