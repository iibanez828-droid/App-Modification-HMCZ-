"""Vista del administrador: resumen, alertas, Gantt, plan (fechas), detalle por
camión (avance, alta de camiones y actividades), atrasos, reportes
y configuración del proyecto. Los usuarios no se
gestionan desde la app (ver scripts/users.py)."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from core import config
from core.events import write_event
from core.executive_report import build_executive_pdf
from core.reports import build_excel, status_csv
from core.workdays import WorkCalendar
from ui.common import (Ctx, act_name, fmt_date, fmt_pct, fmt_ts, kpi_cards, note, password_form, safe_write, section,
                       truck_badge, truck_label, esc)
from ui import supervisor
from ui.gantt import gantt_panels

EDITABLE_STATUSES = ("in_progress", "overdue", "upcoming", "no_dates")


def render(ctx: Ctx) -> None:
    t = ctx.t
    tabs = st.tabs([
        ":material/dashboard: " + t("tab_overview"),
        ":material/view_timeline: " + t("tab_gantt"),
        ":material/edit_calendar: " + t("tab_plan"),
        ":material/local_shipping: " + t("tab_trucks"),
        ":material/schedule: " + t("tab_delays"),
        ":material/summarize: " + t("tab_reports"),
        ":material/settings: " + t("tab_settings"),
    ])
    with tabs[0]:
        _overview(ctx)
    with tabs[1]:
        _gantt(ctx)
    with tabs[2]:
        _plan(ctx)
    with tabs[3]:
        _truck_detail(ctx)
    with tabs[4]:
        _delays(ctx)
    with tabs[5]:
        _reports(ctx)
    with tabs[6]:
        _settings(ctx)
        if not ctx.user.is_master:  # la contraseña del maestro está en los secretos
            section(t("change_password"))
            password_form(ctx, "chg_pw_settings")


# ─── 1. Resumen ───────────────────────────────────────────────────────────
def _overview(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    tr = p.trucks
    n = len(tr)
    counts = tr.status.value_counts()
    kpi_cards([
        (t("kpi_project"), fmt_pct(tr.progress.mean()), t("kpi_project_sub", n=n), ""),
        (t("kpi_completed"), f"{counts.get('completed', 0)} / {n}", t("trucks"), "green"),
        (t("kpi_active"), str(counts.get("in_progress", 0) + counts.get("overdue", 0)), t("kpi_active_sub"), ""),
        (t("kpi_upcoming"), str(counts.get("upcoming", 0)),
         t("kpi_upcoming_sub", days=p.settings.get("lookahead_days", 14)), "blue"),
        (t("kpi_overdue"), str(counts.get("overdue", 0)), t("kpi_overdue_sub"), "red"),
        (t("kpi_mh"), f"{tr.actual_mh.sum():,.1f}", t("kpi_mh_sub"), ""),
    ])

    _alerts(ctx)

    section(t("active_trucks"))
    visible = tr[tr.status.isin(EDITABLE_STATUSES)].sort_values("start", na_position="last")
    if visible.empty:
        note(t("no_active_trucks"))
    else:
        st.dataframe(_truck_table(ctx, visible), hide_index=True, width="stretch",
                     column_config=_truck_cols(ctx))

    section(t("progress_matrix"))
    m = p.activities.pivot(index="truck", columns="act_key", values="progress")
    m = m[sorted(m.columns, key=config.activity_order)] * 100
    m.columns = [act_name(t, k) for k in m.columns]
    m.insert(0, t("status"), tr.set_index("truck").status.map(lambda s: t("st_" + s)))
    cfg = {c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%.0f%%", width=95)
           for c in m.columns[1:]}
    st.dataframe(m, width="stretch", column_config=cfg)
    st.caption(t("matrix_help"))


def _truck_table(ctx: Ctx, df: pd.DataFrame) -> pd.DataFrame:
    t = ctx.t
    limit = int(ctx.project.settings.get("max_working_days", 5))
    return pd.DataFrame({
        "truck": df.truck,
        "status": df.status.map(lambda s: t("st_" + s)),
        "progress": df.progress * 100,
        "start": df.start, "end": df.end, "base_end": df.base_end,
        "delay": df.delay_wd,
        "work_days": [f"{w} / {limit}{' ⚠' if o else ''}" for w, o in zip(df.work_days, df.over_limit)],
        "mh": df.actual_mh,
    })


def _truck_cols(ctx: Ctx) -> dict:
    t = ctx.t
    return {
        "truck": st.column_config.TextColumn(t("truck"), width=70),
        "status": st.column_config.TextColumn(t("status"), width=100),
        "progress": st.column_config.ProgressColumn(t("progress"), min_value=0, max_value=100, format="%.0f%%"),
        "start": st.column_config.DateColumn(t("fc_start"), format="DD-MMM-YYYY"),
        "end": st.column_config.DateColumn(t("fc_end"), format="DD-MMM-YYYY"),
        "base_end": st.column_config.DateColumn(t("base_end"), format="DD-MMM-YYYY"),
        "delay": st.column_config.NumberColumn(t("delay_wd"), format="%+d"),
        "work_days": st.column_config.TextColumn(t("own_work_days")),
        "mh": st.column_config.NumberColumn(t("col_mh"), format="%.1f"),
    }


def _alerts(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    alerts = p.alerts()
    section(t("alerts", n=len(alerts)))
    if not alerts:
        note(t("no_alerts"))
        return
    critical = [a for a in alerts if a["type"] in ("trunnion", "missing_dates", "overdue")]
    others = [a for a in alerts if a not in critical]
    for a in critical:
        _alert_box(ctx, a)
    if others:
        with st.expander(t("other_alerts", n=len(others)), icon=":material/notifications:"):
            for a in others:
                _alert_box(ctx, a)
    if p.acks:
        with st.expander(t("acks_done", n=len(p.acks)), icon=":material/task_alt:"):
            tz = p.settings.get("timezone", "UTC")
            for truck, ev in sorted(p.acks.items()):
                st.markdown(f"- **{truck}** · {fmt_ts(ev['ts'], tz)} · {ev['user']}" + (f" — {ev['note']}" if ev.get("note") else ""))


def _alert_box(ctx: Ctx, a: dict) -> None:
    t, p = ctx.t, ctx.project
    truck = a["truck"]
    if a["type"] == "trunnion":
        items = "; ".join(f"{act_name(t, x['act_key'])} ({fmt_date(x['fc_start'])} → {fmt_date(x['fc_end'])})"
                          for x in a["acts"])
        st.markdown(f'<div class="alert"><b>{esc(truck)} · {esc(t("alert_trunnion_title"))}</b><br>'
                    f'{esc(t("alert_trunnion", items=items))}</div>', unsafe_allow_html=True)
        with st.popover(t("ack_button"), icon=":material/task_alt:"):
            txt = st.text_input(t("ack_note"), key=f"ack_{truck}", placeholder=t("ack_note_ph"))
            if st.button(t("ack_confirm"), key=f"ackb_{truck}", type="primary"):
                payload = {"truck": truck, "note": txt.strip()}
                if safe_write(ctx, lambda: write_event(ctx.store, "ack", payload, ctx.user.username, truck),
                              t("ack_saved")):
                    st.rerun()
    elif a["type"] == "missing_dates":
        names = ", ".join(act_name(t, x["act_key"]) for x in a["acts"])
        st.markdown(f'<div class="alert orange"><b>{esc(truck)} · {esc(t("alert_missing_title"))}</b><br>'
                    f'{esc(t("alert_missing", items=names))}</div>', unsafe_allow_html=True)
    elif a["type"] == "overdue":
        st.markdown(f'<div class="alert"><b>{esc(truck)} · {esc(t("st_overdue"))}</b><br>'
                    f'{esc(t("alert_overdue", days=a["days"]))}</div>', unsafe_allow_html=True)
    elif a["type"] == "act_overdue":
        st.markdown(f'<div class="alert orange"><b>{esc(truck)} · {esc(act_name(t, a["act"]))}</b><br>'
                    f'{esc(t("alert_act_overdue", end=fmt_date(a["end"])))}</div>', unsafe_allow_html=True)
    elif a["type"] == "non_workday":
        st.markdown(f'<div class="alert orange"><b>{esc(truck)} · {esc(act_name(t, a["act"]))}</b><br>'
                    f'{esc(t("alert_non_workday", end=fmt_date(a["end"])))}</div>', unsafe_allow_html=True)
    elif a["type"] == "over_limit":
        st.markdown(f'<div class="alert blue"><b>{esc(truck)} · {esc(t("alert_limit_title"))}</b><br>'
                    f'{esc(t("alert_limit", days=a["days"], limit=p.settings.get("max_working_days", 5)))}</div>',
                    unsafe_allow_html=True)


# ─── 2. Gantt ─────────────────────────────────────────────────────────────
def _gantt(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    tr = p.trucks
    c1, c2, c3 = st.columns([1.2, 1.2, 3], vertical_alignment="bottom")
    show_future = c1.toggle(t("show_future"), key="g_future")
    show_done = c2.toggle(t("show_completed"), key="g_done")
    allowed = tr[tr.status.isin(EDITABLE_STATUSES)
                 | (show_future & tr.status.eq("future"))
                 | (show_done & tr.status.eq("completed"))].truck.tolist()
    trucks = c3.multiselect(t("trucks"), allowed, default=allowed, key=f"g_sel_{show_future}_{show_done}")
    c1, c2 = st.columns([2, 3], vertical_alignment="center")
    mode = c1.segmented_control(t("gantt_mode"), ["truck", "activity"], default="truck", key="g_mode",
                                format_func=lambda m: t("gantt_by_" + m), label_visibility="collapsed") or "truck"
    show_base = c2.checkbox(t("show_baseline"), value=True, key="g_base")
    gantt_panels(p, t, trucks, mode, show_base, "g_admin")


# ─── 3. Plan (fechas del pronóstico) ──────────────────────────────────────
def _plan(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    tr = p.trucks
    note(t("plan_help", days=p.settings.get("lookahead_days", 14)))
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    show_all = c2.toggle(t("plan_show_all"), key="plan_all")
    options = tr.truck.tolist() if show_all else tr[tr.status.isin(EDITABLE_STATUSES)].truck.tolist()
    if not options:
        note(t("no_active_trucks"))
        return
    truck = c1.selectbox(t("truck"), options, key="plan_truck", format_func=lambda x: truck_label(ctx, x))
    row = p.truck_row(truck)
    editable = row.status in EDITABLE_STATUSES
    truck_badge(ctx, truck)
    if not editable:
        note(t("plan_readonly", status=t("st_" + row.status)))

    nonce = st.session_state.setdefault(f"plan_nonce_{truck}", 0)
    cal0 = p.calendar(truck)
    c1, c2, _ = st.columns([1, 1, 3])
    sat = c1.checkbox(t("work_saturday"), value=cal0.saturday, key=f"sat_{truck}_{nonce}", disabled=not editable)
    sun = c2.checkbox(t("work_sunday"), value=cal0.sunday, key=f"sun_{truck}_{nonce}", disabled=not editable)
    cal = WorkCalendar.build(sat, sun, p.settings.get("holidays", []))

    acts = p.truck_activities(truck).reset_index(drop=True)
    base = pd.DataFrame({
        "act": acts.act_key.map(lambda k: act_name(t, k)),
        "ext": acts.external,
        "progress": acts.progress * 100,
        "base_start": acts.base_start, "base_end": acts.base_end,
        "fc_start": acts.fc_start, "fc_end": acts.fc_end,
        "assigned_to": acts.assigned_to,
    })
    key = f"plan_ed_{truck}_{nonce}"
    st.data_editor(
        base, key=key, hide_index=True, width="stretch", num_rows="fixed",
        disabled=["act", "ext", "progress"] + ([] if editable else ["base_start", "base_end", "fc_start", "fc_end", "assigned_to"]),
        column_config={
            "act": st.column_config.TextColumn(t("activity"), width=200),
            "ext": st.column_config.CheckboxColumn(t("external"), width=70),
            "progress": st.column_config.ProgressColumn(t("progress"), min_value=0, max_value=100, format="%.0f%%", width=100),
            "base_start": st.column_config.DateColumn(t("base_start"), format="DD-MMM-YYYY", help=t("baseline_help")),
            "base_end": st.column_config.DateColumn(t("base_end"), format="DD-MMM-YYYY", help=t("baseline_help")),
            "fc_start": st.column_config.DateColumn(t("fc_start"), format="DD-MMM-YYYY"),
            "fc_end": st.column_config.DateColumn(t("fc_end"), format="DD-MMM-YYYY"),
            "assigned_to": st.column_config.TextColumn(t("assigned_to")),
        },
    )
    edited = base.copy()
    for idx, changes in (st.session_state.get(key) or {}).get("edited_rows", {}).items():
        for col, val in changes.items():
            if col in ("base_start", "base_end", "fc_start", "fc_end"):
                val = date.fromisoformat(str(val)[:10]) if val else None
            edited.at[int(idx), col] = val

    # Vista previa con las fechas editadas
    errors, changes = [], []
    work_days: set = set()
    for i, r in edited.iterrows():
        a = acts.loc[i]
        if r.fc_start and r.fc_end and r.fc_end < r.fc_start:
            errors.append(t("err_end_before_start", act=r.act))
        if not a.external and r.fc_start and r.fc_end:
            d = r.fc_start
            while d <= r.fc_end:
                if cal.is_workday(d):
                    work_days.add(d)
                d = d.fromordinal(d.toordinal() + 1)
        ch = {"act": a.act_key}
        for col in ("fc_start", "fc_end"):
            if r[col] != base.at[i, col]:
                ch[col] = r[col].isoformat() if r[col] else ""
        for col in ("base_start", "base_end"):
            if r[col] != base.at[i, col] and not base.at[i, col] and r[col]:
                ch[col] = r[col].isoformat()
        if (r.assigned_to or "") != (base.at[i, "assigned_to"] or ""):
            ch["assigned_to"] = (r.assigned_to or "").strip()
        if len(ch) > 1:
            changes.append(ch)
    starts = [d for d in edited.fc_start if d]
    ends = [d for d in edited.fc_end if d]
    limit = int(p.settings.get("max_working_days", 5))
    kpi_cards([
        (t("own_work_days"), f"{len(work_days)} / {limit}", t("own_work_days_sub"), "red" if len(work_days) > limit else "green"),
        (t("fc_start"), fmt_date(min(starts) if starts else None), "", ""),
        (t("fc_end"), fmt_date(max(ends) if ends else None), "", ""),
        (t("delay_wd"), f"{cal.delay(row.base_end, max(ends) if ends else None):+d}", t("vs_original"), ""),
    ])
    weekend_changed = (sat, sun) != (cal0.saturday, cal0.sunday)
    for e in errors:
        st.error(e, icon=":material/block:")

    if editable:
        reason = st.text_input(t("change_reason"), key=f"reason_{truck}_{nonce}", placeholder=t("change_reason_ph"))
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        c2.caption(t("plan_changes", n=len(changes)))
        if c1.button(t("save_plan"), type="primary", icon=":material/save:", key=f"save_plan_{truck}_{nonce}",
                     disabled=bool(errors) or not (changes or weekend_changed), width="stretch"):
            if not reason.strip():
                st.error(t("err_reason"))
            else:
                payload = {"truck": truck, "changes": changes, "reason": reason.strip()}
                if weekend_changed:
                    payload["weekend"] = {"sat": sat, "sun": sun}
                if safe_write(ctx, lambda: write_event(ctx.store, "plan", payload, ctx.user.username, truck), t("plan_saved")):
                    st.session_state[f"plan_nonce_{truck}"] = nonce + 1
                    st.rerun()

        with st.expander(t("shift_title"), icon=":material/fast_forward:"):
            note(t("shift_help"))
            c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
            n = c1.number_input(t("shift_days"), min_value=-30, max_value=30, value=1, step=1, key=f"shift_{truck}")
            reason2 = c2.text_input(t("change_reason"), key=f"shift_reason_{truck}", placeholder=t("change_reason_ph"))
            if st.button(t("shift_apply"), key=f"shift_btn_{truck}", disabled=n == 0):
                if not reason2.strip():
                    st.error(t("err_reason"))
                else:
                    shift_changes = []
                    for a in acts.itertuples():
                        if a.progress >= 1 or not a.fc_start or not a.fc_end:
                            continue
                        shift_changes.append({"act": a.act_key, "fc_start": cal0.shift(a.fc_start, int(n)).isoformat(),
                                              "fc_end": cal0.shift(a.fc_end, int(n)).isoformat()})
                    payload = {"truck": truck, "changes": shift_changes, "reason": f"{reason2.strip()} ({int(n):+d} wd)"}
                    if safe_write(ctx, lambda: write_event(ctx.store, "plan", payload, ctx.user.username, truck), t("plan_saved")):
                        st.session_state[f"plan_nonce_{truck}"] = nonce + 1
                        st.rerun()


# ─── 4. Detalle por camión ────────────────────────────────────────────────
def _truck_detail(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    tz = p.settings.get("timezone", "UTC")
    _add_truck(ctx)
    trucks = p.trucks.truck.tolist()
    truck = st.selectbox(t("truck"), trucks, key="det_truck", format_func=lambda x: truck_label(ctx, x),
                         index=trucks.index(p.visible_trucks()[0]) if p.visible_trucks() else 0)
    truck_badge(ctx, truck)
    acts = p.truck_activities(truck)

    section(t("activities"))
    st.dataframe(pd.DataFrame({
        "act": [act_name(t, k) + (" ⧉" if ext else "") for k, ext in zip(acts.act_key, acts.external)],
        "status": acts.status.map(lambda s: t("st_" + s)),
        "progress": acts.progress * 100,
        "base": [f"{fmt_date(a)} → {fmt_date(b)}" for a, b in zip(acts.base_start, acts.base_end)],
        "fc": [f"{fmt_date(a)} → {fmt_date(b)}" for a, b in zip(acts.fc_start, acts.fc_end)],
        "delay": acts.delay_wd, "mh": acts.actual_mh,
        "src": acts.has_records.map(lambda h: t("src_app") if h else t("src_gantt")),
    }), hide_index=True, width="stretch", column_config={
        "act": t("activity"), "status": t("status"),
        "progress": st.column_config.ProgressColumn(t("progress"), min_value=0, max_value=100, format="%.0f%%"),
        "base": t("original_plan"), "fc": t("forecast"),
        "delay": st.column_config.NumberColumn(t("delay_wd"), format="%+d"),
        "mh": st.column_config.NumberColumn(t("col_mh"), format="%.1f"), "src": t("data_source"),
    })
    st.caption(t("external_mark"))

    # Registro de avance: el administrador edita igual que el supervisor
    section(t("edit_progress"))
    act_key = st.selectbox(
        t("activity"), acts.act_key.tolist(), key=f"adm_act_{truck}",
        format_func=lambda k: f"{act_name(t, k)} · {fmt_pct(float(acts.set_index('act_key').at[k, 'progress']))}",
    )
    supervisor.activity_editor(ctx, truck, act_key, acts)
    supervisor.history(ctx, truck, act_key)

    _manage_activities(ctx, truck, acts)
    _remove_truck(ctx, truck)

    c1, c2 = st.columns(2)
    with c1:
        section(t("comments"))
        com = p.comments[p.comments.truck == truck]
        if com.empty:
            st.caption(t("no_history"))
        for r in com.iloc[::-1].itertuples():
            st.markdown(f"- *{fmt_ts(r.ts, tz)} · {r.user} · {act_name(t, r.act_key)}:* {r.text}")
    with c2:
        section(t("people_mh"))
        log = p.task_log[(p.task_log.truck == truck)].drop_duplicates(["act_key", "task_id"], keep="last")
        if log.empty:
            st.caption(t("no_history"))
        else:
            sup = log.assign(mh=pd.to_numeric(log.actual_mh, errors="coerce").fillna(0))
            sup = sup.groupby(sup.supervisor.replace("", "—"))["mh"].sum().reset_index()
            st.dataframe(sup, hide_index=True, width="stretch",
                         column_config={"supervisor": t("col_supervisor"), "mh": st.column_config.NumberColumn(t("col_mh"), format="%.1f")})


def _nonce(key: str) -> int:
    return st.session_state.setdefault(f"scope_nonce_{key}", 0)


def _save_scope(ctx: Ctx, payload: dict, subject: str, nonce_key: str) -> None:
    if safe_write(ctx, lambda: write_event(ctx.store, "scope", payload, ctx.user.username, subject), ctx.t("scope_saved")):
        st.session_state[f"scope_nonce_{nonce_key}"] = _nonce(nonce_key) + 1
        st.rerun()


def _new_activity_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:24] or "act"
    key, n = f"cx_{slug}", 2
    while key in config.ACTIVITY_BY_KEY or key in config.CUSTOM_ACTIVITIES:
        key, n = f"cx_{slug}_{n}", n + 1
    return key


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _manage_activities(ctx: Ctx, truck: str, acts: pd.DataFrame) -> None:
    t, p = ctx.t, ctx.project
    nonce = _nonce(truck)
    section(t("manage_activities"))
    tab_add, tab_remove = st.tabs([":material/add: " + t("add_activity"), ":material/delete: " + t("remove_activity")])

    # ── Agregar: actividad general nueva o una actividad que este camión no tiene
    with tab_add:
        missing = [a.key for a in config.all_activities() if a.key not in set(acts.act_key)]
        mode = st.segmented_control(t("add_mode"), ["new", "existing"], default="new", key=f"add_mode_{truck}_{nonce}",
                                    format_func=lambda m: t("add_mode_" + m)) or "new"
        act = None
        if mode == "new":
            note(t("new_activity_help"))
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            name = c1.text_input(t("activity_name"), key=f"new_name_{truck}_{nonce}", placeholder=t("activity_name_ph"))
            external = c2.checkbox(t("external"), key=f"new_ext_{truck}_{nonce}")
            all_trucks = st.toggle(t("add_to_all_trucks"), key=f"new_all_{truck}_{nonce}")
            targets = p.trucks.truck.tolist() if all_trucks else st.multiselect(
                t("trucks"), p.trucks.truck.tolist(), default=[truck], key=f"new_trucks_{truck}_{nonce}")
        elif not missing:
            note(t("no_missing_activities"))
        else:
            act = st.selectbox(t("activity"), missing, key=f"add_act_{truck}_{nonce}", format_func=lambda k: act_name(t, k))
        if mode == "new" or act:
            c1, c2, _ = st.columns([1, 1, 2])
            start = c1.date_input(t("fc_start"), value=None, key=f"add_start_{truck}_{nonce}", format="DD/MM/YYYY")
            end = c2.date_input(t("fc_end"), value=None, key=f"add_end_{truck}_{nonce}", format="DD/MM/YYYY")
            st.caption(t("add_dates_help"))
            if st.button(t("add_activity"), type="primary", icon=":material/add:", key=f"add_btn_{truck}_{nonce}"):
                if start and end and end < start:
                    st.error(t("err_end_before_start", act=t("activity")))
                elif mode == "new":
                    names = {act_name(t, a.key).strip().lower() for a in config.all_activities()}
                    if not name.strip():
                        st.error(t("err_activity_name"))
                    elif name.strip().lower() in names:
                        st.error(t("err_activity_exists"))
                    elif not targets:
                        st.error(t("select_trucks"))
                    else:
                        _save_scope(ctx, {"op": "new_activity", "act": _new_activity_key(name), "name": name.strip(),
                                          "external": external, "trucks": targets, "start": _iso(start),
                                          "end": _iso(end)}, truck, truck)
                else:
                    _save_scope(ctx, {"op": "add_activity", "truck": truck, "act": act,
                                      "start": _iso(start), "end": _iso(end)}, truck, truck)

    # ── Quitar una actividad del camión
    with tab_remove:
        if len(acts) <= 1:
            note(t("err_last_activity"))
        else:
            note(t("remove_activity_help"))
            act = st.selectbox(t("activity"), acts.act_key.tolist(), key=f"rm_act_{truck}_{nonce}",
                               format_func=lambda k: act_name(t, k))
            sure = st.checkbox(t("remove_confirm", act=act_name(t, act), truck=truck), key=f"rm_ok_{truck}_{nonce}")
            if st.button(t("remove_activity"), icon=":material/delete:", key=f"rm_btn_{truck}_{nonce}", disabled=not sure):
                _save_scope(ctx, {"op": "remove_activity", "truck": truck, "act": act}, truck, truck)


def _remove_truck(ctx: Ctx, truck: str) -> None:
    t, p = ctx.t, ctx.project
    nonce = _nonce(truck)
    with st.expander(t("remove_truck"), icon=":material/delete_forever:"):
        if len(p.trucks) <= 1:
            note(t("err_last_truck"))
            return
        note(t("remove_truck_help"))
        typed = st.text_input(t("remove_truck_confirm", truck=truck), key=f"rt_id_{truck}_{nonce}")
        if st.button(t("remove_truck"), icon=":material/delete_forever:", key=f"rt_btn_{truck}_{nonce}",
                     disabled=typed.strip().upper() != truck.upper()):
            _save_scope(ctx, {"op": "remove_truck", "truck": truck}, truck, truck)


def _add_truck(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    nonce = _nonce("_new_truck_")
    with st.expander(t("add_truck"), icon=":material/add_circle:"):
        note(t("add_truck_help"))
        truck = st.text_input(t("truck_id"), key=f"nt_id_{nonce}", placeholder="RD232").strip().upper()
        keys = st.multiselect(t("activities"), [a.key for a in config.all_activities()],
                              default=[a.key for a in config.ACTIVITIES], key=f"nt_acts_{nonce}",
                              format_func=lambda k: act_name(t, k))
        if st.button(t("add_truck"), type="primary", icon=":material/local_shipping:", key=f"nt_btn_{nonce}"):
            if not re.fullmatch(r"[A-Z0-9-]{2,12}", truck):
                st.error(t("err_truck_id"))
            elif truck in set(p.trucks.truck):
                st.error(t("err_truck_exists", truck=truck))
            elif not keys:
                st.error(t("err_no_activities"))
            else:
                acts = [{"act": k} for k in keys]
                _save_scope(ctx, {"op": "add_truck", "truck": truck, "acts": acts}, truck, "_new_truck_")


# ─── 5. Atrasos ───────────────────────────────────────────────────────────
def _delays(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    tz = p.settings.get("timezone", "UTC")
    a = p.activities
    section(t("schedule_deviation"))
    late = a[(a.delay_wd != 0) | (a.status == "overdue")].sort_values(["truck", "order"])
    if late.empty:
        note(t("no_deviation"))
    else:
        st.dataframe(pd.DataFrame({
            "truck": late.truck, "act": late.act_key.map(lambda k: act_name(t, k)),
            "status": late.status.map(lambda s: t("st_" + s)),
            "base_end": late.base_end, "fc_end": late.fc_end, "delay": late.delay_wd,
            "progress": late.progress * 100,
        }), hide_index=True, width="stretch", column_config={
            "truck": t("truck"), "act": t("activity"), "status": t("status"),
            "base_end": st.column_config.DateColumn(t("base_end"), format="DD-MMM-YYYY"),
            "fc_end": st.column_config.DateColumn(t("fc_end"), format="DD-MMM-YYYY"),
            "delay": st.column_config.NumberColumn(t("delay_wd"), format="%+d"),
            "progress": st.column_config.ProgressColumn(t("progress"), min_value=0, max_value=100, format="%.0f%%"),
        })

    section(t("delay_notes", n=len(p.delays)))
    d = p.delays
    if d.empty:
        note(t("no_delay_notes"))
    else:
        c1, c2 = st.columns(2)
        f_truck = c1.multiselect(t("trucks"), sorted(d.truck.unique()), key="dl_truck")
        f_cat = c2.multiselect(t("delay_category"), config.DELAY_CATEGORIES, key="dl_cat",
                               format_func=lambda c: t("dc_" + c))
        if f_truck:
            d = d[d.truck.isin(f_truck)]
        if f_cat:
            d = d[d.category.isin(f_cat)]
        d = d.iloc[::-1]
        st.dataframe(pd.DataFrame({
            "ts": d.ts.map(lambda s: fmt_ts(s, tz)), "user": d.user, "truck": d.truck,
            "act": d.act.map(lambda k: act_name(t, k) if k else t("whole_truck")),
            "cat": d.category.map(lambda c: t("dc_" + c)), "days": d.impact_days, "desc": d.description,
        }), hide_index=True, width="stretch", column_config={
            "ts": t("when"), "user": t("user"), "truck": t("truck"), "act": t("activity"),
            "cat": t("delay_category"), "days": t("impact_days"),
            "desc": st.column_config.TextColumn(t("delay_description"), width="large")})
        by_cat = p.delays.groupby("category")["impact_days"].agg(["count", "sum"]).reset_index()
        by_cat["category"] = by_cat.category.map(lambda c: t("dc_" + c))
        st.dataframe(by_cat, hide_index=True, column_config={
            "category": t("delay_category"), "count": t("notes_count"), "sum": t("impact_days")})

    section(t("plan_history", n=len(p.plan_log)))
    if p.plan_log.empty:
        st.caption(t("no_history"))
    else:
        pl = p.plan_log.iloc[::-1]
        st.dataframe(pd.DataFrame({
            "ts": pl.ts.map(lambda s: fmt_ts(s, tz)), "user": pl.user, "truck": pl.truck,
            "act": pl.act_key.map(lambda k: act_name(t, k)), "fc_start": pl.fc_start, "fc_end": pl.fc_end,
            "reason": pl.reason,
        }), hide_index=True, width="stretch", column_config={
            "ts": t("when"), "user": t("user"), "truck": t("truck"), "act": t("activity"),
            "fc_start": t("fc_start"), "fc_end": t("fc_end"), "reason": t("change_reason")})


# ─── 6. Reportes ──────────────────────────────────────────────────────────
def _reports(ctx: Ctx) -> None:
    """Los archivos se generan solo al presionar el botón: Streamlit ejecuta todas
    las pestañas en cada clic y generarlos siempre haría lenta toda la vista."""
    t, p, ss = ctx.t, ctx.project, st.session_state
    stamp_ = p.today.isoformat()
    tz = p.settings.get("timezone", "UTC")

    c1, c2 = st.columns([1, 2], vertical_alignment="center")
    if c1.button(t("generate_reports"), icon=":material/autorenew:", type="primary", width="stretch"):
        with st.spinner(t("generating")):
            ss.reports = {
                "pdf": build_executive_pdf(p), "xlsx": build_excel(p), "csv": status_csv(p),
                "stamp": stamp_, "ts": pd.Timestamp.now(tz="UTC").isoformat(),
            }
    rep = ss.get("reports")
    if not rep:
        c2.caption(t("generate_help"))
        return
    c2.caption(t("generated_at", when=fmt_ts(rep["ts"], tz)))

    section(t("executive_report"))
    note(t("executive_help"))
    c1, c2, _ = st.columns(3)
    c1.download_button(t("download_pdf"), rep["pdf"], file_name=f"HCMZ_executive_report_{rep['stamp']}.pdf",
                       mime="application/pdf", icon=":material/picture_as_pdf:", type="primary", width="stretch")
    if c2.button(t("publish_report"), icon=":material/cloud_upload:", width="stretch", help=t("publish_help")):
        def publish() -> None:
            ctx.store.write(f"reports/HMCZ_executive_report_{rep['stamp']}.pdf", rep["pdf"],
                            f"[app] reporte ejecutivo {rep['stamp']} · por {ctx.user.username}")
        if safe_write(ctx, publish, t("published")):
            st.rerun()

    section(t("data_export"))
    note(t("reports_help"))
    c1, c2, _ = st.columns(3)
    c1.download_button(t("download_excel"), rep["xlsx"], file_name=f"HCMZ_status_{rep['stamp']}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:", width="stretch")
    c2.download_button(t("download_csv"), rep["csv"], file_name=f"HCMZ_status_{rep['stamp']}.csv", mime="text/csv",
                       icon=":material/table:", width="stretch")


# ─── 7. Configuración ──────────────────
def _settings(ctx: Ctx) -> None:
    t, p = ctx.t, ctx.project
    s = p.settings
    section(t("settings"))
    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        look = c1.number_input(t("set_lookahead"), min_value=1, max_value=90, value=int(s.get("lookahead_days", 14)),
                               help=t("set_lookahead_help"))
        maxwd = c2.number_input(t("set_max_wd"), min_value=1, max_value=30, value=int(s.get("max_working_days", 5)))
        tz = c3.text_input(t("set_tz"), value=s.get("timezone", "UTC"), help=t("set_tz_help"))
        hol = st.text_area(t("set_holidays"), value="\n".join(s.get("holidays", [])), help=t("set_holidays_help"), height=100)
        if st.form_submit_button(t("save_settings"), icon=":material/save:"):
            days, bad = [], []
            for line in hol.replace(",", "\n").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    days.append(date.fromisoformat(line).isoformat())
                except ValueError:
                    bad.append(line)
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz.strip())
            except Exception:
                bad.append(tz)
            if bad:
                st.error(t("err_settings", items=", ".join(bad)))
            else:
                values = {"lookahead_days": int(look), "max_working_days": int(maxwd), "timezone": tz.strip(),
                          "holidays": sorted(set(days))}
                if safe_write(ctx, lambda: write_event(ctx.store, "settings", {"values": values}, ctx.user.username,
                                                       "settings"), t("settings_saved")):
                    st.rerun()
    st.caption(t("data_location", where=ctx.store.label))
