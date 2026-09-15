# Forecast smoke tests

Smoke tests check whether the product behaves like the intended model. They are not optimization targets.

- Chronology: Evidence first observed after a cutoff cannot change that cutoff's forecast.
- Entrants: Valid source-season evidence must not silently fall back to an `outside` prior.
- Personnel: Lower recent-personnel availability must produce the configured temporary uncertainty response. Restoring those personnel removes it.
- xG: Missing xG is missing, never zero. Disabling the channel exactly recovers the goals-only control.
- Separation: Market inputs never change the structural forecast.
- Named cases can falsify implementation semantics, but they must not become tuning objectives.
