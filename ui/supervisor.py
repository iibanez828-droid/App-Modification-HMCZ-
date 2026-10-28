"""Vista del supervisor: registrar el avance de tareas, horas-hombre, personal,
comentarios y notas de atraso."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from core import config
from core.catalog import load_notes
from core.events import write_event
from ui.common import (Ctx, act_name, fmt_date, fmt_pct, fmt_ts, note, pill_html, safe_write, section,
                       truck_badge, truck_label)

EDITABLE = ["status", "actual_mh", "supervisor", "technicians", "date", "qc_result", "remarks"]


def _nonce(key: str) -> int:
    return st.session_state.setdefault(f"nonce_{key}", 0)


def _bump(key: str) -> None:
    st.session_state[f"nonce_{key}"] = _nonce(key) + 1


def _to_date(value) -> date | None:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):  # incluye pd.Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _mh(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, 2)


# ─── Página ───────────────────────────────────────────────────────────────
def render(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    trucks = p.visible_trucks()
    if not trucks:
        note(t("sup_no_trucks", days=p.settings.get("lookahead_days", 14)))
        return

    c1, c2 = st.columns([1, 2])
    truck = c1.selectbox(t("truck"), trucks, key="sup_truck", format_func=lambda x: truck_label(ctx, x))
    acts = p.truck_activities(truck)
    act_key = c2.selectbox(
        t("activity"), acts.act_key.tolist(), key=f"sup_act_{truck}",
        format_func=lambda k: f"{act_name(t, k)} · {fmt_pct(float(acts.set_index('act_key').at[k, 'progress']))}",
    )
    truck_badge(ctx, truck)
    activity_editor(ctx, truck, act_key, acts)
    st.write("")
    _delay_form(ctx, truck, acts)
    history(ctx, truck, act_key)


def activity_editor(ctx: Ctx, truck: str, act_key: str, acts: pd.DataFrame) -> None:
    """Encabezado y registro de avance de una actividad (también lo usa el administrador)."""
    act = acts.set_index("act_key").loc[act_key]
    _activity_header(ctx, act_key, act)
    if config.activity(act_key).sops:
        _sop_tasks(ctx, truck, act_key)
    else:
        _manual_activity(ctx, truck, act_key, act)


def _activity_header(ctx: Ctx, act_key: str, act: pd.Series) -> None:
    t = ctx.t
    section(act_name(t, act_key))
    cols = st.columns(5)
    cols[0].markdown(f"**{t('status')}**<br>{pill_html(t, act.status)}", unsafe_allow_html=True)
    cols[1].markdown(f"**{t('progress')}**<br>{fmt_pct(act.progress)}", unsafe_allow_html=True)
    cols[2].markdown(f"**{t('original_plan')}**<br>{fmt_date(act.base_start)} → {fmt_date(act.base_end)}",
                     unsafe_allow_html=True)
    cols[3].markdown(f"**{t('forecast')}**<br>{fmt_date(act.fc_start)} → {fmt_date(act.fc_end)}", unsafe_allow_html=True)
    cols[4].markdown(f"**{t('actual_mh')}**<br>{act.actual_mh:.1f}", unsafe_allow_html=True)
    st.progress(float(act.progress))
    if act.external:
        note(t("external_note"))
    if not act.has_records and act.progress > 0:
        note(t("imported_note", pct=fmt_pct(act.progress)))


# ─── Actividades con SOP: tabla de tareas ─────────────────────────────────
def _base_rows(ctx: Ctx, truck: str, act_key: str) -> pd.DataFrame:
    t, lang = ctx.t, ctx.lang
    tasks = ctx.project.tasks
    df = tasks[(tasks.truck == truck) & (tasks.act_key == act_key)].reset_index(drop=True)
    desc = df.desc_jp.where((lang == "ja") & (df.desc_jp != ""), df.desc_en)
    return pd.DataFrame({
        "task_id": df.task_id,
        "task": desc,
        "qc": df.qc_gate,
        "cond": df.conditional,
        "status": df.status.map(lambda s: t("ts_" + s)),
        "qc_result": df.qc_result.map(lambda s: t("qc_" + s)),
        "actual_mh": df.actual_mh,
        "date": df.date.map(_to_date),
        "supervisor": df.supervisor,
        "technicians": df.technicians,
        "remarks": df.remarks,
        "stage": df.stage,
    })


def _apply_edits(base: pd.DataFrame, editor_key: str) -> pd.DataFrame:
    rows = base.copy()
    delta = st.session_state.get(editor_key) or {}
    for idx, changes in delta.get("edited_rows", {}).items():
        for col, val in changes.items():
            if col == "date":
                val = _to_date(val)
            rows.at[int(idx), col] = val
    return rows


def _sop_tasks(ctx: Ctx, truck: str, act_key: str) -> None:
    t, user = ctx.t, ctx.user
    sops = config.activity(act_key).sops
    note(t("sop_help", sops=" + ".join(config.SOP_TITLES[s] for s in sops)))

    status_labels = {t("ts_" + s): s for s in config.TASK_STATUSES}
    qc_labels = {t("qc_" + s): s for s in config.QC_RESULTS}
    base = _base_rows(ctx, truck, act_key)
    only_open = st.toggle(t("hide_done"), key=f"hide_{truck}_{act_key}", help=t("hide_done_help"))
    nonce = _nonce(truck + act_key)
    editor_key = f"ed_{truck}_{act_key}_{nonce}_{int(only_open)}"
    view = base[~base.status.isin([t("ts_done"), t("ts_na")])] if only_open else base

    # La fecha se envía como columna de fecha real: si todas están vacías, el
    # editor recibiría una columna sin tipo y no permitiría escribir en ella.
    st.data_editor(
        view.assign(date=pd.to_datetime(view.date)),
        key=editor_key,
        hide_index=True,
        width="stretch",
        height=min(38 + 35 * len(view), 560),
        disabled=["task_id", "stage", "task", "qc", "cond"],
        column_order=["task_id", "task", "qc", "cond", "status", "qc_result", "actual_mh", "date", "supervisor",
                      "technicians", "remarks", "stage"],
        column_config={
            "task_id": st.column_config.TextColumn(t("col_task_id"), width=75, pinned=True),
            "stage": st.column_config.TextColumn(t("col_stage"), width=110),
            "task": st.column_config.TextColumn(t("col_task"), width=290),
            "qc": st.column_config.TextColumn(t("col_qc"), width=115, help=t("col_qc_help")),
            "cond": st.column_config.CheckboxColumn(t("col_cond"), width=125, help=t("col_cond_help")),
            "status": st.column_config.SelectboxColumn(t("col_status"), options=list(status_labels), required=True, width=115),
            "actual_mh": st.column_config.NumberColumn(t("col_mh"), min_value=0.0, max_value=500.0, width=85),
            "supervisor": st.column_config.TextColumn(t("col_supervisor"), width=120),
            "technicians": st.column_config.TextColumn(t("col_technicians"), width=160, help=t("col_technicians_help")),
            "date": st.column_config.DateColumn(t("col_date"), format="DD-MMM-YYYY", width=110),
            "qc_result": st.column_config.SelectboxColumn(t("col_qc_result"), options=list(qc_labels), width=100),
            "remarks": st.column_config.TextColumn(t("col_remarks"), width=200),
        },
    )
    # Las filas editadas se identifican por su posición en la vista mostrada
    edited_view = _apply_edits(view.reset_index(drop=True), editor_key)
    edited_view.index = view.index
    edited = base.copy()
    edited.loc[edited_view.index] = edited_view

    changed = [i for i in base.index if any(_clean(base.at[i, c]) != _clean(edited.at[i, c]) for c in EDITABLE)]

    comment = st.text_area(t("comment"), key=f"cm_{truck}_{act_key}_{nonce}", placeholder=t("comment_ph"), height=80)
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    if changed:
        c2.caption(t("changed_rows", n=len(changed)))
    if c1.button(t("save_progress"), type="primary", icon=":material/save:", key=f"save_{editor_key}",
                 disabled=not changed and not comment.strip(), width="stretch"):
        updates, errors = [], []
        tasks = ctx.project.tasks
        meta = tasks[(tasks.truck == truck) & (tasks.act_key == act_key)].reset_index(drop=True)
        for i in changed:
            r = edited.loc[i]
            status = status_labels.get(r.status, "not_started")
            qc = qc_labels.get(r.qc_result, "pending")
            tid = r.task_id
            if status == "na" and not bool(meta.at[i, "conditional"]):
                errors.append(t("err_na_not_conditional", task=tid))
            if status == "done" and meta.at[i, "qc_gate"] == "HOLD" and qc != "accepted":
                errors.append(t("err_hold_not_accepted", task=tid))
            work_date = _to_date(r.date)
            if work_date is None and status in ("in_progress", "done"):
                work_date = ctx.project.today
            if work_date and work_date > ctx.project.today:
                errors.append(t("err_future_date", task=tid))
            updates.append({
                "task_id": tid, "status": status, "actual_mh": _mh(r.actual_mh),
                "supervisor": _clean(r.supervisor) or (user.name if status != "not_started" else ""),
                "technicians": _clean(r.technicians), "date": work_date.isoformat() if work_date else "",
                "qc_result": qc, "remarks": _clean(r.remarks),
            })
        if errors:
            for e in errors:
                st.error(e, icon=":material/block:")
            return
        payload = {"truck": truck, "act": act_key, "updates": updates, "comment": comment.strip()}
        if safe_write(ctx, lambda: write_event(ctx.store, "task", payload, user.username, truck),
                      t("saved_n", n=len(updates))):
            _bump(truck + act_key)
            st.rerun()

    _task_details(ctx, truck, act_key, base)


def _task_details(ctx: Ctx, truck: str, act_key: str, base: pd.DataFrame) -> None:
    t, lang = ctx.t, ctx.lang
    tasks = ctx.project.tasks
    meta = tasks[(tasks.truck == truck) & (tasks.act_key == act_key)].set_index("task_id")
    with st.expander(t("task_instructions"), icon=":material/menu_book:"):
        tid = st.selectbox(t("col_task_id"), meta.index.tolist(), key=f"det_{truck}_{act_key}",
                           format_func=lambda x: f"{x} · {meta.at[x, 'desc_jp' if lang == 'ja' and meta.at[x, 'desc_jp'] else 'desc_en']}")
        m = meta.loc[tid]
        c1, c2 = st.columns(2)
        c1.markdown(f"**English**\n\n{m.desc_en}\n\n{m.instr_en}")
        c2.markdown(f"**日本語**\n\n{m.desc_jp or '—'}\n\n{m.instr_jp}")
        facts = [(t("col_stage"), m.stage), (t("drawing"), m.drawing), (t("predecessor"), m.predecessor),
                 (t("planned_mh"), "" if pd.isna(m.planned_mh) else f"{m.planned_mh:g}"),
                 (t("col_qc"), f"{m.qc_gate} {m.qc_note}".strip()),
                 (t("col_cond"), t("yes") if m.conditional else t("no"))]
        st.markdown(" · ".join(f"**{k}:** {v}" for k, v in facts if str(v).strip()))
    notes = load_notes()
    notes = notes[notes.sop.isin(config.activity(act_key).sops)]
    if len(notes):
        with st.expander(t("engineering_notes"), icon=":material/engineering:"):
            show = notes.assign(note=notes.note_jp.where((lang == "ja") & (notes.note_jp != ""), notes.note_en))
            st.dataframe(show[["sop", "item", "note", "source"]], hide_index=True, width="stretch",
                         column_config={"sop": "SOP", "item": t("item"), "note": t("note"), "source": t("source")})


# ─── Actividades sin SOP: avance manual ───────────────────────────────────
def _manual_activity(ctx: Ctx, truck: str, act_key: str, act: pd.Series) -> None:
    t, user, p = ctx.t, ctx.user, ctx.project
    log = p.task_log
    last = log[(log.truck == truck) & (log.act_key == act_key) & (log.task_id == config.ACTIVITY_TASK_ID)].tail(1)
    prev = last.iloc[0] if len(last) else None
    key = f"man_{truck}_{act_key}_{_nonce(truck + act_key)}"
    note(t("manual_help"))
    with st.form(key):
        c1, c2, c3 = st.columns(3)
        progress = c1.slider(t("progress") + " (%)", 0, 100, int(round(act.progress * 100 / 5) * 5), step=5)
        mh = c2.number_input(t("col_mh"), min_value=0.0, max_value=2000.0, step=0.5,
                             value=float(prev.actual_mh) if prev is not None and _mh(prev.actual_mh) else 0.0,
                             help=t("mh_total_help"))
        work_date = c3.date_input(t("col_date"), value=p.today, max_value=p.today, format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        supervisor = c1.text_input(t("col_supervisor"), value=_clean(prev.supervisor) if prev is not None else user.name)
        techs = c2.text_input(t("col_technicians"), value=_clean(prev.technicians) if prev is not None else "",
                              help=t("col_technicians_help"))
        remarks = st.text_input(t("col_remarks"))
        comment = st.text_area(t("comment"), placeholder=t("comment_ph"), height=80)
        if st.form_submit_button(t("save_progress"), type="primary", icon=":material/save:"):
            update = {"task_id": config.ACTIVITY_TASK_ID, "progress": progress, "actual_mh": _mh(mh),
                      "supervisor": supervisor.strip(), "technicians": techs.strip(),
                      "date": work_date.isoformat(), "remarks": remarks.strip(),
                      "status": "done" if progress >= 100 else ("in_progress" if progress > 0 else "not_started")}
            payload = {"truck": truck, "act": act_key, "updates": [update], "comment": comment.strip()}
            if safe_write(ctx, lambda: write_event(ctx.store, "task", payload, user.username, truck), t("saved")):
                _bump(truck + act_key)
                st.rerun()


# ─── Notas de atraso ──────────────────────────────────────────────────────
def _delay_form(ctx: Ctx, truck: str, acts: pd.DataFrame) -> None:
    t, user = ctx.t, ctx.user
    with st.expander(t("report_delay"), icon=":material/report:"):
        note(t("delay_help"))
        with st.form(f"delay_{truck}_{_nonce('delay' + truck)}"):
            c1, c2, c3 = st.columns([2, 2, 1])
            act = c1.selectbox(t("activity"), ["_truck_"] + acts.act_key.tolist(),
                               format_func=lambda k: t("whole_truck") if k == "_truck_" else act_name(t, k))
            cat = c2.selectbox(t("delay_category"), config.DELAY_CATEGORIES, format_func=lambda c: t("dc_" + c))
            days = c3.number_input(t("impact_days"), min_value=0.0, max_value=60.0, step=0.5, value=1.0)
            desc = st.text_area(t("delay_description"), placeholder=t("delay_description_ph"))
            if st.form_submit_button(t("submit_delay"), icon=":material/send:"):
                if not desc.strip():
                    st.error(t("err_description"))
                    return
                payload = {"truck": truck, "act": "" if act == "_truck_" else act, "category": cat,
                           "impact_days": days, "description": desc.strip()}
                if safe_write(ctx, lambda: write_event(ctx.store, "delay", payload, user.username, truck), t("delay_saved")):
                    _bump("delay" + truck)
                    st.rerun()


# ─── Historial ────────────────────────────────────────────────────────────
def history(ctx: Ctx, truck: str, act_key: str) -> None:
    t, p = ctx.t, ctx.project
    tz = p.settings.get("timezone", "UTC")
    log = p.task_log[(p.task_log.truck == truck) & (p.task_log.act_key == act_key)]
    com = p.comments[(p.comments.truck == truck) & (p.comments.act_key == act_key)]
    with st.expander(t("history", n=len(log) + len(com)), icon=":material/history:"):
        if len(com):
            st.markdown(f"**{t('comments')}**")
            for r in com.iloc[::-1].itertuples():
                st.markdown(f"- *{fmt_ts(r.ts, tz)} · {r.user}:* {r.text}")
        if len(log):
            show = log.iloc[::-1].copy()
            show["ts"] = show.ts.map(lambda s: fmt_ts(s, tz))
            show["status"] = show.status.map(lambda s: t("ts_" + s) if isinstance(s, str) and s else "")
            show["task_id"] = show.task_id.replace(config.ACTIVITY_TASK_ID, t("activity"))
            show = show.astype(object).where(show.notna(), "")
            st.dataframe(show[["ts", "user", "task_id", "status", "progress", "actual_mh", "supervisor",
                               "technicians", "date", "remarks"]],
                         hide_index=True, width="stretch",
                         column_config={"ts": t("when"), "user": t("user"), "task_id": t("col_task_id"),
                                        "status": t("col_status"), "progress": t("progress"),
                                        "actual_mh": t("col_mh"), "supervisor": t("col_supervisor"),
                                        "technicians": t("col_technicians"), "date": t("col_date"),
                                        "remarks": t("col_remarks")})
        if not len(log) and not len(com):
            st.caption(t("no_history"))
