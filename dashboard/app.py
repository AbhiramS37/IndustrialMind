"""
dashboard/app.py

Industrial Mind - Real SCADA / PLC Security Dashboard.

SCADA -> PLC:
    Security decisions made by middleware.

PLC -> SCADA:
    Only actual PLC confirmations.

No simulated security events.
"""

import os
import sys
import subprocess
import threading
import time
from collections import deque

from flask import Flask, jsonify, render_template, request

try:
    import psutil
except ImportError:
    psutil = None


# =========================================================
# CONFIG
# =========================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

app = Flask(__name__)

MAX_EVENTS = 100

_lock = threading.Lock()

_scada_to_plc = deque(maxlen=MAX_EVENTS)
_plc_to_scada = deque(maxlen=MAX_EVENTS)

_cpu_history = deque(maxlen=60)

_metrics = {
    "total": 0,
    "pass": 0,
    "drop": 0,
}

_telemetry = {
    "TANK_PRESSURE": 50.0,
    "CONVEYOR_SPEED": 0.0,
    "COOLING_VALVE": 45.0,
}


# =========================================================
# TRANSACTION ID MAPPING
# =========================================================

_event_counter = 0
_tx_id_map = {}


def _short_tx_id(tx_id):
    """
    Convert long UUID into a short dashboard ID.

    The same original transaction ID ALWAYS gets
    the same short ID.

    Example:

        long UUID -> TX-001
        same UUID -> TX-001
    """

    global _event_counter

    if not tx_id or tx_id == "-":
        _event_counter += 1
        return f"TX-{_event_counter:03d}"

    tx_id = str(tx_id)

    if tx_id.startswith("TX-"):
        return tx_id

    if tx_id in _tx_id_map:
        return _tx_id_map[tx_id]

    _event_counter += 1

    short_id = f"TX-{_event_counter:03d}"

    _tx_id_map[tx_id] = short_id

    return short_id


# =========================================================
# TIME
# =========================================================

def _format_time(timestamp=None):

    try:

        if timestamp is None:
            timestamp = time.time()

        timestamp = float(timestamp)

        return time.strftime(
            "%H:%M:%S",
            time.localtime(timestamp)
        )

    except Exception:

        return time.strftime(
            "%H:%M:%S"
        )


# =========================================================
# SCADA -> PLC EVENT
# =========================================================

def add_scada_event(event):

    verdict = str(
        event.get(
            "verdict",
            "UNKNOWN"
        )
    ).upper()

    event = {
        "tx_id": _short_tx_id(
            event.get("tx_id")
        ),

        "command": event.get(
            "command",
            "-"
        ),

        "verdict": verdict,

        "reason": event.get(
            "reason",
            "-"
        ),

        "latency_ms": event.get(
            "latency_ms",
            0
        ),

        "timestamp": _format_time(
            event.get("timestamp")
        ),
    }

    with _lock:

        _scada_to_plc.appendleft(event)

        _metrics["total"] += 1

        if verdict == "PASS":
            _metrics["pass"] += 1

        elif verdict == "DROP":
            _metrics["drop"] += 1


# =========================================================
# PLC -> SCADA EVENT
# =========================================================

def add_plc_event(event):

    event = {
        "tx_id": _short_tx_id(
            event.get("tx_id")
        ),

        "command": event.get(
            "command",
            "-"
        ),

        "verdict": str(
            event.get(
                "verdict",
                "PASS"
            )
        ).upper(),

        "reason": event.get(
            "reason",
            "PLC confirmed the requested value."
        ),

        "latency_ms": event.get(
            "latency_ms",
            0
        ),

        "timestamp": _format_time(
            event.get("timestamp")
        ),
    }

    with _lock:

        _plc_to_scada.appendleft(
            event
        )


# =========================================================
# TELEMETRY
# =========================================================

