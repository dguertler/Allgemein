"""Monthly price adjustment (%) per plan year."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
st.title("Preisanpassung je Monat (%)")
st.caption(f"Firma: **{get_gmbh()}**")

st.markdown("""
Trage hier die geplante **Preisanpassung je Monat** in % ein
(positive Werte = Preissteigerung, negative = Preissenkung).
Diese Werte werden als Wachstumsfaktor in der Planung beruecksichtigt.
0 % = kein Preiseffekt in diesem Monat.
""")

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1)

# Read existing values
monat_rows = conn.execute(
    "SELECT monat, wachstum_pct FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchall()
existing_pct = {r["monat"]: r["wachstum_pct"] for r in monat_rows}

MONATE = ["Jan", "Feb", "Maer", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

initial = {m: existing_pct.get(i + 1, 0.0) for i, m in enumerate(MONATE)}
edited = st.data_editor(
    pd.DataFrame([initial]),
    column_config={
        m: st.column_config.NumberColumn(m, min_value=-20.0, max_value=50.0, step=0.1, format="%.1f")
        for m in MONATE
    },
    use_container_width=True,
    hide_index=True,
    key=f"preis_editor_{planjahr}",
)

# Show cumulative
vals = [float(edited[m].iloc[0]) for m in MONATE]
cumul, s = [], 0.0
for v in vals:
    s += v
    cumul.append(round(s, 1))
st.dataframe(
    pd.DataFrame([{m: f"{c:+.1f} %" for m, c in zip(MONATE, cumul)}], index=["Kumuliert"]),
    use_container_width=True,
)

if st.button("Preisanpassungen speichern", type="primary"):
    for i, m in enumerate(MONATE):
        conn.execute("""
            INSERT INTO parameter_monat (planjahr, monat, wachstum_pct)
            VALUES (?,?,?)
            ON CONFLICT(planjahr, monat) DO UPDATE SET wachstum_pct=excluded.wachstum_pct
        """, (planjahr, i + 1, float(edited[m].iloc[0])))
    conn.commit()
    st.success("Gespeichert.")
    st.rerun()
