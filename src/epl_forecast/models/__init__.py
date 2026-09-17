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
    if parameters.pop("canonical_xg", False):
        from epl_forecast.datasets import Dataset

        data = Dataset(parameters.pop("data_cutoff", None))
        try:
            parameters["observations"] = data.xg_observations()
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
