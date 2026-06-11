# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Wichtig für Claude Code:** Diese Datei immer zuerst lesen (`Read CLAUDE.md`), bevor
> irgendwelche Änderungen vorgenommen oder Fragen beantwortet werden. Sie enthält das
> vollständige Wissen über das Projekt, alle Architekturentscheidungen und die offene
> Punkteliste.

> **Pflicht bei JEDER Änderung am Code:** Diese Datei mitpflegen — neue Erkenntnisse,
> geänderte Logik, neue Stolperfallen, erledigte/neue TODOs hier dokumentieren.

> **Pflicht am Ende JEDER Sitzung (automatisch, ohne Aufforderung):**
> 1. CLAUDE.md mit allen Änderungen, neuen Erkenntnissen und TODO-Updates aktualisieren
> 2. Alle Änderungen + CLAUDE.md committen und auf `master` pushen
> 3. **Dem Nutzer eine Zusammenfassung der Sitzungsänderungen ausgeben** (was wurde umgesetzt, welche Dateien geändert, offene Punkte)
> 4. **Download-Link ausgeben:** `https://github.com/dguertler/Allgemein/archive/refs/heads/master.zip`

---

## 1. Projektüberblick

**Ziel:** Web-App (Streamlit + SQLite) zur tagesgenauen Umsatzplanung (Budget) für
ca. 255 Filialen der Bäcker Görtz / Papperts Gruppe. Die App ersetzt eine manuelle
Excel-Budgetierungsdatei. **Stellenwert: sehr hoch** — das komplette Unternehmensbudget
basiert auf diesen Berechnungen. Fehlerrobustheit und Nachvollziehbarkeit jedes
Rechenschritts haben oberste Priorität.

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
        ├── 3_Daten_Import.py       # IST-Umsatz hochladen + Validierung + Sicherheitsabfrage
        ├── 4_Parameter.py          # Planungsparameter (Wachstum, Ferien-Puffer, …)
        ├── 5_Neue_Filialen.py      # Neue Filialen anlegen
        ├── 6_Planung.py            # Planung ausführen (inkl. ferien_kalender→ferien Sync!) + Excel-Export
        ├── 7_Planungsgenauigkeit.py# Plan vs. IST, Abweichung nur bis IST-Importstand
        ├── 8_Feiertage_Import.py   # Feiertage aller 16 Bundesländer + Fasching/Muttertag
        ├── 9_Oeffnungstage.py      # Wochentags- und Feiertags-Öffnung je Filiale
        ├── 10_Herleitung.py        # Additive Effektzerlegung / Wasserfall-Analyse
        ├── 11_Preisanpassung.py    # Monatliche Preisanpassung % je Planjahr
        ├── 12_Schulfilialen.py     # Auto-Erkennung + Matrix-Editor (nur ERKANNTE Filialen werden angezeigt)
        └── 13_Datumsmapping.py     # Datumsmapping generieren + anzeigen
```

---

## 3. Datenfluss (Ende-zu-Ende)

```
1. Filialen anlegen (2_Filialen)          → filialen
2. IST-Umsätze importieren (3_Daten)      → ist_umsatz (UPSERT!) + Auto-Öffnungstage
3. Feiertage/Ferien laden (8_Feiertage)   → feiertage (art: feiertag|feiertagstag|Sondertag)
                                          → ferien_kalender (Schulferien je BL/Jahr)
4. Öffnungstage prüfen (9_Oeffnungstage)  → filial_oeffnung, filial_feiertag
5. Schulfilialen erkennen (12_Schulfil.)  → filial_schulferien
6. Wachstum je Monat (11_Preisanpassung)  → parameter_monat
7. Planung ausführen (6_Planung)          → SYNC ferien_kalender→ferien, dann Engine → planung
8. Validierung: 10_Herleitung (Effekt-Wasserfall), 7_Planungsgenauigkeit (Plan vs. IST)
```

**Wichtig:** Ein IST-Import löst KEINE Neuberechnung der Planung aus und muss es
auch nicht — die Planungsgenauigkeit liest IST live aus `ist_umsatz` und vergleicht
beim Seitenaufruf. Nur eine geänderte Basis (neue Historie) erfordert bewusst eine
neue Planung.

---

## 4. Datenbankschema (SQLite)

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
-- Import ist ein UPSERT (INSERT OR REPLACE je fil_nr+datum)
```

