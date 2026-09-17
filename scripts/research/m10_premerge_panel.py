"""Run the season panel of `scripts/evaluate_seasons.py` with one pre-merge candidate.

The candidate is the product M10 specification with the parameters of `m10_variants.py`. The seasons,
origins, seed and paths are those of the panel arguments.

Usage: uv run python scripts/research/m10_premerge_panel.py --candidate S1 -- <evaluate_seasons arguments>
"""

import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate_seasons  # noqa: E402
from m10_variants import CANDIDATES, install  # noqa: E402

from epl_forecast import cli  # noqa: E402
from epl_forecast.datasets import Dataset  # noqa: E402


def main():
    arguments = sys.argv[1:]
    split = arguments.index("--")
    options, rest = arguments[:split], arguments[split + 1 :]
    candidate = options[options.index("--candidate") + 1]
    install()
    load = cli.load_config

    def load_config(path):
        if path != Path("candidate"):
            return load(path)
        config = load(Path("configs/product.toml"))
        spec = next(s for s in config["models"] if s["kind"] == "bayesian_xg_quality_tilt")
        spec["id"] = f"M10-premerge-{candidate}"
        spec["parameters"].update(CANDIDATES[candidate])
        return config

    observations = {}
    make_model = cli.make_model

    def cached_model(spec):
        # Read the xG observations from R2 once per run, not once per origin.
        parameters = dict(spec.get("parameters", {}))
        if parameters.pop("canonical_xg", False):
            if not observations:
                data = Dataset()
                try:
                    observations["rows"] = data.xg_observations()
                finally:
                    data.close()
            parameters["observations"] = observations["rows"]
        return make_model({**spec, "parameters": parameters})

    cli.make_model = cached_model
    evaluate_seasons.load_config = load_config
    evaluate_seasons.SPECS["M10"] = ("candidate", f"M10-premerge-{candidate}")
    sys.argv = [evaluate_seasons.__file__, *rest]
    evaluate_seasons.main()


if __name__ == "__main__":
    main()
