# Offene Punkte & Änderungshistorie

> Lesen vor: neuen Features, Refactorings, am Sitzungsende zum Aktualisieren

---

## Behoben ✅

- Deutsche Zahlformate beim Import (3.000 ≠ 3,0)
- Sicherheitsabfrage vor Neuimport
- BL-Normalisierung in der Engine (Heilige Drei Könige etc. greifen jetzt)
- ferien_kalender→ferien Sync vor Planung (Sync entfernt, Engine liest direkt)
- Sondertage aus feiertage-Tabelle werden von der Engine gelesen
- Planungsgenauigkeit: Abweichung nur bis IST-Importstand
- feiertag_name bei geschlossenen Feiertagen in der Herleitung sichtbar
- Datumsmapping (wochentagsbasiertes Basis-Referenz-Matching) implementiert
- Regressionstest-Suite (pytest, 14 Tests inkl. Golden-Run)
- Importer-Datumsbug: DD.MM.YYYY-Zeilen wurden stillschweigend verworfen
- Wachstums-Redundanz: Wachstum-Editor aus 4_Parameter entfernt
- Budgetjahr wird bei Firmenwechsel zurückgesetzt
- ferien/ferien_kalender-Dualität: Engine liest direkt aus ferien_kalender
- Engine modularisiert: plan_branch als Pipeline
- Plausibilitätsprüfungs-Seite (14_Validierung) mit Gesamtampel
- Schulferien Auto-Load via `holidays.SCHOOL` für alle 16 BL (06/2026)
- Feiertage-UI: BL-Filter, Spaltenumbenennung, Sortierung BL→Datum (06/2026)
- Datumsmapping: base_bezeichnung für Feiertagstage befüllt (06/2026)
- Validierung: Feiertage/Sondertage/Ferientage Vergleich Basis vs. Budget (06/2026)
- Budgetjahr: Auto-Korrektur in Sidebar wenn gespeichertes Jahr nicht in DB (06/2026)
- Planung: Alle planung-Zeilen des Jahres vor neuem Berechnungslauf gelöscht (06/2026)
- Datumsmapping: BL-Normalisierung → Heilige Drei Könige und BL-spezifische Feiertage jetzt korrekt (06/2026)
- Datumsmapping: stichtag-Fix → Basistag ≠ Budgettag für Planjahr = laufendes Jahr (06/2026)
- Datumsmapping: Separate Ferien-Spalten für Budget- und Basiszeitraum (06/2026)
- Feiertage/Ferien: Nur BL laden, die in Filialen-Stammdaten vorhanden; Erklärungstext (06/2026)
- Validierung: Feiertags-/Ferienvergleich nur für relevante BL (mit Filialen) (06/2026)
- Filialen-Massenimport: Akzeptiert Bundesland als Abkürzung (BY), lang (Bayern) oder DE-BY (06/2026)
- Herleitung: IST aktuell + Abw. IST € + Abw. IST % als letzte Spalten (06/2026)
- Planungsgenauigkeit: Genauigkeit % Spalte (100%−|Abw%|); Analyse-Abschnitt mit Top-Abweichungen (06/2026)

---

## Offen — hohe Priorität

| # | Thema | Risiko/Nutzen |
|---|-------|---------------|
| 2 | **Sondertage-Legacy** abbauen: `sondertage`-Tabelle abschaffen, nur noch `feiertage` mit art='Sondertag' | Mittelfristig |
| 4 | **Engine-Performance**: `_ist_on()` O(Tage×Zeilen). Lösung: Lookup-Dict `{(fil_nr, iso): umsatz}` einmalig bauen | Laufzeit |
| 15 | **Herleitung: Verteilung bei direktem VJ-Vergleich** (Feiertag/Ferien/Sondertag): eff_verteilung soll 0 sein wenn direkter Feiertagsvergleich. Erfordert Engine-Änderung + Regressionstest-Update. | Mittelfristig |
| 16 | **Herleitung: Neue Ferien ohne Vorjahreszeitraum**: eff_ferien via Durchschnitt der letzten verfügbaren Ferien-Perioden schätzen. Derzeit keine Periode → eff_ferien=0. | Mittelfristig |

