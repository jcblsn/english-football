"""API-Football team xG coverage for finished regular-season matches in every division."""

import argparse
from pathlib import Path

from epl_forecast.artifacts import execution_provenance
from epl_forecast.cli import save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.storage import load_environment, write_json

QUERY = """
SELECT f.competition_id, f.season_id,
       count(DISTINCT f.match_id) AS finished_matches,
       count(DISTINCT s.match_id) AS matches_with_statistics,
       count(DISTINCT CASE WHEN s.expected_goals IS NOT NULL THEN s.match_id END)
           AS matches_with_team_xg,
       count(*) FILTER (WHERE s.expected_goals IS NOT NULL) AS team_rows_with_xg,
       count(DISTINCT CASE WHEN u.xg IS NOT NULL THEN u.match_id END) AS matches_with_understat_xg,
       min(s.retrieved_at) AS first_retrieved, max(s.retrieved_at) AS last_retrieved,
       string_agg(DISTINCT s.evidence_basis, ',') AS evidence_basis
FROM (
    SELECT * FROM fixtures WHERE stage = 'regular' AND status = 'finished'
    QUALIFY row_number() OVER (PARTITION BY match_id ORDER BY retrieved_at DESC) = 1
) f
LEFT JOIN team_statistics s ON s.match_id = f.match_id
LEFT JOIN team_process u ON u.match_id = f.match_id AND u.team_id = s.team_id
GROUP BY 1, 2
ORDER BY 1, 2
"""


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = Dataset(args.data)
    try:
        rows = data.rows(QUERY)
        provenance = data.provenance()
    finally:
        data.close()
    for row in rows:
        row["team_xg_coverage"] = row["matches_with_team_xg"] / row["finished_matches"]
        # A season counts as covered only when both teams have xG in nearly every match.
        row["fully_covered"] = row["team_rows_with_xg"] >= 1.9 * row["finished_matches"]
    args.output.mkdir(parents=True, exist_ok=True)
    save_rows(args.output / "coverage.csv", rows)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "data_manifest_batches": len(provenance["batches"]),
            "scope": "finished regular-season matches; team xG from API-Football team_statistics",
        },
    )
    for row in rows:
        if row["matches_with_team_xg"]:
            print(
                row["competition_id"],
                row["season_id"],
                f"{row['matches_with_team_xg']}/{row['finished_matches']}",
                row["evidence_basis"],
            )


if __name__ == "__main__":
    main()
