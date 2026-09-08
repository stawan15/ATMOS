"""Fog scene: horizontal drifting layers, no vertical motion.

Layers are short rows of ─ characters drifting slowly. Density (number of
layers) tracks weather.cloud_coverage as a proxy (fog is a low cloud).

Subtle by design — fog should not visually overwhelm.
"""

from __future__ import annotations

import math
import random

from atmos.engine.frame_buffer import FrameBuffer
from atmos.scenes.base import SceneBase
from atmos.weather.models import WeatherState


class FogScene(SceneBase):
    def __init__(self) -> None:
        self.layers: list[dict] = []
        self._rng = random.Random()
        self.width = 0
        self.height = 0

    def enter(self, weather: WeatherState) -> None:
        self.weather = weather
        self.layers = []
        self._rng = random.Random(weather.location_name + "_fog")

    def update(self, dt: float, weather: WeatherState, width: int, height: int, lighting: "LightingState | None" = None) -> None:
        self.width = width
        self.height = height

        # Wind → drift speed. Fog drifts but slowly compared to clouds.
        rad = math.radians(weather.wind_direction)
        drift = math.sin(rad) * max(0.4, weather.wind_speed / 25.0)

        # Coverage → number + thickness of layers.
        target = max(3, min(8, int(weather.cloud_coverage / 12)))
        if not self.layers or len(self.layers) != target:
            self._init_layers(target, width, height)
        for layer in self.layers:
            layer["x"] += drift * dt
            if drift >= 0 and layer["x"] > width:
                layer["x"] = -layer["length"]
            elif drift < 0 and layer["x"] + layer["length"] < 0:
                layer["x"] = float(width)

    def _init_layers(self, count: int, width: int, height: int) -> None:
        self.layers = []
        # Spread layers through the middle 70% of the screen.
        top = max(2, int(height * 0.15))
        bottom = min(height - 4, int(height * 0.85))
        span = max(1, bottom - top)
        for i in range(count):
            length = self._rng.randint(max(8, width // 6), max(12, width // 3))
            chars = ["─"] * length
            y = top + (span * i) // max(1, count - 1) if count > 1 else (top + bottom) // 2
            self.layers.append(
                {
                    "x": self._rng.uniform(-length, max(1, width - 1)),
                    "y": y,
                    "length": length,
                    "chars": chars,
                }
            )

    def draw(self, buf: FrameBuffer, lighting: "LightingState | None" = None, dim: float = 1.0) -> None:
        # Fog is already drawn in dim grey; dim only suppresses
        # drawing entirely when it is near 0.
        if dim <= 0.0:
            return
        for layer in self.layers:
            start_x = int(layer["x"])
            y = int(layer["y"])
            if y < 0 or y >= buf.height:
                continue
            for offset, char in enumerate(layer["chars"]):
                x = start_x + offset
                if 0 <= x < buf.width and char != " ":
                    buf.set(y, x, char, "240")
