"""Constantes del proyecto EH4000AC-3 Project HCMZ.

Todo lo que define el proyecto (actividades, colores, valores por defecto)
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

PROJECT_NAME = "EH4000AC-3 Project HCMZ"
FLEET = "EH4000AC-3"


# ─── Actividades ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Activity:
    key: str            # identificador interno estable
    gantt_name: str     # nombre tal como aparece en el Gantt
    external: bool = False  # lo ejecuta un contratista externo
    name: str = ""          # nombre visible de las actividades creadas en la app (las fijas usan i18n)


ACTIVITIES: tuple[Activity, ...] = (
    Activity("trailing_lower", "Trailing arm lowering"),
    Activity("trunnion_cap", "Trunnion cap machining", external=True),
    Activity("trunnion_mod", "Trunnion modification", external=True),
    Activity("trailing_assy", "Trailing arm assembly"),
    Activity("high_arch", "High arch reinforcement"),
    Activity("nose_cone", "Nose cone update"),
    Activity("rhs_seat", "RHS seat screw update"),
    Activity("lhs_seat", "LHS seat screw update"),
)
ACTIVITY_BY_KEY = {a.key: a for a in ACTIVITIES}
ACTIVITY_ORDER = {a.key: n for n, a in enumerate(ACTIVITIES)}
EXTERNAL_KEYS = tuple(a.key for a in ACTIVITIES if a.external)

# Actividades generales que el administrador crea desde la app. Se
# leen de los eventos al calcular el proyecto (ver core/project.py).
CUSTOM_ACTIVITIES: dict[str, Activity] = {}


def set_custom_activities(acts: dict[str, Activity]) -> None:
    CUSTOM_ACTIVITIES.clear()
    CUSTOM_ACTIVITIES.update(acts)


def activity(key: str) -> Activity:
    """Actividad fija o creada en la app; una clave desconocida no rompe la vista."""
    return ACTIVITY_BY_KEY.get(key) or CUSTOM_ACTIVITIES.get(key) or Activity(key, key, name=key)


def all_activities() -> list[Activity]:
    return list(ACTIVITIES) + list(CUSTOM_ACTIVITIES.values())


def activity_order(key: str) -> int:
    if key in ACTIVITY_ORDER:
        return ACTIVITY_ORDER[key]
    custom = list(CUSTOM_ACTIVITIES)
    return len(ACTIVITIES) + (custom.index(key) if key in custom else len(custom))

# Todas las actividades registran su avance en % (0–100). Antes, algunas
# actividades se registraban por tareas de SOP; esos registros anteriores se
# siguen leyendo para conservar el avance y las horas-hombre ya cargadas
# (actividad → prefijos de Task ID del catálogo).
LEGACY_TASK_PREFIXES = {
    "high_arch": ("HA",),
    "nose_cone": ("NC",),
    "rhs_seat": ("MF",),
    "lhs_seat": ("LS", "LHS"),
}

# Archivos de origen del catálogo de tareas (solo para seed/build_seed.py)
SOP_FILES = {
    "HA": "23 & 24. High_Arch_Crack_R5_Additional_Welding_Field_Task_Route_EN_JP.xlsx",
    "NC": "4. Nose_Cone_Bracket_Field_Task_Route.xlsx",
    "MF": "18. Main_Frame_Bottom_Plate_RHS_Field_Task_Route_EN_JP.xlsx",
    "LS": "16. LHS_Upright_Seat_Screw_Field_Task_Route_EN_JP.xlsx",
    "LHS": "19. Main_Frame_Bottom_Plate_LHS_Field_Task_Route_EN_JP.xlsx",
}
GANTT_FILE = "Schedule HMCZ Truck modification.xlsx"
ACTIVITIES_SEED = SEED / "activities_seed.csv"
TASKS_CATALOG = SEED / "tasks_catalog.csv"
SOP_NOTES = SEED / "sop_notes.csv"

# ─── Estados ──────────────────────────────────────────────────────────────
TASK_STATUSES = ("not_started", "in_progress", "done", "na")
ACTIVITY_TASK_ID = "_ACTIVITY_"  # registro de avance en % de una actividad

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

# ─── Ready to Work (RTW) ─────────────────────────────────────────────────
# Cierre de cada camión en el Gantt: empieza el día siguiente a su última
# actividad y termina al completar RTW_DAYS días hábiles de lunes a viernes
# (ver core/project.py). Verde más claro que "completed" para distinguirlos.
RTW_DAYS = 2
RTW_COLOR = "#66BB6A"

# ─── Aviso de reemplazo de motor (Engine Service) ────────────────────────
# Camiones que, después de Ready to Work, requieren reemplazo de motor. Se
# muestran con una bandera roja al final de su barra RTW (solo visual: no
# cambia fechas, avance ni estado).
ENGINE_SERVICE_TRUCKS: tuple[str, ...] = ("RD225", "RD226")
ENGINE_FLAG_COLOR = "#C62828"

# ─── Camiones devueltos temporalmente a operación ────────────────────────
# Tramos (inicio, fin, ambos incluidos) en que el camión sale a trabajar y la
# modificación se pausa; se retoma al día siguiente del fin. En el Gantt ese
# tramo de la barra se pinta de otro color con la etiqueta "Returned to
# operation" (solo visual: no cambia fechas, avance ni estado).
OPERATION_PERIODS: dict[str, tuple[tuple[str, str], ...]] = {
    "RD228": (("2026-11-16", "2026-11-27"),),  # en operación desde el 16-nov; vuelve el 28-nov
}
OPERATION_COLOR = "#7E57C2"

# ─── Crédito del equipo de desarrollo ────────────────────────────────────
# Se muestra en la app (encabezado y menú) y en todos los reportes PDF.
DEV_CREDIT = "App developed by HTM Product Support team Canada"
# Bandera de Canadá (proporción 2:1, misma geometría que la bandera oficial), en línea para
# que se vea igual en cualquier equipo; el emoji 🇨🇦 en Windows aparece como "CA".
CANADA_FLAG_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9600 4800" role="img" aria-label="Canada">'
    '<path fill="#D52B1E" d="M0 0h2400l99 99h4602l99-99h2400v4800h-2400l-99-99h-4602l-99 99H0z"/>'
    '<path fill="#FFF" d="M2400 0h4800v4800h-4800zm2490 4430-45-863a95 95 0 0 1 111-98l859 151-116-320a65 65 0 0 1 '
    '20-73l941-762-212-99a65 65 0 0 1-34-79l186-572-542 115a65 65 0 0 1-73-38l-105-247-423 454a65 65 0 0 1-111-57l'
    '204-1052-327 189a65 65 0 0 1-91-27l-332-652-332 652a65 65 0 0 1-91 27l-327-189 204 1052a65 65 0 0 1-111 57l'
    '-423-454-105 247a65 65 0 0 1-73 38l-542-115 186 572a65 65 0 0 1-34 79l-212 99 941 762a65 65 0 0 1 20 73l-116 '
    '320 859-151a95 95 0 0 1 111 98l-45 863z"/></svg>'
)
