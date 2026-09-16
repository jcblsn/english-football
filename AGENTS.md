# Working in this repository

## Writing

Use ASD-STE100 Simplified Technical English for all public facing natural language text in the repo, including documents and comments.

Text in markdown files should not be hard wrapped.

## Branches

- `main` is the product line. It holds only what the four-division M7 product needs: operation, data collection, simulation, verification, publication, prospective scoring, the evidence guide in `evidence/`, tests and current docs. Generated evidence stays in private R2 storage.
- Do model research on a new `research-<topic>` branch from current `main`, one branch for each workstream. The `research` branch and the `research-anchor` tag are an archive of the history before the product consolidation, not a base for new work. See `docs/research.md`.
- Move an improvement to `main` only as one focused pull request, with the evidence that `docs/validation.md` describes. Do not merge the whole `research` branch into `main`.
- Do not add experiment reports, one-off scripts, parameter searches or superseded models to `main`.
- M7 is frozen on `main`. Do not change model statistics in a cleanup or a refactor.

## Verifying

Run `scripts/verify.sh` — it formats, then lints, then tests. Order matters: `ruff check` before `ruff format` aborts on fixable layout findings.

Ruff E501 is disabled, so the formatter owns line length in Python. Do not hand-split string literals to satisfy a line limit.

## Data

- The API key and the R2 settings are in the ignored `.env` file, and `epl_forecast.storage.load_environment` loads it at the start of every CLI command. The shell environment is normally empty, so an unset `$R2_ACCESS_KEY_ID` does not mean the credential is missing. Read `.env` itself before you conclude that an R2 run cannot go locally. Match the names with a pattern that accepts digits: `R2_ACCOUNT_ID` does not match `^[A-Z_]*=`.
- Fetch through `src/epl_forecast/data/capture.py`, never a web-reader tool. Football-Data 503s through readers and on the `www` host.
- Retained Understat payloads are gzip; decompress on the `\x1f\x8b` magic byte. Legacy FPL archives (2016–19) are Latin-1, not UTF-8.
- Team identity comes from `data/teams.csv` verbatim — extend the reviewed registry rather than inventing a slug.
- The private R2 bucket `page324-data` is the authoritative history. Generate hindcasts, season panels and other historical runs from R2 with an empty or ephemeral `--data` workspace, for example a new directory under `runs/`. Do not use the contents of the repository `data/` directory as input: it can be stale and incomplete. `configs/product.toml` sets the M7 `data_root` to `data`, so a runner must replace it with its workspace.
- Preserve raw provider evidence. When a source is internally inconsistent, mark the field unknown and surface it in the audit; do not normalize it away.
