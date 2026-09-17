"""Tables for the M7–market disagreement memo.

Inputs, all under runs/market-disagreement/:
- rolling/matches.csv and rolling-early/matches.csv from market_disagreement_rolling.py
- evidence/match_xg.json: analysis.team_match_xg for Premier League matches from July 2014,
  exported with the query-football-data helper
- evidence/betbrain_odds.json: the BetBrain average pre-closing odds of 2016/17–2018/19, the
  Football-Data average before the market_average family starts in 2019/20
- evidence/chronological.csv: research/evidence/personnel-measurement/68cba95/pm-hindcast-report
"""

import json

import numpy as np
import pandas as pd
from market_disagreement_common import (
    HISTORY,
    OUTCOME_INDEX,
    ROOT,
    TABLES,
    club_design,
    derive,
    ridge,
    team_rows,
)
from scipy.optimize import minimize, minimize_scalar

RUNS = ROOT / "runs/market-disagreement"
PENALTY = 2.0
RNG = np.random.default_rng(20260917)


def season_design(g, keys):
    index = {k: i for i, k in enumerate(keys)}
    x = np.zeros((len(g), len(keys)))
    for row, (s, a, b) in enumerate(zip(g.season_id, g.home_team_id, g.away_team_id, strict=True)):
        x[row, index[s, a]] += 1
        x[row, index[s, b]] -= 1
    return x


