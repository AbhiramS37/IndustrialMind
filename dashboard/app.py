import os
import random
import time
import uuid
from datetime import datetime
from threading import Lock, Thread
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ==========================================
# THREAD-SAFE STATE STORE & MOCK SIMULATOR
# ==========================================
state_lock = Lock()

dashboard_state = {
    "scada_to_plc": {
        "total_requests": 412,
        "pass_count": 365,
        "drop_count": 47,
        "decision_log": []
    },
    "plc_to_scada": {
        "total_requests": 412,
        "pass_count": 365,
        "drop_count": 47,
        "decision_log": []
    },
    "telemetry": {
        "registers": {
            "TANK_PRESSURE": 65.0,   # PSI (0 - 100)
            "CONVEYOR_SPEED": 80.0,  # RPM (0 - 120)
            "COOLING_VALVE": 45.0,   # Degrees (0 - 90)
        },
        "cpu_load": 32.0,            # Percentage (0 - 100)
        "timestamp": int(time.time())
    },
    "cpu_history": [],
}

# Realistically Paired SCADA Commands & PLC Responses
PASS_COMMAND_PAIRS = [
    {
        "scada_cmd": "Set Motor Speed → 50 RPM",
        "scada_reason": "SCADA requested the conveyor motor speed to be changed to 50 RPM.",
        "plc_cmd": "Motor Speed → 50 RPM",
        "plc_reason": "PLC confirmed that the conveyor motor speed was successfully changed to 50 RPM.",
        "speed": 50.0
    },
    {
        "scada_cmd": "Set Motor Speed → 80 RPM",
        "scada_reason": "SCADA requested the conveyor motor speed to be changed to 80 RPM.",
        "plc_cmd": "Motor Speed → 80 RPM",
        "plc_reason": "PLC confirmed that the conveyor motor speed was successfully changed to 80 RPM.",
        "speed": 80.0
    },
    {
        "scada_cmd": "Open Cooling Valve",
        "scada_reason": "SCADA requested the cooling valve to open.",
        "plc_cmd": "Cooling Valve → OPEN",
        "plc_reason": "PLC confirmed that the cooling valve was opened successfully.",
        "valve": 60.0
    },
    {
        "scada_cmd": "Close Cooling Valve",
        "scada_reason": "SCADA requested the cooling valve to close.",
        "plc_cmd": "Cooling Valve → CLOSED",
        "plc_reason": "PLC confirmed that the cooling valve was closed successfully.",
        "valve": 15.0
    },
    {
        "scada_cmd": "Start Motor",
        "scada_reason": "SCADA requested the conveyor motor to start.",
        "plc_cmd": "Conveyor → RUNNING",
        "plc_reason": "PLC reported that the conveyor motor started successfully."
    },
    {
        "scada_cmd": "Stop Motor",
        "scada_reason": "SCADA requested the conveyor motor to stop.",
        "plc_cmd": "Conveyor → STOPPED",
        "plc_reason": "PLC confirmed that the conveyor motor stopped successfully."
    },
    {
        "scada_cmd": "Set Tank Pressure → 65 PSI",
        "scada_reason": "SCADA requested tank pressure to be set to baseline of 65 PSI.",
        "plc_cmd": "Tank Pressure → 65 PSI",
        "plc_reason": "PLC confirmed that the tank pressure was updated to 65 PSI.",
        "pressure": 65.0
    },
    {
        "scada_cmd": "Set Tank Pressure → 85 PSI",
        "scada_reason": "SCADA requested tank pressure to be adjusted to 85 PSI.",
        "plc_cmd": "Tank Pressure → 85 PSI",
        "plc_reason": "PLC reported tank pressure updated to 85 PSI.",
        "pressure": 85.0
    }
]

DROP_COMMAND_PAIRS = [
    {
        "scada_cmd": "Set Motor Speed → 120 RPM",
        "scada_reason": "Requested speed exceeds the configured safe limit of 100 RPM.",
        "plc_cmd": "Motor Speed → REJECTED",
        "plc_reason": "PLC rejected the requested speed because it exceeded the configured safety limit."
    },
    {
        "scada_cmd": "Set Tank Pressure → 135 PSI",
        "scada_reason": "Requested pressure exceeds the configured safe limit of 100 PSI.",
        "plc_cmd": "Tank Pressure → ALARM",
        "plc_reason": "PLC physical guardian blocked pressure change exceeding 100 PSI."
    },
    {
        "scada_cmd": "Set Cooling Valve → 105°",
        "scada_reason": "The requested valve angle exceeds the configured physical safety limit of 90°.",
        "plc_cmd": "Cooling Valve → FAULT",
        "plc_reason": "PLC reported that the requested operation could not be completed because the value exceeded safety limits."
    },
    {
        "scada_cmd": "Rapid Valve Override",
        "scada_reason": "High frequency command burst detected from SCADA endpoint exceeding rate limit.",
        "plc_cmd": "Valve Control → BLOCKED",
        "plc_reason": "PLC rate limiter dropped high frequency command request."
    },
    {
        "scada_cmd": "Replay Command TX-4821",
        "scada_reason": "Replay attack detected: duplicate sequence nonce received.",
        "plc_cmd": "Sequence Nonce → INVALID",
        "plc_reason": "PLC rejected command packet due to invalid sequence identifier."
    }
]


