# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Wichtig für Claude Code:** Diese Datei immer zuerst lesen (`Read CLAUDE.md`), bevor  
> irgendwelche Änderungen vorgenommen oder Fragen beantwortet werden. Sie enthält das  
> vollständige Wissen über das Projekt, alle Architekturentscheidungen und die offene  
> Punkteliste.

> **Pflicht am Ende jeder Sitzung:** Alle Änderungen mit Git-Hash zusammenfassen und  
> einen Download-Link der aktuellen Branch ausgeben, z. B.:  
> `https://github.com/dguertler/Allgemein/archive/refs/heads/claude/branch-revenue-planning-kuVgL.zip`

---

## 1. Projektüberblick

**Ziel:** Web-App (Streamlit + SQLite) zur tagesgenauen Umsatzplanung (Budget) für  
ca. 255 Filialen der Bäcker Görtz / Papperts Gruppe. Die App ersetzt eine manuelle  
Excel-Budgetierungsdatei.

**Stack:**
- Python 3.11+, Streamlit 1.35+
- SQLite (eine `.db`-Datei je GmbH / Mandant)
- Pandas, openpyxl, holidays (Python-Bibliothek), Pillow
- Einstiegspunkt: `revenue_planner/app.py`
- Start: `streamlit run revenue_planner/app.py`

---

## 2. Verzeichnisstruktur

```
revenue_planner/
├── app.py                          # Streamlit-Einstiegspunkt, Navigation, Logos
├── database/
│   ├── schema.py                   # DDL + Migration (_migrate)
│   └── importer.py                 # IST-Import, detect_oeffnungstage, ensure_filialen_from_ist
├── planning/
│   ├── engine.py                   # Kern-Planungslogik (PlanningEngine, PlanParams, DayPlan)
│   └── export.py                   # Excel-Export der Planung
└── ui/
    ├── session.py                  # get_conn(), get_gmbh(), require_db()
    ├── assets/                     # goertz_logo.png, papperts_logo.png
    └── pages/
        ├── 1_Startseite.py
        ├── 2_Filialen.py
        ├── 3_Daten_Import.py       # IST-Umsatz hochladen + Validierung
        ├── 4_Parameter.py          # Planungsparameter (Wachstum, Ferien-Puffer, …)
        ├── 5_Neue_Filialen.py      # Neue Filialen anlegen
        ├── 6_Planung.py            # Planung ausführen + Export
        ├── 7_Planungsgenauigkeit.py# Plan vs. IST Vergleich
        ├── 8_Feiertage_Import.py   # Feiertage aller 16 Bundesländer + Fasching/Muttertag
        ├── 9_Oeffnungstage.py      # Wochentags- und Feiertags-Öffnung je Filiale
        └── 10_Herleitung.py        # Wasserfall-Analyse der Planungseffekte
```

---

## 3. Datenbankschema (SQLite)

### Stammdaten
```sql
filialen       (fil_nr PK, bezeichnung, bundesland, aktiv)
```

### IST-Daten
```sql
ist_umsatz     (fil_nr, datum, umsatz)          -- tagesgenau, UNIQUE(fil_nr, datum)
```

### Feiertage / Sondertage
```sql
feiertage      (name, datum, bundesland, datum_vj, art)
               -- art: 'feiertag' | 'sondertag'
               -- datum_vj: entsprechendes Datum im Basiszeitraum
sondertage     (name, datum, bundesland)         -- Fasching etc.
```

### Öffnungszeiten
```sql
filial_oeffnung  (fil_nr, wochentag, offen)      -- wochentag: 0=Mo … 6=So
filial_feiertag  (fil_nr, feiertag_name, offen)
ferien_faktor    (fil_nr, bundesland, ferien_art, woche, faktor)
```

### Planungsergebnis
```sql
planung (
    fil_nr, datum, bundesland,
    -- Additive Effekte (exakte Identität: Summe = budget)
    ist_vj,           -- IST-Umsatz Vorjahr (Basiszeitraum)
    eff_oeffnung,     -- Effekt neue/weggefallene Öffnungstage
    eff_verteilung,   -- Kalenderverschiebung (Wochentag-Verschiebung im Monat)
    eff_wochentag,    -- Wochentag-Gewichtung (Hoch-Umsatz-Tag vs. Basis)
    eff_preis,        -- Preis-/Wachstumseffekt (globaler %-Satz)
    eff_ferien,       -- Ferieneffekt (per Ferienwoche ermittelt)
    eff_feiertag,     -- Feiertagseffekt (Sondertag / geschlossen)
    eff_norm,         -- Normierungsrest (Rundungausgleich)
    budget,           -- Tagesbudget = Summe aller Effekte + ist_vj
    monat_basis, monat_hoch, monat_plan,
    -- Backwards-compat
    tagesumsatz_plan, liefer_plan, gesamt_plan
)
```

