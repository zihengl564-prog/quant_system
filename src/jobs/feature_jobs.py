from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.features.feature_panel_builder import FeaturePanelBuilder


def build_feature_label_job(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> dict:
    builder = FeaturePanelBuilder(db_path=db_path)
    return builder.build_and_persist(start_date=start_date, end_date=end_date)