"""Capture and normalize National League source seasons for the entry-prior experiment."""

import argparse
import json
from pathlib import Path

from epl_forecast.cloud import sync_data
from epl_forecast.data import football_data
from epl_forecast.data.capture import Fetcher, writer_lock
from epl_forecast.data.sources import season_name, source_url
from epl_forecast.storage import R2Store, load_environment

COMPETITION_ID = "eng-national-league"
DIVISION = "EC"


def source_entry(year, record):
    return {
        "season_start": year,
        "season_id": season_name(year),
        "division": DIVISION,
        "competition_id": COMPETITION_ID,
        "sha256": record["source_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--start", type=int, default=2010)
    parser.add_argument("--end", type=int, default=2026)
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    if args.data.resolve() == Path("data").resolve():
        raise ValueError("Use an empty research workspace, not the repository data directory")
    if args.start > args.end:
        raise ValueError("Start must not be after end")
    load_environment()
    store = R2Store.from_environment("R2_DATA_BUCKET")
    with writer_lock(args.data):
        fetcher = Fetcher(args.data, store=store)
        captures = []
        aliases = football_data.team_aliases()
        unknown = set()
        for year in range(args.start, args.end + 1):
            url = source_url(year, DIVISION)
            record, payload = fetcher.get(
                "football_data",
                url,
                historical=year < args.end,
                max_age=86400,
                context={
                    "season_start": year,
                    "season_id": season_name(year),
                    "division": DIVISION,
                    "competition_id": COMPETITION_ID,
                },
            )
            _, rows = football_data.csv_rows(payload)
            unknown.update(
                row[key]
                for _, row in rows
                for key in ("HomeTeam", "AwayTeam")
                if row[key] not in aliases
            )
            captures.append((year, record, payload))
        if unknown:
            print(json.dumps({"unknown_team_aliases": sorted(unknown)}, indent=2))
            raise ValueError("Review and add the unknown team aliases before normalization")
        audits = []
        for year, record, payload in captures:
            _, _, audit = football_data.normalize_rows(payload, source_entry(year, record), aliases)
            football_data.ingest(args.data, record, payload)
            audits.append(
                {
                    key: audit[key]
                    for key in (
                        "season_id",
                        "matches",
                        "teams",
                        "expected_matches",
                        "complete",
                        "date_min",
                        "date_max",
                        "source_sha256",
                    )
                }
            )
        request_paths = sorted((args.data / "requests").glob("*.json"))
        manifest_paths = sorted((args.data / "manifests").glob("*.json"))
        result = {
            "competition_id": COMPETITION_ID,
            "data_authority": "page324-data",
            "seasons": audits,
            "local_requests": len(request_paths),
            "local_manifests": len(manifest_paths),
        }
        if args.sync:
            result["sync"] = sync_data(
                args.data,
                store,
                manifest_paths=manifest_paths,
                request_paths=request_paths,
            )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