---

## 4. Planungslogik (engine.py)

### 4.1 Basiszeitraum (Rolling 12 Monate)

- **Stichtag** (`stichtag`): Konfigurierbar, Standard = heute
- **Basiszeitraum** = letzte 12 vollständig abgeschlossene Kalendermonate vor Stichtag
- Beispiel: Stichtag 9. Juni 2026 → Basiszeitraum = **Juni 2025 – Mai 2026**
- Jeder Kalendermonat 1–12 wird exakt einem Jahr im Fenster zugeordnet:
  - Jan–Mai → aktuelles Jahr des Fensters (2026)
  - Jun–Dez → Vorjahr des Fensters (2025)
- Methoden: `_compute_base_window()`, `base_year_for_month(month)`, `base_window_label()`

### 4.2 Additive Effektzerlegung (exakte Identität)

```
budget = ist_vj
       + eff_oeffnung    (Öffnungskorrektur: neue oder weggefallene Tage)
       + eff_verteilung  (Wochentag-Verschiebung im Monat: tag_basis − ist_vj)
       + eff_wochentag   (Tages-Gewichtung: tag_hoch − tag_basis)
       + eff_preis       (Preis-/Wachstumsfaktor: tag_plan − tag_hoch)
       + eff_ferien      (Ferieneffekt: raw − tag_plan, nur Ferientage)
       + eff_feiertag    (Feiertagseffekt: raw − tag_plan, nur Feiertage/Sondertage)
       + eff_norm        (Normierungsrest = budget − raw, Rundungsausgleich)
```

Getestet: 0 Verletzungen der additiven Identität über 365 Tage.

### 4.3 Öffnungstage-Logik

- `filial_oeffnung`: Wochentag 0–6, offen=1/0, Auto-Erkennung aus IST-Daten (≥30% Tage mit Umsatz > 0)
- `filial_feiertag`: pro Filiale × Feiertag, Auto-Erkennung: war am entsprechenden Datum im Basiszeitraum Umsatz > 0?
- Fallback für neue Filialen ohne Historie: Feiertag = geschlossen
- `_is_open_weekday(fil_nr, wt)`: Standard True wenn kein Eintrag
- `_is_open_feiertag(fil_nr, name)`: Standard False wenn kein Eintrag

### 4.4 Ferieneffekt (Per-Woche-Faktor)

- Pufferzeitraum: 2 Wochen **vor** Ferienbeginn (konfigurierbar über `ferien_puffer_wochen`)
- Ø IST Ferienwoche / Ø IST Pufferwoche (wochentagsgematcht) = Faktor je Woche
- Cached in `self._ferien_cache` während `plan_branch()`

### 4.5 PlanParams Dataclass

```python
@dataclass
class PlanParams:
    planjahr: int
    wachstum_pct: float = 0.0          # globaler Preis-/Wachstumseffekt in %
    stichtag: date | None = None        # Basiszeitraum-Ankerdatum
    ferien_puffer_wochen: int = 2
    apply_ramadan: bool = False         # OFFEN – noch nicht implementiert
    apply_fasching: bool = False        # OFFEN – noch nicht implementiert
    fasching_wirkung_pct: float = 0.0
```

---

## 5. UI-Seiten

| Seite | Datei | Funktion |
|-------|-------|----------|
| Startseite | 1_Startseite.py | Willkommen + DB-Auswahl |
| Filialen | 2_Filialen.py | Stammdaten Filialen |
| Umsatz-Import | 3_Daten_Import.py | IST-Daten hochladen (Excel/CSV), Validierung gegen Filialen-Stamm |
| Öffnungstage | 9_Oeffnungstage.py | Wochentags- + Feiertags-Öffnung je Filiale, editierbar |
| Feiertage laden | 8_Feiertage_Import.py | Auto-Import aller 16 Bundesländer + Fasching + Muttertag |
| Parameter | 4_Parameter.py | Wachstum%, Stichtag, Ferien-Puffer |
| Neue Filialen | 5_Neue_Filialen.py | Neue Filialen für Planjahr |
| Planung ausführen | 6_Planung.py | Berechnung starten + Excel-Export |
| Herleitung | 10_Herleitung.py | Wasserfall Tag/Woche/Monat × Filiale/BL/Gesamt |
| Planungsgenauigkeit | 7_Planungsgenauigkeit.py | Plan vs. IST (aktuelles + Vorjahr) |

