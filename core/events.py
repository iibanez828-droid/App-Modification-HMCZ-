"""Registro de cambios (eventos).

Cada acción de un usuario se guarda como un archivo JSON nuevo, que nunca se
modifica después:

    log/<tipo>/<AAAA-MM>/<fecha-hora>_<camión>_<usuario>.json

Ventajas: dos personas pueden guardar al mismo tiempo sin conflictos, queda el
historial completo (quién cambió qué y cuándo) y el estado actual se calcula
leyendo los eventos en orden.

Tipos: task (avance de tareas), delay (notas de atraso), plan (fechas del
pronóstico y días de fin de semana), ack (alerta de trunnion atendida),
settings (configuración general), scope (camiones y actividades
que el administrador agrega o quita del plan).
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone

import pandas as pd

from core import config
from storage.base import Store

KINDS = ("task", "delay", "plan", "ack", "settings", "scope")
BASELINE_PATH = "plan/baseline.csv"
SETTINGS_PATH = "plan/settings.json"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "x"


def write_event(store: Store, kind: str, payload: dict, user: str, subject: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(kind)
    now = datetime.now(timezone.utc)
    event = {"kind": kind, "ts": now.isoformat(timespec="microseconds"), "user": user, **payload}
    path = f"log/{kind}/{now:%Y-%m}/{now:%Y%m%dT%H%M%S%f}Z_{_slug(subject or kind)}_{_slug(user)}.json"
    message = f"[app] {kind} · {subject or '-'} · por {user}"
    store.write(path, json.dumps(event, ensure_ascii=False, indent=1).encode(), message)
    return event


def read_events(snapshot: Mapping[str, bytes]) -> dict[str, list[dict]]:
    """Eventos válidos agrupados por tipo y ordenados por fecha."""
    out: dict[str, list[dict]] = {k: [] for k in KINDS}
    for path, raw in snapshot.items():
        if not (path.startswith("log/") and path.endswith(".json")):
            continue
        try:
            ev = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue  # un archivo dañado no debe tumbar la app
        if isinstance(ev, dict) and ev.get("kind") in out and ev.get("ts"):
            out[ev["kind"]].append(ev)
    for evs in out.values():
        evs.sort(key=lambda e: e["ts"])
    return out


# ─── Inicialización de la rama de datos ───────────────────────────────────
def is_initialized(snapshot: Mapping[str, bytes]) -> bool:
    return BASELINE_PATH in snapshot


def initialize(store: Store, user: str) -> None:
    """Copia el plan original del Gantt (seed) a la rama de datos."""
    baseline = pd.read_csv(config.ACTIVITIES_SEED, dtype=str).fillna("")
    buf = io.StringIO()
    baseline.to_csv(buf, index=False)
    store.write(BASELINE_PATH, buf.getvalue().encode(), f"[app] plan original desde el Gantt · por {user}")
    store.write(SETTINGS_PATH, json.dumps(config.DEFAULT_SETTINGS, indent=2).encode(),
                f"[app] configuración inicial · por {user}")


def read_baseline(snapshot: Mapping[str, bytes]) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(snapshot[BASELINE_PATH]), dtype=str).fillna("")


def read_settings(snapshot: Mapping[str, bytes], events: list[dict]) -> dict:
    settings = dict(config.DEFAULT_SETTINGS)
    raw = snapshot.get(SETTINGS_PATH)
    if raw:
        try:
            settings.update(json.loads(raw))
        except ValueError:
            pass
    for ev in events:
        settings.update(ev.get("values", {}))
    return settings
