"""Feiertage & Sondertage laden — bulk load for years 2023-2036."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from datetime import date, timedelta
import pandas as pd

require_db()
conn = get_conn()
st.title("Feiertage & Sondertage laden")
st.caption(f"Firma: **{get_gmbh()}**")

BUNDESLAENDER = ["BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
                 "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"]

RAMADAN = {
    2023: ("2023-03-23", "2023-04-21"),
    2024: ("2024-03-11", "2024-04-09"),
    2025: ("2025-03-01", "2025-03-30"),
    2026: ("2026-02-18", "2026-03-19"),
    2027: ("2027-02-07", "2027-03-08"),
    2028: ("2028-01-27", "2028-02-25"),
    2029: ("2029-01-15", "2029-02-13"),
    2030: ("2030-01-04", "2030-02-02"),
    2031: ("2030-12-25", "2031-01-23"),
    2032: ("2031-12-14", "2032-01-12"),
    2033: ("2032-12-02", "2033-01-01"),
    2034: ("2033-11-21", "2033-12-20"),
    2035: ("2034-11-11", "2034-12-10"),
    2036: ("2035-11-01", "2035-11-30"),
}

LOAD_YEARS = list(range(2023, 2037))


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


def _load_public_holidays_year(planjahr: int) -> list:
    import holidays as hol_lib
    vj = planjahr - 1
    plan_by_state: dict = {}
    vj_by_state: dict = {}
    for bl in BUNDESLAENDER:
        h_plan = hol_lib.country_holidays("DE", subdiv=bl, years=planjahr)
        h_vj = hol_lib.country_holidays("DE", subdiv=bl, years=vj)
        plan_by_state[bl] = {d2.isoformat(): n for d2, n in h_plan.items()}
        vj_by_state[bl] = {d2.isoformat(): n for d2, n in h_vj.items()}

    date_info: dict = {}
    for bl, hdict in plan_by_state.items():
        for iso, name in hdict.items():
            if iso not in date_info:
                date_info[iso] = {"name": name, "states": set()}
            date_info[iso]["states"].add(bl)

    vj_lookup: dict = {}
    for bl, hdict in vj_by_state.items():
        for iso, name in hdict.items():
            vj_lookup.setdefault(name, {})[bl] = iso

    result = []
    for iso, info in sorted(date_info.items()):
        name = info["name"]
        states = info["states"]
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
    """Generate Feiertagstage (day before/after) for each public holiday.

    - Sunday holiday: no Feiertagstage
    - Monday holiday: Saturday(-2), Sunday(-1), Tuesday(+1)
    - Other days: day before(-1), day after(+1)
    """
    result = []
    for row in holiday_rows:
        if row.get("art") != "feiertag":
            continue
        try:
            plan_d = date.fromisoformat(row["datum_plan"])
        except (ValueError, TypeError):
            continue

        wd = plan_d.weekday()  # 0=Mon, 6=Sun
        if wd == 6:
            continue
        elif wd == 0:
            offsets = [-2, -1, 1]  # Sat, Sun, Tue
        else:
            offsets = [-1, 1]

        vj_d = None
        if row.get("datum_vj"):
            try:
                vj_d = date.fromisoformat(row["datum_vj"])
            except (ValueError, TypeError):
                vj_d = None

        for offset in offsets:
            new_plan = plan_d + timedelta(days=offset)
            new_vj = (vj_d + timedelta(days=offset)).isoformat() if vj_d else None
            label = "Vortag" if offset < 0 else "Nachtag"
            result.append({
                "datum_plan": new_plan.isoformat(),
                "datum_vj": new_vj,
                "name": f"{row['name']} ({label})",
                "bundesland": row["bundesland"],
                "art": "feiertagstag",
            })
    return result


def _sondertage_rows_year(planjahr: int, with_muttertag: bool,
                          with_fasching: bool, with_ramadan: bool) -> list:
    rows = []
    vj = planjahr - 1

    if with_muttertag:
        mt_plan = _muttertag(planjahr)
        mt_vj = _muttertag(vj)
        rows.append({
            "datum_plan": mt_plan.isoformat(),
            "datum_referenz": mt_vj.isoformat(),
            "bezeichnung": "Muttertag",
            "methode": "referenz",
            "bundesland": "alle",
        })

    if with_fasching:
        ostern_plan = _easter(planjahr)
        ostern_vj = _easter(vj)
        fasching_days = [
            ("Weiberfastnacht", 52),
            ("Rosen-Freitag", 51),
            ("Faschings-Samstag", 50),
            ("Faschings-Sonntag", 49),
            ("Rosenmontag", 48),
            ("Fastnachtsdienstag", 47),
        ]
        for name, offset in fasching_days:
            rows.append({
                "datum_plan": (ostern_plan - timedelta(days=offset)).isoformat(),
                "datum_referenz": (ostern_vj - timedelta(days=offset)).isoformat(),
                "bezeichnung": name,
                "methode": "referenz",
                "bundesland": "alle",
            })

    if with_ramadan and planjahr in RAMADAN:
        start_iso, ende_iso = RAMADAN[planjahr]
        prev_ramadan = RAMADAN.get(planjahr - 1)
        ref_iso = prev_ramadan[0] if prev_ramadan else None
        rows.append({
            "datum_plan": start_iso,
            "datum_referenz": ref_iso,
            "bezeichnung": "Ramadan (ca.) Start",
            "methode": "referenz",
            "bundesland": "alle",
        })
        rows.append({
            "datum_plan": ende_iso,
            "datum_referenz": None,
            "bezeichnung": "Ramadan (ca.) Ende",
            "methode": "referenz",
            "bundesland": "alle",
        })
    return rows


def _load_all_years(years, with_feiertagstage, with_muttertag,
                    with_fasching, with_ramadan, replace_existing, conn_db) -> dict:
    all_ft = []
    all_st = []
    for yr in years:
        ft_rows = _load_public_holidays_year(yr)
        all_ft.extend(ft_rows)
        if with_feiertagstage:
            all_ft.extend(_feiertagstage_rows(ft_rows))
        all_st.extend(_sondertage_rows_year(yr, with_muttertag, with_fasching, with_ramadan))

    if replace_existing:
        for yr in years:
            conn_db.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
            conn_db.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
        if with_ramadan:
            for yr in years:
                if yr in RAMADAN:
                    start_yr = RAMADAN[yr][0][:4]
                    if start_yr != str(yr):
                        conn_db.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?",
                                       (f"{start_yr}-%",))

    for row in all_ft:
        conn_db.execute("""
            INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art)
            VALUES (:datum_plan, :datum_vj, :name, :bundesland, :art)
        """, row)
    for row in all_st:
        conn_db.execute("""
            INSERT OR IGNORE INTO sondertage (datum_plan, datum_referenz, bezeichnung, methode, bundesland)
            VALUES (:datum_plan, :datum_referenz, :bezeichnung, :methode, :bundesland)
        """, row)
    conn_db.commit()
    return {"feiertage": len(all_ft), "sondertage": len(all_st)}


# ── Section 1: Auto-Load ────────────────────────────────────────────────────────────
st.subheader("1. Automatisch laden")

col_opt1, col_opt2 = st.columns([2, 2])
with col_opt1:
    with_feiertagstage = st.checkbox("Feiertagstage (Vor-/Nachtage) laden", value=True,
        help="Für jeden Feiertag werden der Vor- und Nachtag als 'feiertagstag' markiert.")
    with_muttertag = st.checkbox("Muttertag als Sondertag", value=True)
    with_fasching = st.checkbox("Fasching (Do–Di) als Sondertage", value=True,
        help="Lädt alle 6 Fasching-Tage von Weiberfastnacht bis Fastnachtsdienstag.")
with col_opt2:
    with_ramadan = st.checkbox("Ramadan (ca.) als Sondertage", value=False,
        help="Ungenähre Ramadan-Daten (ca.) für 2023–2036. "
             "Nur aktivieren wenn Ramadan-Filialen betroffen sind.")
    replace_existing = st.checkbox("Bestehende Einträge ersetzen", value=True)

st.caption(f"Jahre: {LOAD_YEARS[0]} – {LOAD_YEARS[-1]} ({len(LOAD_YEARS)} Jahre)")

if st.button("\U0001f504 Alle Jahre laden (2023–2036)", type="primary"):
    with st.spinner("Lade Feiertage für alle Jahre ..."):
        try:
            counts = _load_all_years(
                LOAD_YEARS, with_feiertagstage, with_muttertag,
                with_fasching, with_ramadan, replace_existing, conn
            )
            st.success(
                f"✅ Geladen: {counts['feiertage']} Feiertag-Einträge und "
                f"{counts['sondertage']} Sondertag-Einträge für {len(LOAD_YEARS)} Jahre."
            )
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()

# ── Section 2: Gespeicherte Feiertage (filterable + editable) ────────────────────
st.subheader("2. Gespeicherte Feiertage")

existing_ft = pd.read_sql(
    "SELECT id, datum_plan, datum_vj, name, bundesland, art FROM feiertage ORDER BY datum_plan, bundesland",
    conn,
)

if existing_ft.empty:
    st.info("Noch keine Feiertage hinterlegt.")
else:
    jahre_ft = sorted(
        pd.to_datetime(existing_ft["datum_plan"], errors="coerce")
        .dt.year.dropna().unique().astype(int), reverse=True
    )
    col_fj, col_art = st.columns([1, 1])
    with col_fj:
        filter_jahr = st.selectbox("Jahr", jahre_ft, key="ft_view_jahr")
    with col_art:
        filter_art = st.selectbox("Art", ["alle", "feiertag", "feiertagstag"], key="ft_view_art")

    subset_ft = existing_ft[existing_ft["datum_plan"].str.startswith(str(filter_jahr))]
    if filter_art != "alle":
        subset_ft = subset_ft[subset_ft["art"] == filter_art]

    edited_ft = st.data_editor(
        subset_ft.drop(columns=["id"]).reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
        key="ft_editor",
        height=350,
    )
    st.caption(f"{len(subset_ft)} Einträge für {filter_jahr}"
               + (f" / {filter_art}" if filter_art != "alle" else ""))

    if st.button("\U0001f4be Feiertage-Änderungen speichern", key="save_ft"):
        # Re-map by original id stored in subset_ft
        orig_ids = subset_ft["id"].tolist()
        for i, row in edited_ft.iterrows():
            if i < len(orig_ids):
                conn.execute(
                    "UPDATE feiertage SET datum_plan=?, datum_vj=?, name=?, bundesland=?, art=? WHERE id=?",
                    (row["datum_plan"], row.get("datum_vj"), row["name"],
                     row["bundesland"], row.get("art", "feiertag"), int(orig_ids[i]))
                )
        conn.commit()
        st.success("✅ Feiertage gespeichert.")
        st.rerun()

st.divider()

# ── Section 3: Sondertage (filterable + editable) ──────────────────────────────
st.subheader("3. Sondertage")

existing_st = pd.read_sql(
    "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland "
    "FROM sondertage ORDER BY datum_plan",
    conn,
)

if existing_st.empty:
    st.info("Noch keine Sondertage hinterlegt.")
else:
    jahre_st = sorted(
        pd.to_datetime(existing_st["datum_plan"], errors="coerce")
        .dt.year.dropna().unique().astype(int), reverse=True
    )
    filter_jahr_st = st.selectbox("Jahr", jahre_st, key="st_view_jahr")
    subset_st = existing_st[existing_st["datum_plan"].str.startswith(str(filter_jahr_st))]

    edited_st = st.data_editor(
        subset_st.drop(columns=["id"]).reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
        key="st_editor",
        height=300,
    )
    st.caption(f"{len(subset_st)} Einträge für {filter_jahr_st}")

    if st.button("\U0001f4be Sondertage-Änderungen speichern", key="save_st"):
        orig_ids = subset_st["id"].tolist()
        for i, row in edited_st.iterrows():
            if i < len(orig_ids):
                conn.execute(
                    "UPDATE sondertage SET datum_plan=?, datum_referenz=?, bezeichnung=?, methode=?, bundesland=? WHERE id=?",
                    (row["datum_plan"], row.get("datum_referenz"), row["bezeichnung"],
                     row.get("methode", "referenz"), row["bundesland"], int(orig_ids[i]))
                )
        conn.commit()
        st.success("✅ Sondertage gespeichert.")
        st.rerun()

st.divider()

# ── Section 4: Schulferien ─────────────────────────────────────────────────────────────
st.subheader("4. Schulferien")

st.info(
    "Schulferien werden für die Schulfilialen-Erkennung benötigt. "
    "Versuche, Schulferien über die holidays-Bibliothek zu laden. "
    "Falls nicht verfügbar, bitte manuell in der Tabelle unten eintragen."
)

col_sf1, col_sf2 = st.columns([1, 1])
with col_sf1:
    sf_year = st.number_input("Jahr", min_value=2023, max_value=2036,
                               value=date.today().year, step=1, key="sf_year")
with col_sf2:
    sf_bl = st.selectbox("Bundesland", BUNDESLAENDER, key="sf_bl")

if st.button("Schulferien laden", key="load_schulferien"):
    try:
        import holidays as hol_lib
        school_hols = None
        try:
            school_hols = hol_lib.country_holidays(
                "DE", subdiv=sf_bl, years=sf_year,
                categories=(hol_lib.SCHOOL,)
            )
        except (AttributeError, NotImplementedError, TypeError):
            school_hols = None

        if not school_hols:
            st.info(
                "Die holidays-Bibliothek liefert für dieses Bundesland/Jahr keine Schulferien. "
                "Bitte Schulferien manuell in der Tabelle unten eintragen."
            )
        else:
            by_name: dict = {}
            for d2, name in school_hols.items():
                by_name.setdefault(name, []).append(d2)
            inserted = 0
            for name, dates in by_name.items():
                dates_sorted = sorted(dates)
                start_d = dates_sorted[0].isoformat()
                end_d = dates_sorted[-1].isoformat()
                conn.execute("""
                    INSERT OR IGNORE INTO ferien_kalender
                        (bundesland, art, jahr, start, ende)
                    VALUES (?,?,?,?,?)
                """, (sf_bl, name, sf_year, start_d, end_d))
                inserted += 1
            conn.commit()
            st.success(f"✅ {inserted} Schulferienperioden für {sf_bl} {sf_year} gespeichert.")
    except Exception as e:
        st.error(f"Fehler: {e}")

fk_df = pd.read_sql(
    "SELECT id, bundesland, art, jahr, start, ende FROM ferien_kalender ORDER BY jahr, bundesland, start",
    conn,
)

st.markdown("**Schulferien-Kalender** (bearbeitbar — neue Zeilen am Ende anhängen):")
edited_fk = st.data_editor(
    fk_df.drop(columns=["id"]) if not fk_df.empty else pd.DataFrame(
        columns=["bundesland", "art", "jahr", "start", "ende"]
    ),
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    key="fk_editor",
    column_config={
        "bundesland": st.column_config.SelectboxColumn("Bundesland", options=BUNDESLAENDER + ["alle"]),
        "art": st.column_config.TextColumn("Art (z.B. Sommerferien)"),
        "jahr": st.column_config.NumberColumn("Jahr", min_value=2020, max_value=2040, step=1),
        "start": st.column_config.TextColumn("Start (YYYY-MM-DD)"),
        "ende": st.column_config.TextColumn("Ende (YYYY-MM-DD)"),
    },
)

if st.button("\U0001f4be Schulferien-Kalender speichern", key="save_fk"):
    conn.execute("DELETE FROM ferien_kalender")
    for _, row in edited_fk.iterrows():
        bl = str(row.get("bundesland") or "").strip()
        art = str(row.get("art") or "").strip()
        if not bl or not art:
            continue
        try:
            jahr = int(row.get("jahr") or 0)
        except (ValueError, TypeError):
            continue
        start = str(row.get("start") or "").strip()
        ende = str(row.get("ende") or "").strip()
        if not start or not ende:
            continue
        conn.execute("""
            INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende)
            VALUES (?,?,?,?,?)
        """, (bl, art, jahr, start, ende))
    conn.commit()
    st.success("✅ Schulferien-Kalender gespeichert.")
    st.rerun()
