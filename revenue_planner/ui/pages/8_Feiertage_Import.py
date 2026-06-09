"""Feiertage & Sondertage laden."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from datetime import date, timedelta
import pandas as pd

require_db()
conn = get_conn()
budgetjahr = get_budgetjahr()

st.title("Feiertage & Sondertage laden")
st.caption(f"Firma: **{get_gmbh()}**")

BL_ABBR_TO_NAME = {
    "BB": "Brandenburg", "BE": "Berlin", "BW": "Baden-Württemberg",
    "BY": "Bayern", "HB": "Bremen", "HE": "Hessen", "HH": "Hamburg",
    "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz", "SH": "Schleswig-Holstein", "SL": "Saarland",
    "SN": "Sachsen", "ST": "Sachsen-Anhalt", "TH": "Thüringen",
}
BL_ABBR_LIST = list(BL_ABBR_TO_NAME.keys())
BL_NAME_LIST = list(BL_ABBR_TO_NAME.values())

RAMADAN = {
    2023: ("2023-03-23", "2023-04-21"), 2024: ("2024-03-11", "2024-04-09"),
    2025: ("2025-03-01", "2025-03-30"), 2026: ("2026-02-18", "2026-03-19"),
    2027: ("2027-02-07", "2027-03-08"), 2028: ("2028-01-27", "2028-02-25"),
    2029: ("2029-01-15", "2029-02-13"), 2030: ("2030-01-04", "2030-02-02"),
    2031: ("2030-12-25", "2031-01-23"), 2032: ("2031-12-14", "2032-01-12"),
    2033: ("2032-12-02", "2033-01-01"), 2034: ("2033-11-21", "2033-12-20"),
    2035: ("2034-11-11", "2034-12-10"), 2036: ("2035-11-01", "2035-11-30"),
}

HOLIDAY_NAME_MAP = {
    "Erster Mai": "Tag der Arbeit",
    "1. Mai": "Tag der Arbeit",
    "Tag der Deutschen Einheit": "Tag der Deutschen Einheit",
}


def _normalize_name(name: str) -> str:
    return HOLIDAY_NAME_MAP.get(name, name)


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

    for bl in BL_ABBR_LIST:
        h_plan = hol_lib.country_holidays("DE", subdiv=bl, years=planjahr)
        h_vj = hol_lib.country_holidays("DE", subdiv=bl, years=vj)
        plan_by_state[bl] = {d2.isoformat(): _normalize_name(n) for d2, n in h_plan.items()}
        vj_by_state[bl] = {d2.isoformat(): _normalize_name(n) for d2, n in h_vj.items()}

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
        if len(states) == len(BL_ABBR_LIST):
            vj_date = next((vj_lookup.get(name, {}).get(bl) for bl in BL_ABBR_LIST
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
        elif wd == 0:
            offsets = [-2, -1, 1]
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
            label = (
                f"Tag vor dem Feiertag: {row['name']}"
                if offset < 0
                else f"Tag nach dem Feiertag: {row['name']}"
            )
            result.append({
                "datum_plan": new_plan.isoformat(),
                "datum_vj": new_vj,
                "name": label,
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
            "datum_vj": mt_vj.isoformat(),
            "name": "Muttertag",
            "bundesland": "alle",
            "art": "Sondertag",
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
                "datum_vj": (ostern_vj - timedelta(days=offset)).isoformat(),
                "name": name,
                "bundesland": "alle",
                "art": "Sondertag",
            })

    if with_ramadan and planjahr in RAMADAN:
        start_iso, ende_iso = RAMADAN[planjahr]
        prev_ramadan = RAMADAN.get(planjahr - 1)
        ref_start = prev_ramadan[0] if prev_ramadan else None
        ref_ende = prev_ramadan[1] if prev_ramadan else None
        rows.append({
            "datum_plan": start_iso,
            "datum_vj": ref_start,
            "name": "Ramadan (ca.) Start",
            "bundesland": "alle",
            "art": "Sondertag",
        })
        rows.append({
            "datum_plan": ende_iso,
            "datum_vj": ref_ende,
            "name": "Ramadan (ca.) Ende",
            "bundesland": "alle",
            "art": "Sondertag",
        })

    return rows


def _load_ferien_year(planjahr: int, conn_db) -> int:
    import holidays as hol_lib

    inserted = 0
    for bl_abbr in BL_ABBR_LIST:
        try:
            school_hols = hol_lib.country_holidays(
                "DE", subdiv=bl_abbr, years=planjahr,
                categories=(hol_lib.SCHOOL,)
            )
        except (AttributeError, NotImplementedError):
            continue
        if not school_hols:
            continue

        by_name: dict = {}
        for d2, name in school_hols.items():
            by_name.setdefault(name, []).append(d2)
        for name, dates in by_name.items():
            dates_sorted = sorted(dates)
            start_d = dates_sorted[0].isoformat()
            end_d = dates_sorted[-1].isoformat()
            conn_db.execute("""
                INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende)
                VALUES (?,?,?,?,?)
            """, (bl_abbr, name, planjahr, start_d, end_d))
            inserted += 1
    return inserted


def _load_year(planjahr: int, with_feiertagstage: bool, with_muttertag: bool,
               with_fasching: bool, with_ramadan: bool, with_ferien: bool,
               replace_existing: bool, conn_db) -> dict:
    if replace_existing:
        conn_db.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{planjahr}-%",))
        if planjahr in RAMADAN:
            start_iso = RAMADAN[planjahr][0]
            yr_start = start_iso[:4]
            if yr_start != str(planjahr):
                conn_db.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?",
                                (f"{yr_start}-%",))
        conn_db.execute("DELETE FROM ferien_kalender WHERE jahr = ?", (planjahr,))

    ft_rows = _load_public_holidays_year(planjahr)
    ftt_rows = _feiertagstage_rows(ft_rows) if with_feiertagstage else []
    st_rows = _sondertage_rows_year(planjahr, with_muttertag, with_fasching, with_ramadan)

    for row in ft_rows + ftt_rows + st_rows:
        conn_db.execute("""
            INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art)
            VALUES (:datum_plan, :datum_vj, :name, :bundesland, :art)
        """, row)

    ferien_count = 0
    if with_ferien:
        ferien_count = _load_ferien_year(planjahr, conn_db)

    conn_db.commit()
    return {
        "feiertage": len(ft_rows),
        "feiertagstage": len(ftt_rows),
        "sondertage": len(st_rows),
        "ferien_perioden": ferien_count,
    }


st.subheader("1. Automatisch laden")
st.caption(f"Wird für Budgetjahr {budgetjahr} geladen")

col_opt1, col_opt2 = st.columns([2, 2])
with col_opt1:
    with_feiertagstage = st.checkbox("Feiertagstage (Tag vor/nach Feiertag) laden", value=True)
    with_muttertag = st.checkbox("Muttertag als Sondertag", value=True)
    with_fasching = st.checkbox("Fasching (Do–Di) als Sondertage", value=True)
with col_opt2:
    with_ramadan = st.checkbox("Ramadan (ca.) als Sondertage", value=False)
    with_ferien = st.checkbox("Ferien für alle Bundesländer laden", value=False)
    replace_existing = st.checkbox("Bestehende Einträge ersetzen", value=True)

if st.button(f"Feiertage für {budgetjahr} laden", type="primary"):
    with st.spinner(f"Lade Feiertage für {budgetjahr} …"):
        try:
            counts = _load_year(
                budgetjahr, with_feiertagstage, with_muttertag,
                with_fasching, with_ramadan, with_ferien,
                replace_existing, conn,
            )
            msg = (
                f"Geladen: {counts['feiertage']} Feiertage, "
                f"{counts['feiertagstage']} Feiertagstage, "
                f"{counts['sondertage']} Sondertage"
            )
            if with_ferien:
                msg += f", {counts['ferien_perioden']} Ferienperioden"
            msg += f" für {budgetjahr}."
            st.success(msg)
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()

st.subheader("2. Gespeicherte Feiertage")

ft_raw = pd.read_sql(
    "SELECT id, datum_plan, datum_vj, name, bundesland, art FROM feiertage ORDER BY datum_plan, bundesland",
    conn,
)
fk_raw = pd.read_sql(
    "SELECT id, bundesland, art, jahr, start, ende FROM ferien_kalender ORDER BY jahr, bundesland, start",
    conn,
)

jahre_available = set()
if not ft_raw.empty:
    jahre_available.update(
        pd.to_datetime(ft_raw["datum_plan"], errors="coerce").dt.year.dropna().astype(int).tolist()
    )
if not fk_raw.empty:
    jahre_available.update(fk_raw["jahr"].dropna().astype(int).tolist())

if not jahre_available:
    st.info("Noch keine Feiertage oder Ferien hinterlegt.")
    st.stop()

jahre_sorted = sorted(jahre_available, reverse=True)
default_idx = jahre_sorted.index(budgetjahr) if budgetjahr in jahre_sorted else 0

col_fj, col_bl = st.columns([1, 2])
with col_fj:
    filter_jahr = st.selectbox("Jahr", jahre_sorted, index=default_idx, key="ft_view_jahr")
with col_bl:
    selected_bls = st.multiselect(
        "Bundesland",
        options=["Alle"] + BL_NAME_LIST,
        default=["Alle"],
        key="ft_view_bl",
    )

ft_year = ft_raw[ft_raw["datum_plan"].str.startswith(str(filter_jahr))].copy() if not ft_raw.empty else pd.DataFrame()
fk_year = fk_raw[fk_raw["jahr"] == filter_jahr].copy() if not fk_raw.empty else pd.DataFrame()


def _bl_abbr_to_name(bl: str) -> str:
    if bl in ("alle", "Alle", ""):
        return "Alle"
    return BL_ABBR_TO_NAME.get(bl, bl)


def _bl_name_to_abbr(name: str) -> str:
    if name in ("Alle", "alle", ""):
        return "alle"
    for abbr, n in BL_ABBR_TO_NAME.items():
        if n == name:
            return abbr
    return name


def _art_display(art: str) -> str:
    mapping = {
        "feiertag": "Feiertag",
        "feiertagstag": "Feiertagstag",
        "sondertag": "Sondertag",
        "Sondertag": "Sondertag",
    }
    return mapping.get(art, art)


def _build_display_df(ft_df: pd.DataFrame, fk_df: pd.DataFrame,
                      sel_bls: list) -> tuple[pd.DataFrame, list]:
    rows = []
    meta = []

    show_all = not sel_bls or "Alle" in sel_bls or set(sel_bls) >= set(BL_NAME_LIST)

    if not ft_df.empty:
        for _, r in ft_df.iterrows():
            bl_name = _bl_abbr_to_name(r["bundesland"])
            if not show_all:
                if bl_name not in sel_bls and r["bundesland"] != "alle":
                    continue
            rows.append({
                "_source": "feiertage",
                "_id": r["id"],
                "_bl_abbr": r["bundesland"],
                "Datum": r["datum_plan"],
                "Bis": None,
                "Name": r["name"],
                "Bundesland_raw": bl_name,
                "Art_raw": r["art"],
            })
            meta.append({"source": "feiertage", "ids": [int(r["id"])]})

    if not fk_df.empty:
        for _, r in fk_df.iterrows():
            bl_name = _bl_abbr_to_name(r["bundesland"])
            if not show_all:
                if bl_name not in sel_bls:
                    continue
            rows.append({
                "_source": "ferien_kalender",
                "_id": r["id"],
                "_bl_abbr": r["bundesland"],
                "Datum": r["start"],
                "Bis": r["ende"],
                "Name": r["art"],
                "Bundesland_raw": bl_name,
                "Art_raw": r["art"],
            })
            meta.append({"source": "ferien_kalender", "ids": [int(r["id"])]})

    if not rows:
        empty_df = pd.DataFrame(columns=["Datum", "Bis", "Name", "Bundesland", "Art"])
        return empty_df, []

    tmp = pd.DataFrame(rows)
    tmp["Art_disp"] = tmp["Art_raw"].apply(_art_display)

    if show_all:
        grouped_rows = []
        grouped_meta = []
        key_cols = ["Datum", "Bis", "Name", "Art_disp"]
        tmp["_key"] = tmp[key_cols].astype(str).agg("|".join, axis=1)
        for key, grp in tmp.groupby("_key", sort=False):
            bls = grp["Bundesland_raw"].tolist()
            if "Alle" in bls or len(bls) == len(BL_NAME_LIST):
                bl_disp = "Alle"
            elif len(bls) == 1:
                bl_disp = bls[0]
            else:
                bl_disp = ", ".join(bls)
            first = grp.iloc[0]
            grouped_rows.append({
                "Datum": first["Datum"],
                "Bis": first["Bis"],
                "Name": first["Name"],
                "Bundesland": bl_disp,
                "Art": first["Art_disp"],
            })
            combined_meta = {"source": first["_source"],
                             "ids": grp["_id"].astype(int).tolist()}
            grouped_meta.append(combined_meta)
        display_df = pd.DataFrame(grouped_rows)
        return display_df, grouped_meta
    else:
        tmp["Bundesland"] = tmp["Bundesland_raw"]
        tmp["Art"] = tmp["Art_disp"]
        display_df = tmp[["Datum", "Bis", "Name", "Bundesland", "Art"]].reset_index(drop=True)
        return display_df, meta


display_df, row_meta = _build_display_df(ft_year, fk_year, selected_bls)

if display_df.empty:
    st.info(f"Keine Einträge für {filter_jahr} gefunden.")
else:
    if "Datum" in display_df.columns and not display_df["Datum"].isna().all():
        display_df["Datum"] = pd.to_datetime(display_df["Datum"], errors="coerce")
    if "Bis" in display_df.columns and not display_df["Bis"].isna().all():
        display_df["Bis"] = pd.to_datetime(display_df["Bis"], errors="coerce")

    st.session_state["_ft_row_meta"] = row_meta

    ART_OPTIONS = ["Feiertag", "Feiertagstag", "Sondertag",
                   "Ferien", "Sommerferien", "Winterferien",
                   "Osterferien", "Herbstferien", "Pfingstferien"]

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="ft_unified_editor",
        height=800,
        column_config={
            "Datum": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
            "Bis": st.column_config.DateColumn("Bis", format="DD.MM.YYYY"),
            "Bundesland": st.column_config.SelectboxColumn(
                "Bundesland", options=["Alle"] + BL_NAME_LIST
            ),
            "Art": st.column_config.SelectboxColumn("Art", options=ART_OPTIONS),
        },
    )

    st.caption(f"{len(display_df)} Einträge für {filter_jahr}")

    if st.button("Änderungen speichern", type="primary", key="save_unified"):
        saved = 0
        meta_list = st.session_state.get("_ft_row_meta", [])

        for idx, row in edited_df.iterrows():
            datum_val = row.get("Datum")
            if datum_val is None or (hasattr(datum_val, "__class__") and str(datum_val) == "NaT"):
                continue

            if hasattr(datum_val, "date"):
                datum_iso = datum_val.date().isoformat()
            else:
                datum_iso = str(datum_val)

            bis_val = row.get("Bis")
            if bis_val is not None and str(bis_val) != "NaT" and str(bis_val) != "None":
                if hasattr(bis_val, "date"):
                    bis_iso = bis_val.date().isoformat()
                else:
                    bis_iso = str(bis_val)
            else:
                bis_iso = None

            name_val = str(row.get("Name") or "").strip()
            art_val = str(row.get("Art") or "").strip()
            bl_val = str(row.get("Bundesland") or "Alle").strip()
            bl_db = "alle" if bl_val in ("Alle", "alle") else bl_val

            if not name_val or not art_val:
                continue

            ferien_arts = {"Ferien", "Sommerferien", "Winterferien",
                           "Osterferien", "Herbstferien", "Pfingstferien"}

            if idx < len(meta_list):
                meta = meta_list[idx]
                if art_val in ferien_arts:
                    for rec_id in meta.get("ids", []):
                        if meta.get("source") == "ferien_kalender":
                            conn.execute(
                                "UPDATE ferien_kalender SET bundesland=?, art=?, start=?, ende=? WHERE id=?",
                                (bl_db, name_val, datum_iso, bis_iso or datum_iso, int(rec_id))
                            )
                            saved += 1
                else:
                    art_db = art_val.lower() if art_val in ("Feiertag", "Feiertagstag") else art_val
                    for rec_id in meta.get("ids", []):
                        if meta.get("source") == "feiertage":
                            conn.execute(
                                "UPDATE feiertage SET datum_plan=?, name=?, bundesland=?, art=? WHERE id=?",
                                (datum_iso, name_val, bl_db, art_db, int(rec_id))
                            )
                            saved += 1
            else:
                if art_val in ferien_arts:
                    bl_abbr = _bl_name_to_abbr(bl_val)
                    try:
                        yr = int(datum_iso[:4])
                    except (ValueError, TypeError):
                        yr = filter_jahr
                    conn.execute("""
                        INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende)
                        VALUES (?,?,?,?,?)
                    """, (bl_abbr, name_val, yr, datum_iso, bis_iso or datum_iso))
                    saved += 1
                else:
                    art_db = art_val.lower() if art_val in ("Feiertag", "Feiertagstag") else art_val
                    conn.execute("""
                        INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art)
                        VALUES (?,?,?,?,?)
                    """, (datum_iso, None, name_val, bl_db, art_db))
                    saved += 1

        conn.commit()
        st.success(f"{saved} Einträge gespeichert.")
        st.rerun()
