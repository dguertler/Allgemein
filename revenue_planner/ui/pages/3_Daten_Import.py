"""IST revenue data import page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from database.importer import import_ist_umsatz, ensure_filialen_from_ist
import pandas as pd

require_db()
conn = get_conn()
st.title("IST-Umsätze importieren")
st.caption(f"Firma: **{get_gmbh()}**")

st.markdown("""
Erwartet eine Datei mit mindestens drei Spalten:
- **Datum** (z.B. `15.01.2024` oder `2024-01-15`)
- **Filialnummer** (z.B. `0120`)
- **Umsatz brutto** (Dezimalzahl)

Weitere Spalten werden ignoriert.
""")

# Show result from previous import (above uploader)
if "ist_import_result" in st.session_state:
    result = st.session_state.pop("ist_import_result")
    if result["type"] == "success":
        for w in result.get("warnings", []):
            st.warning(w)
        st.success(result["message"])
        if result.get("new_fil", 0) > 0:
            st.info(f"ℹ️ {result['new_fil']} neue Filial-Einträge automatisch angelegt — bitte Bundesland unter **Filialen** prüfen.")
    elif result["type"] == "error":
        st.error(result["message"])

if "ist_upload_key" not in st.session_state:
    st.session_state["ist_upload_key"] = 0

uploaded = st.file_uploader(
    "Datei hochladen (Excel oder CSV)",
    type=["xlsx", "xls", "csv"],
    key=f"ist_uploader_{st.session_state['ist_upload_key']}",
)

if st.button("⬆️ Importieren", type="primary", disabled=uploaded is None):
    try:
        n, warnings = import_ist_umsatz(conn, uploaded, file_name=uploaded.name)
        new_fil = ensure_filialen_from_ist(conn, "RP")
        st.session_state["ist_import_result"] = {
            "type": "success",
            "message": f"✅ {n:,} Datensätze importiert.",
            "warnings": warnings,
            "new_fil": new_fil,
        }
        st.session_state["ist_upload_key"] += 1
    except ValueError as e:
        st.session_state["ist_import_result"] = {
            "type": "error",
            "message": f"Spaltenfehler: {e}",
        }
    except Exception as e:
        st.session_state["ist_import_result"] = {
            "type": "error",
            "message": f"Import fehlgeschlagen: {e}",
        }
    st.rerun()

st.divider()
st.subheader("Aktueller Datenbestand")

summary = pd.read_sql("""
    SELECT fil_nr,
           MIN(datum) AS von,
           MAX(datum) AS bis,
           COUNT(*)   AS tage,
           ROUND(SUM(umsatz), 2) AS gesamt_eur
    FROM ist_umsatz
    GROUP BY fil_nr
    ORDER BY fil_nr
""", conn)

if summary.empty:
    st.info("Noch keine IST-Daten vorhanden.")
else:
    summary = summary.rename(columns={
        "fil_nr": "Filialnummer",
        "von": "Von",
        "bis": "Bis",
        "tage": "Tage",
        "gesamt_eur": "Gesamtumsatz brutto",
    })
    st.dataframe(summary, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    col1.metric("Filialen mit IST-Daten", len(summary))
    col2.metric("Datensätze gesamt", f"{summary['Tage'].sum():,}")
