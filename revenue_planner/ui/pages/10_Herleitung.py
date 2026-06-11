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
    "eff_feiertag": "+ Feiertag", "budget": "= Budget",
}
if zeit_ebene == "Tag":
    rename["Zeit"] = "Datum"
    rename["_wt_str"] = "Wochentag"
    rename["_tagesinfo"] = "Tagesinfo"

drop_cols = ["_sort", "eff_norm"] + [c for c in ["wochentag", "tagestyp", "feiertag_name", "ferien_art"]
                                      if c in agg.columns and zeit_ebene == "Tag"]
disp = agg.drop(columns=[c for c in drop_cols if c in agg.columns]).rename(columns=rename)

if zeit_ebene == "Tag":
    lead = [c for c in ["Filiale", "Bundesland", "Datum", "Wochentag", "Tagesinfo"] if c in disp.columns]
else:
    lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]
ordered = lead + ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
                  "+ Ferien", "+ Feiertag", "= Budget", "Δ €", "Δ %"]
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
    "Jede `+`-Spalte zeigt den additiven Effekt in €. Summe ergibt **= Budget**. "
    "**Zeile anklicken** für Tagesdetails und Effekterklärung."
)
st.divider()

# ── Tabelle ─────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
            "+ Ferien", "+ Feiertag", "= Budget", "Δ €"]

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

col_cfg = {
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
    "Δ €":         st.column_config.TextColumn("Δ €",
        help="Budget minus IST Basis (absolute Veränderung gegenüber Vorjahresbasis)"),
    "Δ %":         st.column_config.TextColumn("Δ %",
        help="Relative Veränderung: Δ € / IST Basis × 100"),
}

selection = st.dataframe(
    disp_fmt,
    use_container_width=True,
    hide_index=True,
    height=560,
    on_select="rerun",
    selection_mode="single-row",
    column_config={k: v for k, v in col_cfg.items() if k in disp_fmt.columns},
)

