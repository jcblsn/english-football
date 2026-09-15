# Working in this repository

## Writing

Use ASD-STE100 Simplified Technical English for all public facing natural language text in the repo, including documents and comments.

Text in markdown files should not be hard wrapped.

## Branches

- `main` is the product line. It holds only what the four-division M7 product needs: operation, data collection, simulation, verification, publication, prospective scoring, the evidence guide in `evidence/`, tests and current docs. Generated evidence stays in private R2 storage.
- Do model research on the `research` branch or on a temporary branch. The `research-anchor` tag marks the complete history before the product consolidation. See `docs/research.md`.
- Move an improvement to `main` only as one focused pull request, with the evidence that `docs/validation.md` describes. Do not merge the whole `research` branch into `main`.
- Do not add experiment reports, one-off scripts, parameter searches or superseded models to `main`.
- M7 is frozen on `main`. Do not change model statistics in a cleanup or a refactor.

## Verifying

Run `scripts/verify.sh` — it formats, then lints, then tests. Order matters: `ruff check` before `ruff format` aborts on fixable layout findings.

Ruff E501 is disabled, so the formatter owns line length in Python. Do not hand-split string literals to satisfy a line limit.

## Data

- Fetch through `src/epl_forecast/data/capture.py`, never a web-reader tool. Football-Data 503s through readers and on the `www` host.
- Retained Understat payloads are gzip; decompress on the `\x1f\x8b` magic byte. Legacy FPL archives (2016–19) are Latin-1, not UTF-8.
- Team identity comes from `data/teams.csv` verbatim — extend the reviewed registry rather than inventing a slug.
- Preserve raw provider evidence. When a source is internally inconsistent, mark the field unknown and surface it in the audit; do not normalize it away.
