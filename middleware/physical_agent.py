"""
middleware/physical_agent.py — Physical Safety Agent for Industrial Mind

Evaluates command payloads and telemetry feedback against physical plant safety limits
defined in docs/interfaces.py (REGISTER_MAP).
"""

from docs.interfaces import REGISTER_MAP, make_verdict


def check_command(command: dict) -> dict:
    """
    Validates physical bounds for downstream commands (SCADA -> PLC).
    Returns a physical verdict dictionary using make_verdict.
    """
    tx_id = command.get("tx_id", "")
    reg = command.get("register")
    val = command.get("value")

    if reg not in REGISTER_MAP:
        return make_verdict(tx_id, False, "PHYSICS_VIOLATION", "physical")

    reg_info = REGISTER_MAP[reg]
    min_val = reg_info["min"]
    max_val = reg_info["max"]

    if val is None or not isinstance(val, (int, float)) or val < min_val or val > max_val:
        return make_verdict(tx_id, False, "PHYSICS_VIOLATION", "physical")

    return make_verdict(tx_id, True, "OK", "physical")


def check_feedback(feedback: dict) -> dict:
    """
    Validates physical bounds for upstream telemetry feedback (PLC -> SCADA).
    Returns a physical verdict dictionary using make_verdict.
    """
    tx_id = feedback.get("tx_id", "")
    reg = feedback.get("register")
    val = feedback.get("value")

    if reg not in REGISTER_MAP:
        return make_verdict(tx_id, False, "TELEMETRY_MISMATCH", "physical")

    reg_info = REGISTER_MAP[reg]
    min_val = reg_info["min"]
    max_val = reg_info["max"]

    if val is None or not isinstance(val, (int, float)) or val < min_val or val > max_val:
        return make_verdict(tx_id, False, "TELEMETRY_MISMATCH", "physical")

    return make_verdict(tx_id, True, "OK", "physical")