### Feiertage / Sondertage
```sql
feiertage (id, datum_plan TEXT, datum_vj TEXT, name TEXT, bundesland TEXT,
           art TEXT)  -- art: 'feiertag' | 'feiertagstag' | 'Sondertag'
           -- WICHTIG: 'feiertagstag' = Vor-/Nachtage (z.B. 2.1. nach Neujahr)
           -- Engine filtert nur art='feiertag' → Feiertagstage sind normale Tage!
           -- bundesland: Abkürzung 'BW','BY',… oder 'alle'
sondertage (id, datum_plan, datum_referenz, bezeichnung, methode, bundesland)
           -- methode: 'samstag' | 'referenz' — LEGACY (s. Abschnitt 6, Stolperfallen)
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
       -- ENGINE-Quelle! Wird in 6_Planung aus ferien_kalender synchronisiert
ferien_kalender (bundesland, art, jahr, start, ende)  -- manuelle Eingabe (UI)
filial_schulferien (fil_nr, ferien_art, bundesland, geschlossen)  -- Schulfilialen-Matrix
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
datumsmapping (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art)
```

---

## 5. Planungslogik (engine.py)

### 5.1 Basiszeitraum (Rolling 12 Monate)

- **Stichtag:** `date(today.year, 1, 1)` wenn `planjahr <= today.year` (→ volles Vorjahr),
  sonst `date.today()` (rolling)
- **Basiszeitraum** = 12 Monate endend am letzten Monat vor Stichtag
- Methoden: `_compute_base_window()`, `base_year_for_month(month)`, `base_window_label()`

### 5.2 Additive Effektzerlegung (exakte Identität — NIE brechen!)

```
budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
       + eff_preis + eff_ferien + eff_feiertag + eff_norm
```

- `eff_norm` wird in der UI **nicht** angezeigt (in DB gespeichert für Auditing)
- Die Identität gilt exakt auf Tagesebene und summiert sich korrekt auf alle Aggregationen
- Änderungen an dieser Identität nur mit Regressionstest (Summe der Effekte == budget je Tag)

### 5.3 Datumsmapping (Kalender-Tages-Matching)

**Problem (historisch):** Die Engine nutzte `_safe_date(base_year, month, day)` — also
denselben Kalendertag im Basisjahr. Wenn dieser Tag ein Sonntag, Feiertag oder
Ferientag war, war `ist_vj = 0` und `eff_verteilung` übernahm den gesamten Tageswert.

**Lösung (implementiert): Datumsmapping** (`planning/datumsmapping.py`, Tabelle
`datumsmapping`, UI-Seite 13_Datumsmapping):
- Wochentagsbasiertes Matching: gleicher Wochentag in kalenderlich entsprechender ISO-KW
- Feiertag-zu-Feiertag Matching (Christi Himmelfahrt 2026 ↔ Christi Himmelfahrt 2025)
- Ferienwochen-Matching je Bundesland
- Die Engine nutzt den datumsmapping-Lookup für `ist_vj`-Referenztage
- Muss NEU generiert werden, wenn Feiertage/Ferien geändert werden
  (8_Feiertage triggert `_auto_datumsmapping` nach jedem Speichern)

### 5.4 Feiertagstage (art='feiertagstag')

`_relevant_feiertag()` filtert **nur** `art='feiertag'`. Feiertagstage (Vor-/Nachtage
wie 2.1. nach Neujahr) werden als normale Tage behandelt. Das wurde korrigiert nach
Bug: Fil. 120, 2.1.2026 zeigte budget=0 weil Feiertagstag defaultmäßig geschlossen.

### 5.5 Öffnungstage-Defaults

- Wochentag: **offen** (True) wenn kein Eintrag in `filial_oeffnung`
- Feiertag: **geschlossen** (False) wenn kein Eintrag in `filial_feiertag`
- `filial_oeffnung` wird auto-erkannt aus IST-Daten (≥30% Tage mit Umsatz > 0)
- Geschlossener Feiertag: budget=0, `eff_oeffnung = -ist_vj`, `feiertag_name` bleibt
  gesetzt (für Tagesinfo "Geschlossen (Heilige Drei Könige)" in der Herleitung)

