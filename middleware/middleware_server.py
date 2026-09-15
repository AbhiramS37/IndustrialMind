"""
middleware/middleware_server.py — proxy between SCADA and PLC.

Architecture:

SCADA
  |
  v
Middleware :5021
  |
  |-- DROP --> STOP (never reaches PLC)
  |
  |-- PASS --> PLC :5020
                 |
                 v
             PLC feedback
                 |
                 v
              Middleware
                 |
                 v
               SCADA

Dashboard:
  LEFT  = every SCADA -> PLC security decision
  RIGHT = only actual PLC confirmations for PASSed commands
"""

import time
import threading
import uuid
import requests

from pymodbus.client import ModbusTcpClient
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)
from pymodbus.server import StartTcpServer

from docs.interfaces import (
    make_command,
    REGISTER_MAP,
    TANK_PRESSURE,
    CONVEYOR_SPEED,
    COOLING_VALVE,
)

from middleware import (
    cyber_agent,
    physical_agent,
    orchestrator,
)


# =========================================================
# CONFIG
# =========================================================

PLC_HOST = "127.0.0.1"
PLC_PORT = 5020

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5021

DASHBOARD_URL = "http://127.0.0.1:5050"

SCALE = 10

# PLC is checked frequently for real feedback.
POLL_INTERVAL = 0.2

# Dashboard telemetry does not need to be sent every
# PLC polling cycle.
TELEMETRY_REPORT_INTERVAL = 1.0

DEFAULT_SOURCE_IP = "192.168.1.10"

FEEDBACK_SETTLED_TOLERANCE = 0.05


_ALL_REGISTERS = (
    TANK_PRESSURE,
    CONVEYOR_SPEED,
    COOLING_VALVE,
)


# =========================================================
# SHARED STATE
# =========================================================

_state_lock = threading.Lock()

_plc_state = {
    "registers": {
        TANK_PRESSURE: 50.0,
        CONVEYOR_SPEED: 0.0,
        COOLING_VALVE: 45.0,
    },
    "timestamp": time.time(),
}


# Only PASSed commands that were actually forwarded
# to the PLC are stored here.
_pending_commands = {}


_register_settled_since = {
    reg: time.time() - 3.0
    for reg in _ALL_REGISTERS
}


_plc_client: ModbusTcpClient | None = None

_last_telemetry_report = 0.0


# =========================================================
# RAW / REAL VALUE CONVERSION
# =========================================================

def _to_raw(value: float) -> int:
    return max(
        0,
        min(
            65535,
            int(round(value * SCALE))
        )
    )


def _from_raw(raw: int) -> float:
    return raw / SCALE


# =========================================================
# MODBUS DATA BLOCK
# =========================================================

class MiddlewareDataBlock(ModbusSequentialDataBlock):
    """
    SCADA-facing holding registers.

    External writes enter here and are processed by
    the security pipeline.
    """

    def setValues(self, address, values):

        # Store the value locally first.
        super().setValues(address, values)

        # Process every affected register.
        for i, raw_value in enumerate(values):

            register = address + i

            if register in _ALL_REGISTERS:

                value = _from_raw(raw_value)

                _handle_downstream_write(
                    register,
                    value
                )


# =========================================================
# SCADA -> PLC
# =========================================================

def _handle_downstream_write(
    register: int,
    value: float
):

    start_time = time.time()

    tx_id = str(uuid.uuid4())

    register_name = REGISTER_MAP[register]["name"]

    # -----------------------------------------------------
    # Build command
    # -----------------------------------------------------

    command = make_command(
        tx_id=tx_id,
        timestamp=start_time,
        source_ip=DEFAULT_SOURCE_IP,
        function_code=6,
        register=register,
        value=value,
    )

    # -----------------------------------------------------
    # Cyber Agent
    # -----------------------------------------------------

    cyber_verdict = cyber_agent.check(
        command
    )

    # -----------------------------------------------------
    # Current PLC state
    # -----------------------------------------------------

    with _state_lock:

        current_state = {
            "registers": dict(
                _plc_state["registers"]
            ),

            "timestamp": _register_settled_since[
                register
            ],
        }

    # -----------------------------------------------------
    # Physical Agent
    # -----------------------------------------------------

    physical_verdict = physical_agent.check_command(
        command,
        current_state
    )

    # Human-readable command for dashboard.
    physical_verdict["command"] = (
        f"{register_name} → {value:.2f}"
    )

    # -----------------------------------------------------
    # Orchestrator
    # -----------------------------------------------------

    decision = orchestrator.decide(
        cyber_verdict,
        physical_verdict,
        start_time
    )

    # -----------------------------------------------------
    # Terminal output
    # -----------------------------------------------------

    print(
        f"[MIDDLEWARE] "
        f"{decision['verdict']:4s} "
        f"{register_name}={value:.2f} "
        f"reason={decision['reason']}"
    )

    # -----------------------------------------------------
    # DROP
    #
    # Nothing is added to _pending_commands.
    # Therefore there will be NO PLC response.
    # -----------------------------------------------------

    if decision["verdict"] == "DROP":

        return

    # -----------------------------------------------------
    # PASS
    #
    # Register the pending command BEFORE forwarding.
    # -----------------------------------------------------

    with _state_lock:

        _pending_commands[register] = {
            "tx_id": tx_id,
            "value": value,
            "time": start_time,
        }

    # -----------------------------------------------------
    # Forward approved command to REAL PLC
    # -----------------------------------------------------

    success = _forward_to_plc(
        register,
        value
    )

    # If forwarding failed, remove pending command.
    if not success:

        with _state_lock:

            _pending_commands.pop(
                register,
                None
            )


