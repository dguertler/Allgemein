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
st.caption(f"Firma: **{get_gmbh()}** · Budgetjahr: **{planjahr}** · Basiszeitraum (Vorjahr): **{vj}**")

BUNDESLAENDER = ["BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
                 "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"]

BL_ABBR_TO_NAME = {
    "BB": "Brandenburg", "BE": "Berlin", "BW": "Baden-Württemberg",
    "BY": "Bayern", "HB": "Bremen", "HE": "Hessen", "HH": "Hamburg",
    "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz", "SH": "Schleswig-Holstein", "SL": "Saarland",
    "SN": "Sachsen", "ST": "Sachsen-Anhalt", "TH": "Thüringen",
}
BL_NAME_LIST = list(BL_ABBR_TO_NAME.values())

WOCHENTAG_NAMEN = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _wt_name(d) -> str:
    """Return German weekday name for a date/Timestamp/str, or empty string."""
    if d is None:
        return ""
    try:
        import pandas as _pd
        if _pd.isna(d):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return WOCHENTAG_NAMEN[pd.Timestamp(d).weekday()]
    except Exception:
        return ""


def _bl_to_name(bl: str) -> str:
    if not bl or str(bl).strip().lower() == "alle":
        return "Alle"
    return BL_ABBR_TO_NAME.get(str(bl).strip(), str(bl).strip())


def _bl_to_abbr(name: str) -> str:
    n = str(name or "").strip()
    if not n or n.lower() == "alle":
        return "alle"
    for abbr, full in BL_ABBR_TO_NAME.items():
        if full == n:
            return abbr
    return n


def _iso(v):
    """Convert editor cell value (Timestamp/date/str) to YYYY-MM-DD string or None."""
    if v is None:
        return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _norm_for_compare(df: pd.DataFrame, date_cols: list) -> pd.DataFrame:
    """Normalize date columns to YYYY-MM-DD strings for stable DataFrame comparison."""
    out = df.copy()
    for c in date_cols:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.fillna("").astype(str)

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


