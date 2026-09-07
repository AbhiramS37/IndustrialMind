"""
middleware/middleware_server.py — the proxy between SCADA and the PLC.

Architecture:
  - Modbus TCP SERVER on port 5021, facing SCADA (or an attacker).
  - Modbus TCP CLIENT to the PLC on port 5020, forwarding approved writes
    and polling telemetry.

Downstream (SCADA -> PLC):
  1. A write lands on the middleware's own datastore.
  2. Build a command dict, run cyber_agent.check() + physical_agent.check_command().
  3. orchestrator.decide() fuses the two verdicts into a logged PASS/DROP.
  4. PASS  -> forward the write to the real PLC.
     DROP  -> absorb it here. The write is never forwarded, so it has no
              physical effect — but the Modbus transaction itself still
              completes normally against the middleware's own datastore.
              (A real MITM attacker's write looks "successful" to them right
              up until they check whether the plant actually moved.)

Upstream (PLC -> SCADA):
  A background poller reads the PLC's real telemetry every POLL_INTERVAL
  seconds, keeps the SCADA-facing datastore in sync with ground truth, and
  runs physical_agent.check_feedback() against any register with a pending
  commanded value — logging the result via orchestrator with cyber_verdict=None.

Known simplification (read before demoing):
  pymodbus's synchronous datastore hook (the one this file and plc.py both
  use, on the pre-3.13 API) does not expose the TCP peer address to
  setValues(). Every incoming write is tagged with DEFAULT_SOURCE_IP below,
  regardless of whether it came from scada.py or attacker.py. Practically
  this means cyber_agent's rate-limit, replay, and function-code checks
  still work correctly (they judge *behavior*, not *identity*), but the
  UNTRUSTED_SOURCE check can never fire in this build, since every
  connection is labeled as the whitelisted IP. If Gauri's attacker.py needs
  to demo that specific check, the cleanest fix is a second listening port
  dedicated to attacker traffic, tagged with a non-whitelisted IP — flag
  this with the team before demo day if it matters for the metrics slide.
"""

import time
import threading
import uuid

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
from middleware import cyber_agent, physical_agent, orchestrator

# ── Config ───────────────────────────────────────────────────────────────
PLC_HOST = "127.0.0.1"
PLC_PORT = 5020
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5021
SCALE = 10  # must match plc.py's _SCALE
POLL_INTERVAL = 0.2  # seconds between telemetry polls / feedback checks
DEFAULT_SOURCE_IP = "192.168.1.10"  # see "Known simplification" above
FEEDBACK_SETTLED_TOLERANCE = 0.05  # stop tracking a pending command once the PLC is this close to it

_ALL_REGISTERS = (TANK_PRESSURE, CONVEYOR_SPEED, COOLING_VALVE)

# ── Shared state (protected by _state_lock) ─────────────────────────────
_state_lock = threading.Lock()
_plc_state = {
    "registers": {TANK_PRESSURE: 50.0, CONVEYOR_SPEED: 0.0, COOLING_VALVE: 45.0},
    "timestamp": time.time(),
}
_pending_commands = {}  # register -> {"tx_id": str, "value": float, "time": float}
_register_settled_since = {reg: time.time() - 3.0 for reg in _ALL_REGISTERS}
# ^ per-register "how long has this been sitting still" clock, initialized a few
# seconds in the past so the very first legitimate command after middleware
# startup isn't unfairly rate-limited by an artificially tiny window (see
# scada.py's operator profile — first writes land within ~1.5-3s of startup).
# Deliberately NOT a large grace period: too generous here would let an
# obviously-impossible instant jump slip through disguised as "gradual" (tested
# and caught during integration — see pipeline_test.py test 3). 3 seconds covers
# a realistic single operator step without hiding a genuine rate violation.
# Updated only when a pending command's target is reached — NOT on every poll —
# so a rate check run shortly after a poll cycle doesn't see a near-zero window
# either. See _handle_downstream_write() and _poll_once() for where this is read/reset.

_plc_client: ModbusTcpClient | None = None


def _to_raw(value: float) -> int:
    return max(0, min(65535, int(round(value * SCALE))))


def _from_raw(raw: int) -> float:
    return raw / SCALE


class MiddlewareDataBlock(ModbusSequentialDataBlock):
    """SCADA-facing holding registers. A write here runs the full
    cyber + physical + orchestrator pipeline before it's (maybe) forwarded
    to the real PLC. The write is always accepted locally — see module
    docstring for why DROP doesn't mean "reject the Modbus transaction"."""

    def setValues(self, address, values):
        super().setValues(address, values)
        for i, raw_value in enumerate(values):
            register = address + i
            if register in _ALL_REGISTERS:
                _handle_downstream_write(register, _from_raw(raw_value))


