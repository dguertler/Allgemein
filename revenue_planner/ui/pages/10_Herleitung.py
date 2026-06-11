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

eff_cols = ["ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
            "eff_preis", "eff_ferien", "eff_feiertag", "eff_norm", "budget"]
for col in eff_cols:
    if col not in df_all.columns:
        df_all[col] = 0.0
    df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0.0)

if "budget" not in df_all.columns or df_all["budget"].sum() == 0:
    for alt in ["gesamt_plan", "tagesumsatz_plan"]:
        if alt in df_all.columns:
            df_all["budget"] = pd.to_numeric(df_all[alt], errors="coerce").fillna(0.0)
            break

df_all["datum"] = pd.to_datetime(df_all["datum"])
if "bundesland" not in df_all.columns or df_all["bundesland"].isna().all():
    bl_map = {r[0]: r[1] for r in conn.execute("SELECT fil_nr, bundesland FROM filialen").fetchall()}
    df_all["bundesland"] = df_all["fil_nr"].map(bl_map).fillna("?")

for col in ["tagestyp", "feiertag_name", "ferien_art"]:
    if col not in df_all.columns:
        df_all[col] = ""
    df_all[col] = df_all[col].fillna("")

# ── Filter (at top) ────────────────────────────────────────────────────────
cf1, cf2 = st.columns(2)
with cf1:
    fil_filter = st.multiselect(
        "Filtern auf Filiale(n) (leer = alle)",
        sorted(df_all["fil_nr"].unique()),
    )
with cf2:
    bl_filter = st.multiselect(
        "Filtern auf Bundesland (leer = alle)",
        sorted(df_all["bundesland"].dropna().unique()),
    )

if fil_filter:
    df_all = df_all[df_all["fil_nr"].isin(fil_filter)]
if bl_filter:
    df_all = df_all[df_all["bundesland"].isin(bl_filter)]

# ── Steuerung ──────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    zeit_ebene = st.selectbox("Zeit-Ebene", ["Tag", "Woche", "Monat", "Jahr"], index=2)
with c2:
    entity_ebene = st.selectbox("Aggregations-Ebene", ["Filiale", "Bundesland", "Gesamt"])

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

agg = (df_all.groupby([k for k in group_keys if k != "_sort"], as_index=False)
       .agg({**{c: "sum" for c in eff_cols}, "_sort": "min", **extra_agg})
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
    if typ == "geschlossen":
        parts.append("Geschlossen")
    if ferien:
        parts.append(ferien)
    return " | ".join(parts) if parts else ""

if zeit_ebene == "Tag":
    if "wochentag" in agg.columns:
        agg["_wt_str"] = agg["wochentag"].apply(
            lambda w: WT_MAP[int(w)] if pd.notna(w) else "")
    agg["_tagesinfo"] = agg.apply(
        lambda r: _build_tagesinfo(
            r.get("tagestyp", ""), r.get("feiertag_name", ""), r.get("ferien_art", "")),
        axis=1)

agg["Δ €"] = agg["budget"] - agg["ist_vj"]
agg["Δ %"] = agg.apply(lambda x: round(x["Δ €"] / x["ist_vj"] * 100, 1) if x["ist_vj"] else None, axis=1)

rename = {
    "fil_nr": "Filiale", "bundesland": "Bundesland",
    "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung", "eff_verteilung": "+ Verteilung",
    "eff_wochentag": "+ Wochentag", "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
    "eff_feiertag": "+ Feiertag", "eff_norm": "+ Norm.", "budget": "= Budget",
}
if zeit_ebene == "Tag":
    rename["Zeit"] = "Datum"
    rename["_wt_str"] = "Wochentag"
    rename["_tagesinfo"] = "Tagesinfo"

drop_cols = ["_sort"] + [c for c in ["wochentag", "tagestyp", "feiertag_name", "ferien_art"]
                          if c in agg.columns and zeit_ebene == "Tag"]
disp = agg.drop(columns=[c for c in drop_cols if c in agg.columns]).rename(columns=rename)

if zeit_ebene == "Tag":
    lead = [c for c in ["Filiale", "Bundesland", "Datum", "Wochentag", "Tagesinfo"] if c in disp.columns]
else:
    lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]
