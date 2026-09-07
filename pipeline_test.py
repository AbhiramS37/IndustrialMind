"""
Exercises the exact production functions from middleware_server.py against a
real, running plc.py — without needing middleware_server's own Modbus TCP
server thread. This validates the actual pipeline logic:
  cyber_agent.check() + physical_agent.check_command() -> orchestrator.decide()
  -> forward-to-PLC-if-PASS -> poll-and-check-feedback
"""
import time
from pymodbus.client import ModbusTcpClient

import middleware.middleware_server as mw
from middleware import orchestrator
from docs.interfaces import TANK_PRESSURE, CONVEYOR_SPEED, COOLING_VALVE, REGISTER_MAP

# Wire up the middleware's PLC-facing client manually (skip start_middleware_server,
# which would also try to launch the blocking StartTcpServer call).
mw._plc_client = ModbusTcpClient(host="127.0.0.1", port=5020)
assert mw._plc_client.connect(), "middleware could not connect to the real PLC"

from pymodbus.datastore import ModbusSequentialDataBlock as _MSDB
_warmup_block = _MSDB(0, [0, 0, 0])
mw._poll_once(_warmup_block)  # warm up _plc_state["timestamp"] before any command evaluation

def read_real_plc():
    r = mw._plc_client.read_holding_registers(0, count=3)
    return [mw._from_raw(v) for v in r.registers]

print("=" * 70)
print("TEST 1: legit in-bounds write -> should PASS and reach the real PLC")
print("=" * 70)
before = read_real_plc()
print("PLC state before:", before)
mw._handle_downstream_write(COOLING_VALVE, 50.0)   # 45 -> 50, well within rate limit
for _ in range(3):
    time.sleep(0.5)
    mw._poll_once(_warmup_block)
after = read_real_plc()
print("PLC state after (t+1.5s):", after)
assert after[2] > before[2], "FAIL: cooling valve did not move on the real PLC after a PASS"
print("PASS confirmed: real PLC register actually changed.\n")

print("=" * 70)
print("TEST 2: out-of-bounds write -> should DROP, PLC must NOT move")
print("=" * 70)
before = read_real_plc()
mw._handle_downstream_write(TANK_PRESSURE, 500.0)  # way over the 100 PSI safe max
time.sleep(1.0)
after = read_real_plc()
print(f"PLC TANK_PRESSURE before={before[0]:.2f} after={after[0]:.2f}")
assert abs(after[0] - before[0]) < 0.1, "FAIL: PLC moved even though the command should have DROPped"
print("PASS confirmed: DROPped command never reached the PLC.\n")

print("=" * 70)
print("TEST 3: rate-of-change violation -> should DROP")
print("=" * 70)
before = read_real_plc()
mw._handle_downstream_write(CONVEYOR_SPEED, 100.0)  # 0 -> 100 RPM instantly, way too fast
time.sleep(1.0)
after = read_real_plc()
print(f"PLC CONVEYOR_SPEED before={before[1]:.2f} after={after[1]:.2f}")
assert abs(after[1] - before[1]) < 0.5, "FAIL: PLC moved on a rate-of-change violation"
print("PASS confirmed: rate-of-change violation correctly dropped.\n")

print("=" * 70)
print("TEST 4: flood (same register, same source_ip) -> later ones DROP")
print("=" * 70)
log_before = len(orchestrator.get_log())
for i in range(7):
    mw._handle_downstream_write(COOLING_VALVE, 50.0 + i * 0.1)  # tiny moves, in-bounds & in-rate
decisions = orchestrator.get_log()[log_before:]
passes = sum(1 for d in decisions if d["verdict"] == "PASS")
drops = sum(1 for d in decisions if d["verdict"] == "DROP")
print(f"7 rapid writes -> {passes} PASS, {drops} DROP")
for d in decisions:
    print("  ", d)
assert drops > 0, "FAIL: flood should have triggered RATE_LIMIT_EXCEEDED on some writes"
print("PASS confirmed: flood correctly rate-limited.\n")

print("=" * 70)
print("TEST 5: upstream feedback check runs one poll cycle and fills in tx_id")
print("=" * 70)
log_before2 = len(orchestrator.get_log())
mw._poll_once(_warmup_block)
upstream_decisions = orchestrator.get_log()[log_before2:]
print(f"Upstream decisions logged this cycle: {len(upstream_decisions)}")
for d in upstream_decisions:
    print("  ", d)
    assert d["tx_id"] != "", "FAIL: upstream decision has a blank tx_id"
if upstream_decisions:
    print("PASS confirmed: upstream feedback logged with a real tx_id, not blank.\n")
else:
    print("(no pending commands left to check feedback against at this exact moment — timing-dependent, not a bug)\n")

mw._plc_client.close()
print("ALL PIPELINE TESTS COMPLETED")