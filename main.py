from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.image import Image as KivyImage
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.widget import Widget
from kivy.resources import resource_find
from kivy.utils import platform as kivy_platform

from aads import AdaptiveDifficultySystem, Tuning
from generate_assets import ASSET_FILES, ensure_assets


def rank_for_score(score: int) -> str:
    # Prototype-safe thresholds based on the extracted study text.
    if score < 500:
        return "Alipin"
    if score >= 15000:
        return "Bathala"
    return "Intermediate (Alipin to Bathala)"


def tutorial_flag_path() -> Path:
    # Hidden flag file to decide if we auto-show tutorial hint.
    base = Path.home() / ".likha_ang_lahi"
    return base / "has_seen_tutorial.txt"


def has_seen_tutorial() -> bool:
    return tutorial_flag_path().exists()


def mark_tutorial_seen() -> None:
    path = tutorial_flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1", encoding="utf-8")


@dataclass
class ObstacleSpec:
    required_action: str  # "jump" or "crawl" (duck/crouch)
    width: float
    height: float
    color: Tuple[float, float, float, float]
    y_offset: float  # how far above ground to render


OBSTACLE_SPECS: Dict[str, ObstacleSpec] = {
    "Tikbalang": ObstacleSpec(
        required_action="jump",
        width=52,
        height=96,
        color=(0.35, 0.85, 0.95, 1.0),
        y_offset=0.0,
    ),
    "Manananggal": ObstacleSpec(
        required_action="crawl",
        width=60,
        height=72,
        color=(0.95, 0.55, 0.25, 1.0),
        # Manananggal is expected to look "flying", so render it higher.
        y_offset=70.0,
    ),
    "Kapre": ObstacleSpec(
        required_action="jump",
        width=58,
        height=92,
        color=(0.20, 0.75, 0.25, 1.0),
        y_offset=0.0,
    ),
    # Boss will reuse evaluation logic, but with a bigger obstacle for visual impact.
    "Bakunawa": ObstacleSpec(
        required_action="jump",
        width=110,
        height=120,
        color=(0.55, 0.15, 0.95, 1.0),
        y_offset=0.0,
    ),
}


class GameOverPayload:
    def __init__(
        self,
        *,
        score: int,
        survival_seconds: float,
        success_rate: float,
        avg_reaction_ms: float,
        attempts_by_type: Dict[str, int],
        successes_by_type: Dict[str, int],
        death_counts: Dict[str, int],
    ):
        self.score = score
        self.survival_seconds = survival_seconds
        self.success_rate = success_rate
        self.avg_reaction_ms = avg_reaction_ms
        self.attempts_by_type = attempts_by_type
        self.successes_by_type = successes_by_type
        self.death_counts = death_counts


