#!/usr/bin/env python3
"""Run bounded queries against the repository analysis schema."""

import argparse
import json
import re
from datetime import datetime

from epl_forecast.analysis import open_analysis_session
from epl_forecast.storage import load_environment

DEFAULT_MAX_ROWS = 40
DEFAULT_MAX_CELL_CHARS = 400
DEFAULT_MAX_OUTPUT_CHARS = 16_000
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
    result.add_argument("--cutoff", type=datetime.fromisoformat)
    result.add_argument("--max-rows", type=positive_int, default=DEFAULT_MAX_ROWS)
    result.add_argument("--max-cell-chars", type=positive_int, default=DEFAULT_MAX_CELL_CHARS)
    result.add_argument("--max-output-chars", type=positive_int, default=DEFAULT_MAX_OUTPUT_CHARS)
    result.add_argument("--pretty", action="store_true")
    return result


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return number


def query_for(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.sql is not None:
        return args.sql, []
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
    search = args.catalog.casefold()
    return (
        "SELECT object_name, grain, meaning, source, temporal_semantics, private, caveats "
        "FROM analysis.catalog "
        "WHERE ? = '' OR contains(lower(concat_ws(' ', object_name, grain, meaning, "
        "source, temporal_semantics, caveats)), ?) ORDER BY object_name",
        [search, search],
    )


def bounded_value(value, max_chars: int) -> tuple[object, bool]:
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
            bounded, truncated = bounded_value(value, args.max_cell_chars)
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
    try:
        sql, parameters = query_for(args)
    except ValueError as error:
        parser().error(str(error))
    load_environment()
    session = open_analysis_session(args.cutoff)
    try:
        result = execute_bounded(session.connection, sql, parameters, args)
    finally:
        session.close()
    indent = 2 if args.pretty else None
    print(
        json.dumps(
            result,
            default=str,
            ensure_ascii=False,
            separators=None if indent else (",", ":"),
            indent=indent,
        )
    )


if __name__ == "__main__":
    main()