def _load_public_holidays_year(plan_yr: int, bl_filter: list) -> list:
    import holidays as hol_lib
    base_yr = plan_yr - 1
    plan_by_state, vj_by_state = {}, {}
    for bl in bl_filter:
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
        if len(states) == len(bl_filter):
            vj_date = next((vj_lookup.get(name, {}).get(bl) for bl in bl_filter
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


def _extend_ferien_weekend(start: date, ende: date) -> tuple[date, date]:
    """Extend ferien period to include adjacent weekends.

    - If ferien END on Friday → extend to include Saturday + Sunday
    - If ferien END on Saturday → extend to include Sunday
    - If ferien START on Monday → extend back to include preceding Saturday + Sunday
    """
    # Extend end
    if ende.weekday() == 4:   # Friday → add Sat + Sun
        ende = ende + timedelta(days=2)
    elif ende.weekday() == 5:  # Saturday → add Sun
        ende = ende + timedelta(days=1)
    # Extend start
    if start.weekday() == 0:   # Monday → go back to preceding Saturday
        start = start - timedelta(days=2)
    return start, ende


def _load_schulferien_all_bl(years: list[int], bl_filter: list | None = None) -> list:
    """Load school holidays for given BL for given years from holidays library.
    Returns list of ferien_kalender rows (bundesland, art, jahr, start, ende)."""
    import holidays as hol_lib

    bls = bl_filter if bl_filter else BUNDESLAENDER
    result = []
    for yr in years:
        for bl in bls:
            try:
                school_hols = hol_lib.country_holidays(
                    "DE", subdiv=bl, years=yr, categories=(hol_lib.SCHOOL,)
                )
            except Exception:
                continue
            if not school_hols:
                continue

            # Group consecutive days with same name into date ranges
            by_name: dict[str, list[date]] = {}
            for d, name in school_hols.items():
                by_name.setdefault(name, []).append(d)

            for art, dates in by_name.items():
                dates = sorted(dates)
                # Consecutive = gap of at most 1 day (handles adjacent periods)
                start = dates[0]
                prev = dates[0]
                for d in dates[1:]:
                    if (d - prev).days <= 1:
                        prev = d
                    else:
                        start, prev = _extend_ferien_weekend(start, prev)
                        result.append({
                            "bundesland": bl, "art": art, "jahr": yr,
                            "start": start.isoformat(), "ende": prev.isoformat(),
                        })
                        start = d
                        prev = d
                start, prev = _extend_ferien_weekend(start, prev)
                result.append({
                    "bundesland": bl, "art": art, "jahr": yr,
                    "start": start.isoformat(), "ende": prev.isoformat(),
                })
    return result


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
        today_dm = date.today()
        stichtag_dm = date(today_dm.year, 1, 1) if plan_yr <= today_dm.year else today_dm
        params = PlanParams(
            planjahr=plan_yr,
            stichtag=stichtag_dm,
            preiserhoehung_pct=float(par_row["preiserhoehung_pct"] or 0) if par_row else 0,
            ferien_puffer_wochen=int(par_row["ferien_puffer_wochen"] or 2) if par_row else 2,
        )
        engine = PlanningEngine(conn_db, params)
        n = generate_datumsmapping(conn_db, plan_yr, engine)
        return f"Datumsmapping: {n:,} Zeilen aktualisiert."
    except Exception as ex:
        return f"Datumsmapping-Fehler: {ex}"


# ── Bundesländer aus Filialen-Stammdaten ermitteln ───────────────────────────
from planning.engine import _normalize_bl as _nbl
_fil_bl_rows = conn.execute(
    "SELECT DISTINCT bundesland FROM filialen WHERE bundesland IS NOT NULL AND bundesland != ''"
).fetchall()
_fil_bls_abbr = list(dict.fromkeys(
    _nbl(r["bundesland"]) for r in _fil_bl_rows if _nbl(r["bundesland"]) in BUNDESLAENDER
))
# Falls noch keine Filialen angelegt: alle 16 laden
AKTIVE_BL = _fil_bls_abbr if _fil_bls_abbr else BUNDESLAENDER
AKTIVE_BL_NAMES = [BL_ABBR_TO_NAME.get(b, b) for b in sorted(AKTIVE_BL)]

# ── Abschnitt 1: Laden ───────────────────────────────────────────────────────
st.subheader("1. Feiertage, Sondertage und Ferien laden")
if AKTIVE_BL == BUNDESLAENDER:
    st.caption(
        f"Lädt Feiertage, Sondertage und Schulferien für alle 16 Bundesländer — "
        f"Budgetjahr **{planjahr}** und Basiszeitraum **{vj}**."
    )
else:
    bl_names = ", ".join(BL_ABBR_TO_NAME.get(b, b) for b in sorted(AKTIVE_BL))
    st.info(
        f"Es werden nur Feiertage und Ferien für die **{len(AKTIVE_BL)} Bundesländer** geladen, "
        f"die in den Filialstammdaten hinterlegt sind: **{bl_names}**. "
        "Bundesländer ohne Filiale werden ausgelassen, um die Datenmenge zu reduzieren. "
        "Wenn Sie weitere Bundesländer benötigen, legen Sie bitte entsprechende Filialen an."
    )

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
                ft_rows = _load_public_holidays_year(yr, AKTIVE_BL)
                all_ft.extend(ft_rows)
                if with_feiertagstage:
                    all_ft.extend(_feiertagstage_rows(ft_rows))
                all_st.extend(_sondertage_rows(yr, with_muttertag, with_fasching, with_ramadan))

            # Schulferien nur für relevante BL laden
            schulferien_rows = _load_schulferien_all_bl(load_years, AKTIVE_BL)

            if replace_existing:
                for yr in load_years:
                    conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
                    conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
                    conn.execute("DELETE FROM ferien_kalender WHERE jahr=?", (yr,))

            for row in all_ft:
                conn.execute(
                    "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                    "VALUES (:datum_plan, :datum_vj, :name, :bundesland, :art)", row)
            for row in all_st:
                conn.execute(
                    "INSERT OR IGNORE INTO sondertage "
                    "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                    "VALUES (:datum_plan, :datum_referenz, :bezeichnung, :methode, :bundesland)", row)
            for row in schulferien_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende) "
                    "VALUES (:bundesland, :art, :jahr, :start, :ende)", row)
            conn.commit()

            _rebuild_ferien_from_kalender(conn, planjahr)
            dm_msg = _auto_datumsmapping(conn, planjahr)

            n_schulferien_bl = len({r["bundesland"] for r in schulferien_rows})
            st.success(
                f"✅ Geladen: {len(all_ft)} Feiertag-Einträge, "
                f"{len(all_st)} Sondertage, "
                f"{len(schulferien_rows)} Schulferienperioden ({n_schulferien_bl} Bundesländer) "
                f"für Jahre {vj}+{planjahr}.  \n{dm_msg}"
            )
            st.rerun()
        except Exception as e:
            st.error(f"Fehler: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()

# ── Abschnitt 2: Gespeicherte Feiertage, Sondertage und Ferien ───────────────
st.subheader("2. Gespeicherte Feiertage, Sondertage und Ferien")

filter_jahr = planjahr
st.caption(f"Angezeigt wird das Budgetjahr **{planjahr}**.")

tab_ft, tab_st, tab_fer = st.tabs(["Feiertage", "Sondertage", "Ferien"])

# ── Tab Feiertage ──
with tab_ft:
    fc1, fc2 = st.columns(2)
    with fc1:
        filter_art = st.selectbox("Art", ["alle", "Feiertag", "Feiertagstag"], key="ft_art_filter")
    with fc2:
        bl_options_ft = ["alle"] + AKTIVE_BL_NAMES
        filter_bl_ft = st.selectbox("Bundesland", bl_options_ft, key="ft_bl_filter")

    filter_art_raw = filter_art.lower()

    ft_all = pd.read_sql(
        "SELECT id, datum_plan, datum_vj, name, bundesland, art FROM feiertage "
        "WHERE datum_plan LIKE ? ORDER BY bundesland, datum_plan",
        conn, params=(f"{filter_jahr}-%",)
    )
    if filter_art_raw != "alle":
        ft_all = ft_all[ft_all["art"] == filter_art_raw]
    if filter_bl_ft != "alle":
        bl_abbr = _bl_to_abbr(filter_bl_ft)
        ft_all = ft_all[ft_all["bundesland"].isin([bl_abbr, "alle"])]

    ft_orig = ft_all.drop(columns=["id"]).reset_index(drop=True)
    # Bundesland als erste Spalte, dann datum_plan, dann rest
    ft_orig = ft_orig[["bundesland", "datum_plan", "datum_vj", "name", "art"]]
    ft_orig["datum_plan"] = pd.to_datetime(ft_orig["datum_plan"], errors="coerce")
    ft_orig["datum_vj"]   = pd.to_datetime(ft_orig["datum_vj"], errors="coerce")
    ft_orig["bundesland"] = ft_orig["bundesland"].apply(_bl_to_name)
    ft_orig["art"]        = ft_orig["art"].apply(lambda a: str(a).capitalize() if a else a)
    # Weekday display columns (read-only)
    ft_orig["wt_plan"] = ft_orig["datum_plan"].apply(_wt_name)
    ft_orig["wt_vj"]   = ft_orig["datum_vj"].apply(_wt_name)

    edited_ft = st.data_editor(
        ft_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"ft_editor_{filter_jahr}_{filter_art}_{filter_bl_ft}",
        height=350,
        column_config={
            "bundesland": st.column_config.SelectboxColumn("Bundesland",
                                                           options=["Alle"] + AKTIVE_BL_NAMES),
            "datum_plan": st.column_config.DateColumn("Datum Budget", format="DD.MM.YYYY"),
            "wt_plan":    st.column_config.TextColumn("Wochentag Budget", disabled=True),
            "datum_vj":   st.column_config.DateColumn("Datum Basiszeitraum", format="DD.MM.YYYY"),
            "wt_vj":      st.column_config.TextColumn("Wochentag Basis", disabled=True),
            "name":       st.column_config.TextColumn("Beschreibung"),
            "art":        st.column_config.SelectboxColumn("Art", options=["Feiertag", "Feiertagstag"]),
        },
    )
    st.caption(f"{len(ft_orig)} Einträge für {filter_jahr}")

    _date_cols_ft = ["datum_plan", "datum_vj"]
    _cmp_cols_ft = ["bundesland", "datum_plan", "datum_vj", "name", "art"]
    if not _norm_for_compare(ft_orig[_cmp_cols_ft], _date_cols_ft).equals(
            _norm_for_compare(edited_ft[_cmp_cols_ft], _date_cols_ft)):
        if filter_art_raw == "alle":
            conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        else:
            conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ? AND art=?",
                         (f"{filter_jahr}-%", filter_art_raw))
        for _, row in edited_ft.dropna(subset=["datum_plan", "name"]).iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                "VALUES (?,?,?,?,?)",
                (_iso(row.get("datum_plan")), _iso(row.get("datum_vj")), row.get("name"),
                 _bl_to_abbr(row.get("bundesland", "alle")),
                 str(row.get("art") or "feiertag").lower())
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Feiertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Sondertage ──
with tab_st:
    fc1_st, fc2_st = st.columns(2)
    with fc2_st:
        filter_bl_st = st.selectbox("Bundesland", ["alle"] + AKTIVE_BL_NAMES, key="st_bl_filter")

    st_all = pd.read_sql(
        "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage "
        "WHERE datum_plan LIKE ? ORDER BY bundesland, datum_plan",
        conn, params=(f"{filter_jahr}-%",)
    )
    if filter_bl_st != "alle":
        bl_abbr_st = _bl_to_abbr(filter_bl_st)
        st_all = st_all[st_all["bundesland"].isin([bl_abbr_st, "alle"])]

    st_orig = st_all.drop(columns=["id"]).reset_index(drop=True)
    st_orig = st_orig[["bundesland", "datum_plan", "datum_referenz", "bezeichnung", "methode"]]
    st_orig["datum_plan"]     = pd.to_datetime(st_orig["datum_plan"], errors="coerce")
    st_orig["datum_referenz"] = pd.to_datetime(st_orig["datum_referenz"], errors="coerce")
    st_orig["bundesland"]     = st_orig["bundesland"].apply(_bl_to_name)
    # Weekday display columns (read-only)
    st_orig["wt_plan"] = st_orig["datum_plan"].apply(_wt_name)
    st_orig["wt_ref"]  = st_orig["datum_referenz"].apply(_wt_name)

    edited_st = st.data_editor(
        st_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"st_editor_{filter_jahr}_{filter_bl_st}",
        height=350,
        column_config={
            "bundesland":      st.column_config.SelectboxColumn("Bundesland",
                                                                options=["Alle"] + AKTIVE_BL_NAMES),
            "datum_plan":      st.column_config.DateColumn("Datum Budget", format="DD.MM.YYYY"),
            "wt_plan":         st.column_config.TextColumn("Wochentag Budget", disabled=True),
            "datum_referenz":  st.column_config.DateColumn("Datum Basiszeitraum", format="DD.MM.YYYY"),
            "wt_ref":          st.column_config.TextColumn("Wochentag Basis", disabled=True),
            "bezeichnung":     st.column_config.TextColumn("Beschreibung"),
            "methode":         st.column_config.SelectboxColumn("Methode", options=["referenz", "samstag"]),
        },
    )
    st.caption(f"{len(st_orig)} Einträge für {filter_jahr}")

    _date_cols_st = ["datum_plan", "datum_referenz"]
    _cmp_cols_st = ["bundesland", "datum_plan", "datum_referenz", "bezeichnung", "methode"]
    if not _norm_for_compare(st_orig[_cmp_cols_st], _date_cols_st).equals(
            _norm_for_compare(edited_st[_cmp_cols_st], _date_cols_st)):
        conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        for _, row in edited_st.dropna(subset=["datum_plan", "bezeichnung"]).iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO sondertage "
                "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                "VALUES (?,?,?,?,?)",
                (_iso(row.get("datum_plan")), _iso(row.get("datum_referenz")),
                 row.get("bezeichnung"), row.get("methode", "referenz"),
                 _bl_to_abbr(row.get("bundesland", "alle")))
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Sondertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Ferien ──
with tab_fer:
    st.caption(
        "Schulferien je Bundesland — werden automatisch beim Laden-Button befüllt "
        "(Budgetjahr + Basiszeitraum für alle 16 Bundesländer). "
        "Manuelle Korrekturen hier möglich."
    )
    fc1_fer, fc2_fer = st.columns(2)
    with fc1_fer:
        filter_bl_fer = st.selectbox("Bundesland", ["alle"] + AKTIVE_BL_NAMES, key="fer_bl_filter")
    with fc2_fer:
        filter_jahr_fer = st.selectbox(
            "Jahr", [vj, planjahr],
            format_func=lambda y: f"{y} (Basiszeitraum)" if y == vj else f"{y} (Budgetjahr)",
            key="fer_jahr_filter",
        )

    fk_query = "SELECT id, bundesland, art, jahr, start, ende FROM ferien_kalender WHERE jahr=?"
    fk_params = [filter_jahr_fer]
    fk_all = pd.read_sql(fk_query, conn, params=fk_params)

    if filter_bl_fer != "alle":
        bl_abbr_fer = _bl_to_abbr(filter_bl_fer)
        fk_all = fk_all[fk_all["bundesland"] == bl_abbr_fer]

    fk_all = fk_all.sort_values(["bundesland", "start"]).reset_index(drop=True)
    fk_orig = fk_all.drop(columns=["id", "jahr"]).reset_index(drop=True)
    fk_orig = fk_orig[["bundesland", "start", "ende", "art"]]
    fk_orig["start"] = pd.to_datetime(fk_orig["start"], errors="coerce")
    fk_orig["ende"]  = pd.to_datetime(fk_orig["ende"], errors="coerce")
    fk_orig["bundesland"] = fk_orig["bundesland"].apply(_bl_to_name)

    # Weekday columns (read-only)
    fk_orig["wt_start"] = fk_orig["start"].apply(_wt_name)
    fk_orig["wt_ende"]  = fk_orig["ende"].apply(_wt_name)

    # For plan year: load base year dates for same BL+art to allow comparison
    col_cfg_fk: dict = {
        "bundesland": st.column_config.SelectboxColumn("Bundesland",
                                                       options=["Alle"] + AKTIVE_BL_NAMES),
        "start":    st.column_config.DateColumn("Start", format="DD.MM.YYYY"),
        "wt_start": st.column_config.TextColumn("Wochentag Start", disabled=True),
        "ende":     st.column_config.DateColumn("Ende", format="DD.MM.YYYY"),
        "wt_ende":  st.column_config.TextColumn("Wochentag Ende", disabled=True),
        "art":      st.column_config.TextColumn("Beschreibung (z.B. Sommerferien)"),
    }

    if filter_jahr_fer == planjahr:
        vj_rows_fer = pd.read_sql(
            "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
            conn, params=[vj],
        )
        # Index for fast lookup
        vj_lookup_fer = {
            (_bl_to_name(r["bundesland"]), r["art"]): (r["start"], r["ende"])
            for _, r in vj_rows_fer.iterrows()
        }

        def _fer_abweichung(row) -> str:
            key = (row["bundesland"], row["art"])
            vj_pair = vj_lookup_fer.get(key)
            if not vj_pair:
                return "kein Vorjahreseintrag"
            vj_s = pd.Timestamp(vj_pair[0])
            vj_e = pd.Timestamp(vj_pair[1])
            plan_s = row["start"]
            plan_e = row["ende"]
            if pd.isna(plan_s) or pd.isna(plan_e):
                return ""
            diff_start = int((plan_s - vj_s).days)
            diff_ende  = int((plan_e - vj_e).days)
            if diff_start == 0 and diff_ende == 0:
                return "0"
            parts = []
            if diff_start != 0:
                parts.append(f"Start {'+' if diff_start > 0 else ''}{diff_start} Tage")
            if diff_ende != 0:
                parts.append(f"Ende {'+' if diff_ende > 0 else ''}{diff_ende} Tage")
            return ", ".join(parts)

        fk_orig["start_basis"] = fk_orig.apply(
            lambda r: pd.Timestamp(vj_lookup_fer[(r["bundesland"], r["art"])][0])
            if (r["bundesland"], r["art"]) in vj_lookup_fer else pd.NaT, axis=1)
        fk_orig["wt_start_basis"] = fk_orig["start_basis"].apply(_wt_name)
        fk_orig["ende_basis"] = fk_orig.apply(
            lambda r: pd.Timestamp(vj_lookup_fer[(r["bundesland"], r["art"])][1])
            if (r["bundesland"], r["art"]) in vj_lookup_fer else pd.NaT, axis=1)
        fk_orig["wt_ende_basis"] = fk_orig["ende_basis"].apply(_wt_name)
        fk_orig["abweichung"] = fk_orig.apply(_fer_abweichung, axis=1)

        col_cfg_fk.update({
            "start_basis":    st.column_config.DateColumn("Start Basis", format="DD.MM.YYYY",
                                                          disabled=True),
            "wt_start_basis": st.column_config.TextColumn("Wochentag Start Basis", disabled=True),
            "ende_basis":     st.column_config.DateColumn("Ende Basis", format="DD.MM.YYYY",
                                                          disabled=True),
            "wt_ende_basis":  st.column_config.TextColumn("Wochentag Ende Basis", disabled=True),
            "abweichung":     st.column_config.TextColumn("Abweichung", disabled=True),
        })

    edited_fk = st.data_editor(
        fk_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"fk_editor_{planjahr}_{filter_bl_fer}_{filter_jahr_fer}",
        height=400,
        column_config=col_cfg_fk,
        disabled=[c for c in ["wt_start", "wt_ende", "start_basis", "wt_start_basis",
                               "ende_basis", "wt_ende_basis", "abweichung"]
                  if c in fk_orig.columns],
    )
    n_total = conn.execute(
        "SELECT COUNT(*) AS n FROM ferien_kalender WHERE jahr=? OR jahr=?", (vj, planjahr)
    ).fetchone()["n"]
    n_bl = conn.execute(
        "SELECT COUNT(DISTINCT bundesland) AS n FROM ferien_kalender WHERE jahr=? OR jahr=?",
        (vj, planjahr)
    ).fetchone()["n"]
    st.caption(f"{len(fk_orig)} Einträge angezeigt · {n_total} gesamt ({n_bl} Bundesländer) für {vj}+{planjahr}")

    _date_cols_fk = ["start", "ende"]
    _cmp_cols_fk = ["bundesland", "start", "ende", "art"]
    if not _norm_for_compare(fk_orig[_cmp_cols_fk], _date_cols_fk).equals(
            _norm_for_compare(edited_fk[[c for c in _cmp_cols_fk if c in edited_fk.columns]],
                              _date_cols_fk)):
        # Only delete/reinsert for the displayed year + BL filter
        if filter_bl_fer == "alle":
            conn.execute("DELETE FROM ferien_kalender WHERE jahr=?", (filter_jahr_fer,))
        else:
            bl_abbr_del = _bl_to_abbr(filter_bl_fer)
            conn.execute("DELETE FROM ferien_kalender WHERE jahr=? AND bundesland=?",
                         (filter_jahr_fer, bl_abbr_del))
        for _, row in edited_fk.dropna(subset=["bundesland", "art"]).iterrows():
            bl  = _bl_to_abbr(row.get("bundesland"))
            art = str(row.get("art") or "").strip()
            s   = _iso(row.get("start"))
            e   = _iso(row.get("ende"))
            if not bl or not art or not s or not e:
                continue
            jahr_val = int(s[:4])
            conn.execute(
                "INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende) "
                "VALUES (?,?,?,?,?)", (bl, art, jahr_val, s, e)
            )
        conn.commit()
        _rebuild_ferien_from_kalender(conn, planjahr)
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Ferien gespeichert. {dm_msg}")
        st.rerun()
