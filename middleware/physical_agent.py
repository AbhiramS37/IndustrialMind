"""
middleware/physical_agent.py — Physical Agent for the Industrial Mind middleware.

Downstream (SCADA -> PLC):
  check_command(command, current_state) -> verdict
  Three rule layers per command:
    1. Hard bounds        — value must be within the REGISTER_MAP safe range.
    2. Rate-of-change     — value must not imply a jump that the physical plant
                            cannot achieve between the last known timestamp and
                            the command timestamp.
    3. Cross-register     — certain combinations of simultaneous requested moves
                            are physically impossible (e.g. valve slamming shut
                            while pressure is already low).

Upstream (PLC -> SCADA):
  check_feedback(commanded_value, reported_value, register) -> verdict
  Compares what was last commanded with what the PLC is now reporting.
  A small lag is expected (physics ramp). A large mismatch is flagged.

current_state contract (passed in by the caller — middleware or test harness):
  {
      "registers": {
          0: <float>,   # TANK_PRESSURE current value
          1: <float>,   # CONVEYOR_SPEED current value
          2: <float>,   # COOLING_VALVE current value
      },
      "timestamp": <float>   # time.time() when telemetry was captured
  }
  Alternatively, register keys may be the string names — both are tolerated
  (see _get_value helper).
"""

import time
from docs.interfaces import (
    make_verdict,
    REGISTER_MAP,
    TANK_PRESSURE,
    CONVEYOR_SPEED,
    COOLING_VALVE,
)

# ── Rate-of-change limits (degrees/sec, RPM/sec, PSI/sec) ──────────────────
# Mirror the PLC's _RATE_PER_SEC so we know what's physically achievable.
# The Physical Agent gives 10 % headroom on top so marginal-but-legitimate
# commands aren't falsely dropped.
_RATE_LIMIT_PER_SEC = {
    TANK_PRESSURE:  2.0 * 1.10,   # PSI / sec  (+10 % headroom)
    CONVEYOR_SPEED: 10.0 * 1.10,  # RPM / sec
    COOLING_VALVE:  5.0 * 1.10,   # deg / sec
}

# Minimum time window used for rate calculations (avoids division by zero and
# protects against two commands arriving in the same millisecond).
_MIN_DT = 0.05   # seconds

# ── Feedback tolerance ──────────────────────────────────────────────────────
# On the upstream path, the PLC is still ramping toward its target, so some
# lag is expected. We allow up to 20 % of the full safe range as normal lag.
# Beyond that, something is wrong (sensor fault, spoofed telemetry, etc.).
_FEEDBACK_TOLERANCE_FRACTION = 0.20   # 20 % of the register's safe range

# ── Cross-register consistency thresholds ──────────────────────────────────
# How much a value must change (absolute) to count as a "significant move".
_SIG_MOVE = {
    TANK_PRESSURE:  10.0,   # PSI
    CONVEYOR_SPEED: 20.0,   # RPM
    COOLING_VALVE:  15.0,   # degrees
}


# ───────────────────────────────────────────────────────────────────────────
# Internal helpers
# ───────────────────────────────────────────────────────────────────────────

def _get_value(current_state: dict, register: int):
    """Return current register value from current_state, tolerating either
    integer keys or string name keys."""
    regs = current_state.get("registers", {})
    if register in regs:
        return regs[register]
    name = REGISTER_MAP[register]["name"]
    if name in regs:
        return regs[name]
    return None


def _safe_range(register: int):
    """Returns (min, max) safe range for a register."""
    info = REGISTER_MAP[register]
    return info["min"], info["max"]


# ───────────────────────────────────────────────────────────────────────────
# Rule 1 — Hard bounds
# ───────────────────────────────────────────────────────────────────────────

def _check_bounds(tx_id: str, register: int, value: float):
    """Returns a failed verdict if value is outside the safe range, else None."""
    lo, hi = _safe_range(register)
    if not (lo <= value <= hi):
        name = REGISTER_MAP[register]["name"]
        return make_verdict(
            tx_id, False,
            f"OUT_OF_BOUNDS:{name}={value:.2f} (allowed {lo}–{hi})",
            "physical",
        )
    return None


# ───────────────────────────────────────────────────────────────────────────
# Rule 2 — Rate-of-change
# ───────────────────────────────────────────────────────────────────────────

def _check_rate_of_change(tx_id: str, register: int, value: float,
                           current_state: dict, cmd_timestamp: float):
    """Returns a failed verdict if the requested value implies a speed the
    physical plant cannot achieve in the available time window."""
    current_val = _get_value(current_state, register)
    if current_val is None:
        # No baseline to compare against — can't enforce rate; let it through.
        return None

    state_ts = current_state.get("timestamp", cmd_timestamp)
    dt = max(cmd_timestamp - state_ts, _MIN_DT)

    delta = abs(value - current_val)
    max_allowed = _RATE_LIMIT_PER_SEC[register] * dt

    if delta > max_allowed:
        name = REGISTER_MAP[register]["name"]
        return make_verdict(
            tx_id, False,
            f"RATE_OF_CHANGE_EXCEEDED:{name} Δ{delta:.2f} > max {max_allowed:.2f} in {dt:.3f}s",
            "physical",
        )
    return None


