"""Auto-load German public holidays + Muttertag + Fasching into the database."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from datetime import date, timedelta
import pandas as pd

require_db()
conn = get_conn()
st.title("Feiertage automatisch laden")
st.caption(f"Firma: **{get_gmbh()}**")

st.markdown("""
Lädt automatisch alle gesetzlichen Feiertage für alle Bundesländer aus der `holidays`-Bibliothek
und trägt sie in die Datenbank ein. Optional werden **Muttertag** und **Fasching**-Tage
als Sondertage ergänzt.
""")

BUNDESLAENDER = ["BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
                 "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"]


# ── Helper functions ───────────────────────────────────────────────────────

def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""
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
    """2nd Sunday in May."""
    d = date(year, 5, 1)
    sundays = [d + timedelta(days=i) for i in range(31)
               if (d + timedelta(days=i)).month == 5
               and (d + timedelta(days=i)).weekday() == 6]
    return sundays[1]


def _load_public_holidays(planjahr: int) -> list[dict]:
    """Load all German public holidays for all states for plan year and prior year."""
    import holidays as hol_lib

    vj = planjahr - 1
    plan_by_state: dict[str, dict[str, str]] = {}
    vj_by_state: dict[str, dict[str, str]] = {}

    for bl in BUNDESLAENDER:
        h_plan = hol_lib.country_holidays("DE", subdiv=bl, years=planjahr)
        h_vj   = hol_lib.country_holidays("DE", subdiv=bl, years=vj)
        plan_by_state[bl] = {d.isoformat(): n for d, n in h_plan.items()}
        vj_by_state[bl]   = {d.isoformat(): n for d, n in h_vj.items()}

    # Aggregate: date → {name, states_set}
    date_info: dict[str, dict] = {}
    for bl, hdict in plan_by_state.items():
        for iso, name in hdict.items():
            if iso not in date_info:
                date_info[iso] = {"name": name, "states": set()}
            date_info[iso]["states"].add(bl)

    # VJ lookup: name → state → vj_date
    vj_lookup: dict[str, dict[str, str]] = {}
    for bl, hdict in vj_by_state.items():
        for iso, name in hdict.items():
            vj_lookup.setdefault(name, {})[bl] = iso

    result = []
    for iso, info in sorted(date_info.items()):
        name   = info["name"]
        states = info["states"]
        if len(states) == len(BUNDESLAENDER):
            # Bundesweit
            vj_date = next((vj_lookup.get(name, {}).get(bl) for bl in BUNDESLAENDER
                            if vj_lookup.get(name, {}).get(bl)), None)
            result.append({"datum_plan": iso, "datum_vj": vj_date,
                           "name": name, "bundesland": "alle"})
        else:
            for bl in sorted(states):
                vj_date = vj_lookup.get(name, {}).get(bl)
                result.append({"datum_plan": iso, "datum_vj": vj_date,
                               "name": name, "bundesland": bl})
    return result


def _sondertage_rows(planjahr: int, with_muttertag: bool, with_fasching: bool) -> list[dict]:
    rows = []
    vj = planjahr - 1

    if with_muttertag:
        mt_plan = _muttertag(planjahr)
        mt_vj   = _muttertag(vj)
        rows.append({
            "datum_plan":     mt_plan.isoformat(),
            "datum_referenz": mt_vj.isoformat(),
            "bezeichnung":    "Muttertag",
            "methode":        "referenz",
            "bundesland":     "alle",
        })

    if with_fasching:
        ostern_plan = _easter(planjahr)
        ostern_vj   = _easter(vj)
        for name, offset in [
            ("Weiberfastnacht",    52),
            ("Rosenmontag",        48),
            ("Fastnachtsdienstag", 47),
        ]:
            rows.append({
                "datum_plan":     (ostern_plan - timedelta(days=offset)).isoformat(),
                "datum_referenz": (ostern_vj   - timedelta(days=offset)).isoformat(),
                "bezeichnung":    name,
                "methode":        "referenz",
                "bundesland":     "alle",
            })
    return rows


# ── UI ─────────────────────────────────────────────────────────────────────

col1, col2 = st.columns([1, 3])
with col1:
    planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                               value=date.today().year + 1, step=1)

with col2:
    st.markdown("")
    with_muttertag = st.checkbox("Muttertag als Sondertag hinzufügen", value=True)
    with_fasching  = st.checkbox(
        "Fasching-Tage als Sondertage hinzufügen (Weiberfastnacht, Rosenmontag, Fastnachtsdienstag)",
        value=True,
        help="Achtung: Wenn Fasching-Tage hier als Sondertage eingetragen werden, "
             "sollte die Fasching-Wirkung (%) unter Parameter auf 0 gesetzt werden, "
             "um Doppelzählung zu vermeiden.",
    )

replace_existing = st.checkbox(
    "Bestehende Einträge für dieses Jahr ersetzen", value=True,
    help="Löscht alle Feiertage/Sondertage mit Datum im gewählten Jahr vor dem Import."
)

if st.button("🔍 Vorschau & Importieren", type="primary"):
    with st.spinner("Lade Feiertage …"):
        try:
            ft_rows = _load_public_holidays(planjahr)
            st_rows = _sondertage_rows(planjahr, with_muttertag, with_fasching)
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")
            st.stop()

    # Preview
    st.subheader(f"Gesetzliche Feiertage ({len(ft_rows)} Einträge)")
    df_ft = pd.DataFrame(ft_rows).rename(columns={
        "datum_plan": "Datum Plan", "datum_vj": "Datum VJ",
        "name": "Name", "bundesland": "Bundesland",
    })
    bl_counts = df_ft["Bundesland"].value_counts()
    c1, c2 = st.columns(2)
    c1.metric("Bundesweite Feiertage", int((df_ft["Bundesland"] == "alle").sum()))
    c2.metric("Landesspezifische Einträge", int((df_ft["Bundesland"] != "alle").sum()))
    st.dataframe(df_ft, use_container_width=True, hide_index=True, height=300)

    if st_rows:
        st.subheader(f"Sondertage ({len(st_rows)} Einträge)")
        df_st = pd.DataFrame(st_rows).rename(columns={
            "datum_plan": "Datum Plan", "datum_referenz": "Referenz VJ",
            "bezeichnung": "Bezeichnung", "methode": "Methode", "bundesland": "Bundesland",
        })
        st.dataframe(df_st, use_container_width=True, hide_index=True)

        if with_fasching:
            st.warning(
                "Fasching-Tage werden als Sondertage gespeichert. "
                "Bitte die **Fasching-Wirkung %** unter **Parameter** auf **0** setzen."
            )

    # Save
    st.divider()
    year_prefix = f"{planjahr}-%"
    if replace_existing:
        conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (year_prefix,))
        conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (year_prefix,))

    conn.executemany(
        "INSERT OR REPLACE INTO feiertage (datum_plan, datum_vj, name, bundesland) VALUES (:datum_plan, :datum_vj, :name, :bundesland)",
        ft_rows,
    )
    if st_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO sondertage (datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
            "VALUES (:datum_plan, :datum_referenz, :bezeichnung, :methode, :bundesland)",
            st_rows,
        )
    conn.commit()

    n_ft = len(ft_rows)
    n_st = len(st_rows)
    st.success(
        f"✅ {n_ft} Feiertag-Einträge und {n_st} Sondertag-Einträge für {planjahr} gespeichert."
    )

# ── Current state ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Gespeicherte Feiertage")
existing = pd.read_sql(
    "SELECT datum_plan, datum_vj, name, bundesland FROM feiertage ORDER BY datum_plan, bundesland",
    conn,
)
if existing.empty:
    st.info("Noch keine Feiertage hinterlegt.")
else:
    jahre = sorted(pd.to_datetime(existing["datum_plan"]).dt.year.unique(), reverse=True)
    filter_jahr = st.selectbox("Anzeigen für Jahr", jahre, key="ft_view_jahr")
    subset = existing[existing["datum_plan"].str.startswith(str(filter_jahr))]
    st.dataframe(subset.rename(columns={
        "datum_plan": "Datum Plan", "datum_vj": "Datum VJ",
        "name": "Name", "bundesland": "Bundesland",
    }), use_container_width=True, hide_index=True)
    st.caption(f"{len(subset)} Einträge für {filter_jahr}")