ordered = lead + ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
                  "+ Ferien", "+ Feiertag", "+ Norm.", "= Budget", "Δ €", "Δ %"]
disp = disp[[c for c in ordered if c in disp.columns]]

# ── Kennzahlen ─────────────────────────────────────────────────────────────
tot_vj = agg["ist_vj"].sum()
tot_bud = agg["budget"].sum()
m1, m2, m3, m4 = st.columns(4)

def _de(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "–"
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

m1.metric("IST Basis", f"{_de(tot_vj)} €")
m2.metric("Budget", f"{_de(tot_bud)} €")
m3.metric("Δ €", f"{'+' if tot_bud >= tot_vj else ''}{_de(tot_bud - tot_vj)} €")
m4.metric("Δ %", f"{(tot_bud - tot_vj) / tot_vj * 100:+.1f} %" if tot_vj else "–")

st.caption(
    "Lesart: **IST Basis** = Umsatz des korrespondierenden Basistags. "
    "Jede `+`-Spalte zeigt den additiven Effekt in €. Summe ergibt **= Budget**. "
    "**Zeile anklicken** für Tagesdetails und Effekterklärung."
)
st.divider()

# ── Tabelle ─────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
            "+ Ferien", "+ Feiertag", "+ Norm.", "= Budget", "Δ €"]

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
if "Δ %" in disp_fmt.columns:
    disp_fmt["Δ %"] = disp_fmt["Δ %"].apply(_fmt_pct)

selection = st.dataframe(
    disp_fmt,
    use_container_width=True,
    hide_index=True,
    height=560,
    on_select="rerun",
    selection_mode="single-row",
)

# ── Detail-Panel bei Zeilenauswahl ─────────────────────────────────────────
_EFFECT_INFO = [
    ("ist_vj",        "IST Basis",    "Tagesumsatz des korrespondierenden Basistags im Basiszeitraum."),
    ("eff_oeffnung",  "+ Öffnung",    "Korrektur für neu hinzugekommene oder weggefallene Öffnungstage.\n"
                                       "Beispiel: Filiale öffnet ab Planjahr auch samstags (vorher geschlossen) → positiver Wert.\n"
                                       "Oder: Filiale schließt sonntags → negativer Wert."),
    ("eff_verteilung","+ Verteilung", "Glättung: IST-Einzeltag → Wochentagsdurchschnitt des Monats.\n"
                                       "Beispiel: Der Basistag (Mo, 15.1.2025) hatte 6.000 €, der Ø aller Montage im Jan 25 war 5.500 € → Verteilung = -500 €."),
    ("eff_wochentag", "+ Wochentag",  "Anpassung an den Wochentagsmix des Planjahres.\n"
                                       "Beispiel: Jan 2026 hat einen Montag mehr als Jan 2025 → Wochentag > 0 (Montage haben ggf. höheren Umsatz)."),
    ("eff_preis",     "+ Preis",      "Preisanpassung / Wachstumsfaktor aus dem Preisanpassungsparameter.\n"
                                       "Beispiel: 3 % Preiserhöhung im Jan → eff_preis = 0,03 × (monatlicher Basisbetrag) pro Tag."),
    ("eff_ferien",    "+ Ferien",     "Ferienfaktor: Verhältnis Ø Ferienwochenumsatz zu Ø Pufferwochenumsatz.\n"
                                       "Beispiel: In den Osterferien macht Filiale 20 % mehr Umsatz → eff_ferien > 0. "
                                       "Bei Schulfiliale in Ferien: eff_ferien < 0."),
    ("eff_feiertag",  "+ Feiertag",   "Feiertags- oder Sondertag-Effekt.\n"
                                       "Beispiel: Christi Himmelfahrt, Filiale geschlossen → eff_feiertag = -Budget des Tages.\n"
                                       "Sondertag (Muttertag) mit Mehrumsatz → eff_feiertag > 0."),
    ("eff_norm",      "+ Norm.",      "Normalisierungs-Ausgleich: stellt sicher, dass alle Tage eines Monats exakt auf den Monatswert aufgehen.\n"
                                       "Dieser Wert gleicht Rundungsdifferenzen aus und ist meist nahe 0."),
    ("budget",        "= Budget",     "Tagesbudget = IST Basis + Summe aller Effekte.\n"
                                       "Beispiel: IST Basis 5.000 € + Öffnung 0 + Verteilung -200 + Wochentag +100 + Preis +150 + Ferien 0 + Feiertag 0 + Norm. +10 = 5.060 €."),
]