### 5.6 Ferieneffekt (Per-Woche-Faktor)

- Pufferzeitraum: 2 Wochen vor Ferienbeginn (konfigurierbar `ferien_puffer_wochen`)
- Faktor = Ø IST Ferienwoche / Ø IST Pufferwoche (wochentagsgematcht)
- Cached in `self._ferien_cache`

### 5.7 save() — DELETE before INSERT

`engine.save()` löscht zuerst alle existierenden `planung`-Zeilen für die berechneten
`fil_nr` × `planjahr`, dann INSERT OR REPLACE. Verhindert Datenmüll bei Teil-Recalcs.

### 5.8 PlanParams

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

## 6. Stolperfallen (unbedingt beachten!)

### 6.1 Bundesland-Dreifachformat + _normalize_bl
Es kursieren DREI Formate: `"BW"`, `"Baden-Württemberg"`, `"DE-BW"`.
`engine._normalize_bl()` normalisiert auf 2-Buchstaben-Abkürzung und wird in
`plan_branch` aufgerufen (`bl = _normalize_bl(...)`). Die `feiertage`-Tabelle
speichert Abkürzungen (oder `'alle'`). Beim Anfassen von Bundesland-Vergleichen
IMMER normalisieren.

### 6.2 Sondertage — Doppelstruktur
Die UI kann Sondertage in `feiertage` mit `art='Sondertag'` speichern; daneben
existiert die Legacy-Tabelle `sondertage`. Die Engine lädt Sondertage aus BEIDEN
Quellen: `sondertage` UND `feiertage WHERE LOWER(art)='sondertag'` (gemerged in
`_load_reference_data`, feiertage-Einträge mit methode='referenz').
Langfristig: Legacy-Tabelle abschaffen.

### 6.3 ferien vs. ferien_kalender + Sync in 6_Planung
`ferien_kalender` (UI-Eingabe) ≠ `ferien` (Engine-Quelle).
`6_Planung._sync_ferien_kalender_to_ferien()` synchronisiert vor jedem
PlanningEngine-Lauf: Planjahr-Perioden + zugehörige Vorjahres-Perioden (gematcht
über bundesland+art). **Ohne Vorjahres-Eintrag in ferien_kalender wird die Periode
übersprungen** → Ferien immer für Planjahr UND Vorjahr laden!

---

## 7. UI-Seiten und Navigation

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
| Umsatz-Import | 3_Daten_Import.py | Excel/CSV, fil_nr-Validierung, dt. Zahlparser, Sicherheitsabfrage, Auto-Erkennung Öffnungstage |
| Filial-Öffnungstage | 9_Oeffnungstage.py | Wochentag + Feiertag je Filiale, Auto-Save |
| Feiertage u. Ferien | 8_Feiertage_Import.py | Lädt Basiszeitraum+Budgetjahr, Tabs: Feiertage/Sondertage/Ferien, Auto-Save + Datumsmapping-Trigger; Anzeige nur Budgetjahr, DD.MM.YYYY, "Beschreibung", BL ausgeschrieben |
| Schulfilialen | 12_Schulfilialen.py | ≥80% Nullumsatz = Schulfiliale, Matrix-Editor, nur erkannte Filialen |
| Datumsmapping | 13_Datumsmapping.py | Mapping Budgettag→Basistag generieren + prüfen |
| Preisanpassung | 11_Preisanpassung.py | Wachstum % je Monat + Planjahr |
| Planung ausführen | 6_Planung.py | ferien_kalender→ferien-Sync, Berechnung, Bestätigungsdialog, Excel-Export |
| Herleitung | 10_Herleitung.py | Additive Effekte, Zeilenauswahl-Detailpanel |
| Planungsgenauigkeit | 7_Planungsgenauigkeit.py | Plan vs. IST, Abweichung nur bis IST-Importstand |

---

## 8. UI-Patterns und wichtige Implementierungsdetails

### Auto-Save Pattern
Alle Editoren (Filialen, Öffnungstage, Feiertage) verwenden Auto-Save:
- Vergleich `orig.astype(str).equals(edited.astype(str))` bei jedem Rerun
- **Bei Datums-Spalten:** vor dem Vergleich auf "YYYY-MM-DD"-Strings normalisieren
  (`pd.to_datetime(...).dt.strftime("%Y-%m-%d")`) — sonst Toast-Flackern durch
  Timestamp-vs-date-Stringdifferenzen (s. `_norm_for_compare` in 8_Feiertage_Import.py)
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