def _handle_downstream_write(register: int, value: float):
    start_time = time.time()
    tx_id = str(uuid.uuid4())

    command = make_command(
        tx_id=tx_id,
        timestamp=start_time,
        source_ip=DEFAULT_SOURCE_IP,
        function_code=6,
        register=register,
        value=value,
    )

    cyber_verdict = cyber_agent.check(command)

    with _state_lock:
        current_state = {
            "registers": dict(_plc_state["registers"]),
            "timestamp": _register_settled_since[register],
        }
    physical_verdict = physical_agent.check_command(command, current_state)

    decision = orchestrator.decide(cyber_verdict, physical_verdict, start_time)
    name = REGISTER_MAP[register]["name"]
    print(f"[MIDDLEWARE] {decision['verdict']:4s} {name}={value:.2f} reason={decision['reason']}")

    if decision["verdict"] == "PASS":
        _forward_to_plc(register, value)
        with _state_lock:
            _pending_commands[register] = {"tx_id": tx_id, "value": value, "time": start_time}
    # DROP: intentionally do nothing further. The command is absorbed here.


def _forward_to_plc(register: int, value: float):
    if _plc_client is None:
        print("[MIDDLEWARE] WARNING: no PLC connection — write not forwarded")
        return
    try:
        _plc_client.write_register(register, _to_raw(value))
    except Exception as e:
        print(f"[MIDDLEWARE] ERROR forwarding to PLC: {e}")


def _internal_sync_write(block: ModbusSequentialDataBlock, address: int, values: list):
    """Writes to the SCADA-facing datastore WITHOUT re-triggering
    MiddlewareDataBlock.setValues — same pattern as plc.py's internal sync,
    for the same reason: this is us pushing real PLC state into the
    datastore for reads, not a new command to evaluate."""
    ModbusSequentialDataBlock.setValues(block, address, values)


def _poll_once(block: "MiddlewareDataBlock"):
    """Runs one poll cycle: read real PLC state, sync it into the SCADA-facing
    datastore, and check upstream feedback for any pending command.
    Factored out so start_middleware_server() can call this once, synchronously,
    before opening for business, so the SCADA-facing datastore reflects real
    PLC values from the first read rather than all-zeros."""
    if _plc_client is None:
        return
    try:
        result = _plc_client.read_holding_registers(0, count=3)
        if not result.isError():
            raws = result.registers
            now = time.time()
            with _state_lock:
                for reg, raw in zip(_ALL_REGISTERS, raws):
                    _plc_state["registers"][reg] = _from_raw(raw)
                _plc_state["timestamp"] = now

                for reg, raw in zip(_ALL_REGISTERS, raws):
                    _internal_sync_write(block, reg, [raw])

                for reg in list(_pending_commands.keys()):
                    pending = _pending_commands[reg]
                    reported = _plc_state["registers"][reg]
                    fb_verdict = physical_agent.check_feedback(
                        pending["value"], reported, reg
                    )
                    fb_verdict["tx_id"] = pending["tx_id"]  # the documented fill-in step
                    fb_decision = orchestrator.decide(None, fb_verdict, pending["time"])
                    if fb_decision["verdict"] == "DROP":
                        print(
                            f"[MIDDLEWARE] UPSTREAM DROP "
                            f"{REGISTER_MAP[reg]['name']} reason={fb_decision['reason']}"
                        )
                    if abs(reported - pending["value"]) < FEEDBACK_SETTLED_TOLERANCE:
                        del _pending_commands[reg]
                        _register_settled_since[reg] = now  # just reached target -> clock resets here
    except Exception as e:
        print(f"[MIDDLEWARE] ERROR polling PLC: {e}")


def _poll_plc_loop(block: "MiddlewareDataBlock"):
    """Reads real PLC state, mirrors it into the SCADA-facing datastore,
    and runs the upstream feedback check against any pending command."""
    while True:
        _poll_once(block)
        time.sleep(POLL_INTERVAL)


def start_middleware_server(
    listen_host: str = LISTEN_HOST,
    listen_port: int = LISTEN_PORT,
    plc_host: str = PLC_HOST,
    plc_port: int = PLC_PORT,
):
    global _plc_client
    _plc_client = ModbusTcpClient(host=plc_host, port=plc_port)
    if not _plc_client.connect():
        print(
            f"[MIDDLEWARE] WARNING: could not connect to PLC at {plc_host}:{plc_port} "
            "yet — will keep retrying on each poll"
        )

    block = MiddlewareDataBlock(0, [0] * 3)
    store = ModbusSlaveContext(hr=block, zero_mode=True)
    context = ModbusServerContext(slaves=store, single=True)

    _poll_once(block)  # warm up _plc_state before accepting any writes — see _poll_once docstring
    threading.Thread(target=_poll_plc_loop, args=(block,), daemon=True).start()

    print(
        f"[MIDDLEWARE] Listening for SCADA on {listen_host}:{listen_port}, "
        f"forwarding approved writes to PLC at {plc_host}:{plc_port}"
    )
    StartTcpServer(context=context, address=(listen_host, listen_port))


if __name__ == "__main__":
    start_middleware_server()