sel_rows = []
try:
    sel_rows = selection.selection.rows if hasattr(selection, "selection") else []
except Exception:
    pass

if sel_rows:
    row_idx = sel_rows[0]
    if row_idx < len(agg):
        agg_row = agg.iloc[row_idx]

        # Build filter for day-level data
        detail_mask = df_all["Zeit"] == agg_row["Zeit"]
        if entity_ebene == "Filiale" and "fil_nr" in agg_row.index:
            detail_mask &= df_all["fil_nr"] == agg_row["fil_nr"]
        elif entity_ebene == "Bundesland" and "bundesland" in agg_row.index:
            detail_mask &= df_all["bundesland"] == agg_row["bundesland"]

        detail_df = df_all[detail_mask].sort_values("datum").reset_index(drop=True)

        # Context label
        ctx_parts = []
        if entity_ebene == "Filiale" and "fil_nr" in agg_row.index:
            ctx_parts.append(f"Filiale **{agg_row['fil_nr']}**")
        elif entity_ebene == "Bundesland" and "bundesland" in agg_row.index:
            ctx_parts.append(f"Bundesland **{agg_row['bundesland']}**")
        ctx_parts.append(f"**{agg_row['Zeit']}**")

        with st.container(border=True):
            st.subheader("🔍 " + " — ".join(ctx_parts))

            # Effect summary with explanations
            summary_rows = []
            for col, label, explanation in _EFFECT_INFO:
                if col in agg_row.index:
                    val = agg_row[col]
                    summary_rows.append({
                        "Effekt": label,
                        "Summe €": _fmt_de(val) if pd.notna(val) else "",
                        "Erklärung": explanation.split("\n")[0],
                        "Beispiel": "\n".join(explanation.split("\n")[1:]).strip(),
                    })

            summary_df = pd.DataFrame(summary_rows)
            st.dataframe(
                summary_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Effekt": st.column_config.TextColumn(width=110),
                    "Summe €": st.column_config.TextColumn(width=110),
                    "Erklärung": st.column_config.TextColumn(width=300),
                    "Beispiel": st.column_config.TextColumn(width=400),
                },
            )

            # Day-level breakdown (only for aggregated views)
            if not detail_df.empty and zeit_ebene != "Tag":
                with st.expander(f"📅 Tagesdetails ({len(detail_df)} Tage)"):
                    day_cols = ["datum", "wochentag", "tagestyp", "feiertag_name", "ferien_art",
                                "ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
                                "eff_preis", "eff_ferien", "eff_feiertag", "eff_norm", "budget"]
                    day_cols = [c for c in day_cols if c in detail_df.columns]
                    day_show = detail_df[day_cols].copy()
                    day_show["Datum"] = day_show["datum"].dt.strftime("%d.%m.%Y")
                    if "wochentag" in day_show.columns:
                        day_show["Wochentag"] = day_show["wochentag"].apply(
                            lambda w: WT_MAP[int(w)] if pd.notna(w) else "")
                    day_show["Tagesinfo"] = day_show.apply(
                        lambda r: _build_tagesinfo(
                            r.get("tagestyp", ""), r.get("feiertag_name", ""), r.get("ferien_art", "")),
                        axis=1)
                    for c in ["ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
                               "eff_preis", "eff_ferien", "eff_feiertag", "eff_norm", "budget"]:
                        if c in day_show.columns:
                            day_show[c] = day_show[c].apply(_fmt_de)
                    day_show = day_show.drop(columns=[c for c in
                        ["datum", "wochentag", "tagestyp", "feiertag_name", "ferien_art"]
                        if c in day_show.columns])
                    day_show = day_show.rename(columns={
                        "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung",
                        "eff_verteilung": "+ Verteilung", "eff_wochentag": "+ Wochentag",
                        "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
                        "eff_feiertag": "+ Feiertag", "eff_norm": "+ Norm.", "budget": "= Budget",
                    }).fillna("")
                    show_order = ["Datum", "Wochentag", "Tagesinfo"] + [
                        c for c in ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag",
                                    "+ Preis", "+ Ferien", "+ Feiertag", "+ Norm.", "= Budget"]
                        if c in day_show.columns]
                    day_show = day_show[[c for c in show_order if c in day_show.columns]]
                    st.dataframe(day_show, use_container_width=True, hide_index=True)

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

