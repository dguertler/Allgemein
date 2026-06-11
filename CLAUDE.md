# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Wichtig für Claude Code:** Diese Datei immer zuerst lesen (`Read CLAUDE.md`), bevor
> irgendwelche Änderungen vorgenommen oder Fragen beantwortet werden. Sie enthält das
> vollständige Wissen über das Projekt, alle Architekturentscheidungen und die offene
> Punkteliste.

> **Pflicht am Ende JEDER Sitzung (automatisch, ohne Aufforderung):**
> 1. CLAUDE.md mit allen Änderungen, neuen Erkenntnissen und TODO-Updates aktualisieren
> 2. Alle Änderungen + CLAUDE.md committen und auf `master` pushen
> 3. **Dem Nutzer eine Zusammenfassung der Sitzungsänderungen ausgeben** (was wurde umgesetzt, welche Dateien geändert, offene Punkte)
> 4. **Download-Link ausgeben:** `https://github.com/dguertler/Allgemein/archive/refs/heads/master.zip`

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
│   ├── datumsmapping.py            # Generator für datumsmapping-Tabelle (wochentagsbasiertes Matching)
│   └── export.py                   # Excel-Export der Planung
└── ui/
    ├── session.py                  # get_conn(), get_gmbh(), require_db(), get_budgetjahr()
    ├── assets/                     # goertz_logo.png, papperts_logo.png
    └── pages/
        ├── 1_Startseite.py
        ├── 2_Filialen.py
        ├── 3_Daten_Import.py       # IST-Umsatz hochladen + Validierung
        ├── 4_Parameter.py          # Planungsparameter (Wachstum, Ferien-Puffer, …)
        ├── 5_Neue_Filialen.py      # Neue Filialen anlegen
        ├── 6_Planung.py            # Planung ausführen + Excel-Export
        ├── 7_Planungsgenauigkeit.py# Plan vs. IST Vergleich
        ├── 8_Feiertage_Import.py   # Feiertage aller 16 Bundesländer + Fasching/Muttertag
        ├── 9_Oeffnungstage.py      # Wochentags- und Feiertags-Öffnung je Filiale
        ├── 10_Herleitung.py        # Additive Effektzerlegung / Wasserfall-Analyse
        ├── 11_Preisanpassung.py    # Monatliche Preisanpassung % je Planjahr
        ├── 12_Schulfilialen.py     # Auto-Erkennung + Matrix-Editor Schulferien
        └── 13_Datumsmapping.py     # Datumsmapping generieren + anzeigen
```

---

## 3. Datenbankschema (SQLite)

### Stammdaten
```sql
filialen (fil_nr TEXT PK, bezeichnung, bundesland, aktiv,
          eroeffnung TEXT, eroeffnung_ende TEXT, flag_kein_wachstum INTEGER)
```

### IST-Daten
```sql
ist_umsatz (fil_nr TEXT, datum TEXT, umsatz REAL)  -- UNIQUE(fil_nr, datum)
-- fil_nr wird IMMER als TEXT gespeichert (importer.py: astype(str).strip())
-- datum IMMER als ISO "YYYY-MM-DD"
```

### Feiertage / Sondertage
```sql
feiertage (id, datum_plan TEXT, datum_vj TEXT, name TEXT, bundesland TEXT,
           art TEXT)  -- art: 'feiertag' | 'feiertagstag'
           -- WICHTIG: 'feiertagstag' = Vor-/Nachtage (z.B. 2.1. nach Neujahr)
           -- Engine filtert nur art='feiertag' → Feiertagstage sind normale Tage!
sondertage (id, datum_plan, datum_referenz, bezeichnung, methode, bundesland)
           -- methode: 'samstag' | 'referenz'
