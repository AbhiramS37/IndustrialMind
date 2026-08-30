"""
Orchestrator — fuses Cyber Agent and Physical Agent verdicts into one decision.
DROP if either agent fails. PASS only if both (or the only one running) pass.
On the upstream (PLC -> SCADA) path, cyber_verdict will be None — only the
Physical Agent runs there, per the team's design.
"""

import time

from docs.interfaces import make_decision

_decision_log = []


def decide(cyber_verdict: dict | None, physical_verdict: dict, start_time: float = None) -> dict:
    """
    cyber_verdict: verdict dict from cyber_agent.check(), or None on the upstream path.
    physical_verdict: verdict dict from physical_agent.check_command() or check_feedback().
    start_time: time.time() captured when the command first arrived, for latency measurement.
    """
    tx_id = physical_verdict["tx_id"]
    direction = "downstream" if cyber_verdict is not None else "upstream"

    if cyber_verdict is not None and not cyber_verdict["pass"]:
        verdict, reason = "DROP", cyber_verdict["reason"]
    elif not physical_verdict["pass"]:
        verdict, reason = "DROP", physical_verdict["reason"]
    else:
        verdict, reason = "PASS", "OK"

    latency_ms = round((time.time() - start_time) * 1000, 3) if start_time else 0.0

    decision = make_decision(tx_id, verdict, reason, latency_ms, direction)
    _decision_log.append(decision)
    return decision


def get_log() -> list:
    """Returns all logged decisions so far — this is what the dashboard will read."""
    return list(_decision_log)


def reset_log():
    """Clears the decision log — call this between test runs."""
    _decision_log.clear()