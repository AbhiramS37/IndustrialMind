# docs/interfaces.py

TANK_PRESSURE = 0
CONVEYOR_SPEED = 1
COOLING_VALVE = 2

REGISTER_MAP = {
    TANK_PRESSURE: {"name": "TANK_PRESSURE", "min": 0, "max": 100, "unit": "PSI"},
    CONVEYOR_SPEED: {"name": "CONVEYOR_SPEED", "min": 0, "max": 120, "unit": "RPM"},
    COOLING_VALVE: {"name": "COOLING_VALVE", "min": 0, "max": 90, "unit": "deg"},
}

def make_command(tx_id, timestamp, source_ip, function_code, register, value):
    return {
        "tx_id": tx_id,
        "timestamp": timestamp,
        "source_ip": source_ip,
        "function_code": function_code,
        "register": register,
        "value": value,
    }

def make_verdict(tx_id, passed, reason, agent):
    return {"tx_id": tx_id, "pass": passed, "reason": reason, "agent": agent}

def make_decision(tx_id, verdict, reason, latency_ms, direction):
    return {
        "tx_id": tx_id,
        "verdict": verdict,      # "PASS" or "DROP"
        "reason": reason,
        "latency_ms": latency_ms,
        "direction": direction,  # "downstream" or "upstream"
    }