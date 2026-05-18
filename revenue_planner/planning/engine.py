"""
Core planning engine.

Algorithm (per branch, per month):
  1. Monatsumsatz IST: sum of daily actuals for that branch/month in the prior year.
     Missing days at year-end → filled with weekday average of that branch.
     New branches opened mid-year → ignore first 4 weeks; fill pre-open days
     with weekday average.
  2. Monatsumsatz IST hochgerechnet: normalise to the number of open days in the
     plan year (weekday mix corrected).
  3. Monatsumsatz PLAN: apply growth % (skip if flag_kein_wachstum).
     Override with manual planwert_override if set.
  4. Daily distribution:
       Normal day:   Tagesumsatz = Monatsumsatz_PLAN * wt_pct / n_wt_im_monat
       Vacation day: Tagesumsatz * Ferienfaktor
       Holiday:      Vorjahres-Ist des gleichen Feiertags * (1 + growth%)
       Sondertag:    Samstags-Ø Filiale  OR  Vorjahres-Referenztag * (1 + growth%)
       Closed:       0
  5. Normalisation: sum of daily plan → scale to Monatsumsatz_PLAN exactly.
  6. Ramadan shift: redistribute revenue between affected months.
  7. Fasching adjustment: one-off revenue change on Fasching months.
  8. Lieferkunden: monthly actuals * (1 + growth%), spread evenly across open days.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterator

import pandas as pd
import holidays as hol_lib


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PlanParams:
    planjahr: int
    preiserhoehung_pct: float = 0.0
    ferien_puffer_wochen: int = 3
    ramadan_vj_start: date | None = None
    ramadan_vj_ende: date | None = None
    ramadan_plan_start: date | None = None
    ramadan_plan_ende: date | None = None
    ramadan_umsatz_pct: float = 0.0
    fasching_vj_start: date | None = None
    fasching_vj_ende: date | None = None
    fasching_plan_start: date | None = None
    fasching_plan_ende: date | None = None
    fasching_wirkung_pct: float = 0.0


@dataclass
class DayPlan:
    fil_nr: str
    datum: date
    wochentag: int          # 0=Mo…6=So
    ist_vj: float
    monatsumsatz_ist_hoch: float
    monatsumsatz_plan: float
    tagesumsatz_plan: float
    liefer_plan: float
    gesamt_plan: float
    tagestyp: str           # normal|feiertag|sondertag|ferien|geschlossen
    feiertag_name: str
    ferien_art: str
    normalisierung: float


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _from_row(row, key, default=None):
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


# ── Main engine ───────────────────────────────────────────────────────────────

class PlanningEngine:

    def __init__(self, conn: sqlite3.Connection, params: PlanParams):
        self.conn = conn
        self.p = params
        self.vj = params.planjahr - 1
        self._load_reference_data()

    # ── Setup ─────────────────────────────────────────────────────────────

    def _load_reference_data(self):
        p = self.p
        c = self.conn.cursor()

        # Feiertage plan year: {datum_plan → (name, datum_vj, bundesland)}
        rows = c.execute("SELECT datum_plan, datum_vj, name, bundesland FROM feiertage").fetchall()
        self.feiertage: dict[str, dict] = {}
        for r in rows:
            self.feiertage[r["datum_plan"]] = {
                "name": r["name"], "datum_vj": r["datum_vj"], "bundesland": r["bundesland"]
            }

        # Sondertage plan year
        rows = c.execute("SELECT datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage").fetchall()
        self.sondertage: dict[str, dict] = {}
        for r in rows:
            self.sondertage[r["datum_plan"]] = dict(r)

        # Ferien plan year
        rows = c.execute("SELECT * FROM ferien").fetchall()
        self.ferien_plan: list[dict] = [dict(r) for r in rows]

        # Ferien prior year → for Ferienfaktor calculation
        # Puffer windows are derived from ferien_plan using p.ferien_puffer_wochen
        self._build_ferien_windows()

        # All IST data (prior year + partial current if needed)
        df = pd.read_sql(
            "SELECT fil_nr, datum, umsatz FROM ist_umsatz ORDER BY fil_nr, datum",
            self.conn
        )
        df["datum"] = pd.to_datetime(df["datum"])
        df["umsatz"] = df["umsatz"].round(2)
        self.ist_df = df

        # Filialen master
        self.filialen = {
            r["fil_nr"]: dict(r)
            for r in c.execute("SELECT * FROM filialen").fetchall()
        }

        # Lieferkunden monthly (prior year)
        rows = c.execute(
            "SELECT fil_nr, monat, ist_betrag FROM lieferkunden_monat WHERE jahr=?", (self.vj,)
        ).fetchall()
        self.liefer_vj: dict[tuple, float] = {(r["fil_nr"], r["monat"]): r["ist_betrag"] for r in rows}

        # Neue Filialen monthly plan
        rows = c.execute(
            "SELECT fil_nr, monat, planwert, eroeffnung_datum FROM neue_filialen_plan WHERE planjahr=?",
            (p.planjahr,)
        ).fetchall()
        self.neue_plan: dict[tuple, dict] = {
            (r["fil_nr"], r["monat"]): {"planwert": r["planwert"], "eroeffnung": r["eroeffnung_datum"]}
            for r in rows
        }

        # Manual overrides
        rows = c.execute(
            "SELECT fil_nr, monat, planwert FROM planwert_override WHERE planjahr=?", (p.planjahr,)
        ).fetchall()
        self.overrides: dict[tuple, float] = {(r["fil_nr"], r["monat"]): r["planwert"] for r in rows}

    def _build_ferien_windows(self):
        """Build sets of dates that fall inside Ferien or Pufferzeitraum per Bundesland."""
        pw = timedelta(weeks=self.p.ferien_puffer_wochen)
        self.ferien_plan_dates: dict[str, dict[str, str]] = {}   # iso_date → {bl: art}
        self.ferien_puffer_dates: dict[str, dict[str, str]] = {} # iso_date → {bl: art}

        for f in self.ferien_plan:
            bl = f["bundesland"]
            art = f["art"]
            start = date.fromisoformat(f["start_plan"])
            ende = date.fromisoformat(f["ende_plan"])
            puf_start = start - pw
            puf_ende = ende + pw

            for d in _date_range(start, ende):
                self.ferien_plan_dates.setdefault(d.isoformat(), {})[bl] = art

            for d in _date_range(puf_start, start - timedelta(1)):
                self.ferien_puffer_dates.setdefault(d.isoformat(), {})[bl] = art
            for d in _date_range(ende + timedelta(1), puf_ende):
                self.ferien_puffer_dates.setdefault(d.isoformat(), {})[bl] = art

    # ── Per-branch helpers ────────────────────────────────────────────────

    def _branch_ist(self, fil_nr: str) -> pd.DataFrame:
        return self.ist_df[self.ist_df["fil_nr"] == fil_nr].copy()

    def _weekday_avg(self, df: pd.DataFrame, fil: dict) -> dict[int, float]:
        """Average IST revenue per weekday (0=Mo…6=So), excluding first 4 weeks after opening."""
        if df.empty:
            return {i: 0.0 for i in range(7)}
        eroeffnung = fil.get("eroeffnung")
        if eroeffnung:
            cutoff = date.fromisoformat(eroeffnung) + timedelta(weeks=4)
            df = df[df["datum"] >= pd.Timestamp(cutoff)]
        df = df[df["umsatz"] > 0]
        if df.empty:
            return {i: 0.0 for i in range(7)}
        avgs = df.groupby(df["datum"].dt.weekday)["umsatz"].mean().to_dict()
        return {i: avgs.get(i, 0.0) for i in range(7)}

    def _monthly_ist(self, fil_nr: str, fil: dict, year: int) -> dict[int, float]:
        """Monthly IST revenue for given year. Missing months → weekday avg extrapolation."""
        df = self._branch_ist(fil_nr)
        df_yr = df[df["datum"].dt.year == year]
        wt_avg = self._weekday_avg(df, fil)

        result = {}
        for m in range(1, 13):
            df_m = df_yr[df_yr["datum"].dt.month == m]
            if not df_m.empty:
                result[m] = round(df_m["umsatz"].sum(), 2)
            else:
                # Extrapolate from weekday averages
                days_in_month = pd.Period(f"{year}-{m:02d}").days_in_month
                total = sum(
                    wt_avg[date(year, m, day).weekday()]
                    for day in range(1, days_in_month + 1)
                )
                result[m] = round(total, 2)
        return result

    def _count_weekdays_in_month(self, year: int, month: int) -> dict[int, int]:
        """Count occurrences of each weekday (0=Mo…6=So) in a given month."""
        days_in_month = pd.Period(f"{year}-{month:02d}").days_in_month
        counts: dict[int, int] = {i: 0 for i in range(7)}
        for day in range(1, days_in_month + 1):
            counts[date(year, month, day).weekday()] += 1
        return counts

    def _weekday_pct(self, fil_nr: str, year: int, month: int) -> dict[int, float]:
        """Historical % share of each weekday in monthly revenue."""
        df = self._branch_ist(fil_nr)
        df_m = df[(df["datum"].dt.year == year) & (df["datum"].dt.month == month)]
        df_m = df_m[df_m["umsatz"] > 0]
        if df_m.empty:
            # Equal weight fallback
            return {i: 1 / 7 for i in range(7)}
        total = df_m["umsatz"].sum()
        if total == 0:
            return {i: 1 / 7 for i in range(7)}
        pcts = df_m.groupby(df_m["datum"].dt.weekday)["umsatz"].sum() / total
        return {i: float(pcts.get(i, 0.0)) for i in range(7)}

    def _ferien_factor(self, fil_nr: str, bl: str, ferien_art: str) -> float:
        """Ratio: avg Ferien revenue / avg Puffer revenue for this branch."""
        df = self._branch_ist(fil_nr)
        if df.empty:
            return 1.0

        ferien_dates = {
            iso for iso, bls in self.ferien_plan_dates.items() if bls.get(bl) == ferien_art
        }
        puffer_dates = {
            iso for iso, bls in self.ferien_puffer_dates.items() if bls.get(bl) == ferien_art
        }

        def avg(dates_set):
            if not dates_set:
                return None
            mask = df["datum"].dt.strftime("%Y-%m-%d").isin(dates_set)
            sub = df[mask & (df["umsatz"] > 0)]
            return sub["umsatz"].mean() if not sub.empty else None

        f_avg = avg(ferien_dates)
        p_avg = avg(puffer_dates)
        if f_avg is None or p_avg is None or p_avg == 0:
            return 1.0
        return round(f_avg / p_avg, 4)

    def _saturday_avg(self, fil_nr: str) -> float:
        df = self._branch_ist(fil_nr)
        sat = df[df["datum"].dt.weekday == 5]["umsatz"]
        return float(sat[sat > 0].mean()) if not sat.empty else 0.0

    def _is_relevant_feiertag(self, iso_date: str, bundesland: str) -> dict | None:
        ft = self.feiertage.get(iso_date)
        if ft is None:
            return None
        ft_bl = ft["bundesland"]
        if ft_bl == "alle" or ft_bl == bundesland:
            return ft
        return None

    def _is_relevant_sondertag(self, iso_date: str, bundesland: str) -> dict | None:
        st = self.sondertage.get(iso_date)
        if st is None:
            return None
        st_bl = st["bundesland"]
        if st_bl == "alle" or st_bl == bundesland:
            return st
        return None

    def _ferien_art_for_day(self, iso_date: str, bundesland: str) -> str | None:
        bls = self.ferien_plan_dates.get(iso_date, {})
        return bls.get(bundesland) or bls.get("alle")

    # ── Monthly plan calculation ──────────────────────────────────────────

    def _monatsumsatz_plan(self, fil_nr: str, fil: dict, month: int) -> float:
        """Calculate the planned monthly revenue for a branch."""
        # 1. Override takes priority
        if (fil_nr, month) in self.overrides:
            return self.overrides[(fil_nr, month)]

        # 2. New branch → detected by eroeffnung in plan year
        eroeff_str = fil.get("eroeffnung")
        is_neue_filiale = bool(
            eroeff_str and date.fromisoformat(eroeff_str).year == self.p.planjahr
        )
        if is_neue_filiale:
            entry = self.neue_plan.get((fil_nr, month))
            if entry:
                planwert = entry["planwert"]
                # Opening month → 50% unless planwert was manually set (non-zero)
                eroeff = entry.get("eroeffnung")
                if eroeff:
                    eroeff_date = date.fromisoformat(eroeff)
                    if eroeff_date.month == month and eroeff_date.year == self.p.planjahr:
                        planwert = planwert * 0.5
                return planwert
            return 0.0

        # 3. Existing branch: IST VJ normalised + growth
        ist_vj = self._monthly_ist(fil_nr, fil, self.vj)
        monat_ist = ist_vj.get(month, 0.0)

        # Hochrechnung: adjust for different weekday count between VJ and plan year
        wt_vj = self._count_weekdays_in_month(self.vj, month)
        wt_plan = self._count_weekdays_in_month(self.p.planjahr, month)
        wt_avg = self._weekday_avg(self._branch_ist(fil_nr), fil)
        total_wt_vj = sum(wt_vj[w] * wt_avg[w] for w in range(7))
        total_wt_plan = sum(wt_plan[w] * wt_avg[w] for w in range(7))
        factor_hochrech = (total_wt_plan / total_wt_vj) if total_wt_vj > 0 else 1.0
        monat_ist_hoch = monat_ist * factor_hochrech

        # Lieferschein correction: subtract LS VJ to avoid double-counting
        ls_vj = self.liefer_vj.get((fil_nr, month), 0.0)
        monat_ist_hoch = max(0.0, monat_ist_hoch - ls_vj)

        growth = 1.0 if fil.get("flag_kein_wachstum") else (1 + self.p.preiserhoehung_pct / 100)
        return round(monat_ist_hoch * growth, 2)

    # ── Daily planning ────────────────────────────────────────────────────

    def plan_branch(self, fil_nr: str) -> list[DayPlan]:
        fil = self.filialen.get(fil_nr, {"bundesland": "RP"})
        bl = fil.get("bundesland", "RP")
        growth = 1.0 if fil.get("flag_kein_wachstum") else (1 + self.p.preiserhoehung_pct / 100)

        results: list[DayPlan] = []

        for month in range(1, 13):
            monat_plan = self._monatsumsatz_plan(fil_nr, fil, month)
            wt_pct = self._weekday_pct(fil_nr, self.vj, month)
            wt_count = self._count_weekdays_in_month(self.p.planjahr, month)

            days_in_month = pd.Period(f"{self.p.planjahr}-{month:02d}").days_in_month
            daily: list[dict] = []

            for day in range(1, days_in_month + 1):
                d = date(self.p.planjahr, month, day)
                iso = d.isoformat()
                wt = d.weekday()
                iso_vj = date(self.vj, month, day).isoformat()

                # IST Vorjahr
                ist_mask = (
                    (self.ist_df["fil_nr"] == fil_nr) &
                    (self.ist_df["datum"] == pd.Timestamp(iso_vj))
                )
                ist_vj_val = float(self.ist_df.loc[ist_mask, "umsatz"].sum())

                # Closed?
                if fil.get("flag_inaktiv"):
                    ende = fil.get("eroeffnung_ende")
                    if ende and d >= date.fromisoformat(ende):
                        daily.append({"d": d, "typ": "geschlossen", "umsatz": 0.0,
                                      "ist_vj": ist_vj_val, "feiertag": "", "ferien": ""})
                        continue

                # Feiertag?
                ft = self._is_relevant_feiertag(iso, bl)
                if ft:
                    if ft["datum_vj"]:
                        vj_mask = (
                            (self.ist_df["fil_nr"] == fil_nr) &
                            (self.ist_df["datum"] == pd.Timestamp(ft["datum_vj"]))
                        )
                        vj_val = float(self.ist_df.loc[vj_mask, "umsatz"].sum())
                        umsatz = round(vj_val * growth, 2)
                    else:
                        umsatz = 0.0
                    daily.append({"d": d, "typ": "feiertag", "umsatz": umsatz,
                                  "ist_vj": ist_vj_val, "feiertag": ft["name"], "ferien": ""})
                    continue

                # Sondertag?
                st = self._is_relevant_sondertag(iso, bl)
                if st:
                    if st["methode"] == "samstag":
                        umsatz = round(self._saturday_avg(fil_nr) * growth, 2)
                    elif st["datum_referenz"]:
                        ref_mask = (
                            (self.ist_df["fil_nr"] == fil_nr) &
                            (self.ist_df["datum"] == pd.Timestamp(st["datum_referenz"]))
                        )
                        ref_val = float(self.ist_df.loc[ref_mask, "umsatz"].sum())
                        umsatz = round(ref_val * growth, 2)
                    else:
                        umsatz = 0.0
                    daily.append({"d": d, "typ": "sondertag", "umsatz": umsatz,
                                  "ist_vj": ist_vj_val, "feiertag": st["bezeichnung"], "ferien": ""})
                    continue

                # Ferien?
                ferien_art = self._ferien_art_for_day(iso, bl)
                if ferien_art:
                    n_wt = wt_count.get(wt, 1)
                    base = (monat_plan * wt_pct.get(wt, 0) / n_wt) if n_wt > 0 else 0
                    ff = self._ferien_factor(fil_nr, bl, ferien_art)
                    umsatz = round(base * ff, 2)
                    daily.append({"d": d, "typ": "ferien", "umsatz": umsatz,
                                  "ist_vj": ist_vj_val, "feiertag": "", "ferien": ferien_art})
                    continue

                # Normal day
                n_wt = wt_count.get(wt, 1)
                umsatz = round((monat_plan * wt_pct.get(wt, 0) / n_wt) if n_wt > 0 else 0, 2)
                daily.append({"d": d, "typ": "normal", "umsatz": umsatz,
                              "ist_vj": ist_vj_val, "feiertag": "", "ferien": ""})

            # ── Normalisation ─────────────────────────────────────────────
            raw_sum = sum(r["umsatz"] for r in daily)
            norm = (monat_plan / raw_sum) if raw_sum > 0 else 1.0

            for r in daily:
                norm_umsatz = round(r["umsatz"] * norm, 2)
                ls_plan = round(
                    self.liefer_vj.get((fil_nr, month), 0.0) * growth, 2
                ) if r["typ"] != "geschlossen" else 0.0

                # Monatsumsatz IST hochgerechnet (same value for all days of month)
                ist_vj_m = self._monthly_ist(fil_nr, fil, self.vj).get(month, 0.0)
                wt_vj = self._count_weekdays_in_month(self.vj, month)
                wt_plan_m = self._count_weekdays_in_month(self.p.planjahr, month)
                wt_avg = self._weekday_avg(self._branch_ist(fil_nr), fil)
                tot_vj = sum(wt_vj[w] * wt_avg[w] for w in range(7))
                tot_plan = sum(wt_plan_m[w] * wt_avg[w] for w in range(7))
                fh = (tot_plan / tot_vj) if tot_vj > 0 else 1.0
                monat_ist_hoch = round(ist_vj_m * fh, 2)

                results.append(DayPlan(
                    fil_nr=fil_nr,
                    datum=r["d"],
                    wochentag=r["d"].weekday(),
                    ist_vj=r["ist_vj"],
                    monatsumsatz_ist_hoch=monat_ist_hoch,
                    monatsumsatz_plan=monat_plan,
                    tagesumsatz_plan=norm_umsatz,
                    liefer_plan=ls_plan,
                    gesamt_plan=round(norm_umsatz + ls_plan, 2),
                    tagestyp=r["typ"],
                    feiertag_name=r["feiertag"],
                    ferien_art=r["ferien"],
                    normalisierung=round(norm, 4),
                ))

        return results

    # ── Ramadan & Fasching post-processing ────────────────────────────────

    def apply_ramadan(self, results: list[DayPlan], fil_nr: str) -> list[DayPlan]:
        """Shift revenue between Ramadan months (prior year vs plan year)."""
        p = self.p
        fil = self.filialen.get(fil_nr, {})
        if not fil.get("ramadan_sensitiv") or p.ramadan_umsatz_pct == 0:
            return results
        if not all([p.ramadan_vj_start, p.ramadan_vj_ende, p.ramadan_plan_start, p.ramadan_plan_ende]):
            return results

        pct = p.ramadan_umsatz_pct / 100
        vj_months = set(
            d.month for d in _date_range(p.ramadan_vj_start, p.ramadan_vj_ende)
        )
        plan_months = set(
            d.month for d in _date_range(p.ramadan_plan_start, p.ramadan_plan_ende)
        )
        # Months that lose Ramadan revenue (had Ramadan in VJ but not plan year)
        lose_months = vj_months - plan_months
        # Months that gain Ramadan revenue (have Ramadan in plan year but not VJ)
        gain_months = plan_months - vj_months

        for r in results:
            if r.fil_nr != fil_nr:
                continue
            if r.datum.month in lose_months:
                r.tagesumsatz_plan = round(r.tagesumsatz_plan * (1 - pct), 2)
                r.gesamt_plan = round(r.tagesumsatz_plan + r.liefer_plan, 2)
            elif r.datum.month in gain_months:
                r.tagesumsatz_plan = round(r.tagesumsatz_plan * (1 + pct), 2)
                r.gesamt_plan = round(r.tagesumsatz_plan + r.liefer_plan, 2)
        return results

    def fasching_info(self) -> dict:
        """Return Fasching comparison info for display in the UI."""
        p = self.p
        if not all([p.fasching_vj_start, p.fasching_vj_ende, p.fasching_plan_start, p.fasching_plan_ende]):
            return {}
        vj_days = (p.fasching_vj_ende - p.fasching_vj_start).days + 1
        plan_days = (p.fasching_plan_ende - p.fasching_plan_start).days + 1
        diff = plan_days - vj_days
        return {
            "vj_start": p.fasching_vj_start, "vj_ende": p.fasching_vj_ende,
            "vj_tage": vj_days,
            "plan_start": p.fasching_plan_start, "plan_ende": p.fasching_plan_ende,
            "plan_tage": plan_days,
            "differenz_tage": diff,
            "hinweis": (
                f"Fasching {p.planjahr} ist {abs(diff)} Tage "
                f"{'länger' if diff > 0 else 'kürzer'} als {self.vj}."
            ) if diff != 0 else f"Fasching {p.planjahr} hat gleich viele Tage wie {self.vj}.",
        }

    def apply_fasching(self, results: list[DayPlan]) -> list[DayPlan]:
        """Apply Fasching revenue adjustment to affected month(s)."""
        p = self.p
        if not all([p.fasching_plan_start, p.fasching_plan_ende]):
            return results
        if p.fasching_wirkung_pct == 0:
            return results

        vj_days = (p.fasching_vj_ende - p.fasching_vj_start).days + 1 if p.fasching_vj_start else 0
        plan_days = (p.fasching_plan_ende - p.fasching_plan_start).days + 1
        diff = plan_days - vj_days  # positive = longer, negative = shorter

        if diff == 0:
            return results

        # Fasching months in plan year
        fasching_months = set(
            d.month for d in _date_range(p.fasching_plan_start, p.fasching_plan_ende)
        )
        # Revenue change: diff days × daily avg × wirkung_pct
        # Applied as a proportional adjustment on the month's daily values
        month_daily_counts: dict[int, int] = {}
        for r in results:
            if r.datum.month in fasching_months:
                month_daily_counts[r.datum.month] = month_daily_counts.get(r.datum.month, 0) + 1

        for r in results:
            if r.datum.month not in fasching_months:
                continue
            n = month_daily_counts.get(r.datum.month, 1)
            # Distribute the total Fasching adjustment evenly across all days of the month
            day_adj = (diff * (r.tagesumsatz_plan / n) * (p.fasching_wirkung_pct / 100))
            r.tagesumsatz_plan = round(r.tagesumsatz_plan + day_adj, 2)
            r.gesamt_plan = round(r.tagesumsatz_plan + r.liefer_plan, 2)
        return results

    # ── Full run ──────────────────────────────────────────────────────────

    def run(self, fil_nrs: list[str] | None = None) -> list[DayPlan]:
        """Run planning for all (or specified) branches."""
        targets = fil_nrs if fil_nrs else list(self.filialen.keys())
        all_results: list[DayPlan] = []

        for fil_nr in targets:
            branch_results = self.plan_branch(fil_nr)
            branch_results = self.apply_ramadan(branch_results, fil_nr)
            branch_results = self.apply_fasching(branch_results)
            all_results.extend(branch_results)

        return all_results

    def save(self, results: list[DayPlan]):
        """Persist planning results to the planung table."""
        rows = [
            {
                "fil_nr": r.fil_nr,
                "datum": r.datum.isoformat(),
                "wochentag": r.wochentag,
                "ist_vj": r.ist_vj,
                "monatsumsatz_ist_hoch": r.monatsumsatz_ist_hoch,
                "monatsumsatz_plan": r.monatsumsatz_plan,
                "tagesumsatz_plan": r.tagesumsatz_plan,
                "liefer_plan": r.liefer_plan,
                "gesamt_plan": r.gesamt_plan,
                "tagestyp": r.tagestyp,
                "feiertag_name": r.feiertag_name,
                "ferien_art": r.ferien_art,
                "normalisierung": r.normalisierung,
            }
            for r in results
        ]
        self.conn.executemany(
            """INSERT OR REPLACE INTO planung
               (fil_nr, datum, wochentag, ist_vj, monatsumsatz_ist_hoch,
                monatsumsatz_plan, tagesumsatz_plan, liefer_plan, gesamt_plan,
                tagestyp, feiertag_name, ferien_art, normalisierung)
               VALUES
               (:fil_nr, :datum, :wochentag, :ist_vj, :monatsumsatz_ist_hoch,
                :monatsumsatz_plan, :tagesumsatz_plan, :liefer_plan, :gesamt_plan,
                :tagestyp, :feiertag_name, :ferien_art, :normalisierung)""",
            rows,
        )
        self.conn.commit()