# ── Legende ─────────────────────────────────────────────────────────────────
st.divider()
with st.expander("📖 Legende — Spaltenbezeichnungen und Berechnungslogik"):
    st.markdown("""
### Spaltenbedeutungen

| Spalte | Bedeutung | Beispiel |
|--------|-----------|---------|
| **IST Basis** | Tagesumsatz des korrespondierenden Basistags im Basiszeitraum | Montag, 15.01.2025 → 5.234 € |
| **+ Öffnung** | Korrektur für neu hinzugekommene oder weggefallene Öffnungstage | Filiale öffnet ab 2026 samstags (+432 €) |
| **+ Verteilung** | Glättung: IST-Einzeltag → Wochentagsdurchschnitt des Monats | Basistag war mit 5.800 € über dem Ø aller Montage (5.500 €) → −300 € |
| **+ Wochentag** | Anpassung an den Wochentagsmix des Planjahres | Jan 2026 hat einen Montag mehr als Jan 2025 → +200 € |
| **+ Preis** | Preisanpassung / Wachstumsfaktor (% aus Parameter) | 3 % Preiserhöhung → 5.500 € × 3 % / 31 Tage ≈ +53 € je Werktag |
| **+ Ferien** | Ferienfaktor: Verhältnis Ferienwochen- zu Pufferwochenumsatz | Osterferien: Filiale macht 20 % mehr → +1.100 € |
| **+ Feiertag** | Feiertags- oder Sondertag-Effekt | Christi Himmelfahrt, Filiale geschlossen → −5.000 € (ganzer Tagesumsatz) |
| **+ Norm.** | Normalisierungs-Ausgleich für exakte Monatssumme | Rundungsausgleich, typisch < 1 € je Tag |
| **= Budget** | Tagesbudget = Summe aller obigen Effekte + IST Basis | 5.234 + 0 − 300 + 200 + 53 + 0 + 0 + 5 = **5.192 €** |
| **Δ €** | Budget − IST Basis (absolute Veränderung) | 5.192 − 5.234 = −42 € |
| **Δ %** | Δ € / IST Basis × 100 | −42 / 5.234 × 100 = −0,8 % |

### Berechnungsformel (additiv exakt je Tag)

```
Budget = IST Basis + Öffnung + Verteilung + Wochentag + Preis + Ferien + Feiertag + Norm.
```

Diese Zerlegung gilt **exakt** auf Tagesebene und addiert sich durch einfache Summation
auf jede Zeit- und Aggregationsebene (Woche / Monat / Jahr, Filiale / Bundesland / Gesamt).
""")
