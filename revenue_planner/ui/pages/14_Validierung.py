"""Plausibilitätsprüfung: automatische Checks vor der Planung (Ampel-Anzeige)."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from planning.engine import PlanningEngine, PlanParams, _normalize_bl, _BL_NAME_TO_ABBR
import pandas as pd
from datetime import date, timedelta

require_db()
conn = get_conn()
planjahr = get_budgetjahr()

st.title("Plausibilitätsprüfung")
st.caption(f"Firma: **{get_gmbh()}** — Budgetjahr: **{planjahr}**")

VALID_BL = set(_BL_NAME_TO_ABBR.values())

# Gleiche Stichtagslogik wie 6_Planung
today = date.today()
stichtag = date(today.year, 1, 1) if planjahr <= today.year else today
engine = PlanningEngine(conn, PlanParams(planjahr=planjahr, stichtag=stichtag))

checks = []  # (status: 'ok'|'warn'|'crit', titel, detail_df oder None, caption)


def add(status, titel, details=None, caption=""):
    checks.append((status, titel, details, caption))


filialen = [dict(r) for r in conn.execute("SELECT * FROM filialen").fetchall()]

# 1) Filialen ohne/mit unbekanntem Bundesland
bad_bl = [
    {"Filiale": f["fil_nr"], "Bundesland": f.get("bundesland") or "(leer)"}
    for f in filialen
    if not f.get("bundesland") or _normalize_bl(f["bundesland"]) not in VALID_BL
]
add("crit" if bad_bl else "ok",
    f"Filialen ohne/mit unbekanntem Bundesland: {len(bad_bl)}",
    pd.DataFrame(bad_bl) if bad_bl else None,
    "Ohne gültiges Bundesland greifen Feiertage und Ferien nicht korrekt "
    "(Fallback RP).")

# 2) Filialen ohne IST-Daten im Basiszeitraum
base_start = engine.base_start.isoformat()
base_end_excl = engine.base_mask_end.date().isoformat()
ist_in_base = {
    str(r["fil_nr"]): r["n"]
    for r in conn.execute(
        "SELECT fil_nr, COUNT(*) AS n FROM ist_umsatz "
        "WHERE datum >= ? AND datum < ? AND umsatz > 0 GROUP BY fil_nr",
        (base_start, base_end_excl)).fetchall()
}
no_ist = [{"Filiale": f["fil_nr"], "Bezeichnung": f.get("bezeichnung", "")}
          for f in filialen if str(f["fil_nr"]) not in ist_in_base]
add("crit" if no_ist else "ok",
    f"Filialen ohne IST-Daten im Basiszeitraum ({engine.base_window_label()}): {len(no_ist)}",
    pd.DataFrame(no_ist) if no_ist else None,
    "Diese Filialen erhalten ohne Override/Neue-Filialen-Planwert Budget 0.")

# 3) Monate im Basisfenster ohne Umsatz je Filiale (Extrapolations-Fallback)
month_rows = conn.execute(
    "SELECT fil_nr, strftime('%Y-%m', datum) AS ym, SUM(umsatz) AS s "
    "FROM ist_umsatz WHERE datum >= ? AND datum < ? GROUP BY fil_nr, ym",
    (base_start, base_end_excl)).fetchall()
have = {(str(r["fil_nr"]), r["ym"]) for r in month_rows if (r["s"] or 0) > 0}
expected_yms = []
for m in range(1, 13):
    y = engine.base_year_for_month(m)
    expected_yms.append(f"{y:04d}-{m:02d}")
gaps = []
for f in filialen:
    fn = str(f["fil_nr"])
    if fn not in ist_in_base:
        continue  # bereits in Check 2 gemeldet
    missing = [ym for ym in expected_yms if (fn, ym) not in have]
    if missing:
        gaps.append({"Filiale": fn, "Fehlende Monate": ", ".join(sorted(missing))})
add("warn" if gaps else "ok",
    f"Filialen mit Monaten ohne Umsatz im Basisfenster: {len(gaps)}",
    pd.DataFrame(gaps) if gaps else None,
    "Für fehlende Monate greift der Extrapolations-Fallback aus dem "
    "Wochentags-Durchschnitt (prüfen, ob das fachlich gewollt ist).")

# 4) Ferienperioden des Budgetjahrs ohne passende Vorjahresperiode
fer_plan = conn.execute(
    "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
    (planjahr,)).fetchall()
fer_vj_keys = {(r["bundesland"], r["art"]) for r in conn.execute(
    "SELECT bundesland, art FROM ferien_kalender WHERE jahr=?", (planjahr - 1,))}
fer_orphans = [
    {"Bundesland": r["bundesland"], "Art": r["art"],
     "Zeitraum": f'{r["start"]} – {r["ende"]}'}
    for r in fer_plan if (r["bundesland"], r["art"]) not in fer_vj_keys
]
add("warn" if fer_orphans else "ok",
    f"Ferienperioden {planjahr} ohne Vorjahresperiode: {len(fer_orphans)}",
    pd.DataFrame(fer_orphans) if fer_orphans else None,
    "Diese Perioden werden von der Engine IGNORIERT — Ferien immer für "
    "Budgetjahr UND Vorjahr in den Ferienkalender laden.")

# 5) Feiertage des Budgetjahrs ohne datum_vj
ft_no_vj = [
    {"Datum": r["datum_plan"], "Beschreibung": r["name"], "Bundesland": r["bundesland"]}
    for r in conn.execute(
        "SELECT datum_plan, name, bundesland FROM feiertage "
        "WHERE LOWER(art)='feiertag' AND datum_plan LIKE ? "
        "AND (datum_vj IS NULL OR datum_vj='')", (f"{planjahr}-%",))
]
add("warn" if ft_no_vj else "ok",
    f"Feiertage {planjahr} ohne Vorjahres-Referenzdatum: {len(ft_no_vj)}",
    pd.DataFrame(ft_no_vj) if ft_no_vj else None,
    "Ohne datum_vj kann der Feiertagseffekt keinen IST-Referenztag finden "
    "(ist_vj = 0).")

# 6) Feiertage/Ferien für Budgetjahr überhaupt geladen?
n_ft = conn.execute(
    "SELECT COUNT(*) AS n FROM feiertage WHERE LOWER(art)='feiertag' AND datum_plan LIKE ?",
    (f"{planjahr}-%",)).fetchone()["n"]
n_fer = len(fer_plan)
add("crit" if n_ft == 0 else "ok",
    f"Feiertage für {planjahr} geladen: {n_ft}",
    None,
    "0 Feiertage → Seite 'Feiertage u. Ferien' ausführen." if n_ft == 0 else "")
add("warn" if n_fer == 0 else "ok",
    f"Ferienperioden für {planjahr} geladen: {n_fer}",
    None,
    "0 Ferienperioden → Ferienkalender pflegen (sofern relevant)." if n_fer == 0 else "")

# 7) IST-Datenlücken: letztes IST-Datum > 35 Tage vor Max-IST aller Filialen
max_all_row = conn.execute("SELECT MAX(datum) AS d FROM ist_umsatz").fetchone()
stale = []
if max_all_row and max_all_row["d"]:
    max_all = date.fromisoformat(max_all_row["d"])
    cutoff = (max_all - timedelta(days=35)).isoformat()
    last_per_fil = {str(r["fil_nr"]): r["d"] for r in conn.execute(
        "SELECT fil_nr, MAX(datum) AS d FROM ist_umsatz GROUP BY fil_nr")}
    for f in filialen:
        fn = str(f["fil_nr"])
        last = last_per_fil.get(fn)
        if last and last < cutoff:
            stale.append({"Filiale": fn, "Letztes IST-Datum": last,
                          "Max IST gesamt": max_all_row["d"]})
add("warn" if stale else "ok",
    f"Filialen mit IST-Datenlücke (> 35 Tage hinter Max-IST): {len(stale)}",
    pd.DataFrame(stale) if stale else None,
    "Möglicherweise geschlossene Filialen oder unvollständiger Import.")

# 8) parameter_monat für Budgetjahr vorhanden?
n_pm = conn.execute(
    "SELECT COUNT(*) AS n FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchone()["n"]
add("warn" if n_pm == 0 else "ok",
    f"Wachstumsparameter (parameter_monat) für {planjahr}: {n_pm} Monate",
    None,
    "Ohne Einträge wird mit 0 % Wachstum geplant — Seite "
    "'Preisanpassung je Monat' pflegen." if n_pm < 12 else "")

# ── Gesamtampel ─────────────────────────────────────────────────────────────
n_crit = sum(1 for c in checks if c[0] == "crit")
n_warn = sum(1 for c in checks if c[0] == "warn")
if n_crit:
    st.error(f"❌ {n_crit} kritische Punkte, {n_warn} Warnungen — vor der "
             "Planung beheben.")
elif n_warn:
    st.warning(f"⚠️ {n_warn} Warnungen — Planung möglich, Punkte prüfen.")
else:
    st.success("✅ Bereit zur Planung — alle Checks bestanden.")

st.divider()

ICON = {"ok": "✅", "warn": "⚠️", "crit": "❌"}
for status, titel, details, caption in checks:
    st.markdown(f"{ICON[status]} **{titel}**")
    if caption:
        st.caption(caption)
    if details is not None and not details.empty:
        with st.expander(f"Details ({len(details)})"):
            st.dataframe(details, use_container_width=True, hide_index=True)
