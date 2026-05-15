"""Planning parameters page: growth %, Ramadan, Fasching, holidays, vacations."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Parameter", page_icon="⚙️", layout="wide")
st.title("⚙️ Planungsparameter")
require_db()

conn = get_conn()
st.caption(f"GmbH: **{get_gmbh()}**")

# ── Load existing params ───────────────────────────────────────────────────
planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1)

existing = conn.execute("SELECT * FROM parameter WHERE planjahr=?", (planjahr,)).fetchone()
ex = dict(existing) if existing else {}

tabs = st.tabs(["Allgemein", "Feiertage & Sondertage", "Ferien", "Ramadan", "Fasching"])

# ── Tab 1: General ─────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("Allgemeine Parameter")
    with st.form("params_allgemein"):
        preiserh = st.number_input(
            "Umsatzerhöhung / Preisanpassung (%)",
            min_value=-20.0, max_value=50.0,
            value=float(ex.get("preiserhoehung_pct", 3.0)), step=0.1,
            help="Gilt für alle Filialen ohne 'Kein Wachstum'-Flag"
        )
        puffer = st.number_input(
            "Ferien-Pufferzeitraum (Wochen vor/nach Ferien für Ferienfaktor-Berechnung)",
            min_value=1, max_value=8,
            value=int(ex.get("ferien_puffer_wochen", 3)), step=1
        )
        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter (planjahr, preiserhoehung_pct, ferien_puffer_wochen)
                VALUES (?,?,?)
                ON CONFLICT(planjahr) DO UPDATE SET
                  preiserhoehung_pct=excluded.preiserhoehung_pct,
                  ferien_puffer_wochen=excluded.ferien_puffer_wochen
            """, (planjahr, preiserh, puffer))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()

# ── Tab 2: Holidays ────────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Feiertage (Planjahr)")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Bestehende Feiertage**")
        ft_df = pd.read_sql(
            "SELECT id, datum_plan, datum_vj, name, bundesland FROM feiertage ORDER BY datum_plan",
            conn
        )
        if ft_df.empty:
            st.info("Noch keine Feiertage eingetragen.")
        else:
            st.dataframe(ft_df.drop("id", axis=1), use_container_width=True, hide_index=True)
            del_id = st.number_input("ID zum Löschen", min_value=0, value=0, step=1)
            if st.button("🗑️ Löschen", key="del_ft") and del_id > 0:
                conn.execute("DELETE FROM feiertage WHERE id=?", (del_id,))
                conn.commit()
                st.rerun()

    with col2:
        st.markdown("**Feiertag hinzufügen**")
        with st.form("add_feiertag"):
            BUNDESLAENDER = ["alle", "DE-RP", "DE-HE", "DE-BY", "DE-BW", "DE-NW",
                             "DE-NI", "DE-BE", "DE-BB", "DE-HB", "DE-HH",
                             "DE-MV", "DE-SH", "DE-SL", "DE-SN", "DE-ST", "DE-TH"]
            f_datum_plan = st.date_input("Datum Planjahr", value=date(planjahr, 1, 1))
            f_datum_vj = st.date_input("Datum Vorjahr (für 1:1 Planung)",
                                        value=date(planjahr - 1, 1, 1))
            f_name = st.text_input("Name (z.B. Ostermontag)")
            f_bl = st.selectbox("Bundesland", BUNDESLAENDER)
            if st.form_submit_button("➕ Hinzufügen"):
                conn.execute(
                    "INSERT INTO feiertage (datum_plan, datum_vj, name, bundesland) VALUES (?,?,?,?)",
                    (f_datum_plan.isoformat(), f_datum_vj.isoformat(), f_name, f_bl)
                )
                conn.commit()
                st.success("✅ Hinzugefügt.")
                st.rerun()

    st.divider()
    st.subheader("Sondertage (Planjahr)")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Bestehende Sondertage**")
        st_df = pd.read_sql(
            "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage ORDER BY datum_plan",
            conn
        )
        if st_df.empty:
            st.info("Noch keine Sondertage eingetragen.")
        else:
            st.dataframe(st_df.drop("id", axis=1), use_container_width=True, hide_index=True)

    with col4:
        st.markdown("**Sondertag hinzufügen**")
        with st.form("add_sondertag"):
            s_datum = st.date_input("Datum Planjahr", value=date(planjahr, 3, 1), key="s_datum")
            s_bez = st.text_input("Bezeichnung (z.B. Ostersamstag)")
            s_methode = st.radio("Planungsmethode", ["referenz", "samstag"],
                                  help="referenz: Vorjahres-Referenztag; samstag: Samstags-Ø der Filiale")
            s_ref = st.date_input("Referenz-Datum Vorjahr",
                                   value=date(planjahr - 1, 3, 1), key="s_ref") if s_methode == "referenz" else None
            s_bl = st.selectbox("Bundesland", ["alle"] + ["DE-RP", "DE-HE", "DE-BY"], key="s_bl")
            if st.form_submit_button("➕ Hinzufügen"):
                conn.execute("""
                    INSERT INTO sondertage (datum_plan, datum_referenz, bezeichnung, methode, bundesland)
                    VALUES (?,?,?,?,?)
                """, (s_datum.isoformat(), s_ref.isoformat() if s_ref else None,
                      s_bez, s_methode, s_bl))
                conn.commit()
                st.success("✅ Hinzugefügt.")
                st.rerun()

