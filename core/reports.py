"""Reportes consolidados en Excel y CSV (para descargar o publicar en la rama
`data`, carpeta reports/)."""

from __future__ import annotations

import io

import pandas as pd

from core import config
from core.project import Project


def _act(key: str) -> str:
    return config.activity(key).gantt_name if key else ""


def truck_summary(p: Project) -> pd.DataFrame:
    df = p.trucks.copy()
    return pd.DataFrame({
        "Truck": df.truck, "Status": df.status, "Progress %": (df.progress * 100).round(1),
        "Forecast start": df.start, "Forecast end": df.end, "Original end": df.base_end,
        "Delay (working days)": df.delay_wd, "Own-work days": df.work_days,
        "Over limit": df.over_limit, "Actual MH": df.actual_mh.round(1),
        "Saturday": df.sat, "Sunday": df.sun,
    })


def activity_table(p: Project) -> pd.DataFrame:
    a = p.activities.sort_values(["truck", "order"])
    return pd.DataFrame({
        "Truck": a.truck, "Activity": a.act_key.map(_act), "External": a.external,
        "SOP": a.act_key.map(lambda k: " + ".join(config.activity(k).sops)),
        "Status": a.status, "Progress %": (a.progress * 100).round(1),
        "Original start": a.base_start, "Original end": a.base_end,
        "Forecast start": a.fc_start, "Forecast end": a.fc_end,
        "Delay (working days)": a.delay_wd, "Actual MH": a.actual_mh.round(1),
        "Assigned to": a.assigned_to, "Imported from Gantt": ~a.has_records,
    })


def task_table(p: Project) -> pd.DataFrame:
    t = p.tasks
    return pd.DataFrame({
        "Truck": t.truck, "Activity": t.act_key.map(_act), "SOP": t.sop, "Task ID": t.task_id,
        "Stage": t.stage, "Task (EN)": t.desc_en, "Task (JP)": t.desc_jp, "QC gate": t.qc_gate,
        "Conditional": t.conditional, "Status": t.status, "Actual MH": t.actual_mh,
        "Supervisor": t.supervisor, "Technicians": t.technicians, "Date": t.date,
        "QC result": t.qc_result, "Remarks": t.remarks, "Updated by": t.user, "Updated (UTC)": t.ts,
    })


def build_excel(p: Project) -> bytes:
    sheets = {
        "Trucks": truck_summary(p),
        "Activities": activity_table(p),
        "SOP tasks": task_table(p),
        "Task log": p.task_log.assign(act_key=p.task_log.act_key.map(_act)),
        "Delay notes": p.delays.assign(act=p.delays.act.map(_act)),
        "Comments": p.comments.assign(act_key=p.comments.act_key.map(_act)),
        "Plan changes": p.plan_log.assign(act_key=p.plan_log.act_key.map(_act)),
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        head = xw.book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1A1A1A", "border": 1})
        info = pd.DataFrame({"": [config.PROJECT_NAME, f"Generated: {p.today.isoformat()}",
                                  f"Project progress: {p.trucks.progress.mean() * 100:.1f}%"]})
        info.to_excel(xw, sheet_name="Summary", index=False, header=False)
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for c, col in enumerate(df.columns):
                ws.write(0, c, col, head)
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.set_column(c, c, min(width, 50))
            ws.freeze_panes(1, 0)
            if len(df.columns):
                ws.autofilter(0, 0, max(len(df), 1), len(df.columns) - 1)
    return buf.getvalue()


def status_csv(p: Project) -> bytes:
    return activity_table(p).to_csv(index=False).encode("utf-8-sig")