class GameView(Widget):
    """
    Lightweight endless runner prototype (desktop-friendly).

    Metrics collected for AADS:
    - success_rate (overall)
    - avg_reaction_time (seconds, computed from obstacle spawn -> evaluation moment)
    - death_counts per obstacle type
    """

    def __init__(
        self,
        hud_callback: Callable[[int, float, float, float, float], None],
        game_over_callback: Callable[[GameOverPayload], None],
        *,
        tutorial_mode: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.hud_callback = hud_callback
        self.game_over_callback = game_over_callback
        self.tutorial_mode = tutorial_mode

        self.session_active = False
        self.session_start_time = 0.0
        self.session_time = 0.0

        self.score = 0

        self.player_x = 120.0
        self.player_y = 0.0
        self.player_vel_y = 0.0
        self.player_width = 44.0
        self.player_height_stand = 90.0
        self.player_height_slide = 56.0
        self.player_ground_y = 60.0

        self.jumping = False
        self.sliding = False
        self._slide_time_left = 0.0
        # When True, slide/crawl persists until the input is released (long-press).
        # When False, we use timed slide_duration (tap-to-crawl).
        self._slide_until_release = False

        self.jump_velocity = 620.0
        self.gravity = 1750.0
        self.slide_duration = 0.72

        self.base_speed = 340.0
        self.speed_multiplier = 0.85 if self.tutorial_mode else 1.0

        self.base_spawn_interval = 1.25  # seconds
        self.spawn_interval = self.base_spawn_interval / self.speed_multiplier
        self.spawn_timer = 0.7

        self.current_spacing_multiplier = 1.0

        self.combo_probability = 0.12
        self.obstacle_weights: Dict[str, float] = {
            "Tikbalang": 1.0,
            "Manananggal": 1.0,
            "Kapre": 1.0,
            "Bakunawa": 0.15,  # boss is rarer (triggered separately)
        }
        self._base_weights = dict(self.obstacle_weights)

        self.aads = AdaptiveDifficultySystem(obstacle_types=["Tikbalang", "Manananggal", "Kapre", "Bakunawa"])
        self._last_tuning_update = 0.0
        self._tuning_interval = 1.2

        # Metrics
        self.attempts = 0
        self.successes = 0
        self.reaction_times_success: List[float] = []

        self.attempts_by_type: Dict[str, int] = {k: 0 for k in OBSTACLE_SPECS}
        self.successes_by_type: Dict[str, int] = {k: 0 for k in OBSTACLE_SPECS}
        self.death_counts: Dict[str, int] = {k: 0 for k in OBSTACLE_SPECS}

        # Obstacles:
        # obstacle = {"kind": str, "x": float, "widget": KivyImage, "spawn_time": float, "evaluated": bool}
        self.obstacles: List[dict] = []

        # Boss trigger
        self.bakunawa_trigger_seconds = 22.0
        self.bakunawa_min_interval = 16.0
        self.last_bakunawa_spawn_time = -9999.0

        # Canvas instructions
        # Forest-themed background (solid colors for the prototype).
        self._ground_color = (0.10, 0.22, 0.10, 1.0)  # dark forest green
        self._bg_color = (0.03, 0.08, 0.04, 1.0)      # deep forest night
        self._runner_sprite: Optional[KivyImage] = None

        # Ensure placeholder sprites exist (for defense demo visuals).
        self.asset_dir = Path(__file__).resolve().parent / "assets"
        # On Android/iOS, bundled resources are not guaranteed to be writable/available
        # via normal filesystem paths. Use resource_find and avoid placeholder generation.
        if kivy_platform not in ("android", "ios"):
            ensure_assets(self.asset_dir)

        def _asset_source(filename: str) -> str:
            # When packaged, Kivy resources are usually available via resource_find.
            rel = str(Path("assets") / filename).replace("\\", "/")
            found = resource_find(rel)
            if found:
                return found
            # Desktop fallback.
            return str(self.asset_dir / filename)

        self._runner_source = _asset_source(ASSET_FILES["Runner"])
        self._obstacle_sources = {
            "Tikbalang": _asset_source(ASSET_FILES["Tikbalang"]),
            "Manananggal": _asset_source(ASSET_FILES["Manananggal"]),
            "Kapre": _asset_source(ASSET_FILES["Kapre"]),
            "Bakunawa": _asset_source(ASSET_FILES["Bakunawa"]),
        }

        self._init_canvas()
        self.bind(size=self._on_size)
        self._clock_event: Optional[object] = None

    def _init_canvas(self) -> None:
        self.canvas.clear()
        with self.canvas:
            Color(*self._bg_color)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
            # ground
            Color(*self._ground_color)
            self._ground_rect = Rectangle(pos=(0, 0), size=(self.width, 10))

        # Runner sprite (visual element)
        if self._runner_sprite is not None:
            try:
                self.remove_widget(self._runner_sprite)
            except Exception:
                pass
        self._runner_sprite = KivyImage(
            source=self._runner_source,
        )
        self._runner_sprite.size = (self.player_width, self.player_height_stand)
        self._runner_sprite.pos = (self.player_x, self.player_ground_y)
        self.add_widget(self._runner_sprite)

    def _on_size(self, *_args) -> None:
        # Update ground and player anchor when resizing.
        self.player_ground_y = max(46.0, self.height * 0.16)
        self.player_y = self.player_ground_y
        self._ground_rect.pos = (0, self.player_ground_y)
        self._ground_rect.size = (self.width, 10)
        self._bg_rect.size = self.size
        self._bg_rect.pos = self.pos
        if self._runner_sprite is not None:
            if self.sliding:
                self._runner_sprite.size = (self.player_width, self.player_height_slide)
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)
            elif self.jumping:
                self._runner_sprite.size = (self.player_width, self.player_height_stand)
                self._runner_sprite.pos = (self.player_x, self.player_y)
            else:
                self._runner_sprite.size = (self.player_width, self.player_height_stand)
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)

    def start_session(self) -> None:
        self.session_active = True
        self.session_start_time = time.time()
        self.session_time = 0.0
        self.score = 0

        self.attempts = 0
        self.successes = 0
        self.reaction_times_success.clear()

        for k in self.attempts_by_type:
            self.attempts_by_type[k] = 0
            self.successes_by_type[k] = 0
            self.death_counts[k] = 0

        self.jumping = False
        self.sliding = False
        self._slide_time_left = 0.0
        self.player_vel_y = 0.0
        self.player_y = self.player_ground_y
        if self._runner_sprite is not None:
            self._runner_sprite.size = (self.player_width, self.player_height_stand)
            self._runner_sprite.pos = (self.player_x, self.player_ground_y)

        # Reset tuning knobs
        self.speed_multiplier = 0.85 if self.tutorial_mode else 1.0
        self.spawn_interval = self.base_spawn_interval / self.speed_multiplier
        self.spawn_timer = 0.75
        self.current_spacing_multiplier = 1.0
        self.combo_probability = 0.12 if self.tutorial_mode else 0.15
        self.obstacle_weights = dict(self._base_weights)

        self._last_tuning_update = 0.0
        self.last_bakunawa_spawn_time = -9999.0

        # Clear obstacles
        for ob in self.obstacles:
            try:
                widget = ob.get("widget")
                if widget is not None:
                    self.remove_widget(widget)
            except Exception:
                pass
        self.obstacles.clear()

        # Start loop
        if self._clock_event is not None:
            self._clock_event.cancel()
        self._clock_event = Clock.schedule_interval(self._update, 1 / 60.0)

    def request_jump(self) -> None:
        if not self.session_active:
            return
        if self.sliding:
            self.sliding = False
            self._slide_time_left = 0.0
            self._slide_until_release = False
            if self._runner_sprite is not None:
                self._runner_sprite.size = (self.player_width, self.player_height_stand)
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)

        if not self.jumping:
            self.jumping = True
            self.player_vel_y = self.jump_velocity

    def request_slide(self) -> None:
        if not self.session_active:
            return
        if self.jumping:
            # If the player presses slide during a jump, immediately transition.
            # This prevents the "down pressed but nothing happens" feel.
            self.jumping = False
            self.player_vel_y = 0.0
            self.player_y = self.player_ground_y
        # Tap-to-crawl (timed).
        if not self.sliding:
            self.sliding = True
            self._slide_until_release = False
            self._slide_time_left = self.slide_duration
            if self._runner_sprite is not None:
                self._runner_sprite.size = (self.player_width, self.player_height_slide)
            # Keep feet anchored on the ground.
            if self._runner_sprite is not None:
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)

    def request_slide_start(self) -> None:
        """
        Long-press crawl: stays crouched until request_slide_stop() is called.
        """
        if not self.session_active:
            return
        if self.jumping:
            # Convert mid-jump into an immediate crouch/slide.
            self.jumping = False
            self.player_vel_y = 0.0
            self.player_y = self.player_ground_y
        if not self.sliding:
            self.sliding = True
            self._slide_until_release = True
            self._slide_time_left = 0.0
            if self._runner_sprite is not None:
                self._runner_sprite.size = (self.player_width, self.player_height_slide)
            if self._runner_sprite is not None:
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)

    def request_slide_stop(self) -> None:
        """
        Stop long-press crawl (returns to standing).
        """
        if not self.session_active:
            return
        if not self.sliding:
            return
        self.sliding = False
        self._slide_until_release = False
        self._slide_time_left = 0.0
        # Ensure player is standing at ground immediately.
        if self._runner_sprite is not None:
            self._runner_sprite.size = (self.player_width, self.player_height_stand)
            self._runner_sprite.pos = (self.player_x, self.player_ground_y)

    def _choose_obstacle_kind(self, *, exclude_bakunawa: bool = False) -> str:
        kinds = []
        weights = []
        for k, w in self.obstacle_weights.items():
            if exclude_bakunawa and k == "Bakunawa":
                continue
            kinds.append(k)
            weights.append(max(0.0001, w))
        return random.choices(kinds, weights=weights, k=1)[0]

    def _spawn_obstacle(self, kind: str, *, x: float) -> None:
        spec = OBSTACLE_SPECS[kind]
        y = self.player_ground_y + spec.y_offset
        source = self._obstacle_sources.get(kind, "")
        sprite = KivyImage(
            source=source,
        )
        # If assets aren't available, hide the sprite instead of crashing.
        if not source or not Path(source).exists():
            sprite.opacity = 0.0
        sprite.size = (spec.width, spec.height)
        sprite.pos = (x, y)
        self.add_widget(sprite)
        self.obstacles.append(
            {
                "kind": kind,
                "x": x,
                "widget": sprite,
                "y_offset": spec.y_offset,
                "spawn_time": self.session_time,
                "evaluated": False,
            }
        )

    def _maybe_spawn(self) -> None:
        if not self.session_active:
            return

        # Boss trigger
        if (
            self.session_time >= self.bakunawa_trigger_seconds
            and (self.session_time - self.last_bakunawa_spawn_time) >= self.bakunawa_min_interval
        ):
            self.last_bakunawa_spawn_time = self.session_time
            self._spawn_obstacle("Bakunawa", x=self.width + 30)
            return

        # Normal spawn
        kind = self._choose_obstacle_kind(exclude_bakunawa=self.session_time < self.bakunawa_trigger_seconds)

        start_x = self.width + 30
        self._spawn_obstacle(kind, x=start_x)

        # Combo spawn: two obstacles close together.
        if random.random() < self.combo_probability:
            # Make combos survivable: pick second obstacle with the same required action
            # (prevents impossible jump+slide conflicts).
            first_required = OBSTACLE_SPECS[kind].required_action
            candidates: List[str] = []
            weights: List[float] = []
            for k, w in self.obstacle_weights.items():
                if k == "Bakunawa":
                    continue
                if OBSTACLE_SPECS[k].required_action != first_required:
                    continue
                candidates.append(k)
                weights.append(max(0.0001, w))

            if not candidates:
                # Fallback (should be rare): keep previous behavior.
                second_kind = self._choose_obstacle_kind(exclude_bakunawa=True)
            else:
                second_kind = random.choices(candidates, weights=weights, k=1)[0]

            combo_gap = 90 * self.current_spacing_multiplier
            self._spawn_obstacle(second_kind, x=start_x + combo_gap)

    def _update(self, dt: float) -> None:
        if not self.session_active:
            return

        self.session_time += dt

        # Score increases over time (scaled by speed).
        self.score += int(dt * 65 * self.speed_multiplier)

        # Player physics (jump/slide)
        if self.jumping:
            self.player_vel_y -= self.gravity * dt
            self.player_y += self.player_vel_y * dt
            if self.player_y <= self.player_ground_y:
                self.player_y = self.player_ground_y
                self.jumping = False
                self.player_vel_y = 0.0
                if self._runner_sprite is not None:
                    self._runner_sprite.size = (self.player_width, self.player_height_stand)
                    self._runner_sprite.pos = (self.player_x, self.player_ground_y)
            else:
                if self._runner_sprite is not None:
                    self._runner_sprite.size = (self.player_width, self.player_height_stand)
                    self._runner_sprite.pos = (self.player_x, self.player_y)
        elif self.sliding:
            if not self._slide_until_release:
                self._slide_time_left -= dt
                if self._slide_time_left <= 0:
                    self.sliding = False
                    if self._runner_sprite is not None:
                        self._runner_sprite.size = (self.player_width, self.player_height_stand)
                        self._runner_sprite.pos = (self.player_x, self.player_ground_y)
            # While long-pressing, keep the slide sprite locked on the ground.
            if self.sliding and self._runner_sprite is not None:
                self._runner_sprite.size = (self.player_width, self.player_height_slide)
                self._runner_sprite.pos = (self.player_x, self.player_ground_y)

        # Move obstacles and evaluate at the player "trigger line".
        speed = self.base_speed * self.speed_multiplier
        trigger_x = self.player_x + self.player_width * 0.55

        for ob in list(self.obstacles):
            ob["x"] -= speed * dt
            widget = ob.get("widget")
            if widget is not None:
                widget.pos = (ob["x"], self.player_ground_y + float(ob.get("y_offset", 0.0)))

            # If it's off-screen and not evaluated, remove it (it was avoided visually or drift).
            if ob["x"] + OBSTACLE_SPECS[ob["kind"]].width < -80:
                if not ob["evaluated"]:
                    # If it left screen without evaluation, count it as success.
                    # This can happen if we resize or timing changes.
                    self._record_success(ob["kind"], reaction_time=0.01)
                try:
                    widget = ob.get("widget")
                    if widget is not None:
                        self.remove_widget(widget)
                except Exception:
                    pass
                self.obstacles.remove(ob)
                continue

            if not ob["evaluated"] and ob["x"] <= trigger_x:
                ob["evaluated"] = True
                kind = ob["kind"]
                spec = OBSTACLE_SPECS[kind]
                required = spec.required_action

                is_success = False
                if required == "jump":
                    is_success = self.jumping
                elif required in ("slide", "crawl"):
                    is_success = self.sliding

                if is_success:
                    reaction_time_s = max(0.0, self.session_time - ob["spawn_time"])
                    self._record_success(kind, reaction_time=reaction_time_s)
                    # Pass: remove obstacle.
                    try:
                        widget = ob.get("widget")
                        if widget is not None:
                            self.remove_widget(widget)
                    except Exception:
                        pass
                    self.obstacles.remove(ob)
                else:
                    self._record_death(kind)
                    self._end_session()
                    return

        # Spawn control
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self._maybe_spawn()
            self.spawn_timer = self.spawn_interval

        # Update tuning periodically based on collected metrics.
        if (self.session_time - self._last_tuning_update) >= self._tuning_interval:
            self._apply_aads_tuning()
            self._last_tuning_update = self.session_time

        # HUD update
        success_rate = self.successes / max(1, self.attempts)
        avg_rt_ms = (sum(self.reaction_times_success) / max(1, len(self.reaction_times_success))) * 1000.0
        self.hud_callback(self.score, success_rate, avg_rt_ms, self.speed_multiplier, self.combo_probability)

    def _record_success(self, kind: str, *, reaction_time: float) -> None:
        self.attempts += 1
        self.attempts_by_type[kind] += 1
        self.successes += 1
        self.successes_by_type[kind] += 1
        self.reaction_times_success.append(reaction_time)

        # Reward: base + speed scaling.
        self.score += int(120 * self.speed_multiplier)

    def _record_death(self, kind: str) -> None:
        self.attempts += 1
        self.attempts_by_type[kind] += 1
        self.death_counts[kind] += 1

    def _apply_aads_tuning(self) -> None:
        success_rate = self.successes / max(1, self.attempts)
        avg_reaction_time = sum(self.reaction_times_success) / max(1, len(self.reaction_times_success))

        tuning = self.aads.compute_tuning(
            success_rate=float(success_rate),
            avg_reaction_time=float(avg_reaction_time),
            death_counts=self.death_counts,
            base_weights=self._base_weights,
            tutorial_mode=self.tutorial_mode,
        )

        self.speed_multiplier = tuning.speed_multiplier
        self.spawn_interval = self.base_spawn_interval / max(0.7, self.speed_multiplier)
        self.combo_probability = tuning.combo_probability
        self.obstacle_weights = tuning.obstacle_weights
        self.current_spacing_multiplier = tuning.spacing_multiplier

    def _end_session(self) -> None:
        self.session_active = False
        if self._clock_event is not None:
            self._clock_event.cancel()
            self._clock_event = None

        success_rate = self.successes / max(1, self.attempts)
        avg_rt_ms = (sum(self.reaction_times_success) / max(1, len(self.reaction_times_success))) * 1000.0

        payload = GameOverPayload(
            score=int(self.score),
            survival_seconds=float(self.session_time),
            success_rate=float(success_rate),
            avg_reaction_ms=float(avg_rt_ms),
            attempts_by_type=dict(self.attempts_by_type),
            successes_by_type=dict(self.successes_by_type),
            death_counts=dict(self.death_counts),
        )

        self.game_over_callback(payload)


class MenuScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(orientation="vertical", padding=20, spacing=14)
        layout.add_widget(Label(text="LIKHA: ANG LAHI", font_size=32, bold=True))
        layout.add_widget(Label(text="Filipino Mythology-Themed Endless Runner (Prototype)", font_size=16))
        self._tutorial_hint = Label(text="", font_size=14)
        layout.add_widget(self._tutorial_hint)

        layout.add_widget(Widget(size_hint_y=0.2))

        self.btn_start = Button(text="Start (Adaptive AI)", size_hint_y=None, height=48)
        self.btn_start.bind(on_release=self._on_start)
        layout.add_widget(self.btn_start)

        self.btn_tutorial = Button(text="Start (Tutorial Mode)", size_hint_y=None, height=48)
        self.btn_tutorial.bind(on_release=self._on_tutorial_start)
        layout.add_widget(self.btn_tutorial)

        self.btn_rank = Button(text="View Rank/Stats (from last run)", size_hint_y=None, height=48)
        self.btn_rank.bind(on_release=self._on_rank)
        layout.add_widget(self.btn_rank)

        self.add_widget(layout)

    def on_pre_enter(self, *_args) -> None:
        has_seen = has_seen_tutorial()
        # If user hasn't seen tutorial before, show hint.
        self._tutorial_hint.text = (
            "Tutorial is auto-enabled on first run. Use it to learn jump vs crawl/duck!"
            if not has_seen
            else "Tutorial already shown on this device."
        )

    def _on_start(self, *_args) -> None:
        game_screen: GameScreen = self.manager.get_screen("game")  # type: ignore[assignment]
        tutorial_mode = not has_seen_tutorial()
        game_screen.set_tutorial_mode(tutorial_mode)
        self.manager.transition = NoTransition()
        self.manager.current = "game"
        if tutorial_mode:
            mark_tutorial_seen()

    def _on_tutorial_start(self, *_args) -> None:
        game_screen: GameScreen = self.manager.get_screen("game")  # type: ignore[assignment]
        game_screen.set_tutorial_mode(True)
        self.manager.transition = NoTransition()
        self.manager.current = "game"
        mark_tutorial_seen()

    def _on_rank(self, *_args) -> None:
        self.manager.transition = NoTransition()
        self.manager.current = "rank"


class GameScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tutorial_mode = False

        root = FloatLayout()
        self.view = None  # created in reset_ui

        # HUD
        self.score_label = Label(text="Score: 0", size_hint=(None, None), size=(240, 28), pos=(10, 10))
        self.metrics_label = Label(text="Success: -  Reaction(ms): -", size_hint=(None, None), size=(360, 28), pos=(10, 40))
        self.tutorial_label = Label(
            text="",
            size_hint=(None, None),
            size=(360, 28),
            pos=(10, 70),
            color=(1, 1, 0, 1),
        )

        root.add_widget(self.score_label)
        root.add_widget(self.metrics_label)
        root.add_widget(self.tutorial_label)

        # Controls (mobile-friendly):
        # - Right side: Jump
        # - Left side: Up/Down arrows (Down uses long-press)
        controls = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=140,
            pos_hint={"x": 0, "y": 0},
        )

        left_arrows = BoxLayout(orientation="vertical", size_hint_x=0.22, spacing=6, padding=(12, 12))
        self.btn_up = Button(text="UP", size_hint=(1, 0.5))
        self.btn_down = Button(text="DOWN", size_hint=(1, 0.5))
        left_arrows.add_widget(self.btn_up)
        left_arrows.add_widget(self.btn_down)

        mid_spacer = Widget(size_hint_x=1)

        right_jump_box = BoxLayout(orientation="vertical", size_hint_x=0.22, padding=(12, 12))
        self.btn_jump = Button(text="JUMP", size_hint=(1, 1))
        right_jump_box.add_widget(self.btn_jump)

        controls.add_widget(left_arrows)
        controls.add_widget(mid_spacer)
        controls.add_widget(right_jump_box)
        root.add_widget(controls)

        self.btn_up.bind(on_release=lambda *_a: self.view.request_jump())
        # Long-press crawl on mobile/desktop: slide stays until finger/mouse release.
        self.btn_down.bind(state=self._on_slide_state_changed)

        self.add_widget(root)
        self._reset_view(root)

        # Keyboard shortcuts (desktop convenience).
        Window.bind(on_key_down=self._on_key_down)

    def _reset_view(self, root: FloatLayout) -> None:
        # Replace view by recreating (easy for a prototype).
        if self.view is not None:
            try:
                root.remove_widget(self.view)
            except Exception:
                pass

        self.view = GameView(
            hud_callback=self._on_hud_update,
            game_over_callback=self._on_game_over,
            tutorial_mode=self.tutorial_mode,
            size_hint=(1, 0.86),
        )
        # Ensure view doesn't cover bottom controls visually.
        self.view.pos_hint = {"x": 0, "y": 0.14}
        root.add_widget(self.view)
        self._apply_tutorial_ui()

    def _on_slide_state_changed(self, button: Button, state: str) -> None:
        if not self.session_has_view():
            return
        if state == "down":
            self.view.request_slide_start()
        elif state in ("normal", "up"):
            self.view.request_slide_stop()

    def set_tutorial_mode(self, tutorial_mode: bool) -> None:
        self.tutorial_mode = bool(tutorial_mode)
        self._reset_view(self.children[0])  # root is the first widget

    def _apply_tutorial_ui(self) -> None:
        if self.tutorial_mode:
            self.tutorial_label.text = "Tutorial: Tikbalang/Kapre = UP (JUMP) • Manananggal = DOWN (CRAWL)"
        else:
            self.tutorial_label.text = ""

    def on_pre_enter(self, *_args) -> None:
        # Start a new session each time we enter.
        self.score_label.text = "Score: 0"
        self.metrics_label.text = "Success: -  Reaction(ms): -"
        if self.view is not None:
            self.view.start_session()

    def _on_key_down(self, _window, key, _scancode, _codepoint, modifier) -> bool:
        # Space = jump, Down/DownArrow = crawl/duck.
        if not self.session_has_view():
            return False
        if key == 32:  # space
            self.view.request_jump()
            return True
        if key == 274 or key == 273:  # down arrow variants (depends on platform)
            self.view.request_slide()
            return True
        return False

    def session_has_view(self) -> bool:
        return self.view is not None

    def _on_hud_update(self, score: int, success_rate: float, avg_rt_ms: float, speed_mult: float, combo_prob: float) -> None:
        self.score_label.text = f"Score: {score}"
        if success_rate <= 0.0:
            self.metrics_label.text = "Success: -  Reaction(ms): -  AI Speed: -  Combo: -"
        else:
            self.metrics_label.text = (
                f"Success: {success_rate*100:.0f}%  Reaction(ms): {avg_rt_ms:.0f}  "
                f"AI Speed: {speed_mult:.2f}  Combo: {combo_prob*100:.0f}%"
            )

    def _on_game_over(self, payload) -> None:
        # Save stats to rank screen.
        rank_screen: RankScreen = self.manager.get_screen("rank")  # type: ignore[assignment]
        rank_screen.save_last_run(payload)
        self.manager.transition = NoTransition()
        self.manager.current = "rank"


class RankScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_payload: Optional[GameOverPayload] = None

        layout = BoxLayout(orientation="vertical", padding=20, spacing=12)
        layout.add_widget(Label(text="Rank / Last Run Stats", font_size=28, bold=True))
        self._stats_label = Label(text="Run the game to see results.", font_size=16)
        layout.add_widget(self._stats_label)
        layout.add_widget(Widget(size_hint_y=0.4))

        self.btn_back = Button(text="Back to Menu", size_hint_y=None, height=48)
        self.btn_back.bind(on_release=lambda *_a: self._go_menu())
        layout.add_widget(self.btn_back)

        self.add_widget(layout)

    def _go_menu(self) -> None:
        self.manager.transition = NoTransition()
        self.manager.current = "menu"

    def has_seen_tutorial_file(self) -> bool:
        return has_seen_tutorial()

    def mark_tutorial_seen(self) -> None:
        mark_tutorial_seen()

    def save_last_run(self, payload: GameOverPayload) -> None:
        self._last_payload = payload
        self._refresh_label()

    def _refresh_label(self) -> None:
        if self._last_payload is None:
            self._stats_label.text = "Run the game to see results."
            return

        p = self._last_payload
        computed_rank = rank_for_score(p.score)

        top_death = None
        if p.death_counts:
            top_death = max(p.death_counts.items(), key=lambda kv: kv[1])[0]

        self._stats_label.text = (
            f"Score: {p.score}\n"
            f"Rank: {computed_rank}\n"
            f"Survival: {p.survival_seconds:.1f}s\n"
            f"Success rate: {p.success_rate*100:.0f}%\n"
            f"Avg reaction (success only): {p.avg_reaction_ms:.0f} ms\n"
            f"Most deaths: {top_death or 'N/A'}"
        )

    def on_pre_enter(self, *_args) -> None:
        self._refresh_label()


class LikhaAngLahiApp(App):
    def build(self):
        # For desktop prototype, keep the window readable.
        Window.size = (1000, 650)
        Window.clearcolor = (0.06, 0.06, 0.09, 1.0)

        sm = ScreenManager(transition=NoTransition())
        # Add rank screen early to avoid any potential on_pre_enter ordering issues.
        sm.add_widget(RankScreen(name="rank"))
        sm.add_widget(MenuScreen(name="menu"))
        sm.add_widget(GameScreen(name="game"))
        return sm


if __name__ == "__main__":
    LikhaAngLahiApp().run()