def block_interval(g, column, samples=2000):
    blocks = (
        g.season_id + ":" + ((g.match_date - pd.Timestamp("2000-07-01")).dt.days // 28).astype(str)
    )
    sums = g.groupby(blocks)[column].sum().to_numpy()
    counts = g.groupby(blocks)[column].size().to_numpy()
    draws = RNG.integers(0, len(sums), size=(samples, len(sums)))
    values = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return np.quantile(values, [0.025, 0.975])


def load_all():
    frames = [
        pd.read_csv(RUNS / f"{name}/matches.csv", parse_dates=["match_date"])
        for name in ("rolling-early", "rolling")
    ]
    d = pd.concat(frames, ignore_index=True)
    odds = json.loads((RUNS / "evidence/betbrain_odds.json").read_text())
    odds = pd.DataFrame(odds["rows"], columns=odds["columns"]).set_index("match_id")
    implied = 1 / odds[["home_odds", "draw_odds", "away_odds"]]
    fallback = implied.div(implied.sum(axis=1), axis=0).reindex(d.match_id)
    missing = d.mkt_p_home.isna().to_numpy() & fallback.home_odds.notna().to_numpy()
    for column, side in (("home_odds", "home"), ("draw_odds", "draw"), ("away_odds", "away")):
        d.loc[missing, f"mkt_p_{side}"] = fallback[column].to_numpy()[missing]
    d["market_family"] = np.where(
        missing, "betbrain_average_preclosing", "market_average_preclosing"
    )
    d = derive(d[d.mkt_p_home.notna()].reset_index(drop=True))
    t_quality = team_rows(d)
    t_quality["long_quality"] = t_quality.groupby("team_id").quality.transform(
        lambda s: s.shift(1).rolling(114, min_periods=38).mean()
    )
    long_quality = t_quality.set_index(["match_id", "team_id"]).long_quality
    xg = json.loads((RUNS / "evidence/match_xg.json").read_text())
    x = pd.DataFrame(xg["rows"], columns=xg["columns"])
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        rows.append(
            pd.DataFrame(
                {
                    "match_id": x.match_id,
                    "match_date": pd.to_datetime(x.match_date),
                    "team_id": x[f"{side}_team_id"],
                    "attack": x[f"{side}_goals"] - x[f"{side}_xg"],
                    "defense": x[f"{other}_xg"] - x[f"{other}_goals"],
                }
            )
        )
    t = pd.concat(rows).sort_values(["team_id", "match_date"])
    t["finishing"] = t.attack + t.defense
    for column in ("finishing", "attack", "defense"):
        t[f"{column}_trail"] = t.groupby("team_id")[column].transform(
            lambda s: s.shift(1).rolling(38, min_periods=10).mean()
        )
        t[f"{column}_next"] = t.groupby("team_id")[column].transform(
            lambda s: s[::-1].shift(1).rolling(38, min_periods=19).mean()[::-1]
        )
    trail = t.set_index(["match_id", "team_id"])
    for side in ("home", "away"):
        key = pd.MultiIndex.from_arrays([d.match_id, d[f"{side}_team_id"]])
        d[f"{side}_finishing"] = trail.finishing_trail.reindex(key).to_numpy()
        d[f"{side}_long_quality"] = long_quality.reindex(key).to_numpy()
    d["finishing_gap"] = d.home_finishing - d.away_finishing
    d["long_quality_gap"] = d.home_long_quality.fillna(d.home_quality) - d.away_long_quality.fillna(
        d.away_quality
    )
    d["quality_deviation_gap"] = d.quality_gap - d.long_quality_gap
    d["entrant_gap"] = d.home_state_source.str.contains("entry").astype(float) - d[
        "away_state_source"
    ].str.contains("entry").astype(float)
    d["entrant"] = d.entrant_gap != 0
    return d, t


def slopes(d):
    rows = []
    for source in ("m7", "ce", "m2", "close"):
        for season, g in [
            *d.groupby("season_id"),
            ("all 2016-2026", d[d.season_id < "2026"]),
            ("2019-2026 average family", d[(d.season_id >= "2019") & (d.season_id < "2026")]),
            (
                "2023-2026",
                d[d.season_id.isin(HISTORY)],
            ),
        ]:
            if source == "close":
                g = g[g.close_dir.notna()]
                if g.empty:
                    continue
            x = g[f"{source}_dir"] if source != "close" else g.m7_dir
            y = g.mkt_dir if source != "close" else g.close_dir
            b = np.polyfit(x, y, 1)
            reverse = np.polyfit(y, x, 1)[0]
            rows.append(
                {
                    "comparison": "market on " + source if source != "close" else "closing on m7",
                    "season": season,
                    "matches": len(g),
                    "slope": b[0],
                    "intercept": b[1],
                    "inverse_reverse_slope": 1 / reverse,
                    "sd_ratio": y.std() / x.std(),
                }
            )
    return pd.DataFrame(rows)


def stretch(p, beta):
    ratio = (p[:, 0] / p[:, 2]) ** beta
    rest = 1 - p[:, 1]
    return np.column_stack([rest * ratio / (1 + ratio), p[:, 1], rest / (1 + ratio)])


def loss(p, y):
    return -np.log(p[np.arange(len(y)), y]).mean()


def probabilities(g, source):
    return g[[f"{source}_p_home", f"{source}_p_draw", f"{source}_p_away"]].to_numpy()


def outcome_stretch(d):
    rows = []
    for source in ("m7", "ce", "m2", "mkt"):
        for season, g in [
            *d.groupby("season_id"),
            ("all 2016-2026", d[d.season_id < "2026"]),
            ("2019-2026 average family", d[(d.season_id >= "2019") & (d.season_id < "2026")]),
        ]:
            y = g.outcome.map(OUTCOME_INDEX).to_numpy()
            p = probabilities(g, source)
            fit = minimize_scalar(
                lambda b, p=p, y=y: loss(stretch(p, b), y), bounds=(0.5, 2.5), method="bounded"
            )
            rows.append(
                {
                    "source": source,
                    "season": season,
                    "matches": len(g),
                    "optimal_stretch": fit.x,
                    "in_sample_gain": loss(p, y) - fit.fun,
                }
            )
    return pd.DataFrame(rows)


def decomposition(d):
    rows = []
    for label, g in (
        ("2023-2026", d[d.season_id.isin(HISTORY)]),
        ("2016-2026", d[d.season_id < "2026"]),
    ):
        g = g.reset_index(drop=True)
        clubs = sorted(set(g.home_team_id) | set(g.away_team_id))
        c = club_design(g, clubs)
        cs = season_design(g, sorted(set(zip(g.season_id, g.home_team_id, strict=True))))
        one = np.ones(len(g))
        for residual, strength in (
            ("resid", "m7_dir"),
            ("resid_ce", "ce_dir"),
            ("resid_m2", "m2_dir"),
        ):
            y = g[residual].to_numpy()
            x = g[strength].to_numpy()
            specs = {
                "venue": (one[:, None], [0]),
                "venue + scale": (np.column_stack([one, x]), [0, 1]),
                "venue + clubs": (np.column_stack([one, c]), [0]),
                "venue + scale + clubs": (np.column_stack([one, x, c]), [0, 1]),
                "venue + scale + club-seasons": (np.column_stack([one, x, cs]), [0, 1]),
            }
            for name, (design, free) in specs.items():
                b = ridge(design, y, PENALTY, free)
                r = y - design @ b
                rows.append(
                    {
                        "window": label,
                        "residual": residual,
                        "terms": name,
                        "venue": b[0],
                        "scale": b[1] if "scale" in name else np.nan,
                        "explained_share": 1 - (r**2).mean() / (y**2).mean(),
                        "mean_square_residual": (y**2).mean(),
                    }
                )
    return pd.DataFrame(rows)


def club_season_effects(d, residual="resid"):
    frames = []
    for season, g in d.groupby("season_id"):
        g = g.reset_index(drop=True)
        clubs = sorted(set(g.home_team_id) | set(g.away_team_id))
        b = ridge(
            np.column_stack([np.ones(len(g)), club_design(g, clubs)]),
            g[residual].to_numpy(),
            PENALTY,
            [0],
        )
        effects = b[1:] - b[1:].mean()
        t = team_rows(g)
        quality = t.groupby("team_id").quality.mean()
        entrant = t.groupby("team_id").state_source.agg(lambda s: s.str.contains("entry").any())
        frames.append(
            pd.DataFrame(
                {
                    "season_id": season,
                    "club": clubs,
                    "effect": effects,
                    "quality": quality.reindex(clubs).to_numpy(),
                    "entrant": entrant.reindex(clubs).to_numpy(),
                    "matches": [
                        int((g.home_team_id == c).sum() + (g.away_team_id == c).sum())
                        for c in clubs
                    ],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def strength_structure(effects, d):
    e = effects[effects.season_id < "2026"].copy()
    k = np.polyfit(d.home_quality - d.away_quality, d.m7_dir, 1)[0]
    rows = []
    for label, g in (
        ("all club-seasons", e),
        ("continuing clubs", e[~e.entrant]),
        ("entrants", e[e.entrant]),
    ):
        between = g.groupby("club")[["quality", "effect"]].mean()
        multi = g.groupby("club").season_id.transform("size") > 1
        within_q = (g.quality - g.groupby("club").quality.transform("mean"))[multi]
        within_e = (g.effect - g.groupby("club").effect.transform("mean"))[multi]
        rows.append(
            {
                "sample": label,
                "club_seasons": len(g),
                "pooled_slope": np.polyfit(g.quality, g.effect, 1)[0],
                "between_club_slope": np.polyfit(between.quality, between.effect, 1)[0]
                if len(between) > 2
                else np.nan,
                "between_club_corr": between.corr().iloc[0, 1] if len(between) > 2 else np.nan,
                "within_club_slope": np.polyfit(within_q, within_e, 1)[0]
                if multi.sum() > 2
                else np.nan,
                "within_club_corr": np.corrcoef(within_q, within_e)[0, 1]
                if multi.sum() > 2
                else np.nan,
                "compression_implied_slope_at_1_2": 0.2 * k,
            }
        )
    return pd.DataFrame(rows)


def season_persistence(effects):
    e = effects[effects.season_id < "2026"].copy()
    e["quality_adjusted"] = e.effect - np.polyval(np.polyfit(e.quality, e.effect, 1), e.quality)
    seasons = sorted(e.season_id.unique())
    rows = []
    for column in ("effect", "quality_adjusted"):
        wide = e.pivot(index="club", columns="season_id", values=column)
        for lag in (1, 2, 3):
            a, b = [], []
            for first, second in zip(seasons, seasons[lag:], strict=False):
                pair = wide[[first, second]].dropna()
                a.extend(pair[first])
                b.extend(pair[second])
            a, b = np.array(a), np.array(b)
            rows.append(
                {
                    "effect": column,
                    "season_lag": lag,
                    "pairs": len(a),
                    "corr": np.corrcoef(a, b)[0, 1],
                    "sign_agreement": (np.sign(a) == np.sign(b)).mean(),
                    "carry_slope": np.polyfit(a, b, 1)[0],
                }
            )
    return pd.DataFrame(rows)


def predictive_persistence(d):
    rows = []
    seasons = sorted(d.season_id.unique())
    for residual, strength in (("resid", "m7_dir"), ("resid_m2", "m2_dir")):
        for test in seasons[1:]:
            available = [s for s in seasons if s < test]
            for window in sorted({min(w, len(available)) for w in (1, 2, 3, len(available))}):
                earlier = available[-window:]
                train, target = d[d.season_id.isin(earlier)], d[d.season_id == test]
                clubs = sorted(set(train.home_team_id) | set(train.away_team_id))
                y = target[residual].to_numpy()
                for name, use_scale, use_clubs in (
                    ("venue + scale", True, False),
                    ("venue + clubs", False, True),
                    ("venue + scale + clubs", True, True),
                ):
                    columns, free = [np.ones(len(train))], [0]
                    if use_scale:
                        columns.append(train[strength].to_numpy())
                        free.append(1)
                    if use_clubs:
                        columns.append(club_design(train, clubs))
                    b = ridge(np.column_stack(columns), train[residual].to_numpy(), PENALTY, free)
                    prediction = np.full(len(target), b[0])
                    offset = 1
                    if use_scale:
                        prediction = prediction + b[1] * target[strength].to_numpy()
                        offset = 2
                    if use_clubs:
                        effect = dict(zip(clubs, b[offset:], strict=True))
                        prediction = prediction + np.array(
                            [
                                effect.get(h, 0.0) - effect.get(a, 0.0)
                                for h, a in zip(
                                    target.home_team_id, target.away_team_id, strict=True
                                )
                            ]
                        )
                    rows.append(
                        {
                            "residual": residual,
                            "test_season": test,
                            "training_seasons": len(earlier),
                            "terms": name,
                            "matches": len(target),
                            "explained_share": 1 - ((y - prediction) ** 2).mean() / (y**2).mean(),
                            "corr": np.corrcoef(prediction, y)[0, 1],
                        }
                    )
    return pd.DataFrame(rows)


def club_table(d, t):
    h = d[d.season_id.isin(HISTORY)].reset_index(drop=True)
    clubs = sorted(set(h.home_team_id) | set(h.away_team_id))
    c = club_design(h, clubs)
    out = pd.DataFrame({"club": clubs})
    for residual, strength, label in (
        ("resid", "m7_dir", "market_m7"),
        ("resid_m2", "m2_dir", "market_m2"),
    ):
        b = ridge(
            np.column_stack([np.ones(len(h)), h[strength], c]),
            h[residual].to_numpy(),
            PENALTY,
            [0, 1],
        )
        out[f"adjusted_{label}"] = b[2:] - b[2:].mean()
    out["adjusted_m2_m7"] = out.adjusted_market_m7 - out.adjusted_market_m2
    rows = []
    for side in ("home", "away"):
        rows.append(
            pd.DataFrame(
                {
                    "club": h[f"{side}_team_id"],
                    "market_m7_win_pp": 100 * (h[f"mkt_p_{side}"] - h[f"m7_p_{side}"]),
                    "market_m2_win_pp": 100 * (h[f"mkt_p_{side}"] - h[f"m2_p_{side}"]),
                    "m7_m2_win_pp": 100 * (h[f"m7_p_{side}"] - h[f"m2_p_{side}"]),
                    "information_advantage": h.ia_m7,
                }
            )
        )
    raw = (
        pd.concat(rows)
        .groupby("club")
        .agg(
            matches=("market_m7_win_pp", "size"),
            market_m7_win_pp=("market_m7_win_pp", "mean"),
            market_m2_win_pp=("market_m2_win_pp", "mean"),
            m7_m2_win_pp=("m7_m2_win_pp", "mean"),
            information_advantage=("information_advantage", "mean"),
        )
    )
    seasons_same_sign = []
    for club in clubs:
        signs = []
        for season in HISTORY:
            g = h[h.season_id == season]
            home = 100 * (g.mkt_p_home - g.m7_p_home)[g.home_team_id == club]
            away = 100 * (g.mkt_p_away - g.m7_p_away)[g.away_team_id == club]
            values = pd.concat([home, away])
            if len(values):
                signs.append(np.sign(values.mean()))
        seasons_same_sign.append(f"{int(max(signs.count(1), signs.count(-1)))}/{len(signs)}")
    out["seasons_same_sign"] = seasons_same_sign
    finishing = (
        t[(t.match_date >= "2023-08-01") & (t.match_date < "2026-07-01")]
        .groupby("team_id")[["attack", "defense", "finishing"]]
        .sum()
    )
    out = out.join(raw, on="club").join(finishing, on="club")
    return out.sort_values("adjusted_market_m7")


def finishing_tests(d, t):
    g = d.dropna(subset=["finishing_gap"]).reset_index(drop=True)
    rows = []
    for label, part in (
        ("2016-2026", g[g.season_id < "2026"]),
        ("2023-2026", g[g.season_id.isin(HISTORY)]),
    ):
        for y in ("m2_dir_minus_m7_dir", "resid", "resid_m2"):
            target = part.m2_dir - part.m7_dir if y == "m2_dir_minus_m7_dir" else part[y]
            x = np.column_stack([np.ones(len(part)), part.finishing_gap, part.m7_dir])
            b = np.linalg.lstsq(x, target, rcond=None)[0]
            rows.append(
                {
                    "window": label,
                    "target": y,
                    "matches": len(part),
                    "finishing_gap_coef": b[1],
                    "corr": np.corrcoef(part.finishing_gap, target)[0, 1],
                }
            )
    persistence = []
    for column in ("finishing", "attack", "defense"):
        s = t.dropna(subset=[f"{column}_trail", f"{column}_next"])
        s = s[s.groupby("team_id").cumcount() % 38 == 0]
        persistence.append(
            {
                "component": column,
                "pairs": len(s),
                "trailing_38_vs_next_38_corr": np.corrcoef(
                    s[f"{column}_trail"], s[f"{column}_next"]
                )[0, 1],
                "carry_slope": np.polyfit(s[f"{column}_trail"], s[f"{column}_next"], 1)[0],
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(persistence)


def uncertainty(d):
    h = d[d.season_id.isin(HISTORY)].copy()
    rows = []
    favourite_home = h.m7_p_home > h.m7_p_away
    fav = np.where(favourite_home, h.m7_p_home, h.m7_p_away)
    ce = np.where(favourite_home, h.ce_p_home, h.ce_p_away)
    market = np.where(favourite_home, h.mkt_p_home, h.mkt_p_away)
    for low, high in ((0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 1)):
        m = (fav >= low) & (fav < high)
        rows.append(
            {
                "slice": f"M7 favourite {low:.2f}-{high:.2f}",
                "matches": int(m.sum()),
                "m7_favourite": fav[m].mean(),
                "certainty_equivalent_favourite": ce[m].mean(),
                "market_favourite": market[m].mean(),
                "uncertainty_share_of_gap": (ce[m].mean() - fav[m].mean())
                / (market[m].mean() - fav[m].mean()),
            }
        )
    h["phase"] = pd.cut(
        h.team_match_min, [-1, 0, 4, 9, 19, 40], labels=["0", "1-4", "5-9", "10-19", "20+"]
    )
    for key in ("phase", "entrant"):
        for value, g in h.groupby(key, observed=True):
            rows.append(
                {
                    "slice": f"{key} {value}",
                    "matches": len(g),
                    "mean_abs_uncertainty_dir": (g.ce_dir - g.m7_dir).abs().mean(),
                    "mean_abs_residual_dir": g.resid.abs().mean(),
                    "difference_state_sd": np.sqrt(g.m7_difference_state_var).mean(),
                    "log_loss_ce_minus_m7": (g.ce_ll - g.m7_ll).mean(),
                }
            )
    rows.append(
        {
            "slice": "all 2023-2026",
            "matches": len(h),
            "mean_abs_uncertainty_dir": (h.ce_dir - h.m7_dir).abs().mean(),
            "mean_abs_residual_dir": h.resid.abs().mean(),
            "difference_state_sd": np.sqrt(h.m7_difference_state_var).mean(),
            "log_loss_ce_minus_m7": (h.ce_ll - h.m7_ll).mean(),
            "share_of_mean_square_residual": 1 - (h.resid_ce**2).mean() / (h.resid**2).mean(),
        }
    )
    return pd.DataFrame(rows)


def adaptation(d):
    t = team_rows(d).reset_index(drop=True)
    t["entrant"] = t.state_source.str.contains("entry")
    t["j"] = t.groupby(["team_id", "season_id"]).cumcount()
    rows = []
    for k in (1, 5, 10, 19):
        group = t.groupby(["team_id", "season_id"])
        later = group.quality.shift(-k)
        days = (group.match_date.shift(-k) - t.match_date).dt.days
        change = later - t.quality - t.quality * (0.85 ** (days / 365.25) - 1)
        for label, mask in (
            ("all", change.notna()),
            ("entrants", change.notna() & t.entrant),
            ("continuing", change.notna() & ~t.entrant),
        ):
            y = change[mask].to_numpy()
            x = np.column_stack([np.ones(mask.sum()), t.resid[mask], t.quality[mask]])
            b = np.linalg.lstsq(x, y, rcond=None)[0]
            r = y - x @ b
            se = np.sqrt(np.linalg.inv(x.T @ x)[1, 1] * r.var())
            rows.append(
                {
                    "horizon_matches": k,
                    "clubs": label,
                    "rows": int(mask.sum()),
                    "quality_change_per_residual": b[1],
                    "naive_se": se,
                    "share_of_residual_closed": b[1]
                    * np.polyfit(d.home_quality - d.away_quality, d.m7_dir, 1)[0],
                }
            )
    auto = []
    for lag in (1, 5, 10, 19, 38, 76):
        later = t.groupby("team_id").resid.shift(-lag)
        m = later.notna()
        auto.append(
            {
                "lag_matches": lag,
                "pairs": int(m.sum()),
                "club_residual_autocorr": np.corrcoef(t.resid[m], later[m])[0, 1],
            }
        )
    t["phase"] = pd.cut(t.j, [-1, 0, 4, 9, 19, 38], labels=["0", "1-4", "5-9", "10-19", "20-37"])
    by_phase = (
        t[t.season_id < "2026"]
        .groupby(["entrant", "phase"], observed=True)
        .resid.agg(["mean", "size"])
        .reset_index()
    )
    return pd.DataFrame(rows), pd.DataFrame(auto), by_phase


def scoring(d, personnel, seasons=HISTORY):
    h = d[d.season_id.isin(seasons)].copy()
    pm, p7 = probabilities(h, "mkt"), probabilities(h, "m7")
    h["expected_if_market"] = (pm * np.log(pm / p7)).sum(axis=1)
    h["expected_if_m7"] = -(p7 * np.log(p7 / pm)).sum(axis=1)
    h["size"] = pd.cut(
        h.tv_m7, [0, 0.05, 0.10, 0.15, 1], labels=["<5 pp", "5-10 pp", "10-15 pp", "15+ pp"]
    )
    h["kind"] = np.where(
        np.sign(h.mkt_dir) != np.sign(h.m7_dir),
        "favourite differs",
        np.where(h.mkt_dir.abs() > h.m7_dir.abs(), "market more extreme", "market less extreme"),
    )
    h = h.merge(personnel, on="match_id", how="left")
    rows = []
    total = h.ia_m7.sum()
    for key in ("size", "entrant", "kind", "season_id"):
        for value, g in h.groupby(key, observed=True):
            low, high = block_interval(g, "ia_m7")
            rows.append(
                {
                    "slice": f"{key}: {value}",
                    "matches": len(g),
                    "information_advantage": g.ia_m7.mean(),
                    "ci_low": low,
                    "ci_high": high,
                    "expected_if_market_right": g.expected_if_market.mean(),
                    "expected_if_m7_right": g.expected_if_m7.mean(),
                    "outcome_position": (g.ia_m7.mean() - g.expected_if_m7.mean())
                    / (g.expected_if_market.mean() - g.expected_if_m7.mean()),
                    "share_of_total_advantage": g.ia_m7.sum() / total,
                    "m7_better_share": (g.ia_m7 < 0).mean(),
                }
            )
    ordered = h.sort_values("ia_m7", ascending=False)
    rows.append(
        {
            "slice": "all without the top 5% market-favouring matches",
            "matches": len(h) - int(0.05 * len(h)),
            "information_advantage": ordered.iloc[int(0.05 * len(h)) :].ia_m7.mean(),
        }
    )
    big = h[h.tv_m7 >= 0.10]
    clubs = pd.concat([big.home_team_id, big.away_team_id]).value_counts()
    profile = []
    for label, g in (("10+ pp", big), ("under 10 pp", h[h.tv_m7 < 0.10])):
        profile.append(
            {
                "slice": label,
                "matches": len(g),
                "entrant_share": g.entrant.mean(),
                "market_more_extreme_share": (g.kind == "market more extreme").mean(),
                "favourite_differs_share": (g.kind == "favourite differs").mean(),
                "away_favourite_share": (g.mkt_p_away > g.mkt_p_home).mean(),
                "mean_market_favourite": np.maximum(g.mkt_p_home, g.mkt_p_away).mean(),
                "mean_abs_finishing_gap": g.finishing_gap.abs().mean(),
                "mean_difference_state_sd": np.sqrt(g.m7_difference_state_var).mean(),
                "mean_abs_personnel_dir_shift": (3.45 * g.hindcast_delta).abs().mean(),
                "early_share_first_5": (g.team_match_min < 5).mean(),
            }
        )
    return (
        pd.DataFrame(rows),
        pd.DataFrame(profile),
        clubs.rename("matches_10pp_plus").reset_index(),
    )


def home_advantage(d):
    h = d[d.season_id.isin(HISTORY)].copy()
    rows = []
    for label, m in (("M7 home favourite", h.m7_dir > 0), ("M7 away favourite", h.m7_dir < 0)):
        b = np.polyfit(h.m7_dir[m], h.mkt_dir[m], 1)
        rows.append({"slice": label, "matches": int(m.sum()), "slope": b[0], "intercept": b[1]})
    for season, g in h.groupby("season_id"):
        even = g[g.m7_dir.abs() < 0.3]
        rows.append(
            {
                "slice": f"{season} near-even (|M7 log-odds| < 0.3)",
                "matches": len(even),
                "mean_residual": even.resid.mean(),
                "se": even.resid.std() / np.sqrt(len(even)),
                "m7_home_advantage": g.m7_home_advantage.mean(),
                "observed_home_away_goal_log_ratio": np.log(
                    g.home_goals.mean() / g.away_goals.mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def personnel_table(d, personnel):
    h = d[d.season_id.isin(HISTORY)].merge(personnel, on="match_id", how="left")
    k = np.polyfit(h.m7_log_home_rate - h.m7_log_away_rate, h.m7_dir, 1)[0]
    rows = []
    for column in ("hindcast_delta", "oracle_delta"):
        shift = 2 * k * h[column]
        after = h.resid - shift
        moving = shift.abs() > 0.02
        rows.append(
            {
                "shift": column,
                "matches": int(h[column].notna().sum()),
                "mean_abs_dir_shift": shift.abs().mean(),
                "mean_abs_residual": h.resid.abs().mean(),
                "corr_with_residual": np.corrcoef(shift, h.resid)[0, 1],
                "toward_market_share": (np.sign(shift) == np.sign(h.resid))[moving].mean(),
                "mean_square_residual_change": (after**2).mean() / (h.resid**2).mean() - 1,
            }
        )
    return pd.DataFrame(rows)


def outcome_experiments(d):
    y = d.outcome.map(OUTCOME_INDEX).to_numpy()
    d = d.assign(finishing_gap=d.finishing_gap.fillna(0), m2_gap=d.m2_dir - d.m7_dir)
    experiments = {
        "directional stretch (H1)": ["m7_dir"],
        "trailing finishing gap (H4)": ["finishing_gap"],
        "fixed entrant offset (H5 entry)": ["entrant_gap"],
        "M2 direction blend (H4 control)": ["m2_gap"],
        "persistent club level and deviation (H1 against H2)": [
            "long_quality_gap",
            "quality_deviation_gap",
        ],
    }
    seasons = sorted(d.season_id.unique())
    experiments["prior-season market club effects (diagnostic, H2)"] = ["club_prediction"]
    rows = []
    for name, columns in experiments.items():
        for test in seasons[1:]:
            train = (d.season_id < test).to_numpy()
            target = (d.season_id == test).to_numpy()
            if columns == ["club_prediction"]:
                # Club effects from earlier seasons only; the fit weight then uses earlier seasons too.
                d = d.assign(club_prediction=0.0)
                for season in seasons:
                    if season > test:
                        break
                    earlier = d[d.season_id < season]
                    if earlier.empty:
                        continue
                    clubs = sorted(set(earlier.home_team_id) | set(earlier.away_team_id))
                    b = ridge(
                        np.column_stack([np.ones(len(earlier)), club_design(earlier, clubs)]),
                        earlier.resid.to_numpy(),
                        PENALTY,
                        [0],
                    )
                    effect = dict(zip(clubs, b[1:] - b[1:].mean(), strict=True))
                    here = d.season_id == season
                    d.loc[here, "club_prediction"] = [
                        effect.get(h, 0.0) - effect.get(a, 0.0)
                        for h, a in zip(d.home_team_id[here], d.away_team_id[here], strict=True)
                    ]
                if not (train & (d.club_prediction != 0).to_numpy()).any():
                    continue

            def objective(params, mask, columns=columns, d=d):
                g = d[mask]
                draw = g.m7_p_draw.to_numpy()
                ratio = np.exp(
                    g.m7_dir.to_numpy() + np.column_stack([g[c] for c in columns]) @ params
                )
                p = np.column_stack(
                    [(1 - draw) * ratio / (1 + ratio), draw, (1 - draw) / (1 + ratio)]
                )
                return loss(p, y[mask])

            fit = minimize(objective, np.zeros(len(columns)), args=(train,), method="Nelder-Mead")
            rows.append(
                {
                    "experiment": name,
                    "test_season": test,
                    "matches": int(target.sum()),
                    "parameters": np.round(fit.x, 3).tolist(),
                    "candidate_minus_m7": objective(fit.x, target) - d[target].m7_ll.mean(),
                    "market_minus_m7": d[target].mkt_ll.mean() - d[target].m7_ll.mean(),
                }
            )
    return pd.DataFrame(rows)


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    d, t = load_all()
    personnel = pd.read_csv(
        RUNS / "evidence/chronological.csv", usecols=["match_id", "hindcast_delta", "oracle_delta"]
    )
    overview = (
        d.assign(
            window=np.where(
                d.season_id.isin(HISTORY),
                "2023-2026",
                np.where(d.season_id < "2023", "2016-2023", "2026/27 to date"),
            )
        )
        .groupby("window")
        .agg(
            matches=("match_id", "size"),
            m7=("m7_ll", "mean"),
            certainty_equivalent=("ce_ll", "mean"),
            m2=("m2_ll", "mean"),
            market=("mkt_ll", "mean"),
            closing=("close_ll", "mean"),
            median_tv=("tv_m7", "median"),
            p90_tv=("tv_m7", lambda s: s.quantile(0.9)),
        )
        .reset_index()
    )
    tables = {
        "overview": overview,
        "slopes": slopes(d),
        "outcome_stretch": outcome_stretch(d),
        "decomposition": decomposition(d),
    }
    effects = club_season_effects(d)
    tables["club_season_effects"] = effects
    tables["strength_structure"] = strength_structure(effects, d)
    tables["season_persistence"] = season_persistence(effects)
    effects_m2 = club_season_effects(d, "resid_m2")
    tables["season_persistence_m2"] = season_persistence(effects_m2)
    tables["predictive_persistence"] = predictive_persistence(d)
    tables["clubs"] = club_table(d, t)
    tables["finishing"], tables["finishing_persistence"] = finishing_tests(d, t)
    tables["uncertainty"] = uncertainty(d)
    tables["adaptation"], tables["residual_autocorrelation"], tables["residual_by_phase"] = (
        adaptation(d)
    )
    tables["scoring"], tables["large_disagreement_profile"], tables["large_disagreement_clubs"] = (
        scoring(d, personnel)
    )
    tables["scoring_2016_2026"] = scoring(
        d, personnel, tuple(s for s in d.season_id.unique() if s < "2026")
    )[0]
    tables["home_advantage"] = home_advantage(d)
    tables["personnel"] = personnel_table(d, personnel)
    tables["outcome_experiments"] = outcome_experiments(d)
    for name, table in tables.items():
        table.to_csv(TABLES / f"{name}.csv", index=False, float_format="%.5g")
        print(f"\n## {name}\n{table.to_string(max_rows=60)}")


if __name__ == "__main__":
    main()
