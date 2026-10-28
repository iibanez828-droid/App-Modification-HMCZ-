"""Catálogo de tareas de los SOP (generado por seed/build_seed.py)."""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from core import config


@lru_cache(maxsize=1)
def load_catalog() -> pd.DataFrame:
    df = pd.read_csv(config.TASKS_CATALOG, dtype={"task_id": str, "sop": str})
    for col in ("stage", "desc_en", "desc_jp", "instr_en", "instr_jp", "drawing", "predecessor",
                "qc_gate", "qc_note"):
        df[col] = df[col].fillna("").astype(str)
    df["conditional"] = df["conditional"].astype(str).str.lower().eq("true")
    return df


@lru_cache(maxsize=1)
def load_notes() -> pd.DataFrame:
    return pd.read_csv(config.SOP_NOTES, dtype=str).fillna("")


def tasks_for(act_key: str) -> pd.DataFrame:
    """Tareas de una actividad, en el orden de sus SOP."""
    sops = config.activity(act_key).sops
    cat = load_catalog()
    parts = [cat[cat.sop == s].sort_values("seq") for s in sops]
    return pd.concat(parts, ignore_index=True) if parts else cat.iloc[0:0]