# ── Tab 3: Vacations ──────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Ferienzeiten")

    ferien_df = pd.read_sql("SELECT * FROM ferien ORDER BY bundesland, art", conn)
    if not ferien_df.empty:
        st.dataframe(ferien_df.drop("id", axis=1), use_container_width=True, hide_index=True)

    st.markdown("**Ferien hinzufügen**")
    with st.form("add_ferien"):
        col1, col2, col3 = st.columns(3)
        with col1:
            f_bl = st.selectbox("Bundesland", ["DE-RP", "DE-HE", "DE-BY", "DE-BW", "DE-NW"], key="fer_bl")
            f_art = st.selectbox("Ferienart", ["Osterferien", "Sommerferien", "Herbstferien",
                                               "Weihnachtsferien", "Winterferien", "Pfingstferien"])
        with col2:
            f_start_vj = st.date_input("Start Vorjahr", value=date(planjahr - 1, 4, 1), key="fsvj")
            f_ende_vj = st.date_input("Ende Vorjahr", value=date(planjahr - 1, 4, 14), key="fevj")
        with col3:
            f_start_p = st.date_input("Start Planjahr", value=date(planjahr, 4, 1), key="fsp")
            f_ende_p = st.date_input("Ende Planjahr", value=date(planjahr, 4, 14), key="fep")

        if st.form_submit_button("➕ Hinzufügen"):
            conn.execute("""
                INSERT INTO ferien (bundesland, art, start_vj, ende_vj, start_plan, ende_plan)
                VALUES (?,?,?,?,?,?)
            """, (f_bl, f_art, f_start_vj.isoformat(), f_ende_vj.isoformat(),
                  f_start_p.isoformat(), f_ende_p.isoformat()))
            conn.commit()
            st.success("✅ Hinzugefügt.")
            st.rerun()

