"""
Cyber Agent — checks traffic-level behavior of incoming Modbus commands.
Does NOT care what a value means physically — only how it arrived.
"""

import time
from collections import defaultdict, deque

from docs.interfaces import make_verdict

# ---- Configuration ----
RATE_LIMIT_PER_SEC = 5
RATE_WINDOW_SECONDS = 1.0
VALID_FUNCTION_CODES = {3, 6, 16}   # read holding regs, write single, write multiple
ALLOWED_REGISTERS = {0, 1, 2}
SOURCE_WHITELIST = {"192.168.1.10"}  # SCADA's IP — adjust to your test setup
REPLAY_WINDOW_SECONDS = 2.0

# ---- Internal state ----
_request_timestamps = defaultdict(deque)   # source_ip -> timestamps
_recent_payloads = defaultdict(deque)      # source_ip -> (payload, timestamp)


def _check_rate(source_ip, now):
    dq = _request_timestamps[source_ip]
    dq.append(now)
    while dq and now - dq[0] > RATE_WINDOW_SECONDS:
        dq.popleft()
    return len(dq) <= RATE_LIMIT_PER_SEC


def _check_replay(command, now):
    source_ip = command["source_ip"]
    payload_key = (command["function_code"], command["register"], command["value"])
    dq = _recent_payloads[source_ip]
    while dq and now - dq[0][1] > REPLAY_WINDOW_SECONDS:
        dq.popleft()
    is_replay = any(p == payload_key for p, _ in dq)
    dq.append((payload_key, now))
    return not is_replay


def check(command: dict) -> dict:
    """Evaluate a command dict (see make_command) against cyber-level rules."""
    now = command.get("timestamp", time.time())
    source_ip = command.get("source_ip", "")
    tx_id = command.get("tx_id", "")

    if source_ip not in SOURCE_WHITELIST:
        return make_verdict(tx_id, False, "UNTRUSTED_SOURCE", "cyber")

    if command.get("function_code") not in VALID_FUNCTION_CODES:
        return make_verdict(tx_id, False, "INVALID_FUNCTION_CODE", "cyber")

    if command.get("register") not in ALLOWED_REGISTERS:
        return make_verdict(tx_id, False, "INVALID_REGISTER", "cyber")

    if not _check_rate(source_ip, now):
        return make_verdict(tx_id, False, "RATE_LIMIT_EXCEEDED", "cyber")

    if not _check_replay(command, now):
        return make_verdict(tx_id, False, "REPLAY_DETECTED", "cyber")

    return make_verdict(tx_id, True, "OK", "cyber")


def reset_state():
    """Clears rate/replay tracking — call this between test runs."""
    _request_timestamps.clear()
    _recent_payloads.clear()