## 9. Planungsgenauigkeit (7_Planungsgenauigkeit.py)

- Liest `planung` (Budgetjahr) + `ist_umsatz` live beim Seitenaufruf — kein Re-Plan nötig.
- **Abweichung € / % vergleicht IST nur mit dem Budget der Tage, an denen IST bereits
  importiert ist** (`_budget_ist = Budget.where(IST aktuell notna)`). Angebrochene
  Wochen/Monate werden anteilig gerechnet; Caption zeigt "IST importiert bis TT.MM.JJJJ".
- Die Spalte "Budget" zeigt weiterhin das volle Periodenbudget.

---

## 10. Import (3_Daten_Import.py / importer.py)

- Spalten-Fuzzy-Matching (`_detect_columns`): Datum, Filialnummer, Umsatz
- **Deutsches Zahlenformat:** `_parse_num` unterscheidet "3.000"=3000 (Tausenderpunkt),
  "3,5"=3.5, "1.234,56"=1234.56. NIE einfaches `replace(",", ".")` verwenden!
- fil_nr-Validierung gegen `filialen`-Tabelle → bei fehlendem Eintrag: Import abbrechen
  (keine Teilimporte)
- fil_nr wird als TEXT normiert: `df["fil_nr"] = df["fil_nr"].astype(str).str.strip()`
- datum als ISO: `df["datum"] = df["datum"].dt.strftime("%Y-%m-%d")`
- **Sicherheitsabfrage:** Wenn bereits Daten in `ist_umsatz` → Bestätigungsdialog
- Technisch ist der Import ein UPSERT (`INSERT OR REPLACE` je fil_nr+datum) —
  es wird nichts gelöscht, was nicht in der Datei steht.
- Nach Import: `detect_oeffnungstage(force=False)` (nur Filialen ohne Einträge)

---

## 11. Feiertage (8_Feiertage_Import.py)

- Python-Bibliothek `holidays`
- Alle 16 Bundesländer: `holidays.country_holidays("DE", subdiv=bl, years=year)`
- **Feiertagstage** (art='feiertagstag'): Tag vor + nach Feiertag; Sonntag→keine;
  Montag→auch Sa (-2, -1, +1). In Engine als normale Tage behandelt!
- **Fasching:** 6 Tage ab Weiberfastnacht (Ostern-52)
- **Muttertag:** 2. Sonntag im Mai
- **Ramadan:** Hardcoded-Dict 2023–2036
- **Schulferien:** manuelle Eingabe in `ferien_kalender`-Tabelle (holidays-Lib
  unterstützt SCHOOL für DE nicht zuverlässig)
- Lädt für Vorjahr (Basis) + Budgetjahr; nach Speichern: Ferien-Rebuild + Datumsmapping
- **Anzeige:** nur Budgetjahr (kein Jahresfilter), Datum DD.MM.YYYY (DateColumn),
  Spalte "Beschreibung" (nicht "Name"), Art großgeschrieben, BL ausgeschrieben,
  keine redundante Jahr-Spalte bei Ferien (aus Startdatum abgeleitet)
- Auto-Save mit normalisiertem Datums-Vergleich (`_norm_for_compare`) — sonst
  Toast-Flackern durch Timestamp-vs-date-Stringdifferenzen

---

## 12. Systemanalyse — Inkonsistenzen & Optimierungsempfehlungen (Stand 06/2026)

Aus Sicht Senior Controlling / Beratung. Priorisiert:

### 12.1 Behoben
- ✅ Deutsche Zahlformate beim Import (3.000 ≠ 3,0)
- ✅ Sicherheitsabfrage vor Neuimport
- ✅ BL-Normalisierung in der Engine (Heilige Drei Könige etc. greifen jetzt)
- ✅ ferien_kalender→ferien Sync vor Planung
- ✅ Sondertage aus feiertage-Tabelle werden von der Engine gelesen
- ✅ Planungsgenauigkeit: Abweichung nur bis IST-Importstand
- ✅ feiertag_name bei geschlossenen Feiertagen in der Herleitung sichtbar
- ✅ Datumsmapping (wochentagsbasiertes Basis-Referenz-Matching) implementiert