# ───────────────────────────────────────────────────────────────────────────
# Rule 3 — Cross-register consistency
# ───────────────────────────────────────────────────────────────────────────

def _check_cross_register(tx_id: str, command: dict, current_state: dict):
    """
    Flags physically impossible register combinations.

    Current rules:
      A. Valve slamming shut (large negative COOLING_VALVE change) while
         TANK_PRESSURE is already low  — the two together imply a state the
         plant can't physically enter.
      B. CONVEYOR_SPEED at or near max while TANK_PRESSURE is already near
         max — extreme simultaneous load on two subsystems.
    """
    register = command.get("register")
    value    = command.get("value")

    tank_pressure   = _get_value(current_state, TANK_PRESSURE)
    conveyor_speed  = _get_value(current_state, CONVEYOR_SPEED)
    cooling_valve   = _get_value(current_state, COOLING_VALVE)

    # Rule A: valve closing fast while tank pressure already low
    if register == COOLING_VALVE and tank_pressure is not None and cooling_valve is not None:
        valve_drop = cooling_valve - value            # positive = closing
        pressure_lo, _ = _safe_range(TANK_PRESSURE)
        pressure_threshold = pressure_lo + 15.0      # "already low" = < 15 PSI

        if valve_drop >= _SIG_MOVE[COOLING_VALVE] and tank_pressure < pressure_threshold:
            return make_verdict(
                tx_id, False,
                "CROSS_REGISTER:valve closing sharply with tank pressure already low",
                "physical",
            )

    # Rule B: conveyor near max while tank pressure near max
    if register == CONVEYOR_SPEED and tank_pressure is not None:
        _, pressure_hi = _safe_range(TANK_PRESSURE)
        _, speed_hi    = _safe_range(CONVEYOR_SPEED)
        pressure_near_max = tank_pressure > pressure_hi * 0.90
        speed_near_max    = value > speed_hi * 0.90

        if pressure_near_max and speed_near_max:
            return make_verdict(
                tx_id, False,
                "CROSS_REGISTER:conveyor near max speed while tank pressure near limit",
                "physical",
            )

    return None


# ───────────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────────

def check_command(command: dict, current_state: dict) -> dict:
    """
    Downstream check: validate a SCADA->PLC command against physical laws.

    Args:
        command:       Command dict (docs/interfaces.make_command shape).
        current_state: Latest plant state from plc.get_telemetry() or a
                       compatible dict (see module docstring for shape).

    Returns:
        Verdict dict (docs/interfaces.make_verdict shape).
        pass=True only if ALL three rule layers pass.
    """
    tx_id    = command.get("tx_id", "")
    register = command.get("register")
    value    = command.get("value")
    cmd_ts   = command.get("timestamp", time.time())

    if register not in REGISTER_MAP:
        return make_verdict(tx_id, False, f"UNKNOWN_REGISTER:{register}", "physical")

    # Layer 1 — hard bounds
    verdict = _check_bounds(tx_id, register, value)
    if verdict:
        return verdict

    # Layer 2 — rate of change
    verdict = _check_rate_of_change(tx_id, register, value, current_state, cmd_ts)
    if verdict:
        return verdict

    # Layer 3 — cross-register
    verdict = _check_cross_register(tx_id, command, current_state)
    if verdict:
        return verdict

    return make_verdict(tx_id, True, "OK", "physical")


def check_feedback(commanded_value: float, reported_value: float, register: int) -> dict:
    """
    Upstream check: compare what the PLC reports with what was last commanded.

    A small lag is expected while the physics simulation ramps toward the
    target. A large mismatch suggests sensor spoofing, a stuck actuator,
    or a tampered telemetry frame.

    Args:
        commanded_value: The last value sent to this register by the middleware.
        reported_value:  The value the PLC is currently reporting.
        register:        Register number (0, 1, or 2).

    Returns:
        Verdict dict with agent="physical".
        tx_id is set to "" here — callers should replace it with the real tx_id.
    """
    _, hi = _safe_range(register)
    lo, _ = _safe_range(register)
    full_range = hi - lo if hi != lo else 1.0

    tolerance = full_range * _FEEDBACK_TOLERANCE_FRACTION
    deviation  = abs(reported_value - commanded_value)

    if deviation > tolerance:
        name = REGISTER_MAP[register]["name"]
        return make_verdict(
            "", False,
            (f"TELEMETRY_MISMATCH:{name} commanded={commanded_value:.2f} "
             f"reported={reported_value:.2f} deviation={deviation:.2f} > tol={tolerance:.2f}"),
            "physical",
        )

    return make_verdict("", True, "OK", "physical")
