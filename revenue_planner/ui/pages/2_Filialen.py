"""Branch management page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd

st.set_page_config(page_title="Filialen", page_icon="🏪", layout="wide")
st.title("🏪 Filialverwaltung")
require_db()

conn = get_conn()
st.caption(f"GmbH: **{get_gmbh()}**")

BUNDESLAENDER = [
    "DE-RP", "DE-HE", "DE-BY", "DE-BW", "DE-NW", "DE-NI",
    "DE-BE", "DE-BB", "DE-HB", "DE-HH", "DE-MV", "DE-SH",
    "DE-SL", "DE-SN", "DE-ST", "DE-TH",
]

# ── Load current data ──────────────────────────────────────────────────────
df = pd.read_sql("SELECT * FROM filialen ORDER BY fil_nr", conn)

tab1, tab2, tab3 = st.tabs(["Übersicht & Bearbeiten", "Neue Filiale", "Massenimport Stammdaten"])

# ── Tab 1: Overview ────────────────────────────────────────────────────────
with tab1:
    if df.empty:
        st.info("Noch keine Filialen angelegt. Bitte Daten importieren oder manuell erfassen.")
    else:
        st.markdown(f"**{len(df)} Filialen** in der Datenbank")

        flag_cols = {
            "flag_kein_wachstum": "Kein Wachstum",
            "flag_neue_filiale": "Neue Filiale",
            "flag_inaktiv": "Inaktiv",
            "ramadan_sensitiv": "Ramadan",
        }

        display = df.copy()
        for col, label in flag_cols.items():
            if col in display.columns:
                display[col] = display[col].apply(lambda x: "✅" if x else "")
        display = display.rename(columns={
            "fil_nr": "Fil.-Nr.", "bezeichnung": "Bezeichnung",
            "bundesland": "Bundesland", "ort": "Ort",
            "eroeffnung": "Eröffnung", **{k: v for k, v in flag_cols.items()}
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Filiale bearbeiten")
        fil_nrs = df["fil_nr"].tolist()
        selected = st.selectbox("Filiale auswählen", fil_nrs)
        row = df[df["fil_nr"] == selected].iloc[0]

        with st.form("edit_filiale"):
            col1, col2, col3 = st.columns(3)
            with col1:
                bezeichnung = st.text_input("Bezeichnung", value=row.get("bezeichnung") or "")
                ort = st.text_input("Ort", value=row.get("ort") or "")
                eroeffnung = st.text_input("Eröffnung (YYYY-MM-DD)", value=row.get("eroeffnung") or "")
            with col2:
                bl_idx = BUNDESLAENDER.index(row["bundesland"]) if row["bundesland"] in BUNDESLAENDER else 0
                bundesland = st.selectbox("Bundesland", BUNDESLAENDER, index=bl_idx)
                notiz = st.text_area("Notiz", value=row.get("notiz") or "", height=80)
            with col3:
                kein_wachstum = st.checkbox("Kein Wachstum", value=bool(row.get("flag_kein_wachstum")))
                manuell = st.checkbox("Planwert manuell", value=bool(row.get("flag_manuell")))
                neue_fil = st.checkbox("Neue Filiale", value=bool(row.get("flag_neue_filiale")))
                inaktiv = st.checkbox("Inaktiv/Geschlossen", value=bool(row.get("flag_inaktiv")))
                eroeffnung_ende = st.text_input("Schließungsdatum", value=row.get("eroeffnung_ende") or "")
                ramadan = st.checkbox("Ramadan-sensitiv", value=bool(row.get("ramadan_sensitiv")))

            if st.form_submit_button("💾 Speichern"):
                conn.execute("""
                    UPDATE filialen SET bezeichnung=?, bundesland=?, ort=?, eroeffnung=?,
                    flag_kein_wachstum=?, flag_manuell=?, flag_neue_filiale=?,
                    flag_inaktiv=?, eroeffnung_ende=?, ramadan_sensitiv=?, notiz=?
                    WHERE fil_nr=?
                """, (bezeichnung, bundesland, ort, eroeffnung or None,
                      int(kein_wachstum), int(manuell), int(neue_fil),
                      int(inaktiv), eroeffnung_ende or None, int(ramadan), notiz or None,
                      selected))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

# ── Tab 2: New branch ──────────────────────────────────────────────────────
with tab2:
    st.subheader("Neue Filiale anlegen")
    with st.form("neue_filiale"):
        col1, col2 = st.columns(2)
        with col1:
            fil_nr = st.text_input("Filialnummer (oder Platzhalter z.B. NEU_001)")
            bezeichnung = st.text_input("Bezeichnung")
            ort = st.text_input("Ort")
            eroeffnung = st.text_input("Eröffnungsdatum (YYYY-MM-DD)")
        with col2:
            bundesland = st.selectbox("Bundesland", BUNDESLAENDER, key="new_bl")
            neue_fil = st.checkbox("Als neue Filiale markieren", value=True)
            ramadan = st.checkbox("Ramadan-sensitiv", key="new_ram")
            notiz = st.text_area("Notiz", height=80)

        if st.form_submit_button("➕ Anlegen"):
            if not fil_nr.strip():
                st.error("Bitte Filialnummer angeben.")
            else:
                try:
                    conn.execute("""
                        INSERT INTO filialen (fil_nr, bezeichnung, bundesland, ort, eroeffnung,
                        flag_neue_filiale, ramadan_sensitiv, notiz)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (fil_nr.strip(), bezeichnung or None, bundesland,
                          ort or None, eroeffnung or None,
                          int(neue_fil), int(ramadan), notiz or None))
                    conn.commit()
                    st.success(f"✅ Filiale {fil_nr} angelegt.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")

# ── Tab 3: Bulk import ─────────────────────────────────────────────────────
with tab3:
    st.subheader("Stammdaten aus Datei importieren")
    st.info("CSV/Excel mit Spalten: fil_nr, bundesland (+ optional: bezeichnung, ort, eroeffnung)")
    uploaded = st.file_uploader("Datei hochladen", type=["csv", "xlsx"], key="stamm_upload")
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                imp = pd.read_csv(uploaded, dtype=str)
            else:
                imp = pd.read_excel(uploaded, dtype=str)
            imp.columns = imp.columns.str.lower().str.strip()
            st.dataframe(imp.head(10))
            if st.button("Importieren"):
                for _, row in imp.iterrows():
                    conn.execute("""
                        INSERT OR IGNORE INTO filialen (fil_nr, bundesland, bezeichnung, ort, eroeffnung)
                        VALUES (?,?,?,?,?)
                    """, (
                        str(row.get("fil_nr", "")).strip(),
                        str(row.get("bundesland", "DE-RP")).strip(),
                        str(row.get("bezeichnung", "")) or None,
                        str(row.get("ort", "")) or None,
                        str(row.get("eroeffnung", "")) or None,
                    ))
                conn.commit()
                st.success(f"✅ {len(imp)} Filialen importiert.")
                st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Import: {e}")
