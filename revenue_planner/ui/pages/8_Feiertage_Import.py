"""Feiertage und Ferien laden — für Basiszeitraum + Budgetjahr."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from datetime import date, timedelta
import pandas as pd

require_db()
conn = get_conn()
planjahr = get_budgetjahr()
vj = planjahr - 1

st.title("Feiertage und Ferien laden")
st.caption(f"Firma: **{get_gmbh()}** · Budgetjahr: **{planjahr}** · Vorjahr (Basis): **{vj}**")

BUNDESLAENDER = ["BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
                 "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"]

RAMADAN = {
    2023: ("2023-03-23", "2023-04-21"), 2024: ("2024-03-11", "2024-04-09"),
    2025: ("2025-03-01", "2025-03-30"), 2026: ("2026-02-18", "2026-03-19"),
    2027: ("2027-02-07", "2027-03-08"), 2028: ("2028-01-27", "2028-02-25"),
    2029: ("2029-01-15", "2029-02-13"), 2030: ("2030-01-04", "2030-02-02"),
    2031: ("2030-12-25", "2031-01-23"), 2032: ("2031-12-14", "2032-01-12"),
    2033: ("2032-12-02", "2033-01-01"), 2034: ("2033-11-21", "2033-12-20"),
    2035: ("2034-11-11", "2034-12-10"), 2036: ("2035-11-01", "2035-11-30"),
}


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _muttertag(year: int) -> date:
    d = date(year, 5, 1)
    sundays = [d + timedelta(days=i) for i in range(31)
               if (d + timedelta(days=i)).month == 5
               and (d + timedelta(days=i)).weekday() == 6]
    return sundays[1]


def _load_public_holidays_year(plan_yr: int) -> list:
    import holidays as hol_lib
    base_yr = plan_yr - 1
    plan_by_state, vj_by_state = {}, {}
    for bl in BUNDESLAENDER:
        plan_by_state[bl] = {d2.isoformat(): n for d2, n in
                             hol_lib.country_holidays("DE", subdiv=bl, years=plan_yr).items()}
        vj_by_state[bl]   = {d2.isoformat(): n for d2, n in
                             hol_lib.country_holidays("DE", subdiv=bl, years=base_yr).items()}

    date_info: dict = {}
    for bl, hdict in plan_by_state.items():
        for iso, name in hdict.items():
            date_info.setdefault(iso, {"name": name, "states": set()})["states"].add(bl)

    vj_lookup: dict = {}
    for bl, hdict in vj_by_state.items():
        for iso, name in hdict.items():
            vj_lookup.setdefault(name, {})[bl] = iso

    result = []
    for iso, info in sorted(date_info.items()):
        name, states = info["name"], info["states"]
        if len(states) == len(BUNDESLAENDER):
            vj_date = next((vj_lookup.get(name, {}).get(bl) for bl in BUNDESLAENDER
                            if vj_lookup.get(name, {}).get(bl)), None)
            result.append({"datum_plan": iso, "datum_vj": vj_date,
                           "name": name, "bundesland": "alle", "art": "feiertag"})
        else:
            for bl in sorted(states):
                vj_date = vj_lookup.get(name, {}).get(bl)
                result.append({"datum_plan": iso, "datum_vj": vj_date,
                               "name": name, "bundesland": bl, "art": "feiertag"})
    return result


def _feiertagstage_rows(holiday_rows: list) -> list:
    result = []
    for row in holiday_rows:
        if row.get("art") != "feiertag":
            continue
        try:
            plan_d = date.fromisoformat(row["datum_plan"])
        except (ValueError, TypeError):
            continue
        wd = plan_d.weekday()
        if wd == 6:
            continue
        offsets = [-2, -1, 1] if wd == 0 else [-1, 1]
        vj_d = None
        if row.get("datum_vj"):
            try:
                vj_d = date.fromisoformat(row["datum_vj"])
            except (ValueError, TypeError):
                vj_d = None
        for offset in offsets:
            new_plan = plan_d + timedelta(days=offset)
            new_vj = (vj_d + timedelta(days=offset)).isoformat() if vj_d else None
            result.append({
                "datum_plan": new_plan.isoformat(), "datum_vj": new_vj,
                "name": "Feiertagstag", "bundesland": row["bundesland"], "art": "feiertagstag",
            })
    return result


def _sondertage_rows(plan_yr: int, with_muttertag, with_fasching, with_ramadan) -> list:
    rows = []
    base_yr = plan_yr - 1
    if with_muttertag:
        rows.append({"datum_plan": _muttertag(plan_yr).isoformat(),
                     "datum_referenz": _muttertag(base_yr).isoformat(),
                     "bezeichnung": "Muttertag", "methode": "referenz", "bundesland": "alle"})
    if with_fasching:
        ostern_p = _easter(plan_yr)
        ostern_v = _easter(base_yr)
        for name, offset in [("Weiberfastnacht", 52), ("Rosen-Freitag", 51),
                              ("Faschings-Samstag", 50), ("Faschings-Sonntag", 49),
                              ("Rosenmontag", 48), ("Fastnachtsdienstag", 47)]:
            rows.append({"datum_plan": (ostern_p - timedelta(days=offset)).isoformat(),
                         "datum_referenz": (ostern_v - timedelta(days=offset)).isoformat(),
                         "bezeichnung": name, "methode": "referenz", "bundesland": "alle"})
    if with_ramadan and plan_yr in RAMADAN:
        s, e = RAMADAN[plan_yr]
        prev = RAMADAN.get(plan_yr - 1)
        rows.append({"datum_plan": s, "datum_referenz": prev[0] if prev else None,
                     "bezeichnung": "Ramadan (ca.) Start", "methode": "referenz", "bundesland": "alle"})
        rows.append({"datum_plan": e, "datum_referenz": None,
                     "bezeichnung": "Ramadan (ca.) Ende", "methode": "referenz", "bundesland": "alle"})
    return rows


def _rebuild_ferien_from_kalender(conn_db, plan_yr: int):
    """Rebuild ferien table for plan_yr using ferien_kalender pairs (VJ + plan year)."""
    base_yr = plan_yr - 1
    vj_map = {(r["bundesland"], r["art"]): (r["start"], r["ende"])
              for r in conn_db.execute(
                  "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
                  (base_yr,)).fetchall()}
    plan_entries = conn_db.execute(
        "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        (plan_yr,)
    ).fetchall()
    conn_db.execute(
        "DELETE FROM ferien WHERE CAST(strftime('%Y', start_plan) AS INTEGER)=?", (plan_yr,)
    )
    for r in plan_entries:
        bl, art = r["bundesland"], r["art"]
        vj_dates = vj_map.get((bl, art))
        if not vj_dates:
            continue
        conn_db.execute(
            "INSERT INTO ferien (bundesland, art, start_vj, ende_vj, start_plan, ende_plan) "
            "VALUES (?,?,?,?,?,?)",
            (bl, art, vj_dates[0], vj_dates[1], r["start"], r["ende"])
        )
    conn_db.commit()


def _auto_datumsmapping(conn_db, plan_yr: int) -> str:
    try:
        from planning.engine import PlanningEngine, PlanParams
        from planning.datumsmapping import generate_datumsmapping
        par_row = conn_db.execute(
            "SELECT * FROM parameter WHERE planjahr=?", (plan_yr,)
        ).fetchone()
        params = PlanParams(
            planjahr=plan_yr,
            preiserhoehung_pct=float(par_row["preiserhoehung_pct"] or 0) if par_row else 0,
            ferien_puffer_wochen=int(par_row["ferien_puffer_wochen"] or 2) if par_row else 2,
        )
        engine = PlanningEngine(conn_db, params)
        n = generate_datumsmapping(conn_db, plan_yr, engine)
        return f"Datumsmapping: {n:,} Zeilen aktualisiert."
    except Exception as ex:
        return f"Datumsmapping-Fehler: {ex}"


# ── Abschnitt 1: Laden ───────────────────────────────────────────────────────
st.subheader("1. Feiertage, Sondertage und Ferien laden")
st.caption(f"Lädt Daten für Budgetjahr **{planjahr}** und Basisjahr **{vj}**.")

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    with_feiertagstage = st.checkbox("Feiertagstage (Vor-/Nachtage) laden", value=True)
    with_muttertag     = st.checkbox("Muttertag als Sondertag", value=True)
    with_fasching      = st.checkbox("Fasching (Do–Di) als Sondertage", value=True)
with col_opt2:
    with_ramadan       = st.checkbox("Ramadan (ca.) als Sondertage", value=False)
    replace_existing   = st.checkbox("Bestehende Einträge ersetzen", value=True)

if st.button("🔄 Feiertage, Sondertage und Ferien laden", type="primary"):
    with st.spinner("Lade …"):
        try:
            load_years = [vj, planjahr]
            all_ft, all_st = [], []
            for yr in load_years:
                ft_rows = _load_public_holidays_year(yr)
                all_ft.extend(ft_rows)
                if with_feiertagstage:
                    all_ft.extend(_feiertagstage_rows(ft_rows))
                all_st.extend(_sondertage_rows(yr, with_muttertag, with_fasching, with_ramadan))

            if replace_existing:
                for yr in load_years:
                    conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
                    conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{yr}-%",))

            for row in all_ft:
                conn.execute(
                    "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                    "VALUES (:datum_plan, :datum_vj, :name, :bundesland, :art)", row)
            for row in all_st:
                conn.execute(
                    "INSERT OR IGNORE INTO sondertage "
                    "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                    "VALUES (:datum_plan, :datum_referenz, :bezeichnung, :methode, :bundesland)", row)
            conn.commit()

            _rebuild_ferien_from_kalender(conn, planjahr)
            dm_msg = _auto_datumsmapping(conn, planjahr)

            st.success(
                f"✅ Geladen: {len(all_ft)} Feiertag-Einträge, "
                f"{len(all_st)} Sondertage für Jahre {vj}+{planjahr}.  \n{dm_msg}"
            )
            st.rerun()
        except Exception as e:
            st.error(f"Fehler: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()

# ── Abschnitt 2: Gespeicherte Feiertage, Sondertage und Ferien ───────────────
st.subheader("2. Gespeicherte Feiertage, Sondertage und Ferien")

# Jahresfilter gemeinsam oben
all_jahre = sorted(set(
    [r[0] for r in conn.execute(
        "SELECT DISTINCT CAST(substr(datum_plan,1,4) AS INTEGER) FROM feiertage"
    ).fetchall()] +
    [r[0] for r in conn.execute(
        "SELECT DISTINCT CAST(substr(datum_plan,1,4) AS INTEGER) FROM sondertage"
    ).fetchall()] +
    [r[0] for r in conn.execute(
        "SELECT DISTINCT jahr FROM ferien_kalender"
    ).fetchall()]
), reverse=True) or [planjahr]

filter_jahr = st.selectbox("Jahr anzeigen", options=all_jahre, key="ft_jahr_global")

tab_ft, tab_st, tab_fer = st.tabs(["Feiertage", "Sondertage", "Ferien"])

# ── Tab Feiertage ──
with tab_ft:
    filter_art = st.selectbox("Art", ["alle", "feiertag", "feiertagstag"], key="ft_art_filter")

    ft_all = pd.read_sql(
        "SELECT id, datum_plan, datum_vj, name, bundesland, art FROM feiertage "
        "WHERE datum_plan LIKE ? ORDER BY datum_plan, bundesland",
        conn, params=(f"{filter_jahr}-%",)
    )
    if filter_art != "alle":
        ft_all = ft_all[ft_all["art"] == filter_art]

    ft_orig = ft_all.drop(columns=["id"]).reset_index(drop=True)

    edited_ft = st.data_editor(
        ft_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"ft_editor_{filter_jahr}_{filter_art}",
        height=350,
        column_config={
            "datum_plan": st.column_config.TextColumn("Datum Plan (YYYY-MM-DD)"),
            "datum_vj":   st.column_config.TextColumn("Datum VJ (YYYY-MM-DD)"),
            "art":        st.column_config.SelectboxColumn("Art", options=["feiertag", "feiertagstag"]),
            "bundesland": st.column_config.TextColumn("Bundesland"),
        },
    )
    st.caption(f"{len(ft_orig)} Einträge für {filter_jahr}")

    if not ft_orig.astype(str).equals(edited_ft.astype(str)):
        # Delete existing for this year+art, then re-insert
        if filter_art == "alle":
            conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        else:
            conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ? AND art=?",
                         (f"{filter_jahr}-%", filter_art))
        for _, row in edited_ft.dropna(subset=["datum_plan", "name"]).iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                "VALUES (?,?,?,?,?)",
                (row.get("datum_plan"), row.get("datum_vj"), row.get("name"),
                 row.get("bundesland", "alle"), row.get("art", "feiertag"))
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Feiertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Sondertage ──
with tab_st:
    st_all = pd.read_sql(
        "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage "
        "WHERE datum_plan LIKE ? ORDER BY datum_plan",
        conn, params=(f"{filter_jahr}-%",)
    )
    st_orig = st_all.drop(columns=["id"]).reset_index(drop=True)

    edited_st = st.data_editor(
        st_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"st_editor_{filter_jahr}",
        height=350,
        column_config={
            "datum_plan":      st.column_config.TextColumn("Datum Plan (YYYY-MM-DD)"),
            "datum_referenz":  st.column_config.TextColumn("Datum Referenz (YYYY-MM-DD)"),
            "methode":         st.column_config.SelectboxColumn("Methode", options=["referenz", "samstag"]),
            "bundesland":      st.column_config.TextColumn("Bundesland"),
        },
    )
    st.caption(f"{len(st_orig)} Einträge für {filter_jahr}")

    if not st_orig.astype(str).equals(edited_st.astype(str)):
        conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        for _, row in edited_st.dropna(subset=["datum_plan", "bezeichnung"]).iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO sondertage "
                "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                "VALUES (?,?,?,?,?)",
                (row.get("datum_plan"), row.get("datum_referenz"), row.get("bezeichnung"),
                 row.get("methode", "referenz"), row.get("bundesland", "alle"))
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Sondertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Ferien ──
with tab_fer:
    st.caption(
        "Schulferien manuell eintragen. Für beide Jahre (Vorjahr + Budgetjahr) werden "
        "automatisch Ferienperioden für die Planung erstellt."
    )
    fk_all = pd.read_sql(
        "SELECT id, bundesland, art, jahr, start, ende FROM ferien_kalender "
        "WHERE jahr=? OR jahr=? ORDER BY jahr, bundesland, start",
        conn, params=(vj, planjahr)
    )
    fk_orig = fk_all.drop(columns=["id"]).reset_index(drop=True)

    edited_fk = st.data_editor(
        fk_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"fk_editor_{planjahr}",
        height=350,
        column_config={
            "bundesland": st.column_config.SelectboxColumn("Bundesland",
                                                            options=BUNDESLAENDER + ["alle"]),
            "art":   st.column_config.TextColumn("Art (z.B. Sommerferien)"),
            "jahr":  st.column_config.NumberColumn("Jahr", min_value=2020, max_value=2040, step=1),
            "start": st.column_config.TextColumn("Start (YYYY-MM-DD)"),
            "ende":  st.column_config.TextColumn("Ende (YYYY-MM-DD)"),
        },
    )
    st.caption(f"{len(fk_orig)} Einträge für {vj} + {planjahr}")

    if not fk_orig.astype(str).equals(edited_fk.astype(str)):
        conn.execute("DELETE FROM ferien_kalender WHERE jahr=? OR jahr=?", (vj, planjahr))
        for _, row in edited_fk.dropna(subset=["bundesland", "art"]).iterrows():
            try:
                jahr_val = int(row.get("jahr") or 0)
            except (ValueError, TypeError):
                continue
            bl  = str(row.get("bundesland") or "").strip()
            art = str(row.get("art") or "").strip()
            s   = str(row.get("start") or "").strip()
            e   = str(row.get("ende") or "").strip()
            if not bl or not art or not s or not e:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende) "
                "VALUES (?,?,?,?,?)", (bl, art, jahr_val, s, e)
            )
        conn.commit()
        _rebuild_ferien_from_kalender(conn, planjahr)
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Ferien gespeichert. {dm_msg}")
        st.rerun()
