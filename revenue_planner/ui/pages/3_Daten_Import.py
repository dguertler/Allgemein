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
st.caption(f"GmbH: **{get_gmbh()}**")

st.markdown("""
Erwartet eine Datei mit mindestens drei Spalten:
- **Datum** (z.B. `15.01.2024` oder `2024-01-15`)
- **Filialnummer** (z.B. `0120`)
- **Umsatz brutto** (Dezimalzahl)

Weitere Spalten werden ignoriert.
""")

uploaded = st.file_uploader("Datei hochladen (Excel oder CSV)", type=["xlsx", "xls", "csv"])

if uploaded:
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        n, warnings = import_ist_umsatz(conn, tmp_path)
        for w in warnings:
            st.warning(w)
        st.success(f"✅ {n:,} Datensätze importiert.")

        new_fil = ensure_filialen_from_ist(conn, "RP")
        if new_fil > 0:
            st.info(f"ℹ️ {new_fil} neue Filial-Einträge automatisch angelegt — bitte Bundesland unter **Filialen** prüfen.")
    except ValueError as e:
        st.error(f"Spaltenfehler: {e}")
    except Exception as e:
        st.error(f"Import fehlgeschlagen: {e}")
    finally:
        os.unlink(tmp_path)

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
    st.dataframe(summary, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    col1.metric("Filialen mit IST-Daten", len(summary))
    col2.metric("Datensätze gesamt", f"{summary['tage'].sum():,}")