# =========================================================
# FORWARD WRITE TO REAL PLC
# =========================================================

def _forward_to_plc(
    register: int,
    value: float
) -> bool:

    if _plc_client is None:

        print(
            "[MIDDLEWARE] WARNING: "
            "no PLC connection — write not forwarded"
        )

        return False

    try:

        result = _plc_client.write_register(
            register,
            _to_raw(value)
        )

        if result.isError():

            print(
                f"[MIDDLEWARE] "
                f"PLC rejected write "
                f"register={register} "
                f"value={value:.2f}"
            )

            return False

        print(
            f"[MIDDLEWARE] "
            f"FORWARDED TO PLC "
            f"register={register} "
            f"value={value:.2f}"
        )

        return True

    except Exception as e:

        print(
            f"[MIDDLEWARE] "
            f"ERROR forwarding to PLC: {e}"
        )

        return False


# =========================================================
# INTERNAL DATA SYNC
# =========================================================

def _internal_sync_write(
    block: ModbusSequentialDataBlock,
    address: int,
    values: list
):

    """
    Writes real PLC telemetry into the SCADA-facing
    datastore WITHOUT triggering the downstream
    command pipeline again.
    """

    ModbusSequentialDataBlock.setValues(
        block,
        address,
        values
    )


# =========================================================
# DASHBOARD — PLC -> SCADA RESPONSE
# =========================================================

def _report_plc_response(
    tx_id: str,
    register: int,
    value: float,
    latency_ms: float
):

    """
    Report an ACTUAL PLC confirmation.

    This is called ONLY when:

      1. The original command was PASSed.
      2. It was forwarded to the real PLC.
      3. PLC feedback confirms the requested value.

    DROPped commands never reach this function.
    """

    register_name = REGISTER_MAP[register]["name"]

    payload = {
        "tx_id": tx_id,
        "direction": "plc_to_scada",
        "verdict": "PASS",
        "reason": "PLC confirmed the requested value.",
        "command": f"{register_name} → {value:.2f}",
        "latency_ms": round(latency_ms, 2),
        "timestamp": time.time(),
    }

    try:

        response = requests.post(
            f"{DASHBOARD_URL}/api/security-event",
            json=payload,
            timeout=1
        )

        if response.ok:

            print(
                f"[MIDDLEWARE] "
                f"PLC RESPONSE "
                f"tx={tx_id} "
                f"{register_name}={value:.2f}"
            )

        else:

            print(
                f"[MIDDLEWARE] "
                f"Dashboard rejected PLC response: "
                f"{response.status_code}"
            )

    except Exception as e:

        print(
            f"[MIDDLEWARE] "
            f"Could not report PLC response: {e}"
        )


# =========================================================
# DASHBOARD — REAL PLC TELEMETRY
# =========================================================

def _report_telemetry():

    """
    Send actual PLC telemetry to dashboard.
    """

    with _state_lock:

        registers = {
            REGISTER_MAP[reg]["name"]:
            _plc_state["registers"][reg]
            for reg in _ALL_REGISTERS
        }

    payload = {
        "registers": registers
    }

    try:

        requests.post(
            f"{DASHBOARD_URL}/api/telemetry",
            json=payload,
            timeout=1
        )

    except Exception:
        pass


# =========================================================
# PLC POLLING
# =========================================================

