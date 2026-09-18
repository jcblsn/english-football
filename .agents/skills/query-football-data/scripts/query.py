#!/usr/bin/env python3
"""Run bounded queries against the repository analysis schema."""

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

from epl_forecast.analysis import (
    ALL_MODEL_VERSIONS,
    CURRENT_MODEL_VERSION,
    SESSION_DIRECTORY,
    normalize_hindcast_versions,
    open_analysis_session,
)
from epl_forecast.storage import load_environment

DEFAULT_MAX_ROWS = 40
DEFAULT_MAX_CELL_CHARS = 400
DEFAULT_MAX_OUTPUT_CHARS = 16_000
DEFAULT_FLOAT_DIGITS = 6
OBJECT_NAME = re.compile(r"^[a-z0-9_]+$")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    action = result.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--catalog",
        nargs="?",
        const="",
        metavar="SEARCH",
        help="List analysis objects whose metadata contains the optional text.",
    )
    action.add_argument(
        "--describe",
        nargs="+",
        metavar="OBJECT",
        help="Describe one or more analysis objects.",
    )
    action.add_argument("--sql", help="Run one SQL query.")
    action.add_argument(
        "--sql-file", metavar="FILE", help="Run SQL from a file, or use - for stdin."
    )
    action.add_argument(
        "--query",
        nargs=2,
        action="append",
        metavar=("NAME", "SQL"),
        help="Run a named SQL query. Repeat the option to run several queries in one session.",
    )
    result.add_argument("--cutoff", type=datetime.fromisoformat)
    result.add_argument(
        "--hindcast-versions",
        default=CURRENT_MODEL_VERSION,
        metavar="SELECTION",
        help="Hindcast model versions to load: current (default), all, or a comma-separated list.",
    )
    result.add_argument("--max-rows", type=positive_int, default=DEFAULT_MAX_ROWS)
    result.add_argument("--max-cell-chars", type=positive_int, default=DEFAULT_MAX_CELL_CHARS)
    result.add_argument("--max-output-chars", type=positive_int, default=DEFAULT_MAX_OUTPUT_CHARS)
    precision = result.add_mutually_exclusive_group()
    precision.add_argument("--float-digits", type=positive_int, default=DEFAULT_FLOAT_DIGITS)
    precision.add_argument("--full-precision", action="store_true")
    result.add_argument("--pretty", action="store_true")
    return result


def hindcast_versions(value: str):
    """`current`, `all`, or explicit model versions, which a session file keeps in its own slot."""
    try:
        return normalize_hindcast_versions(
            value if value in (CURRENT_MODEL_VERSION, ALL_MODEL_VERSIONS) else value.split(",")
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return number


def catalog_query(search: str) -> tuple[str, list[str]]:
    terms = re.findall(r"[a-z0-9_]+", search.casefold())
    if not terms:
        return (
            "SELECT object_name, grain, meaning, source, temporal_semantics, private, caveats "
            "FROM analysis.catalog ORDER BY object_name",
            [],
        )
    text = "lower(concat_ws(' ', object_name, grain, meaning, source, temporal_semantics, caveats))"
    conditions = " AND ".join(f"contains({text}, ?)" for _ in terms)
    return (
        "SELECT object_name, grain, meaning, source, temporal_semantics, private, caveats "
        f"FROM analysis.catalog WHERE {conditions} ORDER BY object_name",
        terms,
    )


def query_for(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.sql is not None:
        return args.sql, []
    if args.sql_file is not None:
        if args.sql_file == "-":
            import sys

            return sys.stdin.read(), []
        return Path(args.sql_file).read_text(encoding="utf-8"), []
    if args.describe is not None:
        invalid = [name for name in args.describe if not OBJECT_NAME.fullmatch(name)]
        if invalid:
            raise ValueError(f"Invalid analysis object name: {invalid[0]}")
        placeholders = ", ".join("?" for _ in args.describe)
        return (
            "SELECT object_name, column_name, data_type, meaning, unit_or_scale, "
            "nullable_reason, source_field FROM analysis.column_catalog "
            f"WHERE object_name IN ({placeholders}) ORDER BY object_name, column_name",
            args.describe,
        )
    return catalog_query(args.catalog)


def queries_for(args: argparse.Namespace) -> list[tuple[str | None, str, list[str]]]:
    if args.query is None:
        sql, parameters = query_for(args)
        return [(None, sql, parameters)]
    names = [name for name, _ in args.query]
    duplicate = next((name for name in names if names.count(name) > 1), None)
    if duplicate is not None:
        raise ValueError(f"Duplicate query name: {duplicate}")
    return [(name, sql, []) for name, sql in args.query]


def rounded_value(value, digits: int | None):
    if digits is None or not isinstance(value, float) or not math.isfinite(value) or value == 0:
        return value
    places = digits - math.floor(math.log10(abs(value))) - 1
    return round(value, places)


def bounded_value(value, max_chars: int, float_digits: int | None) -> tuple[object, bool]:
    value = rounded_value(value, float_digits)
    serialized = json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= max_chars:
        return value, False
    if isinstance(value, str):
        return value[:max_chars] + f"… [{len(value) - max_chars} chars omitted]", True
    return serialized[:max_chars] + f"… [{len(serialized) - max_chars} chars omitted]", True


def execute_bounded(connection, sql: str, parameters: list[str], args) -> dict:
    cursor = connection.execute(sql, parameters)
    columns = [item[0] for item in cursor.description or ()]
    rows = []
    cell_truncations = 0
    output_chars = len(json.dumps(columns, ensure_ascii=False)) + 256
    reasons = set()

    while len(rows) < args.max_rows:
        raw = cursor.fetchone()
        if raw is None:
            break
        row = []
        row_cell_truncations = 0
        for value in raw:
            bounded, truncated = bounded_value(value, args.max_cell_chars, args.float_digits)
            row.append(bounded)
            row_cell_truncations += truncated
        row_chars = len(json.dumps(row, default=str, ensure_ascii=False, separators=(",", ":")))
        if output_chars + row_chars > args.max_output_chars:
            reasons.add("output_chars")
            break
        rows.append(row)
        cell_truncations += row_cell_truncations
        output_chars += row_chars
    else:
        if cursor.fetchone() is not None:
            reasons.add("rows")

    if cell_truncations:
        reasons.add("cells")
    return {
        "columns": columns,
        "rows": rows,
        "returned_rows": len(rows),
        "truncated": bool(reasons),
        "truncation_reasons": sorted(reasons),
        "truncated_cells": cell_truncations,
    }


def main() -> None:
    args = parser().parse_args()
    if args.full_precision:
        args.float_digits = None
    try:
        queries = queries_for(args)
    except ValueError as error:
        parser().error(str(error))
    load_environment()
    session = open_analysis_session(
        args.cutoff,
        session_directory=SESSION_DIRECTORY,
        hindcast_versions=hindcast_versions(args.hindcast_versions),
    )
    try:
        results = []
        for name, sql, parameters in queries:
            result = execute_bounded(session.connection, sql, parameters, args)
            if name is not None:
                result = {"name": name, **result}
            results.append(result)
    finally:
        session.close()
    output = (
        results[0] if len(results) == 1 and results[0].get("name") is None else {"queries": results}
    )
    output["float_digits"] = args.float_digits
    indent = 2 if args.pretty else None
    print(
        json.dumps(
            output,
            default=str,
            ensure_ascii=False,
            separators=None if indent else (",", ":"),
            indent=indent,
        )
    )


if __name__ == "__main__":
    main()