---

## Offen — mittlere Priorität

| # | Thema |
|---|-------|
| 7 | Feiertagsreferenz-Algorithmus: Vergleich mit umliegenden Sonntagen statt einfachem datum_vj |
| 8 | Ramadan-/Fasching-Effekt: Parameter vorhanden, Berechnung fehlt |
| 9 | Tooltip Herleitung: echte Zellen-Tooltips bräuchten Ag-Grid (Streamlit unterstützt keine) |
| 10 | `ensure_filialen_from_ist` nutzt Default "DE-RP" (Alt-Format) — auf "RP" umstellen |
| 12 | Warengruppen-Budget: bewusst Out of Scope |
| 13 | `liefer_plan` ist Dead Code (immer 0.0) — Spalte bleibt (No-Drop-Regel) |
| 14 | `_ferien_cache` je `plan_branch()`-Aufruf neu init — Performance-Optimierung möglich |

---

## Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| `9544e68` | CLAUDE.md aufgeteilt in docs/architecture, ui-patterns, open-issues; Datenschutzregel |
| `49000d9` | Feiertage/Ferien: BL-Filter, Schulferien auto alle 16 BL, Spaltenumbenennung; Datumsmapping: Feiertagstag in Basisbeschreibung; Validierung: 3 neue Vergleichs-Checks |
| `39fc92b` | Plausibilitätsprüfungs-Seite (14_Validierung) mit Ampel-Checks |
| `d5971f9` | Engine: plan_branch in Pipeline-Methoden modularisiert |
| `10cc2fe` | Engine liest Ferien direkt aus ferien_kalender, Sync entfernt |
| `457ddb7` | Budgetjahr-Reset bei Firmenwechsel |
| `fc5d42d` | Doppelter Wachstum-Editor aus 4_Parameter entfernt |
| `3bef718` | Regressionstest-Suite + Importer-Datumsbug-Fix |
| `0cb9ca8` | Logo margin-top, Budgetjahr-Dropdown, Datumsmapping Feiertagstage/Ferien-Beschreibungen |
| `f8b1118` | German UI-Polish: Auto-Save Öffnungstage, Budgetjahr-Dropdown, Datumsmapping-Redesign |
| `071ae5d` | Bugfix: ISO-String-Variable im plan_branch-Inner-Loop |
| `84d0ebe` | Datumsmapping implementiert, Logo-Größe verdoppelt |
| `67c3c85` | Planungsgenauigkeit Abw.-Fix; Engine liest Sondertage aus feiertage; CLAUDE.md überarbeitet |
| `1bce35d` | BL-Normalisierung in Engine, feiertag_name bei Schließung, Schulfilialen nur erkannte |
| `49edbb2` | Deutscher Zahlparser im Import, Import-Sicherheitsabfrage, Feiertage-Seite |
| `5588984` | Navigation: Öffnungstage nach Umsatz-Import |
| `71a6199` | German placeholders, Filter-Persistenz, 0-Branch-Filter Herleitung |
| `d3a47e2` | Feiertagstag-Bug (art-Filter), Herleitung Tag-Ebene, Planungsgenauigkeit Abw. fix |
| `ceef823` | Filter-First-Layout, Zeilenauswahl-Detailpanel, DELETE-before-INSERT, Brezel-Spinner |
| `5472f92` | Logos zurück in Sidebar, zentrierter Loader, leere Tabellen-Fix |
| `4c3623f` | UX-Überarbeitung: Sidebar Firma+Budgetjahr+Basiszeitraum, Auto-Save |
| `93ce825` | Rolling Basiszeitraum, Öffnungstage, Per-Woche-Ferienfaktoren, additive Herleitung |
| `d036d04` | Auto-Feiertag-Loader (16 BL + Fasching + Muttertag) |
| `594f7cb` | Filialen Inline-Edit, Schulfilialen-Seite, Preisanpassung-Seite |
| `e107e37` | CLAUDE.md erstellt |