```

### Öffnungszeiten
```sql
filial_oeffnung  (fil_nr, wochentag INT, offen INT)  -- 0=Mo…6=So
filial_feiertag  (fil_nr, feiertag_name TEXT, offen INT)
ferien_faktor    (fil_nr, bundesland, ferien_art, woche INT, faktor REAL)
```

### Schulferien
```sql
ferien (id, bundesland, art, start_vj, ende_vj, start_plan, ende_plan)
ferien_kalender (bundesland, art, jahr, start, ende)  -- manuelle Eingabe
filial_schulferien (fil_nr, ferien_art, bundesland)   -- Schulfilialen-Matrix
```

### Planungsergebnis
```sql
planung (
    fil_nr, datum, bundesland, wochentag,
    ist_vj,         -- IST-Umsatz des Basiszeitraum-Referenztags
    eff_oeffnung,   -- Effekt neue/weggefallene Öffnungstage
    eff_verteilung, -- IST-Einzeltag → Wochentags-Ø des Monats
    eff_wochentag,  -- Wochentagsmix-Effekt Planjahr vs. Basisjahr
    eff_preis,      -- Preis-/Wachstumsfaktor
    eff_ferien,     -- Ferieneffekt (per Ferienwoche)
    eff_feiertag,   -- Feiertagseffekt
    eff_norm,       -- Normierungsrest (in UI ausgeblendet, in DB vorhanden)
    budget,         -- Tagesbudget = Summe aller Effekte + ist_vj
    monat_basis, monat_hoch, monat_plan,
    tagestyp TEXT,  -- 'normal'|'feiertag'|'sondertag'|'ferien'|'geschlossen'
    feiertag_name, ferien_art, normalisierung,
    tagesumsatz_plan, gesamt_plan  -- Backwards-compat-Spalten
)
```

### Sonstige
```sql
parameter_monat (planjahr, monat, wachstum_pct)
planwert_override (fil_nr, planjahr, monat, planwert)
neue_filialen_plan (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
```

---

## 4. Planungslogik (engine.py)

### 4.1 Basiszeitraum (Rolling 12 Monate)

- **Stichtag:** `date(today.year, 1, 1)` wenn `planjahr <= today.year` (→ volles Vorjahr),
  sonst `date.today()` (rolling)
- **Basiszeitraum** = 12 Monate endend am letzten Monat vor Stichtag
- Methoden: `_compute_base_window()`, `base_year_for_month(month)`, `base_window_label()`

### 4.2 Additive Effektzerlegung

```
budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
       + eff_preis + eff_ferien + eff_feiertag + eff_norm
```

- `eff_norm` wird in der UI **nicht** angezeigt (in DB gespeichert für Auditing)
- Die Identität gilt exakt auf Tagesebene und summiert sich korrekt auf alle Aggregationen

### 4.3 Bekannte Schwachstelle: Kalender-Tages-Matching

**Problem:** Die Engine nutzt aktuell `_safe_date(base_year, month, day)` — also
denselben Kalendertag im Basisjahr. Wenn dieser Tag ein Sonntag, Feiertag oder
Ferientag war, ist `ist_vj = 0` und `eff_verteilung` übernimmt den gesamten
Tageswert (irreführende Darstellung, Budget trotzdem korrekt).

**Geplante Lösung: Datumsmapping** (siehe Abschnitt 9.1)
- Wochentagsbasiertes Matching: gleicher Wochentag in kalenderlich entsprechender Woche
- Feiertag-zu-Feiertag Matching (Christi Himmelfahrt 2026 ↔ Christi Himmelfahrt 2025)
- Ferienwochen-Matching je Bundesland

### 4.4 Feiertagstage (art='feiertagstag')

`_relevant_feiertag()` filtert **nur** `art='feiertag'`. Feiertagstage (Vor-/Nachtage
wie 2.1. nach Neujahr) werden als normale Tage behandelt. Das wurde korrigiert nach
Bug: Fil. 120, 2.1.2026 zeigte budget=0 weil Feiertagstag defaultmäßig geschlossen.

### 4.5 Öffnungstage-Defaults

- Wochentag: **offen** (True) wenn kein Eintrag in `filial_oeffnung`
- Feiertag: **geschlossen** (False) wenn kein Eintrag in `filial_feiertag`
- `filial_oeffnung` wird auto-erkannt aus IST-Daten (≥30% Tage mit Umsatz > 0)

### 4.6 Ferieneffekt (Per-Woche-Faktor)

- Pufferzeitraum: 2 Wochen vor Ferienbeginn (konfigurierbar `ferien_puffer_wochen`)
- Faktor = Ø IST Ferienwoche / Ø IST Pufferwoche (wochentagsgematcht)
- Cached in `self._ferien_cache`

### 4.7 save() — DELETE before INSERT

`engine.save()` löscht zuerst alle existierenden `planung`-Zeilen für die berechneten
`fil_nr` × `planjahr`, dann INSERT OR REPLACE. Verhindert Datenmüll bei Teil-Recalcs.

### 4.8 PlanParams

```python
@dataclass
class PlanParams:
    planjahr: int
    wachstum_pct: float = 0.0
    stichtag: date | None = None
    ferien_puffer_wochen: int = 2
    wachstum_monat: dict = field(default_factory=dict)  # {monat: pct}
    apply_ramadan: bool = False      # TODO: nicht implementiert
    apply_fasching: bool = False     # TODO: nicht implementiert
    fasching_wirkung_pct: float = 0.0
```

---

## 5. UI-Seiten und Navigation

**Aktuelle Navigation (app.py) — Reihenfolge:**

```
Input & Stammdaten:
  Filialen → Umsatz-Import → Filial-Öffnungstage → Feiertage u. Ferien → Schulfilialen → Datumsmapping → Preisanpassung

Berechnung & Validierung:
  Planung ausführen → Herleitung → Planungsgenauigkeit
```

| Seite | Datei | Funktion |
|-------|-------|----------|
| Startseite | 1_Startseite.py | DB-Auswahl + Budgetjahr-Dropdown (nur linke Hälfte) |
| Filialen | 2_Filialen.py | Inline data_editor, Auto-Save, Delete-Bestätigung |
| Umsatz-Import | 3_Daten_Import.py | Excel/CSV, fil_nr-Validierung, Auto-Erkennung Öffnungstage |
| Filial-Öffnungstage | 9_Oeffnungstage.py | Wochentag + Feiertag je Filiale, Auto-Save |
| Feiertage u. Ferien | 8_Feiertage_Import.py | Lädt Basiszeitraum+Budgetjahr, Tabs: Feiertage/Sondertage/Ferien, Auto-Save + Datumsmapping-Trigger |
| Schulfilialen | 12_Schulfilialen.py | ≥80% Nullumsatz = Schulfiliale, Matrix-Editor |
| Datumsmapping | 13_Datumsmapping.py | Mapping Budgettag→Basistag generieren + prüfen |
| Preisanpassung | 11_Preisanpassung.py | Wachstum % je Monat + Planjahr |
| Planung ausführen | 6_Planung.py | Berechnung, Bestätigungsdialog, Excel-Export |
| Herleitung | 10_Herleitung.py | Additive Effekte, Zeilenauswahl-Detailpanel |
| Planungsgenauigkeit | 7_Planungsgenauigkeit.py | Plan vs. IST, Abweichungen |

---

## 6. UI-Patterns und wichtige Implementierungsdetails

### Auto-Save Pattern
Alle Editoren (Filialen, Öffnungstage, Feiertage) verwenden Auto-Save:
- Vergleich `orig.astype(str).equals(edited.astype(str))` bei jedem Rerun
- Änderung erkannt → DB-Update + `st.toast()`
- Kein expliziter Speichern-Button mehr

### Filter-Persistenz (Session State)
Alle `st.multiselect` und `st.selectbox` in Herleitung und Planungsgenauigkeit
haben `key=`-Parameter → Filterstand bleibt beim Seitenwechsel erhalten.

Keys:
- `herleitung_fil_filter`, `herleitung_bl_filter`, `herleitung_zeit`, `herleitung_entity`
- `plangenau_fil_filter`, `plangenau_bl_filter`, `plangenau_zeit`, `plangenau_entity`

### fil_nr Typ-Normierung
`fil_nr` wird in `ist_umsatz` immer als TEXT gespeichert (importer.py). In `planung`
kann es je nach Insertion als INTEGER vorliegen. **Überall `str(r["fil_nr"])`
verwenden** wenn `ist_umsatz` und `planung` verglichen werden (7_Planungsgenauigkeit.py).

### German Number Format
```python
f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
# → "80.000" für 80000
```

### pd.NA / NaN sichere Formatierung
```python
def _fmt_de(val):
    try:
        if pd.isna(val): return ""
    except (TypeError, ValueError): pass
    try:
        return f"{float(val):,.0f}".replace(",","X").replace(".",",").replace("X",".")
    except (TypeError, ValueError): return ""
```

### Herleitung: Nur berechnete Filialen anzeigen
```python
fil_has_data = df_all.groupby("fil_nr")[["budget","ist_vj"]].sum().abs().sum(axis=1) > 0
active_fils = set(fil_has_data[fil_has_data].index)
df_all = df_all[df_all["fil_nr"].isin(active_fils)]
```

### Herleitung: eff_norm ausgeblendet
`eff_norm` wird in der DB gespeichert aber aus allen UI-Anzeigen entfernt:
- Nicht in `eff_cols` für Aggregation
- Nicht in Spalten-`ordered`-Liste
- Nicht in Tagesdetails-Expander
- Wird beim `drop_cols`-Step explizit gedroppt

### Spinner / Loading
CSS in `app.py` zeigt spinning 🥨 Brezel + "Loading..." Text:
```css
[data-testid="stStatusWidget"]::before { content: "🥨"; animation: brezel-spin 1.5s linear infinite; }
[data-testid="stStatusWidget"]::after { content: "Loading..."; }
```

---

## 7. Feiertage (8_Feiertage_Import.py)

- Python-Bibliothek `holidays`
- Alle 16 Bundesländer: `holidays.country_holidays("DE", subdiv=bl, years=year)`
- **Feiertagstage** (art='feiertagstag'): Tag vor + nach Feiertag; Sonntag→keine;
  Montag→auch Sa (-2, -1, +1). In Engine als normale Tage behandelt!
- **Fasching:** 6 Tage ab Weiberfastnacht (Ostern-52)
- **Muttertag:** 2. Sonntag im Mai
- **Ramadan:** Hardcoded-Dict 2023–2036
- **Schulferien:** manuelle Eingabe in `ferien_kalender`-Tabelle
- Ladezeitraum: `LOAD_YEARS = range(2023, 2037)`

---

## 8. Import-Validierung (3_Daten_Import.py)

- fil_nr-Validierung gegen `filialen`-Tabelle → bei fehlendem Eintrag: Import abbrechen
- fil_nr wird als TEXT normiert: `df["fil_nr"] = df["fil_nr"].astype(str).str.strip()`
- datum als ISO: `df["datum"] = df["datum"].dt.strftime("%Y-%m-%d")`

---

## 9. Offene Punkte (TODO)

### 9.1 Datumsmapping (IMPLEMENTIERT)

**Konzept:** Statt `_safe_date(base_year, month, day)` (gleicher Kalendertag) ein
wochentagsbasiertes Mapping erstellen, das für jeden Plantag den korrekten
Referenztag im Basisjahr bestimmt.

**Mapping-Regeln:**
1. Feiertag (plan) → Feiertag (basis): Christi Himmelfahrt 2026 ↔ Christi Himmelfahrt 2025
2. Ferientag Woche N (plan) → Ferientag Woche N (basis): gleiche Ferienwoche, je Bundesland
3. Normaltag → gleicher Wochentag in kalenderlich entsprechender ISO-KW des Basisjahres

**Neue DB-Tabelle:**
```sql
datumsmapping (
    plan_datum TEXT,      -- ISO Plantag
    base_datum TEXT,      -- ISO Referenztag im Basisjahr
    plan_typ TEXT,        -- 'normal'|'feiertag'|'ferien'|'sondertag'
    base_typ TEXT,
    bundesland TEXT,      -- 'alle' oder spezifisch (für Ferien)
    mapping_art TEXT,     -- 'iso_kw'|'feiertag'|'ferien'
    PRIMARY KEY (plan_datum, bundesland)
)
```

**Neue UI-Seite:** "Datumsmapping" (zwischen Schulfilialen und Planung ausführen)
- Zeigt Tabelle: Datum 2026 | Wochentag | Typ | Referenz 2025 | Wochentag | Typ | BL
- Filter nach Bundesland, Monat
- Wird automatisch generiert wenn Feiertage + Ferien geladen sind
- Muss NEU generiert werden wenn Feiertage/Ferien geändert werden

**Engine-Anpassung:**
- `_ist_on(fil_nr, mapping.get((plan_iso, bl), plan_iso).base_datum)` statt `_safe_date()`
- `ist_vj` wäre dann IMMER ein echter Wochentags-Vergleichswert (nie 0 wegen Sonntag)

### 9.2 Ramadan-Effekt

`apply_ramadan` in PlanParams angelegt, Logik fehlt. Ähnlich Ferieneffekt.

### 9.3 Fasching-Wirkung

`apply_fasching` + `fasching_wirkung_pct` in PlanParams angelegt. Fehlt noch.

### 9.4 Tooltips Herleitung (Zellen)

Streamlit unterstützt **keine** Hover-Tooltips auf einzelnen Tabellenzellen.
Aktueller Stand: Spalten-Header haben `help=`-Text. Zeilenklick öffnet Detail-Panel.
Wenn echte Zellen-Tooltips gewünscht: Ag-Grid oder Custom Component nötig.

### 9.5 Warengruppen-Budget

Bewusst Out of Scope.

### 9.6 Schulferien Auto-Load

holidays-Lib unterstützt SCHOOL für DE nicht. Nur manuelle Eingabe.

---

## 10. Entwicklungsregeln für Claude Code

1. **Diese Datei zuerst lesen** (`Read CLAUDE.md`) vor jeder Arbeitssitzung.
2. **Branch:** `master` (Entwicklung direkt auf master, kein Feature-Branch mehr).
3. **Commits:** Aussagekräftige englische Commit-Messages.
4. **Am Ende JEDER Sitzung — automatisch ohne Aufforderung:**
   - CLAUDE.md aktualisieren (neue Erkenntnisse, TODO-Updates, Architekturentscheidungen)
   - Alle Änderungen + CLAUDE.md committen und auf `master` pushen
   - Git-Hash + Download-Link ausgeben: `https://github.com/dguertler/Allgemein/archive/refs/heads/master.zip`
5. **Keine halben Implementierungen.** Zu große Tasks als TODO in Abschnitt 9 erfassen.
6. **Keine Breaking Changes** an der additiven Effekt-Identität ohne Prüfung.
7. **SQLite-Migrationen** immer in `_migrate()` in `schema.py` ergänzen.
8. **Öffnungstage-Defaults:** Wochentag = offen (True), Feiertag = geschlossen (False).
9. **fil_nr immer als str()** normieren wenn `ist_umsatz` und `planung` verglichen werden.
10. **eff_norm:** In DB behalten, aber aus allen UI-Anzeigen ausblenden.
11. **Deutsches Datumsformat in der UI:** Datumsangaben immer als `DD.MM.YYYY` anzeigen (`.dt.strftime("%d.%m.%Y")`). Multiselect-Placeholders immer auf Deutsch (z.B. `placeholder="Alle Bundesländer"`). Keine englischen "Choose options" o.ä.
12. **Keine Speichern-Buttons bei data_editor:** Immer Auto-Save via `if not orig.astype(str).equals(edited.astype(str)): save(); st.toast(); st.rerun()`.

---

## 11. Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| `0cb9ca8` | Logo margin-top, Budgetjahr-Dropdown immer-anlegen, Datumsmapping Feiertagstage/Ferien-Beschreibungen |
| `f8b1118` | German UI-Polish: Auto-Save Öffnungstage, Budgetjahr-Dropdown, Logo-Margin, Datumsmapping-Redesign |
| `071ae5d` | Bugfix: ISO-String-Variable im plan_branch-Inner-Loop korrigiert (zeigte auf letzten Monatstag) |
| `84d0ebe` | Datumsmapping implementiert (wochentagsbasiertes Basis-Referenz-Matching), Logo-Größe verdoppelt |
| `5588984` | Navigation: Öffnungstage nach Umsatz-Import, Feiertage+Schulfilialen zusammen |
| `71a6199` | German placeholders, Filter-Persistenz, 0-Branch-Filter Herleitung, Norm. aus UI, IST fil_nr-Fix |
| `d3a47e2` | Feiertagstag-Bug (art-Filter), Herleitung Tag-Ebene Datum+Wochentag+Tagesinfo, Planungsgenauigkeit Abw. fix |
| `ceef823` | Filter-First-Layout, Zeilenauswahl-Detailpanel, DELETE-before-INSERT in save(), Brezel-Spinner |
| `5472f92` | Logos zurück in Sidebar, zentrierter Loader, leere Tabellen-Fix, Herleitung Legende |
| `4c3623f` | UX-Überarbeitung: Sidebar Firma+Budgetjahr+Basiszeitraum, Auto-Save, Planung-Fixes |
| `93ce825` | Rolling Basiszeitraum, Öffnungstage, Per-Woche-Ferienfaktoren, additive Herleitung |
| `d036d04` | Auto-Feiertag-Loader (16 BL + Fasching + Muttertag) |
| `594f7cb` | Filialen Inline-Edit, Schulfilialen-Seite, Preisanpassung-Seite |