# ── Detail-Panel bei Zeilenauswahl ─────────────────────────────────────────
_EFFECT_INFO = [
    ("ist_vj",        "IST Basis",
     "Tagesumsatz des korrespondierenden Basistags im Basiszeitraum.",
     "Montag, 06.01.2025 war der Referenztag für Montag, 05.01.2026 → IST Basis = 5.234 €"),
    ("eff_oeffnung",  "+ Öffnung",
     "Korrektur für neu hinzugekommene oder weggefallene Öffnungstage.",
     "Filiale öffnet ab 2026 samstags (vorher geschlossen) → +432 €. "
     "Oder: war im Vorjahr an Neujahr geöffnet, heute nicht → −2.500 €"),
    ("eff_verteilung","+ Verteilung",
     "Glättung: der konkrete Basistag wird auf den Wochentags-Ø des Monats normiert.",
     "Basistag (Mo, 06.01.2025) hatte 6.000 €, aber Ø aller Montage Jan 25 = 5.500 € → Verteilung = −500 €"),
    ("eff_wochentag", "+ Wochentag",
     "Wochentagsmix-Effekt: Planjahr hat andere Anzahl bestimmter Wochentage als Basisjahr.",
     "Jan 2026 hat 5 Montage, Jan 2025 hatte 4 → ein Montag-Anteil mehr → +200 €"),
    ("eff_preis",     "+ Preis",
     "Preis-/Wachstumsfaktor aus den Preisanpassungsparametern (% je Monat).",
     "3 % Preiserhöhung im Jan → Basisbetrag × 3 % / offene Tage ≈ +53 € je Tag"),
    ("eff_ferien",    "+ Ferien",
     "Ferienfaktor: Verhältnis Ø Ferienwochenumsatz zu Ø Pufferwochenumsatz (wochentags-gematcht).",
     "Osterferien: Filiale machte im VJ 20 % mehr → eff_ferien > 0. "
     "Schulfiliale in Ferien: 60 % weniger → eff_ferien < 0"),
    ("eff_feiertag",  "+ Feiertag",
     "Feiertags- oder Sondertag-Effekt (Differenz zum normalen Tagswert).",
     "Christi Himmelfahrt, Filiale geschlossen → eff_feiertag = −Budget des Tages. "
     "Muttertag mit Mehrumsatz → eff_feiertag > 0"),
    ("budget",        "= Budget",
     "Tagesbudget = IST Basis + Summe aller Effekte.",
     "5.234 + 0 − 500 + 200 + 53 + 0 + 0 = 4.987 €"),
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

        detail_mask = df_all["Zeit"] == agg_row["Zeit"]
        if entity_ebene == "Filiale" and "fil_nr" in agg_row.index:
            detail_mask &= df_all["fil_nr"] == agg_row["fil_nr"]
        elif entity_ebene == "Bundesland" and "bundesland" in agg_row.index:
            detail_mask &= df_all["bundesland"] == agg_row["bundesland"]

        detail_df = df_all[detail_mask].sort_values("datum").reset_index(drop=True)

        ctx_parts = []
        if entity_ebene == "Filiale" and "fil_nr" in agg_row.index:
            ctx_parts.append(f"Filiale **{agg_row['fil_nr']}**")
        elif entity_ebene == "Bundesland" and "bundesland" in agg_row.index:
            ctx_parts.append(f"Bundesland **{agg_row['bundesland']}**")
        ctx_parts.append(f"**{agg_row['Zeit']}**")

        with st.container(border=True):
            st.subheader("🔍 " + " — ".join(ctx_parts))

            summary_rows = []
            for col, label, explanation, beispiel in _EFFECT_INFO:
                if col in agg_row.index:
                    val = agg_row[col]
                    summary_rows.append({
                        "Effekt": label,
                        "Summe €": _fmt_de(val) if not pd.isna(val) else "",
                        "Erklärung": explanation,
                        "Beispiel": beispiel,
                    })

            summary_df = pd.DataFrame(summary_rows)
            st.dataframe(
                summary_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Effekt":     st.column_config.TextColumn(width=110),
                    "Summe €":    st.column_config.TextColumn(width=110),
                    "Erklärung":  st.column_config.TextColumn(width=280),
                    "Beispiel":   st.column_config.TextColumn(width=380),
                },
            )

            if not detail_df.empty and zeit_ebene != "Tag":
                with st.expander(f"📅 Tagesdetails ({len(detail_df)} Tage)"):
                    day_cols = ["datum", "wochentag", "tagestyp", "feiertag_name", "ferien_art",
                                "ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
                                "eff_preis", "eff_ferien", "eff_feiertag", "budget"]
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
                               "eff_preis", "eff_ferien", "eff_feiertag", "budget"]:
                        if c in day_show.columns:
                            day_show[c] = day_show[c].apply(_fmt_de)
                    day_show = day_show.drop(columns=[c for c in
                        ["datum", "wochentag", "tagestyp", "feiertag_name", "ferien_art"]
                        if c in day_show.columns])
                    day_show = day_show.rename(columns={
                        "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung",
                        "eff_verteilung": "+ Verteilung", "eff_wochentag": "+ Wochentag",
                        "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
                        "eff_feiertag": "+ Feiertag", "budget": "= Budget",
                    }).fillna("")
                    show_order = ["Datum", "Wochentag", "Tagesinfo"] + [
                        c for c in ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag",
                                    "+ Preis", "+ Ferien", "+ Feiertag", "= Budget"]
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
| **Δ €** | Budget − IST Basis (absolute Veränderung gegenüber Basisjahr) | 4.987 − 5.234 = −247 € |
| **Δ %** | Δ € / IST Basis × 100 | −247 / 5.234 × 100 = −4,7 % |

### Berechnungsformel (additiv je Tag)

```
Budget = IST Basis + Öffnung + Verteilung + Wochentag + Preis + Ferien + Feiertag
```

Diese Zerlegung addiert sich durch einfache Summation auf jede Zeit- und Aggregationsebene
(Woche / Monat / Jahr, Filiale / Bundesland / Gesamt).
""")