def seed_initial_decisions():
    now = time.time()
    for i in range(15, 0, -1):
        t_stamp = datetime.fromtimestamp(now - (i * 3)).strftime("%H:%M:%S")
        is_drop = random.random() < 0.15
        tx_raw = uuid.uuid4().hex[:4].upper()
        latency_scada = round(random.uniform(2.1, 4.2), 1)
        latency_plc = round(random.uniform(1.8, 3.9), 1)

        if is_drop:
            pair = random.choice(DROP_COMMAND_PAIRS)
            verdict = "DROP"
        else:
            pair = random.choice(PASS_COMMAND_PAIRS)
            verdict = "PASS"

        # SCADA -> PLC Event
        dashboard_state["scada_to_plc"]["decision_log"].append({
            "tx_id": f"TX-{tx_raw}",
            "command": pair["scada_cmd"],
            "verdict": verdict,
            "reason": pair["scada_reason"],
            "latency_ms": latency_scada,
            "timestamp": t_stamp
        })

        # PLC -> SCADA Event
        dashboard_state["plc_to_scada"]["decision_log"].append({
            "tx_id": f"PLC-{tx_raw}",
            "command": pair["plc_cmd"],
            "verdict": verdict,
            "reason": pair["plc_reason"],
            "latency_ms": latency_plc,
            "timestamp": t_stamp
        })

    # Seed CPU history
    for i in range(20, 0, -1):
        t_label = datetime.fromtimestamp(now - (i * 3)).strftime("%H:%M:%S")
        load = round(random.uniform(28.0, 36.0), 1)
        dashboard_state["cpu_history"].append({
            "time": t_label,
            "cpu_load": load
        })

seed_initial_decisions()


def generate_simulated_event(force_attack=False):
    with state_lock:
        now_str = datetime.now().strftime("%H:%M:%S")
        tx_raw = uuid.uuid4().hex[:4].upper()
        tx_scada = f"TX-{tx_raw}"
        tx_plc = f"PLC-{tx_raw}"

        if force_attack:
            is_drop = True
            pair = random.choice(DROP_COMMAND_PAIRS)
        else:
            is_drop = random.random() < 0.12
            pair = random.choice(DROP_COMMAND_PAIRS) if is_drop else random.choice(PASS_COMMAND_PAIRS)

        verdict = "DROP" if is_drop else "PASS"
        latency_scada = round(random.uniform(2.1, 4.8 if is_drop else 3.5), 1)
        latency_plc = round(random.uniform(1.8, 4.2 if is_drop else 3.1), 1)

        # Update Counts
        dashboard_state["scada_to_plc"]["total_requests"] += 1
        dashboard_state["plc_to_scada"]["total_requests"] += 1

        if is_drop:
            dashboard_state["scada_to_plc"]["drop_count"] += 1
            dashboard_state["plc_to_scada"]["drop_count"] += 1
        else:
            dashboard_state["scada_to_plc"]["pass_count"] += 1
            dashboard_state["plc_to_scada"]["pass_count"] += 1

        # Append SCADA -> PLC Event
        scada_event = {
            "tx_id": tx_scada,
            "command": pair["scada_cmd"],
            "verdict": verdict,
            "reason": pair["scada_reason"],
            "latency_ms": latency_scada,
            "timestamp": now_str
        }
        dashboard_state["scada_to_plc"]["decision_log"].insert(0, scada_event)
        if len(dashboard_state["scada_to_plc"]["decision_log"]) > 40:
            dashboard_state["scada_to_plc"]["decision_log"].pop()

        # Append PLC -> SCADA Event
        plc_event = {
            "tx_id": tx_plc,
            "command": pair["plc_cmd"],
            "verdict": verdict,
            "reason": pair["plc_reason"],
            "latency_ms": latency_plc,
            "timestamp": now_str
        }
        dashboard_state["plc_to_scada"]["decision_log"].insert(0, plc_event)
        if len(dashboard_state["plc_to_scada"]["decision_log"]) > 40:
            dashboard_state["plc_to_scada"]["decision_log"].pop()

        # Fluctuate telemetry values
        registers = dashboard_state["telemetry"]["registers"]
        if not is_drop and "pressure" in pair:
            registers["TANK_PRESSURE"] = pair["pressure"]
        elif not is_drop and "speed" in pair:
            registers["CONVEYOR_SPEED"] = pair["speed"]
        elif not is_drop and "valve" in pair:
            registers["COOLING_VALVE"] = pair["valve"]
        else:
            registers["TANK_PRESSURE"] = round(min(100.0, max(0.0, registers["TANK_PRESSURE"] + random.uniform(-1.0, 1.0))), 1)
            registers["CONVEYOR_SPEED"] = round(min(120.0, max(0.0, registers["CONVEYOR_SPEED"] + random.uniform(-1.2, 1.2))), 1)
            registers["COOLING_VALVE"] = round(min(90.0, max(0.0, registers["COOLING_VALVE"] + random.uniform(-0.8, 0.8))), 1)

        # CPU load calculation
        cpu_target = random.uniform(65.0, 85.0) if is_drop else random.uniform(25.0, 36.0)
        current_cpu = dashboard_state["telemetry"]["cpu_load"]
        new_cpu = round(current_cpu * 0.4 + cpu_target * 0.6, 1)
        dashboard_state["telemetry"]["cpu_load"] = new_cpu
        dashboard_state["telemetry"]["timestamp"] = int(time.time())

        # Update CPU history
        dashboard_state["cpu_history"].append({
            "time": now_str,
            "cpu_load": new_cpu
        })
        if len(dashboard_state["cpu_history"]) > 25:
            dashboard_state["cpu_history"].pop(0)

        return scada_event, plc_event


