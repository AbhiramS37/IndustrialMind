# Register Map

| Register # | Name            | Safe Range   | Meaning               |
|------------|-----------------|--------------|------------------------|
| 0          | TANK_PRESSURE   | 0 – 100 PSI  | Tank pressure          |
| 1          | CONVEYOR_SPEED  | 0 – 120 RPM  | Conveyor motor speed   |
| 2          | COOLING_VALVE   | 0° – 90°     | Cooling valve angle    |

## Ports (settled convention — use these everywhere)

| Component  | Port | Notes                                      |
|------------|------|---------------------------------------------|
| PLC        | 5020 | `plc.py` — Modbus TCP server                |
| Middleware | 5021 | `middleware_server.py` — Modbus TCP server, faces SCADA/attacker |

`scada.py`, `attacker.py`, and `docs/wireshark_setup.md` must all point at 5021 for the middleware and 5020 for the PLC. If you're building against a different port, stop and check with the team first — mismatched ports are the #1 cause of "can't connect" during integration.

## Interface contract notes

- **`physical_agent.check_feedback()` returns `tx_id=""` by design.** It has no way to know which command it's confirming — that's the caller's context, not its own. Whoever calls it (currently: `middleware_server.py`) must set the real `tx_id` on the returned verdict *before* passing it into `orchestrator.decide()`, e.g. `verdict["tx_id"] = original_tx_id`. Skipping this means every upstream decision in the log has a blank `tx_id`.