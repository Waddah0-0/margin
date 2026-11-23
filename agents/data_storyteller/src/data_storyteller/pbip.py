"""Power BI Project (``.pbip``) export for Data Storyteller runs.

Builds a self-contained Power BI Project archive (``<stem>.pbip.zip``) containing a
PII-stripped cleaned CSV, a ``README.txt`` with setup steps, the ``.pbip`` project entry
point, a TMSL semantic model (``model.bim`` + ``definition.pbism``), and a PBIR-Legacy
report (``report.json`` + ``definition.pbir``).

Keep this module free of top-level imports of ``pandas``, ``scipy``, or ``duckdb`` so
listing agents remains fast and lightweight.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, TextIO
from zipfile import ZIP_DEFLATED, ZipFile

from data_storyteller.models import (
    Chart,
    ColumnProfile,
    DataStorytellerOutput,
    Fact,
    StoryPage,
)
from data_storyteller.names import safe_name

TABLE_NAME = "Data"
DATA_FOLDER_PARAM = "DataFolder"
PAGE_WIDTH = 1280.0
PAGE_HEIGHT = 720.0
MAX_MEASURES = 24
MAX_CARDS_PER_PAGE = 3

_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_YEAR_RE = re.compile(r"^(\d{4})$")


def safe_stem(stem: str) -> str:
    """Sanitize a project stem so it cannot traverse directories or use OS-reserved names."""
    return safe_name(stem, max_len=110, strip_double_dot=True)


def _validate_zip_entry(entry: str) -> None:
    if not entry or entry.startswith(("/", "\\")) or "\\" in entry or ":" in entry:
        raise ValueError(f"Unsafe zip entry name: {entry!r}")
    posix = PurePosixPath(entry)
    if posix.is_absolute() or ".." in posix.parts or ".." in entry:
        raise ValueError(f"Path traversal in zip entry name: {entry!r}")


def _short_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _m_quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _dax_table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _dax_col(table: str, column: str) -> str:
    return f"{_dax_table(table)}[{column.replace(']', ']]')}]"


def _dax_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _pbi_literal_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _dax_member(table: str, column: str, member: str, col_types: Mapping[str, str]) -> str | None:
    """A DAX literal for a group's value, typed like its column, or None when it can't be.

    The facts engine keeps group values as text ("3", "3.0"); comparing a number column
    with a text literal is an error in DAX, so number columns get a number literal.
    """
    kind = col_types.get(column, "string")
    if kind in ("int64", "double"):
        try:
            number = float(member)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return str(int(number))
        return f"{number:.15f}".rstrip("0").rstrip(".")
    if kind in ("date", "dateTime"):
        return None
    return _dax_string(member)


def _dax_member_filter(
    table: str, column: str, member: str, col_types: Mapping[str, str]
) -> str | None:
    literal = _dax_member(table, column, member, col_types)
    return None if literal is None else f"{_dax_col(table, column)} = {literal}"


def _is_per_row(fact: Fact) -> bool:
    """A member change of the average per row (like the value of an average order), which
    the engine builds for a summed number. Its SQL averages instead of summing."""
    return fact.kind == "member_change" and fact.metric is not None and "AVG(" in (fact.sql or "")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _visible_columns(
    data: DataStorytellerOutput,
    clean_columns: Sequence[str] | None,
    csv_columns: Sequence[str] | None,
) -> tuple[list[ColumnProfile], dict[str, str]]:
    """Return non-PII, non-dropped cleaned columns and their header names in the CSV."""
    by_name = {c.name: c for c in data.columns}
    if clean_columns is not None:
        ordered_names = list(clean_columns)
    else:
        ordered_names = [c.name for c in data.columns if c.type != "empty"]

    if csv_columns is not None and len(csv_columns) == len(ordered_names):
        csv_map = dict(zip(ordered_names, csv_columns, strict=True))
    else:
        csv_map = {name: name for name in ordered_names}

    visible: list[ColumnProfile] = []
    for name in ordered_names:
        col = by_name.get(name)
        if col is None or col.personal or col.type == "empty":
            continue
        visible.append(col)
    return visible, {c.name: csv_map[c.name] for c in visible}


def _copy_csv_columns(
    src: TextIO,
    dst: TextIO,
    visible: Sequence[ColumnProfile],
    csv_headers: Mapping[str, str],
    clean_columns: Sequence[str] | None,
) -> None:
    """Copy CSV rows from ``src`` to ``dst`` keeping only the visible (non-personal,
    non-empty) columns. Rows are streamed, so a large table is never held in memory."""
    reader = csv.reader(src)
    header = next(reader, None)
    if header is None:
        return

    visible_names = {c.name for c in visible}
    if clean_columns is not None and len(header) == len(clean_columns):
        keep_indices = [i for i, name in enumerate(clean_columns) if name in visible_names]
    else:
        keep_headers = {csv_headers[c.name] for c in visible}
        keep_indices = [i for i, col in enumerate(header) if col in keep_headers]

    writer = csv.writer(dst, lineterminator="\n")
    writer.writerow([header[i] for i in keep_indices])
    for row in reader:
        writer.writerow([row[i] if i < len(row) else "" for i in keep_indices])


def _strip_csv_columns(
    csv_bytes: bytes,
    visible: Sequence[ColumnProfile],
    csv_headers: Mapping[str, str],
    clean_columns: Sequence[str] | None,
) -> bytes:
    """Return CSV bytes keeping only the visible (non-personal, non-empty) columns."""
    src = io.StringIO(csv_bytes.decode("utf-8-sig"), newline="")
    out = io.StringIO(newline="")
    _copy_csv_columns(src, out, visible, csv_headers, clean_columns)
    return out.getvalue().encode("utf-8-sig") if out.getvalue() else b""


def _resolve_column_types(
    visible: Sequence[ColumnProfile],
    column_types: Mapping[str, str] | None,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for col in visible:
        if column_types and col.name in column_types:
            resolved[col.name] = column_types[col.name]
        elif col.type == "number":
            resolved[col.name] = "double"
        elif col.type == "date":
            resolved[col.name] = "dateTime"
        else:
            resolved[col.name] = "string"
    return resolved


def _tmsl_type(kind: str) -> str:
    if kind == "int64":
        return "int64"
    if kind == "double":
        return "double"
    if kind in ("date", "dateTime"):
        return "dateTime"
    return "string"


def _m_type(kind: str) -> str:
    if kind == "int64":
        return "Int64.Type"
    if kind == "double":
        return "type number"
    if kind == "date":
        return "type date"
    if kind == "dateTime":
        return "type datetime"
    return "type text"


def _column_format(col: ColumnProfile, kind: str) -> str | None:
    if kind in ("date", "dateTime"):
        return "yyyy-mm-dd" if kind == "date" else "yyyy-mm-dd hh:nn:ss"
    if col.unit == "%":
        return "0.0%"
    if kind == "int64" and col.role in ("time", "identifier"):
        return "0"
    if kind == "int64":
        return "#,0"
    if kind == "double":
        if col.unit and len(col.unit) == 1:
            u = col.unit.replace('"', '\\"')
            return f'"{u}"#,0.00;("{u}"#,0.00);"{u}"#,0.00'
        return "#,0.00"
    return None


def _summarize_by(col: ColumnProfile) -> str:
    if col.role == "measure" and col.aggregation == "sum":
        return "sum"
    if col.role == "measure" and col.aggregation == "average":
        return "average"
    return "none"


def _measure_format(fmt_kind: str, unit: str | None) -> str:
    if fmt_kind == "count":
        return "#,0"
    if fmt_kind == "percent":
        return "0.0%"
    if fmt_kind == "change":
        return "+0.0%;-0.0%;0.0%"
    if fmt_kind == "ratio":
        return "0.0"
    if unit and unit != "%" and len(unit) == 1:
        u = unit.replace('"', '\\"')
        return f'"{u}"#,0.00;("{u}"#,0.00);"{u}"#,0.00'
    return "#,0.00"


def _period_bounds(period: str) -> tuple[date, date] | None:
    if m := _DAY_RE.match(period):
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, d + timedelta(days=1)
    if m := _WEEK_RE.match(period):
        start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        return start, start + timedelta(days=7)
    if m := _MONTH_RE.match(period):
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return None
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day) + timedelta(days=1)
    if m := _QUARTER_RE.match(period):
        year, quarter = int(m.group(1)), int(m.group(2))
        first_m = 3 * quarter - 2
        last_m = first_m + 2
        last_day = calendar.monthrange(year, last_m)[1]
        return date(year, first_m, 1), date(year, last_m, last_day) + timedelta(days=1)
    if m := _YEAR_RE.match(period):
        year = int(m.group(1))
        return date(year, 1, 1), date(year + 1, 1, 1)
    return None


def _span_dax_filter(table: str, date_col: str, span: str, *, is_numeric_year: bool) -> str | None:
    col_ref = _dax_col(table, date_col)
    if is_numeric_year:
        if " to " in span:
            start_s, end_s = span.split(" to ", 1)
            if _YEAR_RE.match(start_s.strip()) and _YEAR_RE.match(end_s.strip()):
                return f"{col_ref} >= {int(start_s.strip())} && {col_ref} <= {int(end_s.strip())}"
            return None
        if _YEAR_RE.match(span.strip()):
            return f"{col_ref} = {int(span.strip())}"
        return None

    if " to " in span:
        start_s, end_s = span.split(" to ", 1)
        b_start = _period_bounds(start_s.strip())
        b_end = _period_bounds(end_s.strip())
        if b_start is None or b_end is None:
            return None
        start, end_excl = b_start[0], b_end[1]
    else:
        bounds = _period_bounds(span.strip())
        if bounds is None:
            return None
        start, end_excl = bounds
    return (
        f"{col_ref} >= DATE({start.year}, {start.month}, {start.day}) && "
        f"{col_ref} < DATE({end_excl.year}, {end_excl.month}, {end_excl.day})"
    )


def _base_dax_expr(
    table: str,
    metric: str | None,
    data: DataStorytellerOutput,
    visible_by_name: Mapping[str, ColumnProfile],
    *,
    force_average: bool = False,
) -> str | None:
    if metric is None:
        return f"COUNTROWS({_dax_table(table)})"
    col = visible_by_name.get(metric)
    if col is None:
        return None
    col_ref = _dax_col(table, metric)
    if force_average:
        return f"AVERAGE({col_ref})"
    agg = (
        data.setup.aggregations.get(metric, col.aggregation)
        if data.setup is not None
        else col.aggregation
    )
    if agg == "average":
        weight = data.setup.weights.get(metric) if data.setup is not None else None
        if weight and weight in visible_by_name:
            w_ref = _dax_col(table, weight)
            t_ref = _dax_table(table)
            cond = f"NOT(ISBLANK({col_ref})) && NOT(ISBLANK({w_ref}))"
            num = f"SUMX({t_ref}, IF({cond}, {col_ref} * {w_ref}))"
            den = f"SUMX({t_ref}, IF({cond}, {w_ref}))"
            return f"DIVIDE({num}, {den})"
        return f"AVERAGE({col_ref})"
    if agg in ("sum", "last"):
        return f"SUM({col_ref})"
    if agg == "count_distinct":
        return f"DISTINCTCOUNT({col_ref})"
    return None


def _fact_dax(
    fact: Fact,
    table: str,
    data: DataStorytellerOutput,
    visible_by_name: Mapping[str, ColumnProfile],
    col_types: Mapping[str, str],
) -> str | None:
    if fact.metric is not None and fact.metric not in visible_by_name:
        return None
    if fact.dimension is not None and fact.dimension not in visible_by_name:
        return None

    primary_date = data.setup.primary_date if data.setup is not None else None
    has_date = primary_date is not None and primary_date in visible_by_name
    is_numeric_year = bool(primary_date and col_types.get(primary_date) in ("int64", "double"))

    if fact.kind == "count":
        if fact.metric is None:
            return f"COUNTROWS({_dax_table(table)})"
        return f"DISTINCTCOUNT({_dax_col(table, fact.metric)})"

    if fact.kind == "total":
        if fact.metric is None:
            return None
        expr = f"SUM({_dax_col(table, fact.metric)})"
        if fact.period is None:
            return expr
        if not has_date or primary_date is None:
            return None
        flt = _span_dax_filter(table, primary_date, fact.period, is_numeric_year=is_numeric_year)
        return f"CALCULATE({expr}, {flt})" if flt else None

    if fact.kind == "average":
        if fact.metric is None:
            return None
        return _base_dax_expr(table, fact.metric, data, visible_by_name)

    if fact.kind == "partial_period":
        if not has_date or primary_date is None or not fact.period:
            return None
        flt = _span_dax_filter(table, primary_date, fact.period, is_numeric_year=is_numeric_year)
        return f"CALCULATE(COUNTROWS({_dax_table(table)}), {flt})" if flt else None

    if fact.kind == "period_change":
        if not has_date or primary_date is None:
            return None
        before_p = fact.components.get("before_period")
        after_p = fact.components.get("after_period")
        if not isinstance(before_p, str) or not isinstance(after_p, str):
            return None
        base = _base_dax_expr(table, fact.metric, data, visible_by_name)
        if base is None:
            return None
        f_before = _span_dax_filter(table, primary_date, before_p, is_numeric_year=is_numeric_year)
        f_after = _span_dax_filter(table, primary_date, after_p, is_numeric_year=is_numeric_year)
        if not f_before or not f_after:
            return None
        return (
            f"VAR _Before = CALCULATE({base}, {f_before})\n"
            f"VAR _After = CALCULATE({base}, {f_after})\n"
            "RETURN DIVIDE(_After - _Before, ABS(_Before))"
        )

    if fact.kind == "breakdown":
        if fact.dimension is None or fact.member is None:
            return None
        base = _base_dax_expr(table, fact.metric, data, visible_by_name)
        if base is None:
            return None
        dim_flt = _dax_member_filter(table, fact.dimension, fact.member, col_types)
        if dim_flt is None:
            return None
        return f"DIVIDE(CALCULATE({base}, {dim_flt}), {base})"

    if fact.kind == "member_change":
        if (
            fact.dimension is None
            or fact.member is None
            or not fact.period
            or " vs " not in fact.period
        ):
            return None
        if not has_date or primary_date is None or fact.dimension == primary_date:
            return None
        before_p, after_p = fact.period.split(" vs ", 1)
        base = _base_dax_expr(
            table, fact.metric, data, visible_by_name, force_average=_is_per_row(fact)
        )
        if base is None:
            return None
        f_before = _span_dax_filter(table, primary_date, before_p, is_numeric_year=is_numeric_year)
        f_after = _span_dax_filter(table, primary_date, after_p, is_numeric_year=is_numeric_year)
        dim_flt = _dax_member_filter(table, fact.dimension, fact.member, col_types)
        if not f_before or not f_after or dim_flt is None:
            return None
        return (
            f"VAR _Before = CALCULATE({base}, {dim_flt}, {f_before})\n"
            f"VAR _After = CALCULATE({base}, {dim_flt}, {f_after})\n"
            "RETURN DIVIDE(_After - _Before, ABS(_Before))"
        )

    if fact.kind == "segment_gap":
        if fact.metric is None or fact.dimension is None or fact.member is None:
            return None
        base = _base_dax_expr(table, fact.metric, data, visible_by_name)
        if base is None:
            return None
        dim_col = _dax_col(table, fact.dimension)
        mem = _dax_member(table, fact.dimension, fact.member, col_types)
        if mem is None:
            return None
        rest_flt = f"FILTER(VALUES({dim_col}), NOT(ISBLANK({dim_col})) && {dim_col} <> {mem})"
        return f"DIVIDE(CALCULATE({base}, {dim_col} = {mem}), CALCULATE({base}, {rest_flt}))"

    if fact.kind == "simpsons":
        if fact.metric is None or not fact.period or " vs " not in fact.period:
            return None
        if not has_date or primary_date is None:
            return None
        before_p, after_p = fact.period.split(" vs ", 1)
        base = _base_dax_expr(table, fact.metric, data, visible_by_name)
        if base is None:
            return None
        f_before = _span_dax_filter(table, primary_date, before_p, is_numeric_year=is_numeric_year)
        f_after = _span_dax_filter(table, primary_date, after_p, is_numeric_year=is_numeric_year)
        if not f_before or not f_after:
            return None
        return f"CALCULATE({base}, {f_after}) - CALCULATE({base}, {f_before})"

    if fact.kind == "anomaly" and fact.period is not None:
        if not has_date or primary_date is None:
            return None
        base = _base_dax_expr(table, fact.metric, data, visible_by_name)
        if base is None:
            return None
        t_flt = _span_dax_filter(table, primary_date, fact.period, is_numeric_year=is_numeric_year)
        if not t_flt:
            return None
        if fact.dimension is not None and fact.member is not None:
            if fact.dimension == primary_date:
                return None
            dim_flt = _dax_member_filter(table, fact.dimension, fact.member, col_types)
            if dim_flt is None:
                return None
            return f"CALCULATE({base}, {dim_flt}, {t_flt})"
        return f"CALCULATE({base}, {t_flt})"

    return None


def _unique_measure_name(raw_name: str, fact_id: str, used: set[str]) -> str:
    clean = re.sub(r"[\r\n\t]+", " ", raw_name).strip() or fact_id
    candidate = clean
    if candidate.casefold() in used:
        candidate = f"{clean} ({fact_id})"
    idx = 2
    while candidate.casefold() in used:
        candidate = f"{clean} ({fact_id}-{idx})"
        idx += 1
    used.add(candidate.casefold())
    return candidate


def _display_metric_label(fact: Fact) -> str:
    raw = (fact.metric_label or fact.metric or "Rows").strip()
    if not raw:
        return "Value"
    return raw[:1].upper() + raw[1:]


def _build_measures(
    table: str,
    data: DataStorytellerOutput,
    visible: Sequence[ColumnProfile],
    col_types: Mapping[str, str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, str],
    dict[str | None, str],
    dict[str, tuple[str, str]],
]:
    visible_by_name = {c.name: c for c in visible}
    used = {c.name.casefold() for c in visible}
    measures: list[dict[str, Any]] = []
    by_fact_id: dict[str, str] = {}
    base_by_metric: dict[str | None, str] = {}
    dumbbell_measures: dict[str, tuple[str, str]] = {}

    facts_list = data.facts.facts if data.facts is not None else []
    fact_by_id = {f.id: f for f in facts_list}
    ordered_facts = sorted(
        facts_list,
        key=lambda f: (
            0 if f.kind in ("count", "total", "average") and f.period is None else 1,
            -f.importance,
        ),
    )

    for fact in ordered_facts:
        if len(measures) >= MAX_MEASURES and not (
            fact.kind in ("count", "total", "average") and fact.period is None
        ):
            continue
        expr = _fact_dax(fact, table, data, visible_by_name, col_types)
        if expr is None:
            continue
        name = _unique_measure_name(fact.title, fact.id, used)
        measures.append(
            {
                "name": name,
                "expression": expr,
                "formatString": _measure_format(fact.format, fact.unit),
                "description": fact.statement,
            }
        )
        by_fact_id[fact.id] = name
        if (
            fact.kind in ("count", "total", "average")
            and fact.period is None
            and not (fact.kind == "count" and fact.metric is not None)
            and fact.metric not in base_by_metric
        ):
            base_by_metric[fact.metric] = name

    # Ensure charts on story pages have the base and period measures they need.
    primary_date = data.setup.primary_date if data.setup is not None else None
    has_date = primary_date is not None and primary_date in visible_by_name
    is_numeric_year = bool(primary_date and col_types.get(primary_date) in ("int64", "double"))
    period_measure_cache: dict[tuple[str, str], str] = {}

    if data.story is not None:
        for page in data.story.pages:
            for chart in page.charts[:3]:
                chart_fact = fact_by_id.get(chart.fact_id)
                if chart_fact is None:
                    continue
                if chart.kind in ("line", "bars") and chart_fact.metric not in base_by_metric:
                    base = _base_dax_expr(table, chart_fact.metric, data, visible_by_name)
                    if base is not None:
                        label = _display_metric_label(chart_fact)
                        name = _unique_measure_name(label, f"{chart.fact_id}-base", used)
                        measures.append(
                            {
                                "name": name,
                                "expression": base,
                                "formatString": _measure_format(chart.format, chart.unit),
                                "description": f"{label} across the cleaned table.",
                            }
                        )
                        base_by_metric[chart_fact.metric] = name
                elif (
                    chart.kind == "dumbbell"
                    and chart.fact_id not in dumbbell_measures
                    and has_date
                    and primary_date is not None
                    and chart_fact.dimension is not None
                    and chart_fact.dimension in visible_by_name
                    and chart.before_label
                    and chart.after_label
                ):
                    base = _base_dax_expr(
                        table,
                        chart_fact.metric,
                        data,
                        visible_by_name,
                        force_average=_is_per_row(chart_fact),
                    )
                    f_before = _span_dax_filter(
                        table, primary_date, chart.before_label, is_numeric_year=is_numeric_year
                    )
                    f_after = _span_dax_filter(
                        table, primary_date, chart.after_label, is_numeric_year=is_numeric_year
                    )
                    if base is not None and f_before is not None and f_after is not None:
                        label = _display_metric_label(chart_fact)
                        fmt = _measure_format(chart.format, chart.unit)

                        before_key = (base, f_before)
                        if before_key in period_measure_cache:
                            before_name = period_measure_cache[before_key]
                        else:
                            before_name = _unique_measure_name(
                                f"{label} ({chart.before_label})",
                                f"{chart.fact_id}-before",
                                used,
                            )
                            measures.append(
                                {
                                    "name": before_name,
                                    "expression": f"CALCULATE({base}, {f_before})",
                                    "formatString": fmt,
                                    "description": f"{label} in {chart.before_label}.",
                                }
                            )
                            period_measure_cache[before_key] = before_name

                        after_key = (base, f_after)
                        if after_key in period_measure_cache:
                            after_name = period_measure_cache[after_key]
                        else:
                            after_name = _unique_measure_name(
                                f"{label} ({chart.after_label})",
                                f"{chart.fact_id}-after",
                                used,
                            )
                            measures.append(
                                {
                                    "name": after_name,
                                    "expression": f"CALCULATE({base}, {f_after})",
                                    "formatString": fmt,
                                    "description": f"{label} in {chart.after_label}.",
                                }
                            )
                            period_measure_cache[after_key] = after_name

                        dumbbell_measures[chart.fact_id] = (before_name, after_name)

    if not measures:
        name = _unique_measure_name("Row count", "rows", used)
        measures.append(
            {
                "name": name,
                "expression": f"COUNTROWS({_dax_table(table)})",
                "formatString": "#,0",
                "description": "Rows in the cleaned table.",
            }
        )
        base_by_metric[None] = name

    return measures, by_fact_id, base_by_metric, dumbbell_measures


def _build_m_expression(
    csv_filename: str,
    visible: Sequence[ColumnProfile],
    csv_headers: Mapping[str, str],
    col_types: Mapping[str, str],
) -> list[str]:
    selected = ", ".join(_m_quote(csv_headers[c.name]) for c in visible)
    renames = [
        f"{{{_m_quote(csv_headers[c.name])}, {_m_quote(c.name)}}}"
        for c in visible
        if csv_headers[c.name] != c.name
    ]
    types = ", ".join(f"{{{_m_quote(c.name)}, {_m_type(col_types[c.name])}}}" for c in visible)

    csv_opts = '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]'
    path_expr = (
        f'Text.TrimEnd({DATA_FOLDER_PARAM}, {{"\\", "/"}}) & "\\" & {_m_quote(csv_filename)}'
    )
    lines = [
        "let",
        f"    Source = Csv.Document(File.Contents({path_expr}), {csv_opts}),",
        '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
        f'    #"Selected Columns" = Table.SelectColumns(#"Promoted Headers", {{{selected}}})'
        + ("," if renames or visible else ""),
    ]
    prev = '#"Selected Columns"'
    if renames:
        comma = "," if visible else ""
        lines.append(
            f'    #"Renamed Columns" = Table.RenameColumns({prev}, {{{", ".join(renames)}}}){comma}'
        )
        prev = '#"Renamed Columns"'
    if visible:
        # The CSV is written with "." decimals and ISO dates; without a culture, Power BI
        # would read it with the computer's own settings and misread numbers elsewhere.
        lines.append(
            f'    #"Changed Type" = Table.TransformColumnTypes({prev}, {{{types}}}, "en-US")'
        )
        prev = '#"Changed Type"'
    lines.extend(["in", f"    {prev}"])
    return lines


def _build_model_bim(
    safe: str,
    visible: Sequence[ColumnProfile],
    csv_headers: Mapping[str, str],
    col_types: Mapping[str, str],
    measures: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    columns_json: list[dict[str, Any]] = []
    for col in visible:
        kind = col_types[col.name]
        entry: dict[str, Any] = {
            "name": col.name,
            "dataType": _tmsl_type(kind),
            "sourceColumn": col.name,
            "summarizeBy": _summarize_by(col),
        }
        fmt_str = _column_format(col, kind)
        if fmt_str is not None:
            entry["formatString"] = fmt_str
        columns_json.append(entry)

    return {
        "name": safe,
        "compatibilityLevel": 1550,
        "model": {
            "culture": "en-US",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "dataAccessOptions": {
                "legacyRedirects": True,
                "returnErrorValuesAsNull": True,
            },
            "expressions": [
                {
                    "name": DATA_FOLDER_PARAM,
                    "kind": "m",
                    "expression": [
                        '"" meta [IsParameterQuery=true, Type="Text", '
                        "IsParameterQueryRequired=true]"
                    ],
                    "description": (
                        "Full path to the folder containing the unzipped Power BI project files "
                        "(set once in Transform data -> Edit parameters)."
                    ),
                    "annotations": [
                        {"name": "PBI_NavigationStepName", "value": "Navigation"},
                        {"name": "PBI_ResultType", "value": "Text"},
                    ],
                }
            ],
            "tables": [
                {
                    "name": TABLE_NAME,
                    "columns": columns_json,
                    "partitions": [
                        {
                            "name": TABLE_NAME,
                            "mode": "import",
                            "source": {
                                "type": "m",
                                "expression": _build_m_expression(
                                    f"{safe}.clean.csv", visible, csv_headers, col_types
                                ),
                            },
                        }
                    ],
                    "measures": list(measures),
                }
            ],
        },
    }


def _visual_container(
    seed: str,
    *,
    x: float,
    y: float,
    z: int,
    width: float,
    height: float,
    single_visual: dict[str, Any],
) -> dict[str, Any]:
    config = {
        "name": _short_id(seed),
        "layouts": [
            {
                "id": 0,
                "position": {
                    "x": x,
                    "y": y,
                    "z": z,
                    "width": width,
                    "height": height,
                    "tabOrder": z,
                },
            }
        ],
        "singleVisual": single_visual,
    }
    return {
        "x": x,
        "y": y,
        "z": float(z),
        "width": width,
        "height": height,
        "config": json.dumps(config, ensure_ascii=False),
        "filters": "[]",
    }


def _textbox_visual(lines: Sequence[tuple[str, bool, str]]) -> dict[str, Any]:
    paragraphs = [
        {
            "textRuns": [
                {
                    "value": text,
                    "textStyle": {
                        "fontFamily": "Segoe UI",
                        "fontSize": size,
                        **({"fontWeight": "bold"} if bold else {}),
                    },
                }
            ]
        }
        for text, bold, size in lines
        if text
    ]
    return {
        "visualType": "textbox",
        "drillFilterOtherVisuals": True,
        "objects": {
            "general": [
                {
                    "properties": {
                        "paragraphs": paragraphs,
                    }
                }
            ]
        },
    }


def _title_vc_objects(title: str) -> dict[str, Any]:
    return {
        "title": [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "text": {"expr": {"Literal": {"Value": _pbi_literal_str(title)}}},
                }
            }
        ]
    }


def _card_visual(table: str, measure_name: str, title: str) -> dict[str, Any]:
    qref = f"{table}.{measure_name}"
    return {
        "visualType": "card",
        "projections": {"Values": [{"queryRef": qref}]},
        "prototypeQuery": {
            "Version": 2,
            "From": [{"Name": "d", "Entity": table, "Type": 0}],
            "Select": [
                {
                    "Measure": {
                        "Expression": {"SourceRef": {"Source": "d"}},
                        "Property": measure_name,
                    },
                    "Name": qref,
                    "NativeReferenceName": measure_name,
                }
            ],
        },
        "drillFilterOtherVisuals": True,
        "vcObjects": _title_vc_objects(title),
    }


def _measure_select(measure_name: str) -> tuple[str, dict[str, Any]]:
    m_ref = f"{TABLE_NAME}.{measure_name}"
    return m_ref, {
        "Measure": {
            "Expression": {"SourceRef": {"Source": "d"}},
            "Property": measure_name,
        },
        "Name": m_ref,
        "NativeReferenceName": measure_name,
    }


def _bound_chart_visual(
    visual_type: str,
    title: str,
    *,
    cat_col: str | None,
    measures: Sequence[str],
) -> dict[str, Any]:
    selects: list[dict[str, Any]] = []
    projections: dict[str, list[dict[str, Any]]] = {}
    if cat_col is not None:
        cat_ref = f"{TABLE_NAME}.{cat_col}"
        projections["Category"] = [{"queryRef": cat_ref, "active": True}]
        selects.append(
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": "d"}},
                    "Property": cat_col,
                },
                "Name": cat_ref,
                "NativeReferenceName": cat_col,
            }
        )
    y_refs: list[dict[str, Any]] = []
    for measure_name in measures:
        m_ref, select = _measure_select(measure_name)
        y_refs.append({"queryRef": m_ref})
        selects.append(select)
    projections["Y"] = y_refs
    return {
        "visualType": visual_type,
        "projections": projections,
        "prototypeQuery": {
            "Version": 2,
            "From": [{"Name": "d", "Entity": TABLE_NAME, "Type": 0}],
            "Select": selects,
        },
        "drillFilterOtherVisuals": True,
        "vcObjects": _title_vc_objects(title),
    }


def _chart_fallback_textbox(chart: Chart) -> dict[str, Any]:
    summary_lines: list[tuple[str, bool, str]] = [(chart.title, True, "12pt")]
    if chart.before_label and chart.after_label:
        summary_lines.append((f"{chart.before_label} vs {chart.after_label}", False, "9pt"))
    for p in chart.points[:8]:
        if p.before is not None:
            summary_lines.append((f"• {p.label}: {p.before:,.4g} -> {p.value:,.4g}", False, "10pt"))
        else:
            summary_lines.append((f"• {p.label}: {p.value:,.4g}", False, "10pt"))
    if chart.note:
        summary_lines.append((chart.note, False, "9pt"))
    return _textbox_visual(summary_lines)


def _chart_visual(
    chart: Chart,
    fact: Fact | None,
    data: DataStorytellerOutput,
    visible_names: set[str],
    measure_by_fact: Mapping[str, str],
    base_by_metric: Mapping[str | None, str],
    dumbbell_measures: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    primary_date = data.setup.primary_date if data.setup is not None else None

    if chart.kind == "dumbbell":
        cat_col = fact.dimension if fact and fact.dimension in visible_names else None
        pair = dumbbell_measures.get(chart.fact_id)
        if pair is not None and cat_col is not None:
            return _bound_chart_visual(
                "clusteredColumnChart",
                chart.title,
                cat_col=cat_col,
                measures=pair,
            )
        return _chart_fallback_textbox(chart)

    if chart.kind == "meter":
        measure_name = measure_by_fact.get(chart.fact_id)
        if measure_name is not None:
            return _bound_chart_visual(
                "gauge",
                chart.title,
                cat_col=None,
                measures=[measure_name],
            )
        return _chart_fallback_textbox(chart)

    visual_type = "lineChart" if chart.kind == "line" else "clusteredBarChart"
    cat_col = None
    if chart.kind == "line" and primary_date and primary_date in visible_names:
        cat_col = primary_date
    elif chart.kind == "bars" and fact and fact.dimension in visible_names:
        cat_col = fact.dimension

    target_metric = fact.metric if fact is not None else None
    measure_name = base_by_metric.get(target_metric)
    if measure_name is not None and cat_col is not None:
        return _bound_chart_visual(
            visual_type,
            chart.title,
            cat_col=cat_col,
            measures=[measure_name],
        )

    return _chart_fallback_textbox(chart)


def _chart_slots(count: int) -> list[tuple[float, float, float, float]]:
    if count <= 0:
        return []
    if count == 1:
        return [(464.0, 248.0, 792.0, 448.0)]
    if count == 2:
        return [(464.0, 248.0, 388.0, 448.0), (868.0, 248.0, 388.0, 448.0)]
    return [
        (464.0, 248.0, 388.0, 216.0),
        (868.0, 248.0, 388.0, 216.0),
        (464.0, 480.0, 792.0, 216.0),
    ]


def _page_section(
    page: StoryPage,
    ordinal: int,
    data: DataStorytellerOutput,
    visible_names: set[str],
    fact_by_id: Mapping[str, Fact],
    measure_by_fact: Mapping[str, str],
    base_by_metric: Mapping[str | None, str],
    dumbbell_measures: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    visuals: list[dict[str, Any]] = []
    z = 0

    visuals.append(
        _visual_container(
            f"{page.id}:header",
            x=24.0,
            y=16.0,
            z=z,
            width=1232.0,
            height=96.0,
            single_visual=_textbox_visual(
                [(page.title, True, "16pt"), (page.headline.text, False, "12pt")]
            ),
        )
    )
    z += 1

    if page.role == "actions":
        action_lines: list[tuple[str, bool, str]] = [("Hypotheses to test next", True, "13pt")]
        for act in page.actions:
            action_lines.append((f"• {act.text}", True, "11pt"))
            action_lines.append((f"  How to test: {act.check}", False, "10pt"))
        visuals.append(
            _visual_container(
                f"{page.id}:actions",
                x=24.0,
                y=128.0,
                z=z,
                width=1232.0,
                height=568.0,
                single_visual=_textbox_visual(action_lines),
            )
        )
    else:
        card_facts = [fid for fid in page.fact_ids if fid in measure_by_fact][:MAX_CARDS_PER_PAGE]
        for idx, fid in enumerate(card_facts):
            fact = fact_by_id.get(fid)
            m_name = measure_by_fact[fid]
            visuals.append(
                _visual_container(
                    f"{page.id}:card:{fid}",
                    x=24.0 + idx * 420.0,
                    y=124.0,
                    z=z,
                    width=392.0,
                    height=110.0,
                    single_visual=_card_visual(
                        TABLE_NAME, m_name, fact.title if fact is not None else m_name
                    ),
                )
            )
            z += 1

        body_top = 248.0 if card_facts else 128.0
        body_height = 448.0 if card_facts else 568.0
        charts = page.charts[:3]
        body_width = 420.0 if charts else 1232.0
        body_lines: list[tuple[str, bool, str]] = [(s.text, False, "11pt") for s in page.body]
        if not body_lines:
            body_lines = [(page.headline.text, False, "11pt")]
        visuals.append(
            _visual_container(
                f"{page.id}:body",
                x=24.0,
                y=body_top,
                z=z,
                width=body_width,
                height=body_height,
                single_visual=_textbox_visual(body_lines),
            )
        )
        z += 1

        slots = _chart_slots(len(charts))
        for idx, (chart, (cx, cy, cw, ch)) in enumerate(zip(charts, slots, strict=True)):
            fact = fact_by_id.get(chart.fact_id)
            if not card_facts:
                cy = cy - 120.0
                ch = ch + (120.0 if len(charts) <= 2 else 60.0)
            visuals.append(
                _visual_container(
                    f"{page.id}:chart:{idx}:{chart.fact_id}",
                    x=cx,
                    y=cy,
                    z=z,
                    width=cw,
                    height=ch,
                    single_visual=_chart_visual(
                        chart,
                        fact,
                        data,
                        visible_names,
                        measure_by_fact,
                        base_by_metric,
                        dumbbell_measures,
                    ),
                )
            )
            z += 1

    return {
        "name": f"ReportSection_{_short_id(page.id)}",
        "displayName": page.title[:80] or page.id,
        "displayOption": 1,
        "width": PAGE_WIDTH,
        "height": PAGE_HEIGHT,
        "ordinal": ordinal,
        "filters": "[]",
        "config": "{}",
        "visualContainers": visuals,
    }


def _build_report_json(
    data: DataStorytellerOutput,
    visible: Sequence[ColumnProfile],
    measure_by_fact: Mapping[str, str],
    base_by_metric: Mapping[str | None, str],
    dumbbell_measures: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    visible_names = {c.name for c in visible}
    fact_by_id = {f.id: f for f in data.facts.facts} if data.facts is not None else {}

    sections: list[dict[str, Any]] = []
    if data.story is not None and data.story.pages:
        for idx, page in enumerate(data.story.pages):
            sections.append(
                _page_section(
                    page,
                    idx,
                    data,
                    visible_names,
                    fact_by_id,
                    measure_by_fact,
                    base_by_metric,
                    dumbbell_measures,
                )
            )
    else:
        visuals: list[dict[str, Any]] = [
            _visual_container(
                "summary:header",
                x=24.0,
                y=16.0,
                z=0,
                width=1232.0,
                height=96.0,
                single_visual=_textbox_visual(
                    [(data.source.file, True, "16pt"), ("Cleaned dataset overview", False, "12pt")]
                ),
            )
        ]
        for idx, (fid, m_name) in enumerate(list(measure_by_fact.items())[:MAX_CARDS_PER_PAGE]):
            fact = fact_by_id.get(fid)
            visuals.append(
                _visual_container(
                    f"summary:card:{fid}",
                    x=24.0 + idx * 420.0,
                    y=128.0,
                    z=idx + 1,
                    width=392.0,
                    height=110.0,
                    single_visual=_card_visual(
                        TABLE_NAME, m_name, fact.title if fact is not None else m_name
                    ),
                )
            )
        sections.append(
            {
                "name": "ReportSection_summary",
                "displayName": "Summary",
                "displayOption": 1,
                "width": PAGE_WIDTH,
                "height": PAGE_HEIGHT,
                "ordinal": 0,
                "filters": "[]",
                "config": "{}",
                "visualContainers": visuals,
            }
        )

    report_config = {
        "version": "5.59",
        "activeSectionIndex": 0,
        "defaultDrillFilterOtherVisuals": True,
        "linguisticSchemaSyncVersion": 2,
        "settings": {
            "useNewFilterPaneExperience": True,
            "allowChangeFilterTypes": True,
            "useStylableVisualContainerHeader": True,
            "queryLimitOption": 6,
            "exportDataMode": 1,
            "useDefaultAggregateDisplayName": True,
        },
    }
    return {
        "config": json.dumps(report_config, ensure_ascii=False),
        "layoutOptimization": 0,
        "resourcePackages": [],
        "sections": sections,
    }


def _build_readme_txt(safe: str) -> bytes:
    lines = [
        "How to open this Power BI project",
        "",
        "1. Unzip all files in this archive into one folder.",
        f"2. Open {safe}.pbip in Power BI Desktop.",
        "3. Point Power BI to the unzipped folder once:",
        "   Home -> Transform data -> Edit parameters",
        f"   Set {DATA_FOLDER_PARAM} to the full path of the unzipped folder, then click OK.",
        f"4. Click Refresh (or Apply changes) to load {safe}.clean.csv.",
        "",
        f"Personal-data columns detected during cleaning are left out of {safe}.clean.csv",
        "inside this archive, model.bim, and report.json.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_pbip_files(
    stem: str,
    data: DataStorytellerOutput,
    csv_bytes: bytes | None,
    *,
    clean_columns: Sequence[str] | None = None,
    csv_columns: Sequence[str] | None = None,
    column_types: Mapping[str, str] | None = None,
) -> dict[str, bytes]:
    """Build every file in a self-contained Power BI Project (``.pbip``) bundle.

    With ``csv_bytes`` of None the CSV is left out, for a caller that streams it.
    """
    safe = safe_stem(stem)
    visible, csv_headers = _visible_columns(data, clean_columns, csv_columns)
    resolved_types = _resolve_column_types(visible, column_types)
    measures, measure_by_fact, base_by_metric, dumbbell_measures = _build_measures(
        TABLE_NAME, data, visible, resolved_types
    )

    pbip_doc = {
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{safe}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    }
    pbism_doc = {
        "version": "1.0",
        "settings": {},
    }
    pbir_doc = {
        "version": "1.0",
        "datasetReference": {
            "byPath": {"path": f"../{safe}.SemanticModel"},
            "byConnection": None,
        },
    }
    model_bim = _build_model_bim(safe, visible, csv_headers, resolved_types, measures)
    report_json = _build_report_json(
        data, visible, measure_by_fact, base_by_metric, dumbbell_measures
    )

    files: dict[str, bytes] = {}
    if csv_bytes is not None:
        files[f"{safe}.clean.csv"] = _strip_csv_columns(
            csv_bytes, visible, csv_headers, clean_columns
        )
    files |= {
        f"{safe}.pbip": _json_bytes(pbip_doc),
        f"{safe}.SemanticModel/definition.pbism": _json_bytes(pbism_doc),
        f"{safe}.SemanticModel/model.bim": _json_bytes(model_bim),
        f"{safe}.Report/definition.pbir": _json_bytes(pbir_doc),
        f"{safe}.Report/report.json": _json_bytes(report_json),
        "README.txt": _build_readme_txt(safe),
    }
    for entry in files:
        _validate_zip_entry(entry)
    return files


def write_pbip_zip(
    out: Path,
    stem: str,
    data: DataStorytellerOutput,
    csv_path: Path,
    *,
    clean_columns: Sequence[str] | None = None,
    csv_columns: Sequence[str] | None = None,
    column_types: Mapping[str, str] | None = None,
) -> Path:
    """Write ``<stem>.pbip.zip`` inside ``out``, enforcing path-traversal safety."""
    out_dir = Path(out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_stem(stem)
    zip_path = out_dir / f"{safe}.pbip.zip"
    if zip_path.resolve().parent != out_dir:
        raise ValueError(f"Refusing to write {stem!r} outside {out_dir}")

    files = build_pbip_files(
        safe,
        data,
        None,
        clean_columns=clean_columns,
        csv_columns=csv_columns,
        column_types=column_types,
    )
    visible, csv_headers = _visible_columns(data, clean_columns, csv_columns)
    csv_entry = f"{safe}.clean.csv"
    _validate_zip_entry(csv_entry)
    try:
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            with (
                csv_path.open(encoding="utf-8-sig", newline="") as src,
                archive.open(csv_entry, "w", force_zip64=True) as raw,
                io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as dst,
            ):
                _copy_csv_columns(src, dst, visible, csv_headers, clean_columns)
            for entry, content in files.items():
                _validate_zip_entry(entry)
                archive.writestr(entry, content)
    except BaseException:
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path
