"""Metric layer: governed definitions, clarifying questions, and answers with their assumptions.

This is the deterministic knowledge layer a language model sits on top of. A model (Claude) answering report requests should
(1) look the metric up here, (2) ask the listed clarifying question if the request is ambiguous, otherwise (3) run the
documented SQL and (4) return the number WITH its definition and the assumptions that were made. Nothing here guesses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb
import pandas as pd

from ..config import Config

MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                           "october", "november", "december"])}


@dataclass
class Resolution:
    question: str
    status: str                                  # answered | needs_clarification | unknown_metric
    metric: str | None = None
    period: tuple | None = None
    level: str | None = None
    value: object = None
    table: pd.DataFrame | None = None
    assumptions: list = field(default_factory=list)
    clarifying_questions: list = field(default_factory=list)
    definition: str = ""
    caveats: str = ""
    sql: str = ""


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def parse_period(q: str, as_of: date):
    """Return ((start, end) inclusive, label, assumption or None), or None if the question names no period."""
    s = q.lower()
    y = as_of.year
    if "yesterday" in s:
        d = as_of - timedelta(days=1); return (d, d), "yesterday", None
    if "today" in s:
        return (as_of, as_of), "today", None
    if "last week" in s:
        st = _monday(as_of) - timedelta(days=7); return (st, st + timedelta(days=6)), "last week", "weeks run Monday-Sunday; 'last week' is the most recent complete week"
    if "this week" in s:
        st = _monday(as_of); return (st, as_of), "this week (to date)", "weeks run Monday-Sunday"
    m = re.search(r"last (\d+) days", s)
    if m:
        n = int(m.group(1)); return (as_of - timedelta(days=n - 1), as_of), f"last {n} days", None
    if "last month" in s:
        first = as_of.replace(day=1); end = first - timedelta(days=1); return (end.replace(day=1), end), "last month", "calendar month"
    if "this month" in s:
        return (as_of.replace(day=1), as_of), "this month (to date)", None
    m = re.search(r"\bq([1-4])(?:\s*(20\d\d))?\b", s)
    if m:
        qn, yy = int(m.group(1)), int(m.group(2) or y)
        st = date(yy, 3 * qn - 2, 1); en = (date(yy + (qn == 4), (3 * qn) % 12 + 1, 1) - timedelta(days=1)); return (st, en), f"Q{qn} {yy}", "calendar quarters"
    for name, num in MONTHS.items():
        m = re.search(rf"\b{name}\b(?:\s+(20\d\d))?", s)
        if m:
            yy = int(m.group(1) or y)
            if not m.group(1) and date(yy, num, 1) > as_of:
                yy -= 1
            st = date(yy, num, 1); en = (date(yy + (num == 12), num % 12 + 1, 1) - timedelta(days=1)); return (st, en), f"{name.title()} {yy}", None
    m = re.search(r"\b(20\d\d)\b", s)
    if m:
        yy = int(m.group(1)); return (date(yy, 1, 1), date(yy, 12, 31)), str(yy), None
    return None


class MetricLayer:
    def __init__(self, cfg: Config, con: duckdb.DuckDBPyConnection):
        self.cfg, self.con = cfg, con
        d = cfg.metric_definitions
        if not d:
            raise FileNotFoundError("config/metric_definitions.yaml not found")
        self.defn = d
        self.metrics = d["metrics"]
        self.as_of = date.fromisoformat(str(d["defaults"]["as_of"]))
        self.ask = bool(d["defaults"].get("ask_when_ambiguous", True))
        self.log: list[dict] = []

    # ------------------------------------------------------------------ parsing
    def _find_metric(self, q: str):
        s = q.lower()
        best, best_len = None, 0
        for mid, m in self.metrics.items():
            for syn in [m["label"].lower()] + [x.lower() for x in m.get("synonyms", [])]:
                if re.search(rf"\b{re.escape(syn)}\b", s) and len(syn) > best_len:
                    best, best_len = mid, len(syn)
        return best

    def _ambiguity(self, q: str):
        s = q.lower()
        for a in self.defn.get("ambiguous_terms", []):
            if a["needs"] == "none":
                continue
            if re.search(rf"\b{a['term']}\b", s):
                chosen = None
                for key, mid in a["options"].items():
                    pat = {"gross": r"\bgross\b", "net": r"\bnet\b", "sold": r"\b(on|for) sold\b|\bsold items\b", "all": r"\ball (listed )?items\b|\bincluding unsold\b"}.get(key)
                    if pat and re.search(pat, s):
                        chosen = mid
                if chosen:
                    return None, chosen
                return a, None
        return None, None

    def _level(self, q: str):
        s = q.lower()
        if not re.search(r"\bby\b|\bper\b|\beach\b|\bacross\b|\bsplit\b|\bbreak ?down\b", s):
            return None
        best, bl = None, 0
        for k, v in self.defn["levels"].items():
            for w in v["words"]:
                if re.search(rf"\b{re.escape(w)}\b", s) and len(w) > bl:
                    best, bl = k, len(w)
        return best

    # ------------------------------------------------------------------ answering
    def ask_question(self, question: str) -> Resolution:
        res = Resolution(question=question, status="answered")
        amb, forced = self._ambiguity(question)
        metric = forced or self._find_metric(question)
        if amb and not forced and metric is None:
            if self.ask:
                res.status = "needs_clarification"; res.clarifying_questions.append(amb["question"])
                self.log.append({"question": question, "ambiguity": amb["term"], "resolution": "asked"})
                return res
            metric = amb["options"][amb["default"]]
            res.assumptions.append(f"'{amb['term']}' was ambiguous; used the documented default: {metric}")
            self.log.append({"question": question, "ambiguity": amb["term"], "resolution": f"defaulted to {metric}"})
        if metric is None:
            term_hit = re.search(r"\b(sales|revenue|recovery|profit)\b", question.lower())
            if term_hit:
                t = term_hit.group(1)
                a = next(x for x in self.defn["ambiguous_terms"] if x["term"] == t)
                if a["needs"] == "none":
                    metric = a["options"]["default"]
                elif self.ask:
                    res.status = "needs_clarification"; res.clarifying_questions.append(a["question"])
                    self.log.append({"question": question, "ambiguity": t, "resolution": "asked"})
                    return res
                else:
                    metric = a["options"][a["default"]]
                    res.assumptions.append(f"'{t}' was ambiguous; used the documented default: {metric}")
        if metric is None:
            res.status = "unknown_metric"
            res.clarifying_questions.append("I do not have a documented metric for that. Which of these do you mean: " + ", ".join(m["label"] for m in self.metrics.values()) + "?")
            self.log.append({"question": question, "ambiguity": "metric", "resolution": "unknown"})
            return res
        m = self.metrics[metric]
        res.metric, res.definition, res.caveats = metric, m["definition"], m.get("caveats", "")
        if metric == "gross_recovery_rate" and forced is None and not re.search(r"\bgross\b", question.lower()):
            res.assumptions.append("'recovery' means gross recovery on ALL closed items (unsold counted as zero), the documented default; "
                                   "say 'on sold items' or 'net recovery' for the other versions")
        period = parse_period(question, self.as_of)
        if period is None:
            if self.ask:
                res.status = "needs_clarification"
                res.clarifying_questions.append(f"For which period? (data runs to {self.as_of:%b %d, %Y}; e.g. 'last week', 'October 2026', 'Q3')")
                self.log.append({"question": question, "ambiguity": "period", "resolution": "asked"})
                return res
            period = ((self.as_of - timedelta(days=29), self.as_of), "last 30 days", "no period given; used the last 30 days")
        (st, en), label, note = period
        res.period = (st, en)
        if note:
            res.assumptions.append(note)
        date_field = m["date_field"]
        res.assumptions.append(f"dated by {date_field}: {self.defn['date_fields'][date_field]}")
        lvl = self._level(question)
        res.level = lvl
        where = f"({m['where']}) and cast({date_field} as date) between date '{st}' and date '{en}'"
        grp = self.defn["levels"][lvl]["column"] if lvl else None
        sql = f"select {grp + ' as grp, ' if grp else ''}({m['sql']}) as value, count(*) as items from mart_item where {where}" + (" group by 1 order by 2 desc" if grp else "")
        res.sql = sql
        df = self.con.execute(sql).df()
        res.table = df
        res.value = None if grp else (None if df.empty else df["value"].iloc[0])
        if res.value is not None and pd.isna(res.value):
            res.status = "answered"; res.assumptions.append("no closed items in that period")
        self.log.append({"question": question, "ambiguity": "", "resolution": "answered"})
        return res

    def to_prompt_context(self) -> str:
        """Render the metric layer as text a language model can use to answer report requests."""
        lines = ["You answer report requests ONLY from these documented metrics. If a request is ambiguous, ask the listed question.",
                 "Always state the definition, the period, the date field and any assumption with the number.", ""]
        for mid, m in self.metrics.items():
            lines.append(f"- {m['label']} [{mid}]: {m['definition']} (date: {m['date_field']}; table: {m['source_table']}). Caveat: {m.get('caveats') or 'none'}")
        lines.append("")
        for a in self.defn["ambiguous_terms"]:
            if a["needs"] != "none":
                lines.append(f"Ambiguous '{a['term']}': ask \"{a['question']}\"")
        lines.append("")
        for k, v in self.defn["glossary"].items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)