### 12.2 Offen — hohe Priorität
| # | Thema | Risiko/Nutzen |
|---|-------|---------------|
| 1 | **Regressionstest-Suite** (pytest): additive Identität je Tag, Monatsnormierung (Σ Tage == monat_plan), BL-Normalisierung, Importer-Zahlparser. Aktuell gibt es KEINE Tests. | Höchstes Risiko: stille Rechenfehler im Budget |
| 2 | **Datenmodell konsolidieren**: `sondertage`-Legacy-Tabelle und `ferien`/`ferien_kalender`-Dualität abbauen (eine Quelle der Wahrheit, Engine liest direkt). Sync-Schritte sind Fehlerquellen. | Mittelfristig Pflicht |
| 3 | **BL-Normalisierung an der Quelle**: beim Anlegen/Editieren von Filialen normalisieren statt (nur) in der Engine. | Konsistenz |
| 4 | **Engine-Performance**: `_ist_on()` filtert pro Tag das gesamte IST-DataFrame (O(Tage×Zeilen)). Bei 255 Filialen × 365 Tagen langsam. Lösung: Lookup-Dict `{(fil_nr, iso): umsatz}` einmalig bauen. | Laufzeit |
| 5 | **Validierungs-/Plausibilitätsseite**: automatische Checks vor Planung (Filialen ohne BL, Ferien ohne VJ-Periode, Feiertage ohne datum_vj, Monate ohne Basisumsatz, IST-Lücken im Basisfenster) mit Ampel-Anzeige. | Fehlerprävention |

### 12.3 Offen — mittlere Priorität
| # | Thema |
|---|-------|
| 6 | Effekt-Berechnung modularisieren: jeder Effekt (Öffnung, Verteilung, Wochentag, Preis, Ferien, Feiertag) als eigene, unabhängig testbare Funktion/Modul mit einheitlicher Signatur, damit neue Rechenschritte die bestehenden nicht verändern (Pipeline-Muster). `plan_branch()` ist aktuell ein Monolith. |
| 7 | Feiertagsreferenz-Algorithmus: Vergleich mit umliegenden Sonntagen (nicht gleiche Woche, nicht in Ferien, mit Umsatz) statt einfachem datum_vj |
| 8 | Ramadan-/Fasching-Effekt: Parameter (`apply_ramadan`, `apply_fasching`, `fasching_wirkung_pct`) vorhanden, Berechnung fehlt |
| 9 | Tooltip Herleitung: verwendete Vergleichstage bei Feiertagseffekten anzeigen. Streamlit unterstützt keine Hover-Tooltips auf Zellen — Spalten-Header haben `help=`, Zeilenklick öffnet Detail-Panel; echte Zellen-Tooltips bräuchten Ag-Grid/Custom Component. |
| 10 | `ensure_filialen_from_ist` nutzt Default "DE-RP" (Alt-Format) — auf "RP" umstellen |
| 11 | Schulferien Auto-Load (holidays-Lib kann SCHOOL für DE nicht) — externe Quelle/API prüfen |
| 12 | Warengruppen-Budget: bewusst Out of Scope. |

### 12.4 Architektur-Leitplanken (bei jeder Änderung beachten)
1. Additive Identität ist heilig — jeder neue Effekt muss additiv in € sein und
   in die Normierung integriert werden.
2. Neue Rechenschritte als NEUE eff_*-Spalte + eigenes Modul, bestehende Effekte
   nicht umdefinieren (sonst sind historische Planungen nicht mehr vergleichbar).
3. SQLite-Migrationen nur additiv in `schema.py::_migrate()` (nie droppen).
4. Jede Zahl im UI muss bis zum Tagesbeleg nachvollziehbar sein (Herleitung).
5. Defaults: Wochentag offen, Feiertag geschlossen.

---

## 13. Entwicklungsregeln für Claude Code

1. **Diese Datei zuerst lesen** (`Read CLAUDE.md`) vor jeder Arbeitssitzung und
   **bei JEDER Änderung mitpflegen** (Abschnitte 5–12 aktuell halten).
