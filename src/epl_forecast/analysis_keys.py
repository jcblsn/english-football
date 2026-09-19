"""The mutable R2 pointers that select the derived analysis corpus.

These keys are the whole identity of that corpus: every document they reach is immutable, and a
pointer changes whenever the set it selects changes. They live in their own module so that a
warm analysis session can name them without importing the model, publication or artifact code.
"""

from epl_forecast.competitions import COMPETITION_IDS

HINDCAST_INDEX_KEY = "hindcasts/index.json"
MATCH_HINDCAST_INDEX_KEY = "match-hindcasts/index.json"
PUBLICATION_ROOTS = (
    "forecasts/current.json",
    *(f"forecasts/{competition_id}/archive.json" for competition_id in COMPETITION_IDS),
    HINDCAST_INDEX_KEY,
    MATCH_HINDCAST_INDEX_KEY,
    "record.json",
)
CANONICAL_ROOTS = ("state/manifests.json", "state/canonical-snapshot.json")
RESULT_ROOTS = tuple(f"state/results/{competition_id}.json" for competition_id in COMPETITION_IDS)


def publication_identities(publish_store) -> dict:
    """Compact change tokens for the mutable pointers, from one HEAD request for each."""
    return publish_store.identities(PUBLICATION_ROOTS)
