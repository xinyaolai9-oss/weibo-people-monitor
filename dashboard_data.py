"""Pure data preparation helpers for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd


def prepare_records(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    # Supabase returns valid ISO 8601 timestamps with or without fractional
    # seconds. Pandas 2 parses a Series using one inferred format by default,
    # so mixed historical/live rows must opt into per-value ISO parsing.
    frame["observed_at"] = pd.to_datetime(
        frame["observed_at"], format="mixed", utc=True
    )
    frame["score"] = pd.to_numeric(frame["score"])
    frame["score_approx"] = frame["score_approx"].astype(bool)
    return frame
