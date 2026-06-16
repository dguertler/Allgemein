"""Herleitung der Budgetberechnung — additive Effektzerlegung je Ebene."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
import pandas as pd
import io

require_db()
conn = get_conn()
gmbh = get_gmbh()
planjahr = get_budgetjahr()

st.title("Herleitung der Budgetberechnung")

df_all = pd.read_sql(
    "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    conn, params=(planjahr,),
)

if df_all.empty:
    st.info(
        f"Noch keine Planungsdaten für {planjahr} vorhanden. "
        "Bitte zuerst unter **Planung ausführen** eine Berechnung starten."
    )
    st.stop()

# IST-Umsätze des Budgetjahrs laden (für Plan vs. tatsächlichem IST-Vergleich)
_ist_rows_hrl = conn.execute(
    "SELECT fil_nr, datum, umsatz FROM ist_umsatz WHERE datum LIKE ?",
    (f"{planjahr}-%",),
).fetchall()
_ist_lookup_hrl = {(str(r["fil_nr"]), r["datum"]): r["umsatz"] for r in _ist_rows_hrl}

eff_cols = ["ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
            "eff_preis", "eff_ferien", "eff_feiertag", "budget"]
for col in eff_cols + ["eff_norm"]:
    if col not in df_all.columns:
        df_all[col] = 0.0
    df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0.0)

if "budget" not in df_all.columns or df_all["budget"].sum() == 0:
    for alt in ["gesamt_plan", "tagesumsatz_plan"]:
        if alt in df_all.columns:
            df_all["budget"] = pd.to_numeric(df_all[alt], errors="coerce").fillna(0.0)
            break

df_all["datum"] = pd.to_datetime(df_all["datum"])

# Datumsmapping für Basisdatum-Spalte im Tag-View laden
_dm_rows = conn.execute(
    "SELECT plan_datum, base_datum, bundesland FROM datumsmapping "
    "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER)=?",
    (planjahr,),
).fetchall()
_dm_lookup = {(r["plan_datum"], r["bundesland"]): r["base_datum"] for r in _dm_rows}

def _base_datum_for(row) -> str:
    iso = row["datum"].strftime("%Y-%m-%d")
    bl = str(row.get("bundesland", "") or "")
    bd = _dm_lookup.get((iso, bl)) or _dm_lookup.get((iso, "alle")) or ""
    if not bd:
        return ""
    try:
        return pd.Timestamp(bd).strftime("%d.%m.%Y")
    except Exception:
        return bd

# Last imported day for IST comparison limit
_last_ist_date = conn.execute(
    "SELECT MAX(datum) FROM ist_umsatz WHERE datum LIKE ?", (f"{planjahr}-%",)
).fetchone()[0] or ""

df_all["ist_aktuell"] = df_all.apply(
    lambda r: _ist_lookup_hrl.get((str(r["fil_nr"]), r["datum"].strftime("%Y-%m-%d"))),
    axis=1
)
if "bundesland" not in df_all.columns or df_all["bundesland"].isna().all():
    bl_map = {r[0]: r[1] for r in conn.execute("SELECT fil_nr, bundesland FROM filialen").fetchall()}
    df_all["bundesland"] = df_all["fil_nr"].map(bl_map).fillna("?")

for col in ["tagestyp", "feiertag_name", "ferien_art"]:
    if col not in df_all.columns:
        df_all[col] = ""
    df_all[col] = df_all[col].fillna("")

# Filter out branches with no meaningful data (all budget and ist_vj = 0)
fil_has_data = df_all.groupby("fil_nr")[["budget", "ist_vj"]].sum().abs().sum(axis=1) > 0
active_fils = set(fil_has_data[fil_has_data].index)
df_all = df_all[df_all["fil_nr"].isin(active_fils)]

if df_all.empty:
    st.info("Keine berechneten Planungsdaten vorhanden.")
    st.stop()

# ── Filter (at top, state persisted via key) ──────────────────────────────
cf1, cf2 = st.columns(2)
with cf1:
    fil_filter = st.multiselect(
        "Filtern auf Filiale(n) (leer = alle)",
        sorted(df_all["fil_nr"].unique()),
        placeholder="Filialen auswählen...",
        key="herleitung_fil_filter",
    )
with cf2:
    bl_filter = st.multiselect(
        "Filtern auf Bundesland (leer = alle)",
        sorted(df_all["bundesland"].dropna().unique()),
        placeholder="Bundesland auswählen...",
        key="herleitung_bl_filter",
    )

if fil_filter:
    df_all = df_all[df_all["fil_nr"].isin(fil_filter)]
if bl_filter:
    df_all = df_all[df_all["bundesland"].isin(bl_filter)]

# ── Steuerung ──────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    zeit_ebene = st.selectbox(
        "Zeit-Ebene", ["Tag", "Woche", "Monat", "Jahr"], index=2,
        key="herleitung_zeit",
    )
with c2:
    entity_ebene = st.selectbox(
        "Aggregations-Ebene", ["Filiale", "Bundesland", "Gesamt"],
        key="herleitung_entity",
    )

# ── Zeit-Gruppierung ────────────────────────────────────────────────────────
if zeit_ebene == "Tag":
    df_all["Zeit"] = df_all["datum"].dt.strftime("%d.%m.%Y")
    df_all["_sort"] = df_all["datum"]
elif zeit_ebene == "Woche":
    iso = df_all["datum"].dt.isocalendar()
    df_all["Zeit"] = "KW " + iso["week"].astype(str).str.zfill(2) + "/" + iso["year"].astype(str)
    df_all["_sort"] = df_all["datum"].dt.to_period("W").apply(lambda p: p.start_time)
elif zeit_ebene == "Monat":
    MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    df_all["Zeit"] = df_all["datum"].dt.month.map(lambda m: MON[m - 1]) + " " + df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.to_period("M").apply(lambda p: p.start_time)
else:
    df_all["Zeit"] = df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.year

group_keys = ["Zeit", "_sort"]
if entity_ebene == "Filiale":
    group_keys = ["fil_nr"] + group_keys
elif entity_ebene == "Bundesland":
    group_keys = ["bundesland"] + group_keys

extra_agg = {}
if zeit_ebene == "Tag":
    for c in ["wochentag", "tagestyp", "feiertag_name", "ferien_art"]:
        if c in df_all.columns:
            extra_agg[c] = "first"

# Budget up to last imported day (for Abw. IST comparison)
if _last_ist_date:
    df_all["_budget_for_ist"] = df_all.apply(
        lambda r: r["budget"] if r["datum"].strftime("%Y-%m-%d") <= _last_ist_date else None,
        axis=1
    )
else:
    df_all["_budget_for_ist"] = None

agg = (df_all.groupby([k for k in group_keys if k != "_sort"], as_index=False)
       .agg({**{c: "sum" for c in eff_cols},
             "ist_aktuell": lambda x: x.sum() if x.notna().any() else None,
             "_budget_for_ist": lambda x: x.sum() if x.notna().any() else None,
             "_sort": "min", **extra_agg})
       .sort_values([k for k in (["_sort"] if entity_ebene == "Gesamt"
                                  else [group_keys[0], "_sort"])]))
agg = agg.reset_index(drop=True)

WT_MAP = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

def _build_tagesinfo(tagestyp, feiertag_name, ferien_art):
    parts = []
    typ = tagestyp or ""
    name = feiertag_name or ""
    ferien = ferien_art or ""
    if typ in ("feiertag", "sondertag") and name:
        parts.append(name)
    elif typ == "geschlossen":
        if name:
            parts.append(f"Geschlossen ({name})")
        else:
            parts.append("Geschlossen")
    if ferien:
        parts.append(ferien)
    return " | ".join(parts) if parts else ""

if zeit_ebene == "Tag":
    if "wochentag" in agg.columns:
        agg["_wt_str"] = agg["wochentag"].apply(
            lambda w: WT_MAP[int(w)] if pd.notna(w) else "")
    def _lookup_basisdatum(row) -> str:
        try:
            iso = pd.Timestamp(row["Zeit"], dayfirst=True).strftime("%Y-%m-%d")
        except Exception:
            return ""
        bl = str(row.get("bundesland", "") or "")
        bd = _dm_lookup.get((iso, bl)) or _dm_lookup.get((iso, "alle")) or ""
        if not bd:
            return ""
        try:
            return pd.Timestamp(bd).strftime("%d.%m.%Y")
        except Exception:
            return bd
    agg["_basisdatum"] = agg.apply(_lookup_basisdatum, axis=1)
    agg["_tagesinfo"] = agg.apply(
        lambda r: _build_tagesinfo(
            r.get("tagestyp", ""), r.get("feiertag_name", ""), r.get("ferien_art", "")),
        axis=1)

# IST aktuell vs. Budget — nur bis zum letzten importierten Tag
agg["Abw. IST €"] = agg.apply(
    lambda x: round(float(x["ist_aktuell"]) - float(x["_budget_for_ist"]), 2)
    if not pd.isna(x["ist_aktuell"]) and not pd.isna(x.get("_budget_for_ist")) else None, axis=1
)
agg["Abw. IST %"] = agg.apply(
    lambda x: round(float(x["Abw. IST €"]) / float(x["_budget_for_ist"]) * 100, 1)
    if not pd.isna(x.get("Abw. IST €")) and float(x.get("_budget_for_ist", 0) or 0) != 0 else None,
    axis=1
)

rename = {
    "fil_nr": "Filiale", "bundesland": "Bundesland",
    "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung", "eff_verteilung": "+ Verteilung",
    "eff_wochentag": "+ Wochentag", "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
    "eff_feiertag": "+ Feiertag", "budget": "= Budget",
    "ist_aktuell": "IST aktuell",
}
if zeit_ebene == "Tag":
    rename["Zeit"] = "Datum"
    rename["_wt_str"] = "Wochentag"
    rename["_basisdatum"] = "Basisdatum"
    rename["_tagesinfo"] = "Tagesinfo"

drop_cols = ["_sort", "eff_norm", "_budget_for_ist"] + [
    c for c in ["wochentag", "tagestyp", "feiertag_name", "ferien_art"]
    if c in agg.columns and zeit_ebene == "Tag"
]
if zeit_ebene != "Tag" and "_basisdatum" in agg.columns:
    drop_cols.append("_basisdatum")
disp = agg.drop(columns=[c for c in drop_cols if c in agg.columns]).rename(columns=rename)

if zeit_ebene == "Tag":
    lead = [c for c in ["Filiale", "Bundesland", "Datum", "Basisdatum", "Wochentag", "Tagesinfo"] if c in disp.columns]
else:
    lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]
# Δ € and Δ % removed (after = Budget); Abw. IST only up to last imported day
ordered = lead + ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
                  "+ Ferien", "+ Feiertag", "= Budget",
                  "IST aktuell", "Abw. IST €", "Abw. IST %"]
disp = disp[[c for c in ordered if c in disp.columns]]

# ── Kennzahlen ─────────────────────────────────────────────────────────────
tot_vj = agg["ist_vj"].sum()
tot_bud = agg["budget"].sum()
m1, m2, m3, m4 = st.columns(4)

def _de(val) -> str:
    try:
        if pd.isna(val):
            return "–"
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "–"

m1.metric("IST Basis", f"{_de(tot_vj)} €")
m2.metric("Budget", f"{_de(tot_bud)} €")
m3.metric("Δ €", f"{'+' if tot_bud >= tot_vj else ''}{_de(tot_bud - tot_vj)} €")
m4.metric("Δ %", f"{(tot_bud - tot_vj) / tot_vj * 100:+.1f} %" if tot_vj else "–")

st.caption(
    "Lesart: **IST Basis** = Umsatz des korrespondierenden Basistags. "
    "Jede `+`-Spalte zeigt den additiven Effekt in €. Summe ergibt **= Budget**."
)
st.divider()

# ── Tabelle ─────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
            "+ Ferien", "+ Feiertag", "= Budget", "IST aktuell", "Abw. IST €"]

def _fmt_de(val):
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""

def _fmt_pct(val):
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(val):+.1f} %"
    except (TypeError, ValueError):
        return ""

disp_fmt = disp.copy()
for c in num_cols:
    if c in disp_fmt.columns:
        disp_fmt[c] = disp_fmt[c].apply(_fmt_de)
if "Abw. IST %" in disp_fmt.columns:
    disp_fmt["Abw. IST %"] = disp_fmt["Abw. IST %"].apply(_fmt_pct)

col_cfg = {
    "Basisdatum":   st.column_config.TextColumn("Basisdatum",
        help="Referenztag aus dem Basiszeitraum, dessen IST-Umsatz als Grundlage dient"),
    "IST Basis":    st.column_config.TextColumn("IST Basis",
        help="Tagesumsatz des Basiszeitraum-Referenztags (gleicher Wochentag, gleiches Monat im Vorjahr)"),
    "+ Öffnung":   st.column_config.TextColumn("+ Öffnung",
        help="Effekt durch geänderte Öffnungstage: positiv wenn Filiale im Planjahr mehr Tage geöffnet hat, negativ wenn weniger"),
    "+ Verteilung":st.column_config.TextColumn("+ Verteilung",
        help="Glättung: korrigiert, dass der konkrete Basistag über- oder unterdurchschnittlich war. "
             "Basis-Einzeltag → Wochentagsdurchschnitt des Monats"),
    "+ Wochentag": st.column_config.TextColumn("+ Wochentag",
        help="Wochentagsmix-Effekt: Planjahr hat andere Wochentag-Verteilung als Basisjahr. "
             "Z.B. Jan 2026 hat einen Montag mehr als Jan 2025 → positiver Wert"),
    "+ Preis":     st.column_config.TextColumn("+ Preis",
        help="Preis- / Wachstumseffekt aus den Preisanpassungsparametern (% je Monat)"),
    "+ Ferien":    st.column_config.TextColumn("+ Ferien",
        help="Ferieneffekt: Verhältnis Ø Ferienwochenumsatz zu Ø Pufferwochenumsatz (wochentags-gematcht). "
             "Positiv bei Bäckereien mit Mehrumsatz in Ferien, negativ bei Schulfilialen"),
    "+ Feiertag":  st.column_config.TextColumn("+ Feiertag",
        help="Feiertags-/Sondertag-Effekt. Geschlossener Feiertag = negativer Wert (kein Umsatz). "
             "Sondertag (z.B. Muttertag) = positiver Wert"),
    "= Budget":    st.column_config.TextColumn("= Budget",
        help="Tagesbudget = IST Basis + alle Effekte"),
    "IST aktuell": st.column_config.TextColumn("IST aktuell",
        help="Tatsächlich erreichter IST-Umsatz im Budgetjahr (soweit importiert)"),
    "Abw. IST €":  st.column_config.TextColumn("Abw. IST €",
        help="IST aktuell − Budget (positiv = über Budget, negativ = unter Budget)"),
    "Abw. IST %":  st.column_config.TextColumn("Abw. IST %",
        help="Abweichung IST vs. Budget in Prozent"),
}

st.dataframe(
    disp_fmt,
    use_container_width=True,
    hide_index=True,
    height=560,
    column_config={k: v for k, v in col_cfg.items() if k in disp_fmt.columns},
)

# ── Excel-Export ────────────────────────────────────────────────────────────
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    disp.to_excel(writer, index=False, sheet_name="Herleitung")
    from openpyxl.styles import Font
    ws = writer.sheets["Herleitung"]
    for cell in ws[1]:
        cell.font = Font(bold=True)
st.download_button(
    "📥 Excel herunterladen",
    data=buf.getvalue(),
    file_name=f"Herleitung_{planjahr}_{zeit_ebene}_{entity_ebene}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)

# ── Legende (immer ausgeklappt) ──────────────────────────────────────────────
st.divider()
with st.expander("📖 Legende — Spaltenbezeichnungen und Berechnungslogik", expanded=True):
    st.markdown("""
