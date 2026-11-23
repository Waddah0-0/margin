"""Tests for Phase DS6: self-contained Power BI Project (.pbip.zip) export."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pandas as pd
import pytest
from data_storyteller import DataStorytellerAgent, pbip
from data_storyteller.models import (
    Chart,
    ChartPoint,
    ColumnProfile,
    DataStorytellerOutput,
    Fact,
    FactsReport,
    Story,
    StoryPage,
    StorySentence,
    StorySetup,
)
from margin_core import RunContext

_DAX_COL_RE = re.compile(r"'((?:[^']|'')+)'\[((?:[^\]]|\]\])+)\]")


async def _run(dataset: Path, **fields: Any):  # type: ignore[no-untyped-def]
    return await DataStorytellerAgent().execute(
        {"dataset": str(dataset), "assume_defaults": True, **fields},
        RunContext(),
    )


def _strip_dax_strings(expr: str) -> str:
    """Replace double-quoted DAX string literals with empty quotes so regexes ignore them."""
    out: list[str] = []
    i = 0
    n = len(expr)
    while i < n:
        if expr[i] == '"':
            out.append('""')
            i += 1
            while i < n:
                if expr[i] == '"':
                    if i + 1 < n and expr[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        else:
            out.append(expr[i])
            i += 1
    return "".join(out)


def _split_dax_args(arg_str: str) -> list[str]:
    """Split top-level comma-separated DAX arguments, respecting parens and quotes."""
    args: list[str] = []
    depth = 0
    in_double = False
    in_single = False
    start = 0
    i = 0
    n = len(arg_str)
    while i < n:
        ch = arg_str[i]
        if in_double:
            if ch == '"':
                if i + 1 < n and arg_str[i + 1] == '"':
                    i += 2
                    continue
                in_double = False
        elif in_single:
            if ch == "'":
                if i + 1 < n and arg_str[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(arg_str[start:i].strip())
                start = i + 1
        i += 1
    tail = arg_str[start:].strip()
    if tail:
        args.append(tail)
    return args


def _find_calculate_calls(expr: str) -> list[list[str]]:
    """Return the split argument lists of every CALCULATE(...) call in ``expr``."""
    calls: list[list[str]] = []
    i = 0
    n = len(expr)
    in_double = False
    in_single = False
    while i < n:
        ch = expr[i]
        if in_double:
            if ch == '"':
                if i + 1 < n and expr[i + 1] == '"':
                    i += 2
                    continue
                in_double = False
            i += 1
            continue
        if in_single:
            if ch == "'":
                if i + 1 < n and expr[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if expr[i : i + 10].upper() == "CALCULATE(" and (
            i == 0 or not (expr[i - 1].isalnum() or expr[i - 1] == "_")
        ):
            j = i + 10
            depth = 1
            d_q = False
            s_q = False
            while j < n and depth > 0:
                c = expr[j]
                if d_q:
                    if c == '"':
                        if j + 1 < n and expr[j + 1] == '"':
                            j += 2
                            continue
                        d_q = False
                elif s_q:
                    if c == "'":
                        if j + 1 < n and expr[j + 1] == "'":
                            j += 2
                            continue
                        s_q = False
                else:
                    if c == '"':
                        d_q = True
                    elif c == "'":
                        s_q = True
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                j += 1
            assert depth == 0, f"Unclosed CALCULATE( in {expr!r}"
            inside = expr[i + 10 : j - 1]
            calls.append(_split_dax_args(inside))
            i += 10
            continue
        i += 1
    return calls


def _assert_valid_calculate_predicates(expr: str) -> None:
    """Assert every CALCULATE filter argument references at most one column and valid syntax."""
    for args in _find_calculate_calls(expr):
        assert len(args) >= 2, f"CALCULATE call missing filter argument: {args!r}"
        for flt in args[1:]:
            stripped = _strip_dax_strings(flt)
            cols = set(_DAX_COL_RE.findall(stripped))
            assert len(cols) <= 1, (
                f"CALCULATE filter argument references multiple columns {cols}: {flt!r}\n"
                f"Full expression: {expr!r}"
            )
            if not stripped.lstrip().upper().startswith("FILTER("):
                assert "ISBLANK(" not in stripped.upper(), (
                    f"Bare ISBLANK in CALCULATE boolean filter argument: {flt!r}\n"
                    f"Full expression: {expr!r}"
                )


def _eval_base_dax(df: pd.DataFrame, expr: str) -> float:
    expr = expr.strip()
    if m := re.fullmatch(r"COUNTROWS\('Data'\)", expr):
        return float(len(df))
    if m := re.fullmatch(r"DISTINCTCOUNT\('Data'\[([^\]]+)\]\)", expr):
        col = m.group(1).replace("]]", "]")
        return float(df[col].nunique(dropna=True))
    if m := re.fullmatch(r"SUM\('Data'\[([^\]]+)\]\)", expr):
        col = m.group(1).replace("]]", "]")
        return float(df[col].astype("float64").sum())
    if m := re.fullmatch(r"AVERAGE\('Data'\[([^\]]+)\]\)", expr):
        col = m.group(1).replace("]]", "]")
        return float(df[col].astype("float64").mean())
    if m := re.fullmatch(
        r"DIVIDE\(SUMX\('Data', IF\(NOT\(ISBLANK\('Data'\[([^\]]+)\]\)\) && "
        r"NOT\(ISBLANK\('Data'\[([^\]]+)\]\)\), 'Data'\[[^\]]+\] \* 'Data'\[[^\]]+\]\)\), "
        r"SUMX\('Data', IF\(NOT\(ISBLANK\('Data'\[[^\]]+\]\)\) && "
        r"NOT\(ISBLANK\('Data'\[[^\]]+\]\)\), 'Data'\[[^\]]+\]\)\)\)",
        expr,
    ):
        c, w = m.group(1).replace("]]", "]"), m.group(2).replace("]]", "]")
        both = df[c].notna() & df[w].notna()
        num = (df.loc[both, c].astype("float64") * df.loc[both, w].astype("float64")).sum()
        den = df.loc[both, w].astype("float64").sum()
        return float(num / den)
    raise AssertionError(f"Unsupported base DAX in test evaluator: {expr!r}")


def _eval_filter_dax(df: pd.DataFrame, flt: str) -> pd.Series[bool]:
    flt = flt.strip()
    if flt.startswith("FILTER(") and flt.endswith(")"):
        inner_args = _split_dax_args(flt[7:-1])
        assert len(inner_args) == 2, f"Unexpected FILTER() args: {flt!r}"
        assert re.fullmatch(r"VALUES\('Data'\[(?:[^\]]|\]\])+\]\)", inner_args[0]), (
            f"Unexpected FILTER table arg: {inner_args[0]!r}"
        )
        flt = inner_args[1]

    mask: pd.Series[bool] = pd.Series(True, index=df.index)
    for clause in [p.strip() for p in flt.split("&&")]:
        if m := re.fullmatch(
            r"'Data'\[([^\]]+)\]\s*(>=|<|<=|=)\s*DATE\((\d+),\s*(\d+),\s*(\d+)\)", clause
        ):
            col = m.group(1).replace("]]", "]")
            op = m.group(2)
            target = pd.Timestamp(int(m.group(3)), int(m.group(4)), int(m.group(5)))
            dates = pd.to_datetime(df[col])
            if op == ">=":
                mask &= dates >= target
            elif op == "<":
                mask &= dates < target
            elif op == "<=":
                mask &= dates <= target
            else:
                mask &= dates == target
        elif m := re.fullmatch(r"'Data'\[([^\]]+)\]\s*(>=|<=|=)\s*(\d+)", clause):
            col = m.group(1).replace("]]", "]")
            op, num_val = m.group(2), int(m.group(3))
            nums = df[col].astype("float64")
            if op == ">=":
                mask &= nums >= num_val
            elif op == "<=":
                mask &= nums <= num_val
            else:
                mask &= nums == num_val
        elif m := re.fullmatch(r"'Data'\[([^\]]+)\]\s*=\s*\"((?:[^\"]|\"\")*)\"", clause):
            col = m.group(1).replace("]]", "]")
            eq_val = m.group(2).replace('""', '"')
            mask &= df[col].astype(str) == eq_val
        elif m := re.fullmatch(r"NOT\(ISBLANK\('Data'\[([^\]]+)\]\)\)", clause):
            col = m.group(1).replace("]]", "]")
            mask &= df[col].notna()
        elif m := re.fullmatch(r"'Data'\[([^\]]+)\]\s*<>\s*\"((?:[^\"]|\"\")*)\"", clause):
            col = m.group(1).replace("]]", "]")
            neq_val = m.group(2).replace('""', '"')
            mask &= df[col].astype(str) != neq_val
        else:
            raise AssertionError(f"Unsupported filter clause in test evaluator: {clause!r}")
    return mask


def _eval_calculate_expr(df: pd.DataFrame, calc_expr: str) -> float:
    calc_expr = calc_expr.strip()
    assert calc_expr.startswith("CALCULATE(") and calc_expr.endswith(")")
    args = _split_dax_args(calc_expr[10:-1])
    assert len(args) >= 2
    mask: pd.Series[bool] = pd.Series(True, index=df.index)
    for flt in args[1:]:
        mask &= _eval_filter_dax(df, flt)
    return _eval_base_dax(df[mask], args[0])


def _eval_dax_measure(df: pd.DataFrame, expr: str) -> float:
    expr = expr.strip()
    if expr.startswith("VAR _Before = "):
        lines = expr.splitlines()
        assert len(lines) == 3, f"Unexpected VAR DAX: {expr!r}"
        assert lines[0].startswith("VAR _Before = ")
        assert lines[1].startswith("VAR _After = ")
        assert lines[2] == "RETURN DIVIDE(_After - _Before, ABS(_Before))"
        before = _eval_calculate_expr(df, lines[0].removeprefix("VAR _Before = "))
        after = _eval_calculate_expr(df, lines[1].removeprefix("VAR _After = "))
        return float((after - before) / abs(before))

    if expr.startswith("DIVIDE(") and expr.endswith(")"):
        parts = _split_dax_args(expr[7:-1])
        if len(parts) == 2 and parts[0].startswith("CALCULATE("):
            num = _eval_calculate_expr(df, parts[0])
            den = (
                _eval_calculate_expr(df, parts[1])
                if parts[1].startswith("CALCULATE(")
                else _eval_base_dax(df, parts[1])
            )
            return float(num / den)

    if expr.startswith("CALCULATE("):
        # Check for "CALCULATE(...) - CALCULATE(...)"
        calls = _find_calculate_calls(expr)
        if len(calls) == 2 and " - CALCULATE(" in expr:
            left, right = expr.split(" - ", 1)
            return float(_eval_calculate_expr(df, left) - _eval_calculate_expr(df, right))
        return _eval_calculate_expr(df, expr)

    return _eval_base_dax(df, expr)


async def test_pbip_zip_only_created_in_story_mode(golden: dict[str, Path], tmp_path: Path) -> None:
    clean_out = tmp_path / "clean"
    clean_res = await _run(golden["ecommerce"], stop_after="clean", output_dir=str(clean_out))
    assert clean_res.status == "ok", clean_res.error
    assert [Path(p).name for p in clean_res.data["files"]] == [
        "golden_ecommerce.clean.csv",
        "golden_ecommerce.cleaning.json",
    ]
    assert not list(clean_out.glob("*.pbip.zip"))

    story_out = tmp_path / "story"
    story_res = await _run(golden["ecommerce"], stop_after="story", output_dir=str(story_out))
    assert story_res.status == "ok", story_res.error
    written = [Path(p).name for p in story_res.data["files"]]
    assert written == [
        "golden_ecommerce.clean.csv",
        "golden_ecommerce.cleaning.json",
        "golden_ecommerce.pbip.zip",
    ]
    assert (story_out / "golden_ecommerce.pbip.zip").is_file()


async def test_pbip_zip_structure_and_valid_json_schemas(
    golden: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = await _run(golden["ecommerce"], stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error

    stem = "golden_ecommerce"
    zip_path = out / f"{stem}.pbip.zip"
    expected_entries = {
        f"{stem}.clean.csv",
        f"{stem}.pbip",
        f"{stem}.SemanticModel/definition.pbism",
        f"{stem}.SemanticModel/model.bim",
        f"{stem}.Report/definition.pbir",
        f"{stem}.Report/report.json",
        "README.txt",
    }

    with ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert set(names) == expected_entries
        assert len(names) == 7
        for entry in names:
            assert not entry.startswith(("/", "\\"))
            assert "\\" not in entry and ":" not in entry
            assert ".." not in entry and ".." not in PurePosixPath(entry).parts

        zipped = zf.read(f"{stem}.clean.csv").decode("utf-8-sig").splitlines()
        on_disk = (out / f"{stem}.clean.csv").read_text(encoding="utf-8-sig").splitlines()
        assert zipped == on_disk

        readme_text = zf.read("README.txt").decode("utf-8")
        pbip_doc = json.loads(zf.read(f"{stem}.pbip"))
        pbism_doc = json.loads(zf.read(f"{stem}.SemanticModel/definition.pbism"))
        model_bim = json.loads(zf.read(f"{stem}.SemanticModel/model.bim"))
        pbir_doc = json.loads(zf.read(f"{stem}.Report/definition.pbir"))
        report_json = json.loads(zf.read(f"{stem}.Report/report.json"))

    assert "DataFolder" in readme_text
    assert "Edit parameters" in readme_text
    assert f"{stem}.pbip" in readme_text

    assert pbip_doc["version"] == "1.0"
    assert pbip_doc["artifacts"] == [{"report": {"path": f"{stem}.Report"}}]
    assert pbism_doc["version"] == "1.0"
    assert pbir_doc["version"] == "1.0"
    assert pbir_doc["datasetReference"]["byPath"] == {"path": f"../{stem}.SemanticModel"}

    assert model_bim["compatibilityLevel"] == 1550
    expressions = model_bim["model"].get("expressions", [])
    param = next((e for e in expressions if e["name"] == "DataFolder"), None)
    assert param is not None
    assert param["kind"] == "m"
    param_expr = "\n".join(param["expression"])
    assert "IsParameterQuery=true" in param_expr
    assert 'Type="Text"' in param_expr
    assert "IsParameterQueryRequired=true" in param_expr

    table = model_bim["model"]["tables"][0]
    col_types = {c["name"]: c["dataType"] for c in table["columns"]}
    assert col_types == {
        "order_id": "string",
        "order_date": "dateTime",
        "customer_id": "string",
        "category": "string",
        "region": "string",
        "sales": "double",
        "quantity": "int64",
        "profit": "double",
    }
    m_expr = "\n".join(table["partitions"][0]["source"]["expression"])
    assert table["partitions"][0]["mode"] == "import"
    assert table["partitions"][0]["source"]["type"] == "m"
    assert 'File.Contents(Text.TrimEnd(DataFolder, {"\\", "/"}) & "\\" & ' in m_expr
    assert f'"{stem}.clean.csv"' in m_expr
    assert f'File.Contents("{stem}.clean.csv")' not in m_expr
    assert "Encoding=65001" in m_expr
    assert len(table["measures"]) >= 5

    measure_names = {m["name"] for m in table["measures"]}
    col_names = set(col_types)
    assert measure_names.isdisjoint(col_names)

    assert json.loads(report_json["config"])["version"]
    story_pages = result.data["story"]["pages"]
    assert len(report_json["sections"]) == len(story_pages)
    visual_types: set[str] = set()
    for section, page in zip(report_json["sections"], story_pages, strict=True):
        assert section["displayName"] == page["title"][:80]
        assert section["visualContainers"]
        for container in section["visualContainers"]:
            cfg = json.loads(container["config"])
            sv = cfg["singleVisual"]
            visual_types.add(sv["visualType"])
            for sel in sv.get("prototypeQuery", {}).get("Select", []):
                if "Column" in sel:
                    assert sel["Column"]["Property"] in col_names
                if "Measure" in sel:
                    assert sel["Measure"]["Property"] in measure_names
    assert {"textbox", "card", "lineChart", "clusteredBarChart"} <= visual_types


async def test_pbip_excludes_dropped_empty_and_pii_columns(tmp_path: Path) -> None:
    rows = ["customer_name,email,phone,empty_col,region,order_id,sales,order_date"]
    for i in range(120):
        rows.append(
            f"Person {chr(65 + i % 26)}{chr(97 + i % 7)} Smith,p{i}@secret.example,"
            f"+1-555-01{i % 90 + 10:02d},,{['North', 'South', 'East'][i % 3]},"
            f"ORD-{i:04d},{100 + (i * 29) % 500},2024-{1 + i % 6:02d}-{1 + i % 27:02d}"
        )
    dataset = tmp_path / "orders_pii.csv"
    dataset.write_text("\n".join(rows) + "\n", encoding="utf-8")

    out = tmp_path / "out"
    result = await _run(dataset, stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error

    # Full cleaned CSV in output_dir keeps personal columns per existing contract.
    disk_csv = (out / "orders_pii.clean.csv").read_text(encoding="utf-8-sig")
    disk_header = pd.read_csv(io.StringIO(disk_csv)).columns.tolist()
    assert {"customer_name", "email", "phone"} <= set(disk_header)

    with ZipFile(out / "orders_pii.pbip.zip") as zf:
        bim_text = zf.read("orders_pii.SemanticModel/model.bim").decode("utf-8")
        report_text = zf.read("orders_pii.Report/report.json").decode("utf-8")
        csv_text = zf.read("orders_pii.clean.csv").decode("utf-8-sig")
        readme_text = zf.read("README.txt").decode("utf-8")

    model_bim = json.loads(bim_text)
    cols = [c["name"] for c in model_bim["model"]["tables"][0]["columns"]]
    assert cols == ["region", "order_id", "sales", "order_date"]

    for forbidden in (
        "customer_name",
        "email",
        "phone",
        "empty_col",
        "secret.example",
        "Person ",
        "555-01",
    ):
        assert forbidden not in csv_text
        assert forbidden not in bim_text
        assert forbidden not in report_text
        assert forbidden not in readme_text

    zip_df = pd.read_csv(io.StringIO(csv_text))
    assert zip_df.columns.tolist() == ["region", "order_id", "sales", "order_date"]
    assert len(zip_df) == 120


@pytest.mark.parametrize("name", ["ecommerce", "saas", "logistics"])
async def test_pbip_ds6_pregate_reconciles_five_or_more_kpis(
    golden: dict[str, Path], tmp_path: Path, name: str
) -> None:
    out = tmp_path / name
    result = await _run(golden[name], stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error

    stem = f"golden_{name}"
    with ZipFile(out / f"{stem}.pbip.zip") as zf:
        csv_bytes = zf.read(f"{stem}.clean.csv")
        model_bim = json.loads(zf.read(f"{stem}.SemanticModel/model.bim"))

    df = pd.read_csv(io.BytesIO(csv_bytes))
    measures = {m["name"]: m["expression"] for m in model_bim["model"]["tables"][0]["measures"]}
    facts_by_title = {f["title"]: f for f in result.data["facts"]["facts"]}

    reconciled = 0
    for title, dax_expr in measures.items():
        _assert_valid_calculate_predicates(dax_expr)
        fact = facts_by_title.get(title)
        if fact is None:
            continue
        direct_val = _eval_dax_measure(df, dax_expr)
        expected_val = float(fact["value"])
        assert (
            abs(direct_val - expected_val) <= 1e-4 * max(abs(direct_val), abs(expected_val)) + 1e-9
        ), f"{name} / {title}: DAX={direct_val} vs fact={expected_val}\n{dax_expr}"
        reconciled += 1

    assert reconciled >= 5, f"Expected >= 5 reconciled KPIs for {name}, got {reconciled}"


def test_pbip_calculate_predicates_single_column_all_fact_kinds() -> None:
    data = DataStorytellerOutput.model_validate(
        {
            "source": {
                "file": "sales.csv",
                "format": "csv",
                "tables": [],
                "table": "sales",
                "header_row": 1,
            },
            "cleaning": {
                "rows_in": 4,
                "rows_out": 4,
                "columns_in": 3,
                "columns_out": 3,
                "steps": [],
                "check": [],
            },
            "columns": [
                {
                    "name": "order_date",
                    "source_name": "order_date",
                    "type": "date",
                    "role": "time",
                    "aggregation": "none",
                    "reason": "dates",
                    "count": 4,
                    "missing": 0,
                    "distinct": 4,
                },
                {
                    "name": "region",
                    "source_name": "region",
                    "type": "text",
                    "role": "category",
                    "aggregation": "count_distinct",
                    "reason": "labels",
                    "count": 4,
                    "missing": 0,
                    "distinct": 2,
                },
                {
                    "name": "sales",
                    "source_name": "sales",
                    "type": "number",
                    "role": "measure",
                    "aggregation": "sum",
                    "reason": "sum",
                    "count": 4,
                    "missing": 0,
                    "distinct": 4,
                },
            ],
            "setup": StorySetup(
                north_star="sales",
                grain="one order per row",
                primary_date="order_date",
                aggregations={"sales": "sum"},
            ).model_dump(),
            "facts": FactsReport(
                facts=[
                    Fact(
                        id="F001",
                        kind="member_change",
                        title="North sales change",
                        statement="North sales rose 50%.",
                        metric="sales",
                        dimension="region",
                        member="North",
                        period="2024-01 vs 2024-02",
                        value=0.5,
                        format="change",
                        method="sum",
                        n=4,
                        confidence="high",
                        importance=0.9,
                    ),
                    Fact(
                        id="F002",
                        kind="anomaly",
                        title="North spike in 2024-02",
                        statement="North sales spiked in 2024-02.",
                        metric="sales",
                        dimension="region",
                        member="North",
                        period="2024-02",
                        value=300.0,
                        format="number",
                        method="sum",
                        n=2,
                        confidence="high",
                        importance=0.85,
                    ),
                    Fact(
                        id="F003",
                        kind="segment_gap",
                        title="North vs other regions",
                        statement="North is 2x other regions.",
                        metric="sales",
                        dimension="region",
                        member="North",
                        value=2.0,
                        format="ratio",
                        method="ratio",
                        n=4,
                        confidence="high",
                        importance=0.8,
                    ),
                    Fact(
                        id="F004",
                        kind="simpsons",
                        title="Overall sales reversed",
                        statement="Overall changed by 100.",
                        metric="sales",
                        dimension="region",
                        period="2024-01 vs 2024-02",
                        value=100.0,
                        format="number",
                        method="diff",
                        n=4,
                        confidence="high",
                        importance=0.75,
                    ),
                ]
            ).model_dump(),
        }
    )
    csv_bytes = (
        b"order_date,region,sales\n"
        b"2024-01-10,North,100\n"
        b"2024-02-10,North,150\n"
        b"2024-01-15,South,50\n"
        b"2024-02-15,South,75\n"
    )
    files = pbip.build_pbip_files("sales", data, csv_bytes)
    model_bim = json.loads(files["sales.SemanticModel/model.bim"])
    measures = {m["name"]: m["expression"] for m in model_bim["model"]["tables"][0]["measures"]}
    assert set(measures) == {
        "North sales change",
        "North spike in 2024-02",
        "North vs other regions",
        "Overall sales reversed",
    }

    for expr in measures.values():
        _assert_valid_calculate_predicates(expr)

    # Confirm separate comma-separated filter arguments for member_change and dimensioned anomaly.
    member_calls = _find_calculate_calls(measures["North sales change"])
    assert len(member_calls) == 2
    assert all(len(args) == 3 for args in member_calls)

    anomaly_calls = _find_calculate_calls(measures["North spike in 2024-02"])
    assert len(anomaly_calls) == 1
    assert len(anomaly_calls[0]) == 3

    # Confirm segment_gap uses FILTER(VALUES(...), ...) for the non-blank exclusion filter.
    gap_calls = _find_calculate_calls(measures["North vs other regions"])
    assert len(gap_calls) == 2
    assert gap_calls[1][1].startswith("FILTER(VALUES(")


@pytest.mark.parametrize("name", ["ecommerce", "saas"])
async def test_pbip_dumbbell_visuals_bind_two_period_measures_or_fallback(
    golden: dict[str, Path], tmp_path: Path, name: str
) -> None:
    out = tmp_path / name
    result = await _run(golden[name], stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error

    stem = f"golden_{name}"
    with ZipFile(out / f"{stem}.pbip.zip") as zf:
        model_bim = json.loads(zf.read(f"{stem}.SemanticModel/model.bim"))
        report_json = json.loads(zf.read(f"{stem}.Report/report.json"))

    measures = {m["name"]: m["expression"] for m in model_bim["model"]["tables"][0]["measures"]}
    dumbbells_seen = 0
    for section, page in zip(report_json["sections"], result.data["story"]["pages"], strict=True):
        charts = page["charts"][:3]
        chart_containers = section["visualContainers"][-len(charts) :] if charts else []
        for chart, container in zip(charts, chart_containers, strict=True):
            if chart["kind"] != "dumbbell":
                continue
            dumbbells_seen += 1
            sv = json.loads(container["config"])["singleVisual"]
            assert sv["visualType"] in ("clusteredColumnChart", "textbox")
            if sv["visualType"] == "clusteredColumnChart":
                y_proj = sv["projections"]["Y"]
                assert len(y_proj) == 2
                y_measures = [
                    sel["Measure"]["Property"]
                    for sel in sv["prototypeQuery"]["Select"]
                    if "Measure" in sel
                ]
                assert len(y_measures) == 2
                assert len(set(y_measures)) == 2
                for m_name in y_measures:
                    assert m_name in measures
                    _assert_valid_calculate_predicates(measures[m_name])

    assert dumbbells_seen >= 1


def test_pbip_dumbbell_without_periods_falls_back_to_textbox() -> None:
    data = DataStorytellerOutput.model_validate(
        {
            "source": {
                "file": "sales.csv",
                "format": "csv",
                "tables": [],
                "table": "sales",
                "header_row": 1,
            },
            "cleaning": {
                "rows_in": 2,
                "rows_out": 2,
                "columns_in": 2,
                "columns_out": 2,
                "steps": [],
                "check": [],
            },
            "columns": [
                {
                    "name": "region",
                    "source_name": "region",
                    "type": "text",
                    "role": "category",
                    "aggregation": "count_distinct",
                    "reason": "labels",
                    "count": 2,
                    "missing": 0,
                    "distinct": 2,
                },
                {
                    "name": "sales",
                    "source_name": "sales",
                    "type": "number",
                    "role": "measure",
                    "aggregation": "sum",
                    "reason": "sum",
                    "count": 2,
                    "missing": 0,
                    "distinct": 2,
                },
            ],
            "facts": FactsReport(
                facts=[
                    Fact(
                        id="F001",
                        kind="member_change",
                        title="North sales change",
                        statement="North rose from 10 to 20.",
                        metric="sales",
                        dimension="region",
                        member="North",
                        period=None,
                        value=1.0,
                        format="change",
                        method="sum",
                        n=2,
                        confidence="high",
                        importance=0.9,
                    )
                ]
            ).model_dump(),
            "story": Story(
                title="Sales moved",
                shape="composition",
                written_by="template",
                pages=[
                    StoryPage(
                        id="drivers",
                        role="drivers",
                        title="North rose",
                        headline=StorySentence(text="North rose.", fact_ids=["F001"]),
                        charts=[
                            Chart(
                                kind="dumbbell",
                                title="Sales by region",
                                fact_id="F001",
                                format="number",
                                points=[ChartPoint(label="North", before=10.0, value=20.0)],
                            )
                        ],
                        fact_ids=["F001"],
                    )
                ],
            ).model_dump(),
        }
    )
    files = pbip.build_pbip_files("sales", data, b"region,sales\nNorth,10\nSouth,20\n")
    report_json = json.loads(files["sales.Report/report.json"])
    chart_visual = json.loads(report_json["sections"][0]["visualContainers"][-1]["config"])[
        "singleVisual"
    ]
    assert chart_visual["visualType"] == "textbox"
    text = " ".join(
        run["value"]
        for para in chart_visual["objects"]["general"][0]["properties"]["paragraphs"]
        for run in para["textRuns"]
    )
    assert "10 -> 20" in text


def test_pbip_path_traversal_safety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = DataStorytellerOutput.model_validate(
        {
            "source": {
                "file": "sales.csv",
                "format": "csv",
                "tables": [],
                "table": "sales",
                "header_row": 1,
            },
            "cleaning": {
                "rows_in": 2,
                "rows_out": 2,
                "columns_in": 2,
                "columns_out": 2,
                "steps": [],
                "check": [],
            },
            "columns": [
                {
                    "name": "region",
                    "source_name": "region",
                    "type": "text",
                    "role": "category",
                    "aggregation": "count_distinct",
                    "reason": "labels",
                    "count": 2,
                    "missing": 0,
                    "distinct": 2,
                },
                {
                    "name": "sales",
                    "source_name": "sales",
                    "type": "number",
                    "role": "measure",
                    "aggregation": "sum",
                    "reason": "sum",
                    "count": 2,
                    "missing": 0,
                    "distinct": 2,
                },
            ],
        }
    )
    csv_path = tmp_path / "sales.clean.csv"
    csv_path.write_bytes(b"region,sales\nNorth,10\nSouth,20\n")
    out = tmp_path / "out"

    for bad_stem in ("../../evil", "/abs/path", "sales._.._.._escaped", "NUL"):
        zip_path = pbip.write_pbip_zip(out, bad_stem, data, csv_path)
        assert zip_path.resolve().parent == out.resolve()
        with ZipFile(zip_path) as zf:
            for entry in zf.namelist():
                assert not entry.startswith(("/", "\\"))
                assert ".." not in entry and ".." not in PurePosixPath(entry).parts
                assert ":" not in entry and "\\" not in entry

    monkeypatch.setattr(pbip, "safe_stem", lambda _s: "../escape")
    with pytest.raises(ValueError, match="Refusing to write"):
        pbip.write_pbip_zip(out, "../escape", data, csv_path)


async def test_pbip_handles_formula_quoted_column_headers(tmp_path: Path) -> None:
    rows = ["region,=SUM(1),order_date"]
    for i in range(40):
        rows.append(f"{['North', 'South'][i % 2]},{10 + i},2024-{1 + i % 4:02d}-{1 + i % 27:02d}")
    dataset = tmp_path / "formula.csv"
    dataset.write_text("\n".join(rows) + "\n", encoding="utf-8")

    out = tmp_path / "out"
    result = await _run(dataset, stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error

    with ZipFile(out / "formula.pbip.zip") as zf:
        model_bim = json.loads(zf.read("formula.SemanticModel/model.bim"))
    table = model_bim["model"]["tables"][0]
    assert [c["name"] for c in table["columns"]] == ["region", "=SUM(1)", "order_date"]
    m_expr = "\n".join(table["partitions"][0]["source"]["expression"])
    assert "'=SUM(1)" in m_expr
    assert "Table.RenameColumns" in m_expr


def test_importing_pbip_does_not_load_data_libraries() -> None:
    code = (
        "import sys, data_storyteller.pbip\n"
        "print(sorted({'pandas', 'scipy', 'duckdb'} & set(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_pbip_member_literals_match_the_column_type() -> None:
    types = {"store": "int64", "price": "double", "region": "string", "day": "date"}
    assert pbip._dax_member_filter("Data", "store", "3.0", types) == "'Data'[store] = 3"
    assert pbip._dax_member("Data", "price", "2.5", types) == "2.5"
    assert pbip._dax_member("Data", "region", 'N"orth', types) == '"N""orth"'
    assert pbip._dax_member("Data", "store", "n/a", types) is None
    assert pbip._dax_member("Data", "store", "inf", types) is None
    assert pbip._dax_member("Data", "day", "2024-01-01", types) is None


async def test_pbip_reads_the_csv_with_a_fixed_culture(
    golden: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = await _run(golden["ecommerce"], stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error
    with ZipFile(out / "golden_ecommerce.pbip.zip") as zf:
        model = json.loads(zf.read("golden_ecommerce.SemanticModel/model.bim"))
    m_code = "\n".join(model["model"]["tables"][0]["partitions"][0]["source"]["expression"])
    assert re.search(r'Table\.TransformColumnTypes\(.*, "en-US"\)', m_code)


def test_pbip_numeric_group_columns_get_number_literals() -> None:
    setup = StorySetup(
        north_star="sales",
        grain="one order per row",
        primary_date="order_date",
        aggregations={"sales": "sum"},
    )
    data = SimpleNamespace(setup=setup)
    profiles = {
        name: ColumnProfile.model_validate(
            {
                "name": name,
                "source_name": name,
                "type": kind,
                "role": role,
                "aggregation": agg,
                "reason": "test",
                "count": 4,
                "missing": 0,
                "distinct": 3,
            }
        )
        for name, kind, role, agg in [
            ("order_date", "date", "time", "none"),
            ("store", "number", "category", "none"),
            ("sales", "number", "measure", "sum"),
        ]
    }
    types = {"order_date": "date", "store": "int64", "sales": "double"}
    common = {
        "title": "t",
        "statement": "s",
        "method": "m",
        "metric": "sales",
        "dimension": "store",
        "member": "3.0",
        "n": 40,
        "confidence": "high",
        "importance": 0.5,
    }
    facts = [
        Fact.model_validate({**common, **extra})
        for extra in [
            {"id": "F1", "kind": "breakdown", "value": 0.4, "format": "percent"},
            {"id": "F2", "kind": "segment_gap", "value": 1.5, "format": "ratio"},
            {"id": "F3", "kind": "member_change", "value": 0.2, "format": "change",
             "period": "2024-01 vs 2024-02"},
            {"id": "F4", "kind": "anomaly", "value": 9.0, "format": "number",
             "period": "2024-02"},
        ]
    ]  # fmt: skip
    for fact in facts:
        expr = pbip._fact_dax(fact, "Data", data, profiles, types)  # type: ignore[arg-type]
        assert expr is not None, fact.kind
        assert "'Data'[store] = 3" in expr or "'Data'[store] <> 3" in expr, expr
        assert '"3' not in expr, expr


async def test_pbip_failure_keeps_the_clean_table_and_warns(
    golden: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(pbip, "write_pbip_zip", broken)
    out = tmp_path / "out"
    result = await _run(golden["ecommerce"], stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error
    assert [Path(p).name for p in result.data["files"]] == [
        "golden_ecommerce.clean.csv",
        "golden_ecommerce.cleaning.json",
    ]
    assert any("Power BI project could not be written" in w for w in result.warnings)
    assert not list(out.glob("*.pbip.zip"))


async def test_pbip_story_page_without_charts(tmp_path: Path) -> None:
    # This table's story has a page with no chart; the export used to crash on it.
    rows = ["store,month,sales"]
    for month in range(1, 13):
        for store in (1, 2, 3):
            sales = 100 + month * (5 if store == 1 else 1) + store
            rows.extend(f"{store},2024-{month:02d}-{day:02d},{sales}" for day in (3, 17))
    dataset = tmp_path / "stores.csv"
    dataset.write_text("\n".join(rows) + "\n", encoding="utf-8")

    out = tmp_path / "out"
    result = await _run(dataset, stop_after="story", output_dir=str(out))
    assert result.status == "ok", result.error
    assert any(not page["charts"] for page in result.data["story"]["pages"])
    assert not any("Power BI" in w for w in result.warnings)
    with ZipFile(out / "stores.pbip.zip") as zf:
        report = json.loads(zf.read("stores.Report/report.json"))
    assert len(report["sections"]) == len(result.data["story"]["pages"])