2. **Branch:** `master` (Entwicklung direkt auf master, kein Feature-Branch mehr).
3. **Commits:** Aussagekräftige englische Commit-Messages.
4. **Am Ende JEDER Sitzung — automatisch ohne Aufforderung:**
   - CLAUDE.md aktualisieren (neue Erkenntnisse, TODO-Updates, Architekturentscheidungen)
   - Alle Änderungen + CLAUDE.md committen und auf `master` pushen
   - Git-Hash + Download-Link ausgeben: `https://github.com/dguertler/Allgemein/archive/refs/heads/master.zip`
5. **Keine halben Implementierungen.** Zu große Tasks als TODO in Abschnitt 12 erfassen.
6. **Keine Breaking Changes** an der additiven Effekt-Identität ohne Regressionstest.
7. **SQLite-Migrationen** immer in `_migrate()` in `schema.py` ergänzen.
8. **Öffnungstage-Defaults:** Wochentag = offen (True), Feiertag = geschlossen (False).
9. **fil_nr immer als str()** normieren wenn `ist_umsatz` und `planung` verglichen werden.
10. **eff_norm:** In DB behalten, aber aus allen UI-Anzeigen ausblenden.
11. **Deutsches Datumsformat in der UI:** Datumsangaben immer als `DD.MM.YYYY` anzeigen (`.dt.strftime("%d.%m.%Y")` bzw. `DateColumn(format="DD.MM.YYYY")`). Multiselect-Placeholders immer auf Deutsch (z.B. `placeholder="Alle Bundesländer"`). Keine englischen "Choose options" o.ä.
12. **Keine Speichern-Buttons bei data_editor:** Immer Auto-Save via Vergleich (Datums-Spalten vorher normalisieren!) + `st.toast()` + `st.rerun()`.
13. **Bundesland-Vergleiche** immer über `_normalize_bl()` normalisieren.

---

## 14. Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| `0cb9ca8` | Logo margin-top, Budgetjahr-Dropdown immer-anlegen, Datumsmapping Feiertagstage/Ferien-Beschreibungen |
| `f8b1118` | German UI-Polish: Auto-Save Öffnungstage, Budgetjahr-Dropdown, Logo-Margin, Datumsmapping-Redesign |
| `071ae5d` | Bugfix: ISO-String-Variable im plan_branch-Inner-Loop korrigiert (zeigte auf letzten Monatstag) |
| `84d0ebe` | Datumsmapping implementiert (wochentagsbasiertes Basis-Referenz-Matching), Logo-Größe verdoppelt |
| `67c3c85` | Planungsgenauigkeit: Abw. nur bis IST-Importstand; Engine liest Sondertage aus feiertage-Tabelle; CLAUDE.md komplett überarbeitet (Systemanalyse, Stolperfallen, Leitplanken) |
| `1bce35d` | BL-Normalisierung in Engine, feiertag_name bei Schließung, ferien_kalender→ferien-Sync, Schulfilialen nur erkannte |
| `49edbb2` | Deutscher Zahlparser im Import, Import-Sicherheitsabfrage, Feiertage-Seite (Titel/Beschreibung/kein Jahresfilter/Flicker-Fix) |
| `5588984` | Navigation: Öffnungstage nach Umsatz-Import, Feiertage+Schulfilialen zusammen |
| `71a6199` | German placeholders, Filter-Persistenz, 0-Branch-Filter Herleitung, Norm. aus UI, IST fil_nr-Fix |
| `d3a47e2` | Feiertagstag-Bug (art-Filter), Herleitung Tag-Ebene Datum+Wochentag+Tagesinfo, Planungsgenauigkeit Abw. fix |
| `ceef823` | Filter-First-Layout, Zeilenauswahl-Detailpanel, DELETE-before-INSERT in save(), Brezel-Spinner |
| `5472f92` | Logos zurück in Sidebar, zentrierter Loader, leere Tabellen-Fix, Herleitung Legende |
| `4c3623f` | UX-Überarbeitung: Sidebar Firma+Budgetjahr+Basiszeitraum, Auto-Save, Planung-Fixes |
| `93ce825` | Rolling Basiszeitraum, Öffnungstage, Per-Woche-Ferienfaktoren, additive Herleitung |
| `d036d04` | Auto-Feiertag-Loader (16 BL + Fasching + Muttertag) |
| `594f7cb` | Filialen Inline-Edit, Schulfilialen-Seite, Preisanpassung-Seite |
| `e107e37` | CLAUDE.md erstellt |
