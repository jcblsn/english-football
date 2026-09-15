"""The product model M7 and its benchmark M2 share one fit/predict interface."""

from epl_forecast.models.baselines import AttackDefensePoisson
from epl_forecast.models.xg_quality_tilt import BayesianXGQualityTilt

MODEL_TYPES = {
    "attack_defense_poisson": AttackDefensePoisson,
    "bayesian_xg_quality_tilt": BayesianXGQualityTilt,
}


def make_model(spec: dict):
    try:
        model_type = MODEL_TYPES[spec["kind"]]
    except KeyError as error:
        raise ValueError(f"Unknown model kind: {spec.get('kind')}") from error
    parameters = dict(spec.get("parameters", {}))
    competition = parameters.pop("competition_id", "eng-premier-league")
    data_root = parameters.pop("data_root", None)
    xg_sources = parameters.pop("xg_sources", None)
    if data_root is not None:
        from epl_forecast.datasets import Dataset

        data = Dataset(data_root, parameters.pop("data_cutoff", None))
        try:
            parameters["observations"] = (
                data.process() if xg_sources is None else xg_observations(data, xg_sources)
            )
        finally:
            data.close()
    try:
        model = model_type(**parameters)
    except TypeError as error:
        raise ValueError(f"Invalid parameters for {spec['kind']}: {error}") from error
    for member in getattr(model, "members", [model]):
        if hasattr(member, "primary_competition"):
            member.primary_competition = competition
    return model


def xg_observations(data, sources):
    """Observation rows from each named provider, limited to its listed competitions."""
    rows = []
    for source in sources:
        competitions = source.get("competitions")
        if source["provider"] == "understat":
            rows.extend(
                row
                for row in data.process()
                if competitions is None or row["match_id"].split(":")[0] in competitions
            )
        elif source["provider"] == "api_football":
            rows.extend(data.api_xg_process(competitions))
        else:
            raise ValueError(f"Unknown xG provider: {source['provider']}")
    return rows