# Background thread daemon
def background_simulator():
    while True:
        try:
            generate_simulated_event()
        except Exception as e:
            print(f"[Simulator Error] {e}")
        time.sleep(2.5)


# ==========================================
# FLASK WEB ROUTE (SINGLE DASHBOARD SCREEN)
# ==========================================
@app.route("/")
def index():
    """Renders the unified Industrial Mind Dashboard."""
    return render_template("index.html")


# ==========================================
# CONSOLIDATED API DATA ENDPOINT
# ==========================================
@app.route("/api/dashboard", methods=["GET"])
def get_dashboard_data():
    """Returns overview KPIs, SCADA->PLC log, PLC->SCADA log, telemetry, and CPU history."""
    with state_lock:
        total_msg = dashboard_state["scada_to_plc"]["total_requests"] + dashboard_state["plc_to_scada"]["total_requests"]
        total_pass = dashboard_state["scada_to_plc"]["pass_count"] + dashboard_state["plc_to_scada"]["pass_count"]
        total_drop = dashboard_state["scada_to_plc"]["drop_count"] + dashboard_state["plc_to_scada"]["drop_count"]

        return jsonify({
            "overview": {
                "total_requests": total_msg,
                "pass": total_pass,
                "drop": total_drop
            },
            "scada_to_plc": list(dashboard_state["scada_to_plc"]["decision_log"]),
            "plc_to_scada": list(dashboard_state["plc_to_scada"]["decision_log"]),
            "telemetry": dict(dashboard_state["telemetry"]),
            "cpu_history": list(dashboard_state["cpu_history"])
        })


@app.route("/api/trigger-attack", methods=["POST"])
def trigger_attack():
    scada_ev, plc_ev = generate_simulated_event(force_attack=True)
    return jsonify({
        "status": "success",
        "scada_event": scada_ev,
        "plc_event": plc_ev
    })


@app.route("/api/reset", methods=["POST"])
def reset_metrics():
    with state_lock:
        dashboard_state["scada_to_plc"]["total_requests"] = 0
        dashboard_state["scada_to_plc"]["pass_count"] = 0
        dashboard_state["scada_to_plc"]["drop_count"] = 0
        dashboard_state["scada_to_plc"]["decision_log"].clear()

        dashboard_state["plc_to_scada"]["total_requests"] = 0
        dashboard_state["plc_to_scada"]["pass_count"] = 0
        dashboard_state["plc_to_scada"]["drop_count"] = 0
        dashboard_state["plc_to_scada"]["decision_log"].clear()

        dashboard_state["cpu_history"].clear()
        seed_initial_decisions()
    return jsonify({"status": "reset_complete"})


if __name__ == "__main__":
    # Start single background simulator thread
    sim_thread = Thread(target=background_simulator, daemon=True)
    sim_thread.start()

    port = int(os.environ.get("PORT", 5050))
    print("\n=======================================================")
    print(" 🛡️ INDUSTRIAL MIND SECURITY MONITORING SYSTEM ")
    print(f" Unified Dashboard: http://127.0.0.1:{port}")
    print("=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

