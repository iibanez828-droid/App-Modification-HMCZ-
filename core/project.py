"""Estado actual del proyecto, calculado a partir del plan original y los eventos.

Reglas de negocio (todas en este archivo):
- Avance de una actividad = porcentaje (0–100) que registra el supervisor.
- Si una actividad todavía no tiene registro en %, pero tiene registros por
  tareas del sistema anterior, se conserva ese avance: tareas terminadas ÷
  tareas aplicables (las marcadas N/A no cuentan).
- Mientras una actividad no tenga registros, se usa el avance importado del Gantt.
- Avance de un camión = promedio simple de sus actividades.
- Días de trabajo propio = días hábiles en que hay al menos una actividad
  propia programada (no cuenta la espera por el trabajo externo de trunnion).
- Visibilidad: un camión aparece cuando faltan `lookahead_days` días o menos
  para su inicio, o cuando ya empezó.
- Grupo: los camiones del plan original del Gantt forman la flota ("fleet");
  los que agrega el administrador en la app son máquinas en operación
  ("operating") y tienen su propio Gantt. Las métricas son las mismas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core import config
from core.catalog import load_catalog
from core.events import read_baseline, read_events, read_settings
from core.workdays import WorkCalendar

VISIBLE_STATUSES = ("in_progress", "overdue", "upcoming", "no_dates")


def _d(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value or (isinstance(value, float) and value != value):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _f(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


@dataclass
class Project:
    settings: dict
    today: date
    activities: pd.DataFrame          # una fila por camión × actividad
    trucks: pd.DataFrame              # una fila por camión
    tasks: pd.DataFrame               # estado de las tareas registradas con el sistema anterior
    task_log: pd.DataFrame            # todas las actualizaciones registradas
    delays: pd.DataFrame              # notas de atraso de los supervisores
    comments: pd.DataFrame            # comentarios por actividad
    plan_log: pd.DataFrame            # cambios de fechas del administrador
    acks: dict[str, dict] = field(default_factory=dict)
    truck_cal: dict[str, WorkCalendar] = field(default_factory=dict)
    custom_acts: dict[str, config.Activity] = field(default_factory=dict)  # actividades creadas en la app

    # ── Consultas frecuentes ────────────────────────────────────────────
    def calendar(self, truck: str) -> WorkCalendar:
        return self.truck_cal.get(truck) or WorkCalendar.build(False, False, self.settings.get("holidays", []))

    def truck_row(self, truck: str) -> pd.Series:
        return self.trucks.set_index("truck").loc[truck]

    def truck_activities(self, truck: str) -> pd.DataFrame:
        return self.activities[self.activities.truck == truck].sort_values("order")

    def group_trucks(self, group: str) -> list[str]:
        return self.trucks[self.trucks.group == group].truck.tolist()

    def visible_trucks(self) -> list[str]:
        return self.trucks[self.trucks.status.isin(VISIBLE_STATUSES)].truck.tolist()

    def alerts(self) -> list[dict]:
        """Alertas para el administrador, de la más a la menos urgente."""
        out: list[dict] = []
        for _, tr in self.trucks.iterrows():
            if tr.status not in VISIBLE_STATUSES:
                continue
            acts = self.truck_activities(tr.truck)
            ext = acts[acts.external & (acts.progress < 1)]
            if len(ext) and tr.truck not in self.acks:
                out.append({"type": "trunnion", "truck": tr.truck, "acts": ext.to_dict("records")})
            missing = acts[(acts.fc_start.isna() | acts.fc_end.isna()) & (acts.progress < 1)]
            if len(missing):
                out.append({"type": "missing_dates", "truck": tr.truck, "acts": missing.to_dict("records")})
            if tr.status == "overdue":
                out.append({"type": "overdue", "truck": tr.truck, "days": tr.delay_wd})
            if tr.over_limit:
                out.append({"type": "over_limit", "truck": tr.truck, "days": tr.work_days})
            late = acts[(acts.status == "overdue")]
            for _, a in late.iterrows():
                out.append({"type": "act_overdue", "truck": tr.truck, "act": a.act_key, "end": a.fc_end})
            idle = acts[acts.fc_start.notna() & acts.fc_end.notna() & (acts.work_days == 0) & (acts.progress < 1)]
            for _, a in idle.iterrows():
                out.append({"type": "non_workday", "truck": tr.truck, "act": a.act_key, "end": a.fc_end})
        order = {"trunnion": 0, "missing_dates": 1, "overdue": 2, "act_overdue": 3, "non_workday": 4, "over_limit": 5}
        return sorted(out, key=lambda a: order[a["type"]])


def today_in(settings: dict) -> date:
    try:
        tz = ZoneInfo(settings.get("timezone") or "UTC")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


def _activity_status(progress: float, start: date | None, end: date | None, today: date) -> str:
    if progress >= 1:
        return "completed"
    if start is None or end is None:
        return "no_dates"
    if today > end:
        return "overdue"
    if progress > 0 or today >= start:
        return "in_progress"
    return "not_started"


def _new_row(truck: str, act: str, start: str = "", end: str = "") -> dict:
    return {"truck": truck, "act_key": act, "base_start": start or "", "base_end": end or "", "assigned_to": "",
            "imported_progress": "", "fc_start": start or "", "fc_end": end or ""}


def _apply_scope(ev: dict, rows: dict, task_sel: dict, custom: dict) -> None:
    """Cambios de alcance del administrador:
    - new_activity: crea una actividad general y la agrega a `trucks`.
    - add_activity: agrega una actividad existente a un camión.
    - remove_activity: quita una actividad de un camión (su historial se conserva).
    - set_tasks: (eventos anteriores) tareas incluidas en una actividad de un camión.
    - add_truck: agrega un camión nuevo con sus actividades.
    - remove_truck: quita el camión del plan (su historial se conserva)."""
    op, truck = ev.get("op"), ev.get("truck", "")

    def add(truck: str, act: str, tasks=None, start: str = "", end: str = "") -> None:
        if not truck or not act or (truck, act) in rows:
            return
        rows[(truck, act)] = _new_row(truck, act, start, end)
        task_sel.pop((truck, act), None)
        if tasks is not None and act in config.LEGACY_TASK_PREFIXES:
            task_sel[(truck, act)] = list(tasks)

    if op == "new_activity" and ev.get("act") and ev.get("name"):
        custom[ev["act"]] = config.Activity(ev["act"], ev["name"], bool(ev.get("external")), name=ev["name"])
        for tr in ev.get("trucks", []):
            add(tr, ev["act"], None, ev.get("start", ""), ev.get("end", ""))
    elif op == "add_activity":
        add(truck, ev.get("act"), ev.get("tasks"), ev.get("start", ""), ev.get("end", ""))
    elif op == "remove_activity":
        rows.pop((truck, ev.get("act")), None)
        task_sel.pop((truck, ev.get("act")), None)
    elif op == "set_tasks" and (truck, ev.get("act")) in rows:
        task_sel[(truck, ev["act"])] = list(ev.get("tasks", []))
    elif op == "remove_truck":
        for key in [k for k in rows if k[0] == truck]:
            rows.pop(key)
            task_sel.pop(key, None)
    elif op == "add_truck" and truck and not any(k[0] == truck for k in rows):
        for a in ev.get("acts", []):
            add(truck, a.get("act"), a.get("tasks"), a.get("start", ""), a.get("end", ""))


def build_project(snapshot: Mapping[str, bytes], today: date | None = None) -> Project:
    events = read_events(snapshot)
    settings = read_settings(snapshot, events["settings"])
    today = today or today_in(settings)
    lookahead = int(settings.get("lookahead_days", 14))
    max_wd = int(settings.get("max_working_days", 5))
    holidays = settings.get("holidays", [])

    # ── Plan: original + cambios del administrador ──────────────────────
    # Los cambios de alcance (scope) y de fechas (plan) se aplican en orden
    # cronológico: una actividad agregada después puede recibir fechas.
    base = read_baseline(snapshot)
    fleet = set(base.truck)
    cols = list(base.columns) + ["fc_start", "fc_end"]
    rows: dict[tuple[str, str], dict] = {}
    for r in base.to_dict("records"):
        rows[(r["truck"], r["act_key"])] = {**r, "fc_start": r["base_start"], "fc_end": r["base_end"]}
    task_sel: dict[tuple[str, str], list[str]] = {}  # tareas incluidas, sistema anterior (sin entrada = todas)
    custom: dict[str, config.Activity] = {}
    weekend: dict[str, dict] = {}
    plan_rows = []
    for ev in sorted(events["scope"] + events["plan"], key=lambda e: e["ts"]):
        if ev["kind"] == "scope":
            _apply_scope(ev, rows, task_sel, custom)
            continue
        truck = ev.get("truck")
        if "weekend" in ev:
            weekend[truck] = ev["weekend"]
        for ch in ev.get("changes", []):
            row = rows.get((truck, ch.get("act")))
            if row is None:
                continue
            for fld in ("fc_start", "fc_end", "assigned_to"):
                if fld in ch:
                    row[fld] = ch[fld] or ""
            for fld in ("base_start", "base_end"):  # solo se completa si estaba vacía
                if ch.get(fld) and not row[fld]:
                    row[fld] = ch[fld]
            plan_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": truck, "act_key": ch.get("act"),
                              "fc_start": ch.get("fc_start", ""), "fc_end": ch.get("fc_end", ""),
                              "reason": ev.get("reason", "")})
    config.set_custom_activities(custom)
    acts = pd.DataFrame(list(rows.values()), columns=cols).fillna("")
    idx = {(r.truck, r.act_key): i for i, r in acts.iterrows()}

    truck_cal = {
        t: WorkCalendar.build(weekend.get(t, {}).get("sat", False), weekend.get(t, {}).get("sun", False), holidays)
        for t in acts.truck.unique()
    }

    # ── Registros de tareas: el último por tarea manda ──────────────────
    log_rows, comment_rows = [], []
    for ev in events["task"]:
        for up in ev.get("updates", []):
            log_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": ev.get("truck"), "act_key": ev.get("act"), **up})
        if (ev.get("comment") or "").strip():
            comment_rows.append({"ts": ev["ts"], "user": ev["user"], "truck": ev.get("truck"),
                                 "act_key": ev.get("act"), "text": ev["comment"].strip()})
    log_cols = ["ts", "user", "truck", "act_key", "task_id", "status", "progress", "actual_mh", "supervisor",
                "technicians", "date", "qc_result", "remarks"]
    task_log = pd.DataFrame(log_rows, columns=log_cols) if log_rows else pd.DataFrame(columns=log_cols)
    latest = task_log.drop_duplicates(["truck", "act_key", "task_id"], keep="last")

    # Estado de las tareas registradas con el sistema anterior (solo se usan
    # para conservar el avance cargado antes del registro en %)
    cat = load_catalog()
    task_frames = []
    for (truck, act_key) in idx:
        sops = config.LEGACY_TASK_PREFIXES.get(act_key, ())
        if not sops:
            continue
        t = cat[cat.sop.isin(sops)].copy()
        if (truck, act_key) in task_sel:
            t = t[t.task_id.isin(task_sel[(truck, act_key)])]
        t["sop_order"] = t.sop.map({s: n for n, s in enumerate(sops)})
        t = t.sort_values(["sop_order", "seq"])
        t.insert(0, "truck", truck)
        t.insert(1, "act_key", act_key)
        task_frames.append(t)
    tasks = pd.concat(task_frames, ignore_index=True) if task_frames else cat.iloc[0:0].assign(truck="", act_key="")
    rec = latest[latest.task_id != config.ACTIVITY_TASK_ID].drop(columns=["progress"])
    tasks = tasks.merge(rec, on=["truck", "act_key", "task_id"], how="left")
    tasks["status"] = tasks["status"].fillna("not_started")
    tasks["qc_result"] = tasks["qc_result"].where(tasks["qc_result"].notna() & (tasks["qc_result"] != ""), "pending")
    tasks["actual_mh"] = pd.to_numeric(tasks["actual_mh"], errors="coerce")
    for col in ("supervisor", "technicians", "date", "remarks", "user", "ts"):
        tasks[col] = tasks[col].fillna("")

    # ── Avance por actividad ────────────────────────────────────────────
    act_manual = latest[latest.task_id == config.ACTIVITY_TASK_ID].set_index(["truck", "act_key"])
    has_task_rec = set(map(tuple, rec[["truck", "act_key"]].drop_duplicates().values))
    progress, has_records, mh = [], [], []
    for _, a in acts.iterrows():
        key = (a.truck, a.act_key)
        if key in act_manual.index:
            row = act_manual.loc[key]
            p = (_f(row.progress) or 0.0) / 100
            has_records.append(True)
            mh.append(_f(row.actual_mh) or 0.0)
        elif key in has_task_rec:
            t = tasks[(tasks.truck == a.truck) & (tasks.act_key == a.act_key)]
            applicable = t[t.status != "na"]
            p = (applicable.status == "done").sum() / len(applicable) if len(applicable) else 1.0
            has_records.append(True)
            mh.append(float(t.actual_mh.sum(skipna=True)))
        else:
            p = _f(a.imported_progress) or 0.0
            has_records.append(False)
            mh.append(0.0)
        progress.append(min(max(p, 0.0), 1.0))
    acts["progress"] = progress
    acts["has_records"] = has_records
    acts["actual_mh"] = mh
    acts["order"] = acts.act_key.map(config.activity_order)
    acts["external"] = acts.act_key.map(lambda k: config.activity(k).external)
    for col in ("base_start", "base_end", "fc_start", "fc_end"):
        acts[col] = acts[col].map(_d)
    acts["status"] = [
        _activity_status(r.progress, r.fc_start, r.fc_end, today) for r in acts.itertuples()
    ]
    acts["delay_wd"] = [truck_cal[r.truck].delay(r.base_end, r.fc_end) for r in acts.itertuples()]
    acts["work_days"] = [truck_cal[r.truck].count(r.fc_start, r.fc_end) for r in acts.itertuples()]

    # ── Resumen por camión ──────────────────────────────────────────────
    truck_rows = []
    for truck, g in acts.groupby("truck", sort=True):
        cal = truck_cal[truck]
        starts = [d for d in g.fc_start if d]
        ends = [d for d in g.fc_end if d]
        bends = [d for d in g.base_end if d]
        start, end = (min(starts) if starts else None), (max(ends) if ends else None)
        base_end = max(bends) if bends else None
        p = float(g.progress.mean())
        # Días hábiles con trabajo propio programado (unión de rangos)
        days: set[date] = set()
        for r in g[~g.external].itertuples():
            if r.fc_start and r.fc_end:
                d = r.fc_start
                while d <= r.fc_end:
                    if cal.is_workday(d):
                        days.add(d)
                    d += timedelta(days=1)
        if p >= 1:
            status = "completed"
        elif start is None:
            status = "no_dates"
        elif end and today > end:
            status = "overdue"
        elif today >= start or p > 0:
            status = "in_progress"
        elif (start - today).days <= lookahead:
            status = "upcoming"
        else:
            status = "future"
        truck_rows.append({
            "truck": truck, "start": start, "end": end, "base_end": base_end,
            "progress": p, "status": status, "work_days": len(days),
            "over_limit": len(days) > max_wd and p < 1,
            "delay_wd": cal.delay(base_end, end) if p < 1 else 0,
            "actual_mh": float(g.actual_mh.sum()),
            "sat": cal.saturday, "sun": cal.sunday,
            "days_to_start": (start - today).days if start else None,
            "group": "fleet" if truck in fleet else "operating",
        })
    trucks = pd.DataFrame(truck_rows)

    # ── Atrasos, comentarios y alertas atendidas ────────────────────────
    delay_cols = ["ts", "user", "truck", "act", "category", "impact_days", "description"]
    delays = pd.DataFrame([{c: ev.get(c, "") for c in delay_cols} for ev in events["delay"]], columns=delay_cols)
    comments = pd.DataFrame(comment_rows, columns=["ts", "user", "truck", "act_key", "text"])
    plan_log = pd.DataFrame(plan_rows, columns=["ts", "user", "truck", "act_key", "fc_start", "fc_end", "reason"])
    acks = {ev["truck"]: ev for ev in events["ack"] if ev.get("truck")}

    return Project(settings=settings, today=today, activities=acts, trucks=trucks, tasks=tasks,
                   task_log=task_log, delays=delays, comments=comments, plan_log=plan_log,
                   acks=acks, truck_cal=truck_cal, custom_acts=custom)
