"""Pruebas de la lógica de negocio (sin interfaz)."""

from datetime import date

import pytest

from core import config
from core.auth import authenticate, hash_password, load_users, dump_users, User, validate_new
from core.catalog import load_catalog
from core.events import initialize, write_event
from core.i18n import TEXTS
from core.project import build_project
from core.workdays import WorkCalendar
from storage.local_store import LocalStore

TODAY = date(2026, 10, 25)  # domingo


@pytest.fixture
def store(tmp_path):
    s = LocalStore(tmp_path / "data")
    initialize(s, "tester")
    return s


# ─── Calendario ───────────────────────────────────────────────────────────
def test_calendar_weekdays_only():
    cal = WorkCalendar.build(False, False, ["2026-10-28"])
    assert cal.count(date(2026, 10, 26), date(2026, 11, 1)) == 4  # lun–dom, sin festivo miércoles
    assert cal.shift(date(2026, 10, 30), 1) == date(2026, 11, 2)  # viernes +1 → lunes
    assert cal.shift(date(2026, 11, 2), -1) == date(2026, 10, 30)
    assert cal.delay(date(2026, 10, 30), date(2026, 11, 3)) == 2


def test_calendar_weekend_enabled():
    cal = WorkCalendar.build(True, True, [])
    assert cal.count(date(2026, 10, 26), date(2026, 11, 1)) == 7


# ─── Datos de origen ──────────────────────────────────────────────────────
def test_catalog_counts():
    cat = load_catalog()
    assert cat.groupby("sop").size().to_dict() == {"HA": 23, "LHS": 20, "LS": 18, "MF": 19, "NC": 17}
    cond = set(cat[cat.conditional].task_id)
    assert {"NC-005", "NC-009", "MF-007", "MF-012", "LHS-009", "LHS-011"} <= cond
    assert "LS-009" not in cond  # "preheat condicional" no es una tarea condicional


def test_baseline_has_12_trucks(store):
    p = build_project(store.snapshot(), today=TODAY)
    assert len(p.trucks) == 12
    counts = p.activities.groupby("truck").size()
    assert counts["RD220"] == 6 and counts["RD221"] == 6 and counts["RD224"] == 8


# ─── Avance ───────────────────────────────────────────────────────────────
def test_sop_progress_excludes_na(store):
    updates = [{"task_id": "NC-001", "status": "done"}] + [
        {"task_id": f"NC-00{i}", "status": "na"} for i in range(5, 10)
    ]
    write_event(store, "task", {"truck": "RD224", "act": "nose_cone", "updates": updates}, "sup")
    p = build_project(store.snapshot(), today=TODAY)
    act = p.activities.set_index(["truck", "act_key"]).loc[("RD224", "nose_cone")]
    assert act.progress == pytest.approx(1 / 12)  # 17 tareas − 5 N/A = 12 aplicables
    assert act.has_records


def test_lhs_activity_uses_two_sops(store):
    p = build_project(store.snapshot(), today=TODAY)
    t = p.tasks[(p.tasks.truck == "RD224") & (p.tasks.act_key == "lhs_seat")]
    assert set(t.sop) == {"LS", "LHS"} and len(t) == 38
    assert t.iloc[0].task_id == "LS-001"


def test_latest_record_wins_and_manual_progress(store):
    write_event(store, "task", {"truck": "RD224", "act": "high_arch",
                                "updates": [{"task_id": "HA-001", "status": "in_progress", "actual_mh": 1}]}, "a")
    write_event(store, "task", {"truck": "RD224", "act": "high_arch",
                                "updates": [{"task_id": "HA-001", "status": "done", "actual_mh": 3}]}, "b")
    write_event(store, "task", {"truck": "RD224", "act": "trailing_lower",
                                "updates": [{"task_id": config.ACTIVITY_TASK_ID, "progress": 40, "actual_mh": 5}]}, "a")
    p = build_project(store.snapshot(), today=TODAY)
    ha = p.tasks[(p.tasks.truck == "RD224") & (p.tasks.task_id == "HA-001")].iloc[0]
    assert ha.status == "done" and ha.actual_mh == 3 and ha.user == "b"
    acts = p.activities.set_index(["truck", "act_key"])
    assert acts.loc[("RD224", "trailing_lower")].progress == pytest.approx(0.4)
    assert p.truck_row("RD224").actual_mh == pytest.approx(8)


def test_imported_progress_until_first_record(store):
    p = build_project(store.snapshot(), today=TODAY)
    assert p.truck_row("RD220").status == "completed"
    assert p.truck_row("RD220").progress == 1


# ─── Plan y visibilidad ───────────────────────────────────────────────────
def test_visibility_and_plan_change(store):
    p = build_project(store.snapshot(), today=TODAY)
    assert p.truck_row("RD231").status == "future"
    assert "RD231" not in p.visible_trucks()
    write_event(store, "plan", {"truck": "RD224", "reason": "test",
                                "changes": [{"act": "lhs_seat", "fc_start": "2026-11-16", "fc_end": "2026-11-17"}]}, "admin")
    p = build_project(store.snapshot(), today=TODAY)
    a = p.activities.set_index(["truck", "act_key"]).loc[("RD224", "lhs_seat")]
    assert a.fc_end == date(2026, 11, 17) and a.base_end == date(2026, 11, 12)  # el original no cambia
    assert a.delay_wd == 3
    assert len(p.plan_log) == 1


def test_trunnion_alert_and_ack(store):
    p = build_project(store.snapshot(), today=TODAY)
    assert any(a["type"] == "trunnion" and a["truck"] == "RD224" for a in p.alerts())
    write_event(store, "ack", {"truck": "RD224", "note": "PO 123"}, "admin")
    p = build_project(store.snapshot(), today=TODAY)
    assert not any(a["type"] == "trunnion" and a["truck"] == "RD224" for a in p.alerts())


