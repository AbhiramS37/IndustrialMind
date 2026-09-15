"""
scada/scada.py

SCADA operator simulation.

Sends one Modbus write every 2 seconds to the middleware.

Flow:
    SCADA -> Middleware :5021 -> PLC :5020
"""

import argparse
import random
import time
import uuid

from pymodbus.client import ModbusTcpClient

from docs.interfaces import REGISTER_MAP


# ============================================================
# CONFIGURATION
# ============================================================

SCADA_SOURCE_IP = "192.168.1.10"

FUNCTION_CODE = 6
SCALE = 10

COMMAND_INTERVAL = 2.0


# ============================================================
# OPERATOR PROFILES
# ============================================================

OPERATOR_PROFILES = {
    "pressure": {
        "register": 0,
        "target": 60.0,
        "step": 1.0,
        "current": 50.0,
    },

    "conveyor": {
        "register": 1,
        "target": 80.0,
        "step": 2.0,
        "current": 0.0,
    },

    "valve": {
        "register": 2,
        "target": 60.0,
        "step": 1.0,
        "current": 45.0,
    },
}


# ============================================================
# SETPOINT GENERATION
# ============================================================

def _next_setpoint(name):
    """
    Gradually move the simulated operator value
    toward the target value.
    """

    profile = OPERATOR_PROFILES[name]

    current = profile["current"]
    target = profile["target"]
    step = profile["step"]

    if current < target:
        current = min(current + step, target)

    elif current > target:
        current = max(current - step, target)

    profile["current"] = current

    return current


# ============================================================
# VALUE CONVERSION
# ============================================================

def _to_raw(register, value):
    """
    Convert engineering value into Modbus register value.
    """

    config = REGISTER_MAP[register]

    minimum = config["min"]
    maximum = config["max"]

    value = max(minimum, min(maximum, value))

    return int(round(value * SCALE))


# ============================================================
# SEND MODBUS WRITE
# ============================================================

def send_write(client, register, value):
    """
    Send one holding-register write to middleware.
    """

    raw_value = _to_raw(register, value)

    tx_id = str(uuid.uuid4())[:8]

    register_name = REGISTER_MAP[register]["name"]

    print(
        f"[SCADA] WRITE "
        f"tx={tx_id} "
        f"reg={register_name} "
        f"value={value:.2f}"
    )

    try:
        result = client.write_register(
            address=register,
            value=raw_value,
            slave=1
        )

        if result.isError():
            print(
                f"[SCADA] WRITE FAILED "
                f"tx={tx_id} "
                f"reg={register_name}"
            )

        else:
            print(
                f"[SCADA] WRITE SENT "
                f"tx={tx_id} "
                f"reg={register_name} "
                f"value={value:.2f}"
            )

    except Exception as e:
        print(
            f"[SCADA] ERROR "
            f"tx={tx_id}: {e}"
        )


# ============================================================
# OPERATOR SIMULATION
# ============================================================

def run_operator_loop(host="127.0.0.1", port=5021):
    """
    Connect to middleware and continuously simulate
    normal SCADA operator commands.

    Exactly ONE command is sent every 2 seconds.
    """

    client = ModbusTcpClient(
        host,
        port=port
    )

    print()
    print("=" * 60)
    print(" SCADA OPERATOR SIMULATION")
    print("=" * 60)

    print(
        f"[SCADA] Connecting to "
        f"{host}:{port} ..."
    )

    if not client.connect():
        print("[SCADA] Connection failed.")
        return

    print("[SCADA] Connected successfully.")
    print(
        "[SCADA] Sending ONE command every "
        f"{COMMAND_INTERVAL:.0f} seconds."
    )
    print("[SCADA] Press Ctrl-C to stop.")
    print()

    # Rotate through the three plant parameters.
    registers = [
        "pressure",
        "conveyor",
        "valve",
    ]

    index = 0

    try:

        while True:

            name = registers[index]

            profile = OPERATOR_PROFILES[name]

            register = profile["register"]

            value = _next_setpoint(name)

            send_write(
                client=client,
                register=register,
                value=value
            )

            # Move to the next parameter.
            index = (index + 1) % len(registers)

            # Wait exactly 2 seconds before
            # generating the next command.
            time.sleep(COMMAND_INTERVAL)

    except KeyboardInterrupt:

        print()
        print("[SCADA] Operator simulation stopped.")

    finally:

        client.close()

        print("[SCADA] Connection closed.")


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Industrial Mind SCADA simulator"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Middleware host"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5021,
        help="Middleware Modbus port"
    )

    args = parser.parse_args()

    run_operator_loop(
        host=args.host,
        port=args.port
    )


if __name__ == "__main__":
    main()