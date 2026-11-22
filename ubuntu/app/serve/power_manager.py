"""Advisory GPU power and temperature monitoring for Strata.

Monitors GPU power, temperature, and inference speed in real-time, computes
efficiency (tok/s per watt), and reports threshold alerts. The server does not
use these alerts to enforce GPU power limits or throttle generation.

Modes:
  - "performance": alerts at 95°C or 9999W
  - "balanced": alerts at 80°C or 250W
  - "eco": alerts at 70°C or 150W
  - "custom": user-defined thresholds

The manager exposes:
  - current state (power, temp, speed, efficiency)
  - alert status (legacy API names: throttling, reason, cooldown remaining)
  - configuration (mode, custom thresholds)
  - history (for sparklines)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class PowerState:
    """Current power/thermal/speed snapshot."""
    timestamp: float = 0.0
    power_w: float = 0.0          # GPU power in watts
    temp_c: float = 0.0           # GPU temperature in Celsius
    speed_tps: float = 0.0        # tokens per second
    efficiency: float = 0.0       # tok/s per watt
    throttling: bool = False
    throttle_reason: str = ""
    cooldown_s: float = 0.0       # remaining cooldown in seconds


@dataclass
class PowerConfig:
    """Power management configuration."""
    mode: str = "balanced"        # performance | balanced | eco | custom
    custom_temp_limit: float = 75.0
    custom_power_limit: float = 200.0
    cooldown_s: float = 5.0       # alert retention; never pauses generation
    min_speed_tps: float = 1.0    # evaluate thresholds during active generation

    # Mode presets
    PRESETS = {
        "performance": {"temp_limit": 95.0, "power_limit": 9999.0},
        "balanced": {"temp_limit": 80.0, "power_limit": 250.0},
        "eco": {"temp_limit": 70.0, "power_limit": 150.0},
    }

    def temp_limit(self) -> float:
        if self.mode == "custom":
            return self.custom_temp_limit
        return self.PRESETS.get(self.mode, self.PRESETS["balanced"])["temp_limit"]

    def power_limit(self) -> float:
        if self.mode == "custom":
            return self.custom_power_limit
        return self.PRESETS.get(self.mode, self.PRESETS["balanced"])["power_limit"]


class PowerManager:
    """Reports power/thermal alerts without enforcing inference limits."""

    def __init__(self, config: Optional[PowerConfig] = None):
        self.config = config or PowerConfig()
        self.state = PowerState()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[PowerState], None]] = []
        self._throttle_until: float = 0.0
        self._throttle_reason: str = ""
        self._history: list[PowerState] = []
        self._max_history = 60  # keep last 60 samples (1 minute at 1 Hz)

    def register_callback(self, cb: Callable[[PowerState], None]) -> None:
        """Register a callback to be called on every state update."""
        self._callbacks.append(cb)

    def update(self, power_w: float, temp_c: float, speed_tps: float) -> PowerState:
        """Update the current state and report threshold alerts if needed.

        Called by the telemetry loop (every second) with fresh readings.
        Returns advisory state; legacy throttling fields describe alerts only.
        """
        # Missing hardware readings must not break /metrics. The hardware payload
        # retains None so clients can distinguish unavailable sensors from zero.
        power_w, temp_c, speed_tps = power_w or 0.0, temp_c or 0.0, speed_tps or 0.0
        now = time.time()
        efficiency = speed_tps / power_w if power_w > 0 else 0.0

        # Evaluate advisory alerts. No driver writes or inference pauses.
        throttling = False
        reason = ""
        cooldown = 0.0

        if now < self._throttle_until:
            # Still in cooldown
            throttling = True
            reason = self._throttle_reason
            cooldown = self._throttle_until - now
        elif speed_tps >= self.config.min_speed_tps:
            # Check thresholds
            temp_limit = self.config.temp_limit()
            power_limit = self.config.power_limit()

            if temp_c >= temp_limit:
                throttling = True
                reason = f"temp {temp_c:.0f}°C ≥ {temp_limit:.0f}°C"
                self._throttle_until = now + self.config.cooldown_s
                self._throttle_reason = reason
                cooldown = self.config.cooldown_s
            elif power_w >= power_limit:
                throttling = True
                reason = f"power {power_w:.0f}W ≥ {power_limit:.0f}W"
                self._throttle_until = now + self.config.cooldown_s
                self._throttle_reason = reason
                cooldown = self.config.cooldown_s

        state = PowerState(
            timestamp=now,
            power_w=power_w,
            temp_c=temp_c,
            speed_tps=speed_tps,
            efficiency=efficiency,
            throttling=throttling,
            throttle_reason=reason,
            cooldown_s=cooldown,
        )

        with self._lock:
            self.state = state
            self._history.append(state)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        # Notify callbacks
        for cb in self._callbacks:
            try:
                cb(state)
            except Exception:
                pass

        return state

    def should_throttle(self) -> bool:
        """Legacy accessor for active alerts; not used to pause inference."""
        with self._lock:
            return self.state.throttling

    def get_state(self) -> PowerState:
        """Get the current state (thread-safe)."""
        with self._lock:
            return self.state

    def get_history(self) -> list[PowerState]:
        """Get the history of states (thread-safe)."""
        with self._lock:
            return list(self._history)

    def set_mode(self, mode: str) -> None:
        """Set the power mode (performance/balanced/eco/custom)."""
        if mode not in ("performance", "balanced", "eco", "custom"):
            raise ValueError(f"unknown mode: {mode}")
        self.config.mode = mode

    def set_custom_limits(self, temp_limit: float, power_limit: float) -> None:
        """Set custom thresholds (only used when mode='custom')."""
        from serve.configuration import whole_number
        temp_limit = whole_number(temp_limit, "temp_limit", 50, 95)
        power_limit = whole_number(power_limit, "power_limit", 50, 350)
        self.config.custom_temp_limit = temp_limit
        self.config.custom_power_limit = power_limit

    def reset_throttle(self) -> None:
        """Clear the retained advisory alert."""
        self._throttle_until = 0.0
        self._throttle_reason = ""