### Spaltenbedeutungen

| Spalte | Bedeutung | Beispiel |
|--------|-----------|---------|
| **IST Basis** | Tagesumsatz des korrespondierenden Basistags (gleicher Wochentag, gleicher Monat, Basisjahr) | Mo, 06.01.2025 → 5.234 € (Referenz für Mo, 05.01.2026) |
| **+ Öffnung** | Effekt durch geänderte Öffnungstage im Planjahr | Filiale öffnet ab 2026 samstags (+432 €); geschlossener Feiertag (−2.500 €) |
| **+ Verteilung** | Glättung: der konkrete Basistag wird auf den Wochentags-Ø des Monats normiert. Korrigiert, dass einzelne Basis-Tage zufällig über- oder unterdurchschnittlich waren. | Basistag 06.01.2025 hatte 6.000 €, Ø Montag Jan 25 = 5.500 € → Verteilung = −500 € |
| **+ Wochentag** | Wochentagsmix-Effekt: hat Planjahr mehr/weniger bestimmte Wochentage als Basisjahr? | Jan 2026 hat 5 Montage, Jan 2025 hatte 4 → ein Montag-Anteil mehr → +200 € |
| **+ Preis** | Preis-/Wachstumsfaktor aus den Preisanpassungsparametern (% je Monat) | 3 % im Jan → Basisbetrag × 3 % / offene Tage ≈ +53 € je Tag |
| **+ Ferien** | Ferienfaktor: Verhältnis Ø Ferienwochenumsatz zu Ø Pufferwochenumsatz | Osterferien: +20 % → +1.100 €; Schulfiliale in Ferien: −40 % → −800 € |
| **+ Feiertag** | Feiertags-/Sondertag-Effekt (Abweichung vom normalen Tagswert) | Christi Himmelfahrt geschlossen → −5.000 €; Muttertag Mehrumsatz → +600 € |
| **= Budget** | Tagesbudget = IST Basis + Summe aller Effekte | 5.234 − 500 + 200 + 53 + 0 + 0 = **4.987 €** |

### Berechnungsformel (additiv je Tag)

```
Budget = IST Basis + Öffnung + Verteilung + Wochentag + Preis + Ferien + Feiertag
```

Diese Zerlegung addiert sich durch einfache Summation auf jede Zeit- und Aggregationsebene
(Woche / Monat / Jahr, Filiale / Bundesland / Gesamt).
""")