# ── Tab 4: Ramadan ────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("Ramadan-Parameter")
    st.info("""
    Ramadan verschiebt Umsätze zwischen Monaten (kein Verlust).
    Tragen Sie die Ramadan-Zeiträume für Vorjahr und Planjahr ein sowie den
    prozentualen Anteil des Monatsumsatzes, der Ramadan-sensitiv ist.
    """)

    with st.form("params_ramadan"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Vorjahr**")
            r_vj_start = st.date_input("Ramadan Start VJ",
                value=date.fromisoformat(ex["ramadan_vj_start"]) if ex.get("ramadan_vj_start") else date(planjahr-1, 3, 1),
                key="rvjs")
            r_vj_ende = st.date_input("Ramadan Ende VJ",
                value=date.fromisoformat(ex["ramadan_vj_ende"]) if ex.get("ramadan_vj_ende") else date(planjahr-1, 3, 30),
                key="rvje")
        with col2:
            st.markdown("**Planjahr**")
            r_plan_start = st.date_input("Ramadan Start Planjahr",
                value=date.fromisoformat(ex["ramadan_plan_start"]) if ex.get("ramadan_plan_start") else date(planjahr, 2, 18),
                key="rps")
            r_plan_ende = st.date_input("Ramadan Ende Planjahr",
                value=date.fromisoformat(ex["ramadan_plan_ende"]) if ex.get("ramadan_plan_ende") else date(planjahr, 3, 19),
                key="rpe")

        r_pct = st.slider(
            "Ramadan-sensitiver Anteil am Monatsumsatz (%)",
            min_value=0.0, max_value=30.0,
            value=float(ex.get("ramadan_umsatz_pct", 5.0)), step=0.5
        )

        # Show shift info
        if r_vj_start and r_plan_start:
            shift_days = (r_plan_start - r_vj_start).days
            dir_txt = "früher" if shift_days < 0 else "später"
            st.info(f"ℹ️ Ramadan {planjahr} beginnt **{abs(shift_days)} Tage {dir_txt}** als {planjahr-1}.")

        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter
                  (planjahr, ramadan_vj_start, ramadan_vj_ende, ramadan_plan_start,
                   ramadan_plan_ende, ramadan_umsatz_pct)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(planjahr) DO UPDATE SET
                  ramadan_vj_start=excluded.ramadan_vj_start,
                  ramadan_vj_ende=excluded.ramadan_vj_ende,
                  ramadan_plan_start=excluded.ramadan_plan_start,
                  ramadan_plan_ende=excluded.ramadan_plan_ende,
                  ramadan_umsatz_pct=excluded.ramadan_umsatz_pct
            """, (planjahr, r_vj_start.isoformat(), r_vj_ende.isoformat(),
                  r_plan_start.isoformat(), r_plan_ende.isoformat(), r_pct))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()

# ── Tab 5: Fasching ───────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("Fasching-Parameter")
    st.info("""
    Eine kürzere/längere Faschingszeit führt zu echten Umsatzveränderungen (kein Shift).
    Das System berechnet automatisch die Differenz in Tagen und zeigt sie an.
    """)

    with st.form("params_fasching"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Vorjahr**")
            fa_vj_start = st.date_input("Fasching Start VJ",
                value=date.fromisoformat(ex["fasching_vj_start"]) if ex.get("fasching_vj_start") else date(planjahr-1, 2, 27),
                key="favjs")
            fa_vj_ende = st.date_input("Fasching Ende VJ",
                value=date.fromisoformat(ex["fasching_vj_ende"]) if ex.get("fasching_vj_ende") else date(planjahr-1, 3, 4),
                key="favje")
        with col2:
            st.markdown("**Planjahr**")
            fa_plan_start = st.date_input("Fasching Start Planjahr",
                value=date.fromisoformat(ex["fasching_plan_start"]) if ex.get("fasching_plan_start") else date(planjahr, 2, 16),
                key="faps")
            fa_plan_ende = st.date_input("Fasching Ende Planjahr",
                value=date.fromisoformat(ex["fasching_plan_ende"]) if ex.get("fasching_plan_ende") else date(planjahr, 2, 24),
                key="fape")

        # Auto-calculate diff and display
        vj_tage = (fa_vj_ende - fa_vj_start).days + 1
        plan_tage = (fa_plan_ende - fa_plan_start).days + 1
        diff = plan_tage - vj_tage

        if diff != 0:
            farbe = "🔴" if diff < 0 else "🟢"
            st.warning(
                f"{farbe} Fasching {planjahr} hat **{plan_tage} Tage** "
                f"({'+' if diff>0 else ''}{diff} Tage vs. {planjahr-1} mit {vj_tage} Tagen)."
            )
        else:
            st.success(f"✅ Fasching {planjahr} hat gleich viele Tage wie {planjahr-1} ({plan_tage} Tage).")

        fa_wirkung = st.slider(
            "Umsatzwirkung pro Tag-Differenz (%)",
            min_value=-20.0, max_value=0.0,
            value=float(ex.get("fasching_wirkung_pct", -3.0)), step=0.5,
            help="Negativer Wert = Umsatzverlust pro kürzerem Tag. Bsp: -3% bedeutet jeder fehlende Faschingstag reduziert den Monatsumsatz um 3% des Tagesumsatzes."
        )

        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter
                  (planjahr, fasching_vj_start, fasching_vj_ende,
                   fasching_plan_start, fasching_plan_ende, fasching_wirkung_pct)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(planjahr) DO UPDATE SET
                  fasching_vj_start=excluded.fasching_vj_start,
                  fasching_vj_ende=excluded.fasching_vj_ende,
                  fasching_plan_start=excluded.fasching_plan_start,
                  fasching_plan_ende=excluded.fasching_plan_ende,
                  fasching_wirkung_pct=excluded.fasching_wirkung_pct
            """, (planjahr, fa_vj_start.isoformat(), fa_vj_ende.isoformat(),
                  fa_plan_start.isoformat(), fa_plan_ende.isoformat(), fa_wirkung))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()
