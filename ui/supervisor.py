"""Vista del supervisor: registrar el avance de las actividades (%), horas-hombre, personal,
comentarios y notas de atraso."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config
from core.events import write_event
from ui.common import (Ctx, act_name, fmt_date, fmt_pct, fmt_ts, note, pill_html, safe_write, section,
                       truck_badge, truck_label)


def _nonce(key: str) -> int:
    return st.session_state.setdefault(f"nonce_{key}", 0)


def _bump(key: str) -> None:
    st.session_state[f"nonce_{key}"] = _nonce(key) + 1


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


# ─── Registro de avance en % ──────────────────────────────────────────────
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
                             value=float(prev.actual_mh) if prev is not None and _mh(prev.actual_mh) else float(act.actual_mh),
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
