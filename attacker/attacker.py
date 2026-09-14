"""
attacker/attacker.py — Cyber Attack Demonstration Tool for Industrial Mind

Demonstrates four cyber attack vectors against the security middleware:
1. flood — High-frequency command burst triggering RATE_LIMIT_EXCEEDED (Cyber Agent).
2. false-injection — False telemetry feedback payload triggering TELEMETRY_MISMATCH (Physical Agent).
3. impossible-command — Out-of-bounds physical command triggering PHYSICS_VIOLATION (Physical Agent).
4. replay — Duplicate payload retransmitted within replay window triggering REPLAY_DETECTED (Cyber Agent).
"""

import sys
import time
from pymodbus.client import ModbusTcpClient

from docs.interfaces import make_command
from middleware.cyber_agent import check as cyber_check
from middleware.physical_agent import check_command as phys_check_command, check_feedback as phys_check_feedback
from middleware.orchestrator import decide

PLC_HOST = "127.0.0.1"
PLC_PORT = 5020
SCALE = 10


def send_through_middleware(command_dict: dict, is_telemetry_feedback: bool = False) -> dict:
    """
    Routes an attack command payload through the complete
    Cyber Agent -> Physical Agent -> Orchestrator security pipeline.
    If the decision is PASS, executes the write to the real PLC.
    """
    start_t = time.time()

    if is_telemetry_feedback:
        # Upstream path: Cyber Agent is None, Physical Agent validates telemetry feedback
        phys_v = phys_check_feedback(command_dict)
        decision = decide(None, phys_v, start_t)
        cyber_v = {"tx_id": command_dict["tx_id"], "pass": True, "reason": "N/A (Upstream)", "agent": "cyber"}
    else:
        # Downstream path: Cyber Agent -> Physical Agent -> Orchestrator
        cyber_v = cyber_check(command_dict)
        phys_v = phys_check_command(command_dict)

        reg = command_dict.get("register", "N/A")
        val = command_dict.get("value", "N/A")
        phys_v["command"] = f"WRITE_REGISTER {hex(reg) if isinstance(reg, int) else reg} {val}"

        decision = decide(cyber_v, phys_v, start_t)

        # Forward to PLC ONLY if decision is PASS
        if decision["verdict"] == "PASS":
            client = ModbusTcpClient(PLC_HOST, port=PLC_PORT)
            if client.connect():
                try:
                    raw_val = int(command_dict["value"] * SCALE)
                    client.write_register(address=command_dict["register"], value=raw_val, slave=1)
                except Exception as e:
                    print(f"[PLC Write Warning] {e}")
                finally:
                    client.close()

    return {
        "command": command_dict,
        "cyber_verdict": cyber_v,
        "physical_verdict": phys_v,
        "decision": decision
    }


def attack_flood():
    print("\n--- [ATTACK MODE: FLOOD] ---")
    source_ip = "192.168.1.10"
    results = []

    # Send a controlled burst of 7 rapid requests (limit is 5/sec)
    for i in range(7):
        tx_id = f"ATK-FLD-{int(time.time()*1000)}-{i}"
        cmd = make_command(
            tx_id=tx_id,
            timestamp=time.time(),
            source_ip=source_ip,
            function_code=6,
            register=1,
            value=40.0 + i
        )
        res = send_through_middleware(cmd)
        results.append(res)
        print(f"Request #{i+1} [{tx_id}]: Cyber={res['cyber_verdict']['reason']} | Physical={res['physical_verdict']['reason']} => Verdict={res['decision']['verdict']}")
        time.sleep(0.05)

    return results


def attack_false_injection():
    print("\n--- [ATTACK MODE: FALSE INJECTION] ---")
    tx_id = f"ATK-INJ-{int(time.time())}"
    # Valid SCADA IP (192.168.1.10) & valid function code (6), but forged negative telemetry speed (-50.0 RPM)
    # Exceeds physical bounds [0, 120] in REGISTER_MAP
    cmd = make_command(
        tx_id=tx_id,
        timestamp=time.time(),
        source_ip="192.168.1.10",
        function_code=6,
        register=1,  # CONVEYOR_SPEED
        value=-50.0   # Physically impossible negative speed telemetry
    )
    res = send_through_middleware(cmd, is_telemetry_feedback=True)
    print(f"Payload: Register=1 (CONVEYOR_SPEED), Value=-50.0 RPM (Abnormal negative telemetry)")
    print(f"Target Security Layer: Physical Agent telemetry validation (check_feedback)")
    print(f"Physical Verdict: {res['physical_verdict']}")
    print(f"Orchestrator Decision: {res['decision']}")
    return res


def attack_impossible_command():
    print("\n--- [ATTACK MODE: IMPOSSIBLE COMMAND] ---")
    tx_id = f"ATK-IMP-{int(time.time())}"
    # Valid SCADA IP (192.168.1.10), valid function code (6), valid register index (0: TANK_PRESSURE)
    # But physically impossible value (999.0 PSI > max 100.0 PSI in REGISTER_MAP)
    cmd = make_command(
        tx_id=tx_id,
        timestamp=time.time(),
        source_ip="192.168.1.10",
        function_code=6,
        register=0,   # TANK_PRESSURE
        value=999.0   # Physically impossible pressure (> 100 PSI)
    )
    res = send_through_middleware(cmd)
    print(f"Payload: Source IP=192.168.1.10, Register=0 (TANK_PRESSURE), Value=999.0 PSI")
    print(f"Target Security Layer: Physical Agent command validation (check_command)")
    print(f"Cyber Verdict: {res['cyber_verdict']}")
    print(f"Physical Verdict: {res['physical_verdict']}")
    print(f"Orchestrator Decision: {res['decision']}")
    return res


def attack_replay():
    print("\n--- [ATTACK MODE: REPLAY] ---")
    source_ip = "192.168.1.10"
    reg = 2
    val = 30.0

    # 1. First Legitimate Send
    tx_1 = f"ATK-RPLY-LEGIT-{int(time.time())}"
    cmd1 = make_command(tx_id=tx_1, timestamp=time.time(), source_ip=source_ip, function_code=6, register=reg, value=val)
    res1 = send_through_middleware(cmd1)
    print(f"Legitimate Send [{tx_1}]: Cyber={res1['cyber_verdict']['reason']} | Physical={res1['physical_verdict']['reason']} => Verdict={res1['decision']['verdict']}")

    time.sleep(0.1)

    # 2. Replay Identical Payload within 2 second window
    tx_2 = f"ATK-RPLY-REUSE-{int(time.time())}"
    cmd2 = make_command(tx_id=tx_2, timestamp=time.time(), source_ip=source_ip, function_code=6, register=reg, value=val)
    res2 = send_through_middleware(cmd2)
    print(f"Replay Send [{tx_2}]: Cyber={res2['cyber_verdict']['reason']} | Physical={res2['physical_verdict']['reason']} => Verdict={res2['decision']['verdict']}")

    return res1, res2


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 attacker/attacker.py [flood | false-injection | impossible-command | replay]")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "flood":
        attack_flood()
    elif mode == "false-injection":
        attack_false_injection()
    elif mode == "impossible-command":
        attack_impossible_command()
    elif mode == "replay":
        attack_replay()
    else:
        print(f"Unknown attack mode: {mode}")
        print("Available modes: flood, false-injection, impossible-command, replay")
        sys.exit(1)


if __name__ == "__main__":
    main()
