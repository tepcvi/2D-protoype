from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
try:
    # Optional on Android: scikit-learn often breaks APK builds.
    from sklearn.neighbors import KNeighborsRegressor  # type: ignore
except Exception:  # pragma: no cover
    KNeighborsRegressor = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Tuning:
    # Multiplier applied to obstacle speed.
    speed_multiplier: float
    # Multiplier applied to spacing between obstacles (higher => more space).
    spacing_multiplier: float
    # Probability of spawning a "combo" (two obstacles close together).
    combo_probability: float
    # Per-obstacle-type weight overrides (lower weight => less frequent).
    obstacle_weights: Dict[str, float]


class AdaptiveDifficultySystem:
    """
    AADS (AI-Powered Adaptive Difficulty System).

    Prototype implementation:
    - Uses scikit-learn model (trained on synthetic data) to predict difficulty.
    - Applies rule-based adjustments for combo spawning and obstacle type throttling.
    """

    def __init__(self, obstacle_types: List[str]):
        self.obstacle_types = list(obstacle_types)
        if KNeighborsRegressor is not None:
            self._model = KNeighborsRegressor(n_neighbors=5)
            self._fit_synthetic_model()
        else:
            self._model = None

    def _fit_synthetic_model(self) -> None:
        rng = np.random.default_rng(42)
        n = 600

        # success_rate: 0..1
        success_rate = rng.uniform(0.0, 1.0, size=n)
        # avg_reaction_time: seconds (lower is better); 0.2..3.0
        avg_reaction_time = rng.uniform(0.2, 3.0, size=n)
        # repeated_deaths: how many times the "most deadly" obstacle type killed the player
        repeated_deaths = rng.integers(0, 6, size=n).astype(np.float64)

        # Difficulty mapping (synthetic ground truth):
        # Higher success_rate -> harder; higher reaction time -> slightly easier; higher deaths -> easier.
        y = (
            0.85
            + 0.55 * (success_rate - 0.5)
            - 0.08 * (avg_reaction_time - 1.0)
            - 0.05 * repeated_deaths
        )
        y = np.clip(y, 0.6, 1.6)

        X = np.stack([success_rate, avg_reaction_time, repeated_deaths], axis=1)
        self._model.fit(X, y)

    def compute_tuning(
        self,
        *,
        success_rate: float,
        avg_reaction_time: float,
        death_counts: Dict[str, int],
        base_weights: Dict[str, float],
        tutorial_mode: bool = False,
        combo_enabled: bool = True,
    ) -> Tuning:
        repeated_death = float(max(death_counts.values(), default=0))

        # Predict a difficulty multiplier.
        if self._model is not None:
            features = np.array([[success_rate, avg_reaction_time, repeated_death]], dtype=np.float64)
            predicted = float(self._model.predict(features)[0])
        else:
            # Heuristic fallback (keeps Android builds working without scikit-learn).
            predicted = (
                0.85
                + 0.55 * (success_rate - 0.5)
                - 0.08 * (avg_reaction_time - 1.0)
                - 0.05 * repeated_death
            )

        # Apply tutorial boost: keep it easier on first-time users.
        if tutorial_mode:
            predicted *= 0.85

        predicted = float(np.clip(predicted, 0.6, 1.7))

        # Spacing is inverse to speed: faster means tighter spacing.
        spacing_multiplier = 1.0 / max(0.75, predicted)

        # Combo probability based on success_rate.
        if not combo_enabled:
            combo_probability = 0.0
        else:
            if success_rate > 0.80:
                combo_probability = 0.35
            elif success_rate < 0.40:
                combo_probability = 0.05
            else:
                combo_probability = 0.15

        # Reduce spawn weight for obstacle types that recently killed the player.
        obstacle_weights: Dict[str, float] = dict(base_weights)
        for k in self.obstacle_types:
            deaths = death_counts.get(k, 0)
            if deaths >= 2:
                obstacle_weights[k] = obstacle_weights.get(k, 1.0) * 0.5
            elif deaths == 1:
                obstacle_weights[k] = obstacle_weights.get(k, 1.0) * 0.8

        # Normalize weights (avoid all zeros).
        total = sum(max(w, 0.0001) for w in obstacle_weights.values())
        for k in obstacle_weights:
            obstacle_weights[k] = max(0.0001, obstacle_weights[k]) * len(obstacle_weights) / total

        return Tuning(
            speed_multiplier=predicted,
            spacing_multiplier=float(np.clip(spacing_multiplier, 0.55, 1.6)),
            combo_probability=float(combo_probability),
            obstacle_weights=obstacle_weights,
        )