---

## 6. Import-Validierung (3_Daten_Import.py)

- Vor dem eigentlichen Import: fil_nr aus Upload-Datei vs. `filialen`-Tabelle prüfen
- **Wenn eine Filiale fehlt: kompletten Import abbrechen** (keine Teilimporte)
- Erfolgsmeldung enthält: Anzahl importierte Zeilen + Anzahl neu erkannte Öffnungstage

---

## 7. Feiertage (8_Feiertage_Import.py)

- Python-Bibliothek `holidays` (bereits in requirements.txt)
- Alle 16 Bundesländer: `holidays.country_holidays("DE", subdiv=bl, years=year)`
- Bundesweit-Flag: Feiertag ist in allen 16 Ländern vorhanden
- `datum_vj`: Entsprechendes Datum im Basiszeitraum (für Öffnungserkennnung)
- Fasching: Weiberfastnacht (Ostern−52), Rosenmontag (Ostern−48), Fastnachtsdienstag (Ostern−47)
- Muttertag: 2. Sonntag im Mai

---

## 8. Logos & Styling

- `app.py`: `_combined_logo_bytes()` kombiniert goertz_logo.png + papperts_logo.png zu einem PNG via Pillow
- `st.logo(bytes, size="large")` platziert Logo **über** der Navigation
- CSS-Injection: `[data-testid="stSidebarHeader"] img { background: #ffffff !important; border-radius: 5px !important; }`

---

## 9. Offene Punkte (TODO)

| # | Thema | Details |
|---|-------|---------|
| 1 | **Ramadan-Effekt** | Ähnlich Fasching: Sonderfaktor für betroffene Filialen. `apply_ramadan` in PlanParams bereits angelegt, Logik fehlt noch. |
| 2 | **Fasching-Wirkung** | `apply_fasching` + `fasching_wirkung_pct` in PlanParams bereits angelegt. Warnung in UI wenn Fasching geladen: "Fasching-Wirkung% in Parameter setzen". Berechnung fehlt noch. |
| 3 | **Warengruppen-Budget** | Artikelgruppen-Budgetierung bewusst ausgelassen (Out of Scope). |

---

## 10. Entwicklungsregeln für Claude Code

1. **Diese Datei zuerst lesen** (`Read CLAUDE.md`) vor jeder Arbeitssitzung.
2. **Branch:** Alle Änderungen auf `claude/branch-revenue-planning-kuVgL` entwickeln.
3. **Commits:** Aussagekräftige englische Commit-Messages.
4. **Am Ende jeder Sitzung:**
   - Alle Änderungen mit Git-Hash zusammenfassen
   - Download-Link ausgeben:  
     `https://github.com/dguertler/Allgemein/archive/refs/heads/claude/branch-revenue-planning-kuVgL.zip`
5. **Keine halben Implementierungen.** Wenn etwas zu groß ist, als TODO in dieser Datei erfassen.
6. **Keine Breaking Changes** an der additiven Effekt-Identität ohne Regressionstests.
7. **SQLite-Migrationen** immer in `_migrate()` in `schema.py` ergänzen (nie Tabellen droppen).
8. **Öffnungstage-Defaults:** Wochentag = offen (True), Feiertag = geschlossen (False) wenn kein Eintrag.

---

## 11. Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| `93ce825` | Rolling base period, opening days (filial_oeffnung/feiertag), per-week vacation factors, additive Herleitung waterfall page, Lieferkunden removed |
| `d036d04` | Auto holiday loader (all 16 Bundesländer + Fasching + Muttertag), monthly subtotals in Planungsgenauigkeit, multi-state holiday fix |
| `1911096` | Logo CSS fix, IST/Abw columns always visible in Planungsgenauigkeit |
| `632dd3c` | Filial validation on import, logo rounded corners, Planungsgenauigkeit overhaul |
| `b2f229f` | Logo above nav (st.logo), import UX fix, planning without params, Planungsgenauigkeit page added |
