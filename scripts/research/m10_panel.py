"""Run the season panel of `scripts/evaluate_seasons.py` with M7 and one M10 dynamics candidate.

The candidate is the product M7 specification with the Quality dynamics of one candidate of
`m10_rolling.py`. Everything else, including the seasons, origins, seed and paths, is the panel.

Usage: uv run python scripts/research/m10_panel.py --candidate r1.00-s0.09 -- <evaluate_seasons arguments>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate_seasons  # noqa: E402
from m10_rolling import CANDIDATES  # noqa: E402

from epl_forecast import cli  # noqa: E402


def main():
    arguments = sys.argv[1:]
    split = arguments.index("--")
    options, rest = arguments[:split], arguments[split + 1 :]
    candidate = options[options.index("--candidate") + 1]
    load = cli.load_config

    def load_config(path):
        if path != Path("m10"):
            return load(path)
        config = load(Path("configs/product.toml"))
        spec = next(s for s in config["models"] if s["kind"] == "bayesian_xg_quality_tilt")
        spec["id"] = "M10-candidate"
        spec["parameters"].update(CANDIDATES[candidate])
        return config

    evaluate_seasons.load_config = load_config
    evaluate_seasons.SPECS["M10"] = ("m10", "M10-candidate")
    sys.argv = [evaluate_seasons.__file__, *rest]
    evaluate_seasons.main()


if __name__ == "__main__":
    main()
