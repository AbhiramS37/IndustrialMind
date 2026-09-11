import time
from pymodbus.client import ModbusTcpClient

from middleware.cyber_agent import check as cyber_check
from middleware.physical_agent import check_command as phys_check_command
from middleware.orchestrator import decide

PLC_HOST = "127.0.0.1"
PLC_PORT = 5020

def process_command(command_dict: dict) -> dict:
    """
    Routes incoming SCADA commands through Cyber Agent, Physical Agent, and Orchestrator.
    """
    start_t = time.time()

    # 1. Evaluate Cyber Security Agent
    cyber_v = cyber_check(command_dict)

    # 2. Evaluate Physical Safety Agent
    phys_v = phys_check_command(command_dict)

    # 3. Pass agent verdicts to Orchestrator for final decision
    decision = decide(cyber_v, phys_v, start_t)

    # 4. Forward to PLC only if verdict is PASS
    if decision.get("verdict") == "PASS":
        client = ModbusTcpClient(PLC_HOST, port=PLC_PORT)
        if client.connect():
            reg = command_dict.get("register")
            val = command_dict.get("value")
            client.write_register(address=reg, value=val)
            client.close()
            decision["plc_executed"] = True
        else:
            decision["plc_executed"] = False
            decision["error"] = "PLC Connection Failed"
    else:
        decision["plc_executed"] = False

    return decision

if __name__ == "__main__":
    print("Middleware Pipeline initialized successfully.")