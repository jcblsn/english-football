import importlib.util
from argparse import Namespace
from pathlib import Path

import duckdb


def query_module():
    path = Path(__file__).parents[1] / ".agents/skills/query-football-data/scripts/query.py"
    spec = importlib.util.spec_from_file_location("query_football_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_search_matches_each_token():
    module = query_module()
    sql, parameters = module.catalog_query("Probability stage")

    assert parameters == ["probability", "stage"]
    assert sql.count("contains(") == 2


def test_named_queries_share_one_request():
    module = query_module()
    args = module.parser().parse_args(
        ["--query", "counts", "SELECT 1", "--query", "rates", "SELECT 2"]
    )

    assert module.queries_for(args) == [
        ("counts", "SELECT 1", []),
        ("rates", "SELECT 2", []),
    ]


def test_forecast_ids_select_a_bounded_live_result_scope():
    module = query_module()
    args = module.parser().parse_args(
        ["--sql", "SELECT 1", "--forecast-id", "forecast-1", "--forecast-id", "forecast-2"]
    )

    assert args.forecast_id == ["forecast-1", "forecast-2"]


def test_query_output_rounds_floats_to_significant_digits():
    module = query_module()
    connection = duckdb.connect()
    args = Namespace(max_rows=40, max_cell_chars=400, max_output_chars=16_000, float_digits=6)

    result = module.execute_bounded(connection, "SELECT 12345.678901::DOUBLE AS value", [], args)

    assert result["rows"] == [[12345.7]]