def update_telemetry(registers):

    with _lock:

        for name in (
            "TANK_PRESSURE",
            "CONVEYOR_SPEED",
            "COOLING_VALVE",
        ):

            if name in registers:

                try:

                    _telemetry[name] = float(
                        registers[name]
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    pass


# =========================================================
# CPU HISTORY
# =========================================================

def update_cpu_history():

    if psutil is None:
        return

    try:

        cpu = psutil.cpu_percent(
            interval=None
        )

        with _lock:

            _cpu_history.append({
                "time": time.strftime(
                    "%H:%M:%S"
                ),
                "value": round(
                    float(cpu),
                    1
                )
            })

    except Exception:
        pass


def _cpu_loop():

    if psutil is not None:

        psutil.cpu_percent(
            interval=None
        )

    while True:

        update_cpu_history()

        time.sleep(1)


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


@app.route(
    "/api/security-event",
    methods=["POST"]
)
def security_event():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    direction = data.get(
        "direction",
        "scada_to_plc"
    )

    if direction == "scada_to_plc":

        add_scada_event(data)

    elif direction == "plc_to_scada":

        add_plc_event(data)

    return jsonify({
        "success": True
    })


@app.route(
    "/api/telemetry",
    methods=["POST"]
)
def telemetry():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    registers = data.get(
        "registers",
        data
    )

    update_telemetry(
        registers
    )

    return jsonify({
        "success": True
    })


@app.route(
    "/api/dashboard",
    methods=["GET"]
)
def dashboard_data():

    with _lock:

        return jsonify({

            "overview": {
                "total_requests":
                    _metrics["total"],

                "pass":
                    _metrics["pass"],

                "drop":
                    _metrics["drop"],
            },

            "scada_to_plc":
                list(_scada_to_plc),

            "plc_to_scada":
                list(_plc_to_scada),

            "telemetry": {

                "registers":
                    dict(_telemetry),

                "cpu_load":
                    (
                        _cpu_history[-1]["value"]
                        if _cpu_history
                        else 0
                    ),
            },

            "cpu_history":
                list(_cpu_history),
        })


# =========================================================
# ATTACK TRIGGER
# =========================================================

@app.route(
    "/api/trigger-attack",
    methods=["POST"]
)
def trigger_attack():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    attack = data.get(
        "attack"
    )

    allowed = {
        "flood",
        "impossible-command",
        "replay",
        "false-injection",
    }

    if attack not in allowed:

        return jsonify({
            "success": False,
            "error": "Invalid attack type"
        }), 400

    try:

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "attacker.attacker",
                attack
            ],
            cwd=PROJECT_ROOT
        )

        print(
            f"[DASHBOARD] "
            f"Launching attack: {attack}"
        )

        return jsonify({
            "success": True,
            "attack": attack
        })

    except Exception as e:

        print(
            f"[DASHBOARD] "
            f"Attack failed: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# RESET
# =========================================================

@app.route(
    "/api/reset",
    methods=["POST"]
)
def reset_dashboard():

    global _event_counter

    with _lock:

        _scada_to_plc.clear()

        _plc_to_scada.clear()

        _cpu_history.clear()

        _metrics["total"] = 0
        _metrics["pass"] = 0
        _metrics["drop"] = 0

        _telemetry[
            "TANK_PRESSURE"
        ] = 50.0

        _telemetry[
            "CONVEYOR_SPEED"
        ] = 0.0

        _telemetry[
            "COOLING_VALVE"
        ] = 45.0

        _event_counter = 0
        _tx_id_map.clear()

    print(
        "[DASHBOARD] Reset"
    )

    return jsonify({
        "success": True
    })


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=_cpu_loop,
        daemon=True
    ).start()

    print()
    print("=" * 60)
    print(
        " 🛡️ INDUSTRIAL MIND SECURITY MONITORING SYSTEM"
    )
    print("=" * 60)
    print(
        " Dashboard: http://127.0.0.1:5050"
    )
    print(
        " Security API: "
        "http://127.0.0.1:5050/api/security-event"
    )
    print("=" * 60)
    print()

    app.run(
        host="127.0.0.1",
        port=5050,
        debug=False,
        use_reloader=False
    )