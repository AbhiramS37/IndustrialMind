"""
scada/scada.py — SCADA operator client for Industrial Mind.

Sends periodic, small, in-bounds Modbus writes to the middleware (or directly
to the PLC for standalone testing). Simulates a human operator slowly adjusting
plant setpoints: opening the cooling valve 1° at a time, nudging the conveyor
speed, bleeding tank pressure.

Usage (standalone test — point directly at Sharon's plc.py):
    python -m scada.scada --host 127.0.0.1 --port 5020

Usage (through middleware — normal operation):
    python -m scada.scada --host 127.0.0.1 --port 5502
"""

import argparse
import time
import uuid
import random

from pymodbus.client import ModbusTcpClient

from docs.interfaces import (
    make_command,
    REGISTER_MAP,
    TANK_PRESSURE,
    CONVEYOR_SPEED,
    COOLING_VALVE,
)

# ── Operator profile ────────────────────────────────────────────────────────
# Each register has a setpoint the "operator" is slowly moving toward and a
# step size per write (kept small and realistic).

SCADA_SOURCE_IP = "192.168.1.10"    # must be in the cyber_agent whitelist
FUNCTION_CODE   = 6                  # Write Single Register
_SCALE          = 10                 # Must match plc.py's _SCALE

_OPERATOR_PROFILE = {
    TANK_PRESSURE: {
        "target":   60.0,    # PSI — where the operator wants to end up
        "step":      1.0,    # PSI per write
        "interval":  2.0,    # seconds between writes to this register
    },
    CONVEYOR_SPEED: {
        "target":   80.0,    # RPM
        "step":      2.0,
        "interval":  3.0,
    },
    COOLING_VALVE: {
        "target":   60.0,    # degrees open
        "step":      1.0,
        "interval":  1.5,
    },
}


# ── Internal state ───────────────────────────────────────────────────────────

_last_write_time = {reg: 0.0 for reg in _OPERATOR_PROFILE}
_current_setpoint = {
    TANK_PRESSURE:  50.0,   # start values (match PLC defaults)
    CONVEYOR_SPEED:  0.0,
    COOLING_VALVE:  45.0,
}


def _next_setpoint(register: int) -> float:
    """Advance the operator's setpoint one step toward the target, staying
    within the register's safe range."""
    profile = _OPERATOR_PROFILE[register]
    current = _current_setpoint[register]
    target  = profile["target"]
    step    = profile["step"]

    lo = REGISTER_MAP[register]["min"]
    hi = REGISTER_MAP[register]["max"]

    if current < target:
        new_val = min(current + step, target)
    elif current > target:
        new_val = max(current - step, target)
    else:
        # At target — occasionally drift ±step to simulate human micro-adjustments
        drift = random.choice([-step, 0.0, step])
        new_val = current + drift

    new_val = max(lo, min(hi, new_val))
    _current_setpoint[register] = new_val
    return new_val


def _float_to_raw(value: float) -> int:
    """Convert float plant value to raw 16-bit int using the shared scale factor."""
    return max(0, min(65535, int(round(value * _SCALE))))


def send_write(client: ModbusTcpClient, register: int, value: float) -> dict | None:
    """
    Send a single Modbus write to the server and return the command dict
    that was sent (for logging / testing). Returns None if the connection fails.
    """
    raw = _float_to_raw(value)
    result = client.write_register(register, raw)

    if result.isError():
        print(f"[SCADA] Modbus error writing register {register}: {result}")
        return None

    command = make_command(
        tx_id        = str(uuid.uuid4()),
        timestamp    = time.time(),
        source_ip    = SCADA_SOURCE_IP,
        function_code= FUNCTION_CODE,
        register     = register,
        value        = value,
    )
    print(
        f"[SCADA] WRITE reg={REGISTER_MAP[register]['name']} "
        f"value={value:.2f} {REGISTER_MAP[register]['unit']} "
        f"tx={command['tx_id'][:8]}…"
    )
    return command


def run_operator_loop(host: str = "127.0.0.1", port: int = 5502):
    """
    Main loop: connect to the middleware (or PLC), then send periodic,
    realistic Modbus writes representing a human operator.

    Runs indefinitely until interrupted (Ctrl-C).

    Args:
        host: Target server host.
        port: Target server port.  5502 = middleware, 5020 = PLC directly.
    """
    print(f"[SCADA] Connecting to {host}:{port} …")
    client = ModbusTcpClient(host=host, port=port)

    if not client.connect():
        print(f"[SCADA] ERROR: Could not connect to {host}:{port}")
        return

    print("[SCADA] Connected. Starting operator loop. Press Ctrl-C to stop.")

    try:
        while True:
            now = time.time()

            for register, profile in _OPERATOR_PROFILE.items():
                if now - _last_write_time[register] >= profile["interval"]:
                    value = _next_setpoint(register)
                    send_write(client, register, value)
                    _last_write_time[register] = now

            time.sleep(0.1)   # tight poll; writes are gated by per-register intervals

    except KeyboardInterrupt:
        print("\n[SCADA] Operator loop stopped.")
    finally:
        client.close()


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Industrial Mind SCADA client")
    parser.add_argument("--host", default="127.0.0.1", help="Target host")
    parser.add_argument("--port", type=int, default=5502,
                        help="Target port (5502=middleware, 5020=PLC direct)")
    args = parser.parse_args()
    run_operator_loop(args.host, args.port)