def test_weekend_affects_work_days(store):
    p = build_project(store.snapshot(), today=TODAY)
    before = p.truck_row("RD224").work_days
    write_event(store, "plan", {"truck": "RD224", "weekend": {"sat": True, "sun": False}, "changes": [], "reason": "x"}, "a")
    p = build_project(store.snapshot(), today=TODAY)
    assert p.truck_row("RD224").work_days == before + 1  # el ensamble del sábado 14-nov ahora cuenta


def test_corrupt_event_is_ignored(store):
    store.write("log/task/2026-10/broken.json", b"{not json", "x")
    build_project(store.snapshot(), today=TODAY)



# ─── Alcance: camiones, actividades y tareas SOP ──────────────────────────
def test_scope_add_remove_activities_and_tasks(store):
    write_event(store, "scope", {"op": "new_activity", "act": "cx_cleaning", "name": "Cleaning", "external": False,
                                 "trucks": ["RD224", "RD225"], "start": "2026-11-20", "end": "2026-11-20"}, "admin")
    write_event(store, "scope", {"op": "remove_activity", "truck": "RD224", "act": "trailing_lower"}, "admin")
    write_event(store, "scope", {"op": "set_tasks", "truck": "RD224", "act": "nose_cone",
                                 "tasks": ["NC-001", "NC-002"]}, "admin")
    write_event(store, "task", {"truck": "RD224", "act": "nose_cone",
                                "updates": [{"task_id": "NC-001", "status": "done"}]}, "sup")
    p = build_project(store.snapshot(), today=TODAY)
    acts = p.activities.set_index(["truck", "act_key"])
    assert ("RD224", "cx_cleaning") in acts.index and ("RD225", "cx_cleaning") in acts.index
    assert ("RD226", "cx_cleaning") not in acts.index
    assert ("RD224", "trailing_lower") not in acts.index
    assert acts.loc[("RD224", "cx_cleaning")].fc_end == date(2026, 11, 20)
    assert acts.loc[("RD224", "nose_cone")].progress == pytest.approx(0.5)
    assert config.activity("cx_cleaning").name == "Cleaning"
    assert p.activities[p.activities.truck == "RD224"].order.max() == len(config.ACTIVITIES)
    # Una actividad agregada después recibe fechas del plan
    write_event(store, "scope", {"op": "add_activity", "truck": "RD224", "act": "trailing_lower"}, "admin")
    write_event(store, "plan", {"truck": "RD224", "reason": "x", "changes": [
        {"act": "trailing_lower", "fc_start": "2026-11-18", "fc_end": "2026-11-18"}]}, "admin")
    p = build_project(store.snapshot(), today=TODAY)
    assert p.activities.set_index(["truck", "act_key"]).loc[("RD224", "trailing_lower")].fc_end == date(2026, 11, 18)


def test_scope_add_truck(store):
    write_event(store, "scope", {"op": "add_truck", "truck": "RD240", "acts": [
        {"act": "high_arch", "tasks": ["HA-001", "HA-002", "HA-003"]}, {"act": "trailing_lower", "tasks": None}]}, "a")
    p = build_project(store.snapshot(), today=TODAY)
    assert len(p.trucks) == 13
    assert p.truck_row("RD240").status == "no_dates"
    assert "RD240" in p.visible_trucks()
    assert len(p.tasks[p.tasks.truck == "RD240"]) == 3
    assert any(a["type"] == "missing_dates" and a["truck"] == "RD240" for a in p.alerts())
    write_event(store, "scope", {"op": "remove_truck", "truck": "RD240"}, "a")
    write_event(store, "scope", {"op": "remove_truck", "truck": "RD231"}, "a")
    p = build_project(store.snapshot(), today=TODAY)
    assert len(p.trucks) == 11 and "RD240" not in set(p.trucks.truck) and "RD231" not in set(p.activities.truck)

# ─── Usuarios ─────────────────────────────────────────────────────────────
def test_users_roundtrip_and_auth():
    users = {"ana": User("ana", "Ana", "supervisor", hash_password("password1"))}
    loaded = load_users({"users/users.json": dump_users(users)})
    assert authenticate(loaded, "ANA ", "password1").name == "Ana"
    assert authenticate(loaded, "ana", "wrong") is None
    loaded["ana"].active = False
    assert authenticate(loaded, "ana", "password1") is None
    assert validate_new("A b", "password1") == "err_username"
    assert validate_new("bob", "short") == "err_password_short"


def test_master_account():
    from core.auth import master_account
    master = master_account({"master": {"username": "Boss", "password_hash": hash_password("boss-pass")}})
    assert authenticate({}, "boss", "boss-pass", master).is_master
    assert authenticate({}, "boss", "wrong", master) is None
    assert master_account({}) is None


# ─── Textos ───────────────────────────────────────────────────────────────
def test_every_dynamic_key_is_translated():
    keys = [f"act_{a.key}" for a in config.ACTIVITIES]
    keys += [f"ts_{s}" for s in config.TASK_STATUSES] + [f"qc_{s}" for s in config.QC_RESULTS]
    keys += [f"dc_{c}" for c in config.DELAY_CATEGORIES] + [f"role_{r}" for r in config.ROLES]
    keys += [f"st_{s}" for s in config.STATUS_COLORS] + ["st_not_started"]
    missing = [k for k in keys if k not in TEXTS]
    assert not missing
    assert all(len(v) == 2 and v[0] and v[1] for v in TEXTS.values())
