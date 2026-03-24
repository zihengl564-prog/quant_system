from __future__ import annotations

import numpy as np
import pandas as pd


def build_liquidity_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    从标准化日线表生成成交/流动性/规模类特征。
    """
    required_cols = {"ts_code", "trade_date"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"build_liquidity_features missing columns: {missing}")

    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    g = data.groupby("ts_code", group_keys=False)

    feat = data[["ts_code", "trade_date"]].copy()

    # 对数规模
    if "vol" in data.columns:
        feat["feat_log_vol"] = np.log1p(data["vol"].clip(lower=0))
        vol_ma5 = g["vol"].transform(lambda s: s.rolling(5).mean())
        feat["feat_vol_to_ma5"] = np.where(vol_ma5.notna() & (vol_ma5 != 0), data["vol"] / vol_ma5, np.nan)

    if "amount" in data.columns:
        feat["feat_log_amount"] = np.log1p(data["amount"].clip(lower=0))
        amount_ma5 = g["amount"].transform(lambda s: s.rolling(5).mean())
        feat["feat_amount_to_ma5"] = np.where(amount_ma5.notna() & (amount_ma5 != 0), data["amount"] / amount_ma5, np.nan)

    # 换手与量比
    if "turnover_rate" in data.columns:
        feat["feat_turnover_rate"] = data["turnover_rate"]
        tr_ma5 = g["turnover_rate"].transform(lambda s: s.rolling(5).mean())
        feat["feat_turnover_to_ma5"] = np.where(tr_ma5.notna() & (tr_ma5 != 0), data["turnover_rate"] / tr_ma5, np.nan)

    if "turnover_rate_f" in data.columns:
        feat["feat_turnover_rate_f"] = data["turnover_rate_f"]

    if "volume_ratio" in data.columns:
        feat["feat_volume_ratio"] = data["volume_ratio"]

    # 市值相关
    if "total_mv" in data.columns:
        feat["feat_log_total_mv"] = np.log1p(data["total_mv"].clip(lower=0))

    if "circ_mv" in data.columns:
        feat["feat_log_circ_mv"] = np.log1p(data["circ_mv"].clip(lower=0))
        if "total_mv" in data.columns:
            feat["feat_circ_to_total_mv"] = np.where(
                data["total_mv"].notna() & (data["total_mv"] != 0),
                data["circ_mv"] / data["total_mv"],
                np.nan,
            )

    # 估值因子先直接带原值，后续可做行业中性化/去极值
    for col in ["pe_ttm", "pb", "ps_ttm"]:
        if col in data.columns:
            feat[f"feat_{col}"] = data[col]

    numeric_cols = [c for c in feat.columns if c not in ("ts_code", "trade_date")]
    feat[numeric_cols] = feat[numeric_cols].replace([np.inf, -np.inf], np.nan)

    feat["trade_date"] = feat["trade_date"].dt.strftime("%Y-%m-%d")
    return feat