"""Constantes del proyecto HMCZ Truck Modification.

Todo lo que define el proyecto (actividades, SOP, colores, valores por defecto)
vive aquí para que cambiarlo sea editar un solo archivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SEED = ROOT / "seed"
LOGO_PATH = ASSETS / "landcros_logo.webp"
TRUCK_IMAGE_PATH = ASSETS / "eh5000.webp"

PROJECT_NAME = "HMCZ Truck Modification"
FLEET = "EH5000"


# ─── Actividades ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Activity:
    key: str            # identificador interno estable
    gantt_name: str     # nombre tal como aparece en el Gantt
    sops: tuple[str, ...]  # prefijos de Task ID de los SOP asociados (vacío = sin SOP)
    external: bool = False  # lo ejecuta un contratista externo
    name: str = ""          # nombre visible de las actividades creadas en la app (las fijas usan i18n)


ACTIVITIES: tuple[Activity, ...] = (
    Activity("trailing_lower", "Trailing arm lowering", ()),
    Activity("trunnion_cap", "Trunnion cap machining", (), external=True),
    Activity("trunnion_mod", "Trunnion modification", (), external=True),
    Activity("trailing_assy", "Trailing arm assembly", ()),
    Activity("high_arch", "High arch reinforcement", ("HA",)),
    Activity("nose_cone", "Nose cone update", ("NC",)),
    Activity("rhs_seat", "RHS seat screw update", ("MF",)),
    Activity("lhs_seat", "LHS seat screw update", ("LS", "LHS")),
)
ACTIVITY_BY_KEY = {a.key: a for a in ACTIVITIES}
ACTIVITY_ORDER = {a.key: n for n, a in enumerate(ACTIVITIES)}
EXTERNAL_KEYS = tuple(a.key for a in ACTIVITIES if a.external)

# Actividades generales (sin SOP) que el administrador crea desde la app. Se
# leen de los eventos al calcular el proyecto (ver core/project.py).
CUSTOM_ACTIVITIES: dict[str, Activity] = {}


def set_custom_activities(acts: dict[str, Activity]) -> None:
    CUSTOM_ACTIVITIES.clear()
    CUSTOM_ACTIVITIES.update(acts)


def activity(key: str) -> Activity:
    """Actividad fija o creada en la app; una clave desconocida no rompe la vista."""
    return ACTIVITY_BY_KEY.get(key) or CUSTOM_ACTIVITIES.get(key) or Activity(key, key, (), name=key)


def all_activities() -> list[Activity]:
    return list(ACTIVITIES) + list(CUSTOM_ACTIVITIES.values())


def activity_order(key: str) -> int:
    if key in ACTIVITY_ORDER:
        return ACTIVITY_ORDER[key]
    custom = list(CUSTOM_ACTIVITIES)
    return len(ACTIVITIES) + (custom.index(key) if key in custom else len(custom))

# SOP: prefijo de Task ID → archivo de origen en seed/
SOP_FILES = {
    "HA": "23 & 24. High_Arch_Crack_R5_Additional_Welding_Field_Task_Route_EN_JP.xlsx",
    "NC": "4. Nose_Cone_Bracket_Field_Task_Route.xlsx",
    "MF": "18. Main_Frame_Bottom_Plate_RHS_Field_Task_Route_EN_JP.xlsx",
    "LS": "16. LHS_Upright_Seat_Screw_Field_Task_Route_EN_JP.xlsx",
    "LHS": "19. Main_Frame_Bottom_Plate_LHS_Field_Task_Route_EN_JP.xlsx",
}
SOP_TITLES = {
    "HA": "SOP 23 & 24 · High Arch Crack R5 Additional Welding",
    "NC": "SOP 4 · Nose Cone Bracket",
    "MF": "SOP 18 · Main Frame Bottom Plate RHS",
    "LS": "SOP 16 · LHS Upright Seat Screw",
    "LHS": "SOP 19 · Main Frame Bottom Plate LHS",
}
GANTT_FILE = "Schedule HMCZ Truck modification.xlsx"
ACTIVITIES_SEED = SEED / "activities_seed.csv"
TASKS_CATALOG = SEED / "tasks_catalog.csv"
SOP_NOTES = SEED / "sop_notes.csv"

# ─── Estados ──────────────────────────────────────────────────────────────
TASK_STATUSES = ("not_started", "in_progress", "done", "na")
QC_RESULTS = ("pending", "accepted", "rejected")
ACTIVITY_TASK_ID = "_ACTIVITY_"  # registro de avance manual de actividades sin SOP

DELAY_CATEGORIES = (
    "materials", "manpower", "equipment", "external", "qc", "engineering",
    "weather", "safety", "other",
)

# ─── Valores por defecto (editables por el administrador) ────────────────
DEFAULT_SETTINGS = {
    "lookahead_days": 14,       # días calendario antes del inicio en que un camión se vuelve visible
    "max_working_days": 5,      # días hábiles permitidos por camión (trabajo propio)
    "timezone": "Africa/Lusaka",
    "holidays": [],             # lista de fechas ISO sin trabajo
}

ROLES = ("admin", "supervisor")
LANGUAGES = {"en": "English", "ja": "日本語"}

# ─── Colores (identidad LANDCROS, igual que el dashboard de referencia) ───
ORANGE = "#FF6B00"
BLACK = "#1A1A1A"
GREY = "#888888"
LIGHT = "#F7F7F7"
STATUS_COLORS = {
    "completed": "#2E7D32",
    "in_progress": ORANGE,
    "overdue": "#C62828",
    "upcoming": "#1565C0",
    "future": "#9E9E9E",
    "no_dates": "#6D4C41",
}