def _poll_once(
    block: "MiddlewareDataBlock"
):

    global _last_telemetry_report

    """
    One polling cycle:

    1. Read actual PLC telemetry.
    2. Update middleware state.
    3. Synchronize SCADA-facing registers.
    4. Check PASSed pending commands.
    5. Create PLC -> SCADA response only after
       actual PLC confirmation.
    """

    if _plc_client is None:
        return

    try:

        # -------------------------------------------------
        # Read REAL PLC
        # -------------------------------------------------

        if not _plc_client.is_socket_open():

            _plc_client.connect()

        result = _plc_client.read_holding_registers(
            0,
            count=3
        )

        if result.isError():
            return

        raws = result.registers

        now = time.time()

        # -------------------------------------------------
        # Update middleware's copy of REAL PLC state
        # -------------------------------------------------

        with _state_lock:

            for reg, raw in zip(
                _ALL_REGISTERS,
                raws
            ):

                _plc_state["registers"][reg] = (
                    _from_raw(raw)
                )

            _plc_state["timestamp"] = now

            # -------------------------------------------------
            # Mirror REAL PLC state into SCADA datastore
            # -------------------------------------------------

            for reg, raw in zip(
                _ALL_REGISTERS,
                raws
            ):

                _internal_sync_write(
                    block,
                    reg,
                    [raw]
                )

        # -------------------------------------------------
        # Dashboard telemetry: once per second
        #
        # PLC polling remains every 0.2 seconds.
        # -------------------------------------------------

        if (
            now - _last_telemetry_report
            >= TELEMETRY_REPORT_INTERVAL
        ):

            _report_telemetry()

            _last_telemetry_report = now

        # -------------------------------------------------
        # Check ONLY commands that were PASSed
        # -------------------------------------------------

        for reg in list(_pending_commands.keys()):

            with _state_lock:

                pending = _pending_commands.get(reg)

                if pending is None:
                    continue

                reported = (
                    _plc_state["registers"][reg]
                )

            # -------------------------------------------------
            # Check actual PLC value
            # -------------------------------------------------

            feedback_ok = (
                abs(
                    reported -
                    pending["value"]
                )
                < FEEDBACK_SETTLED_TOLERANCE
            )

            # -------------------------------------------------
            # PLC has NOT confirmed yet.
            #
            # No right-side event.
            # -------------------------------------------------

            if not feedback_ok:

                continue

            # -------------------------------------------------
            # PLC HAS confirmed the command.
            #
            # Now create the PLC -> SCADA response.
            # -------------------------------------------------

            latency_ms = (
                now - pending["time"]
            ) * 1000

            _report_plc_response(
                tx_id=pending["tx_id"],
                register=reg,
                value=pending["value"],
                latency_ms=latency_ms
            )

            # -------------------------------------------------
            # Remove pending command so the same response
            # is not reported repeatedly.
            # -------------------------------------------------

            with _state_lock:

                _pending_commands.pop(
                    reg,
                    None
                )

                _register_settled_since[reg] = now

    except Exception as e:

        print(
            f"[MIDDLEWARE] "
            f"ERROR polling PLC: {e}"
        )


# =========================================================
# POLLING LOOP
# =========================================================

def _poll_plc_loop(
    block: "MiddlewareDataBlock"
):

    while True:

        _poll_once(block)

        time.sleep(
            POLL_INTERVAL
        )


# =========================================================
# START MIDDLEWARE
# =========================================================

def start_middleware_server(
    listen_host: str = LISTEN_HOST,
    listen_port: int = LISTEN_PORT,
    plc_host: str = PLC_HOST,
    plc_port: int = PLC_PORT,
):

    global _plc_client

    # -----------------------------------------------------
    # Connect to PLC
    # -----------------------------------------------------

    _plc_client = ModbusTcpClient(
        host=plc_host,
        port=plc_port
    )

    if not _plc_client.connect():

        print(
            f"[MIDDLEWARE] WARNING: "
            f"could not connect to PLC at "
            f"{plc_host}:{plc_port} yet — "
            f"will keep retrying"
        )

    # -----------------------------------------------------
    # Create SCADA-facing datastore
    # -----------------------------------------------------

    block = MiddlewareDataBlock(
        0,
        [0] * 3
    )

    store = ModbusSlaveContext(
        hr=block,
        zero_mode=True
    )

    context = ModbusServerContext(
        slaves=store,
        single=True
    )

    # -----------------------------------------------------
    # Initial PLC synchronization
    # -----------------------------------------------------

    _poll_once(block)

    # -----------------------------------------------------
    # Start background polling
    # -----------------------------------------------------

    threading.Thread(
        target=_poll_plc_loop,
        args=(block,),
        daemon=True
    ).start()

    # -----------------------------------------------------
    # Start Modbus server
    # -----------------------------------------------------

    print(
        f"[MIDDLEWARE] "
        f"Listening for SCADA on "
        f"{listen_host}:{listen_port}, "
        f"forwarding approved writes to PLC at "
        f"{plc_host}:{plc_port}"
    )

    StartTcpServer(
        context=context,
        address=(
            listen_host,
            listen_port
        )
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    start_middleware_server()