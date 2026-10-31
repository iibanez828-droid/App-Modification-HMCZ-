"""Catálogo de tareas del sistema anterior (generado por seed/build_seed.py).

Solo se usa para conservar el avance registrado por tareas antes del registro en %."""

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

