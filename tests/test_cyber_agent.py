import time
from docs.interfaces import make_command
from middleware import cyber_agent

cyber_agent.reset_state()
SRC = "192.168.1.10"

# 1. Normal command -> expect PASS
cmd = make_command("tx1", time.time(), SRC, 6, 2, 45.0)
print("1. Normal command:", cyber_agent.check(cmd))
# EXPECTED: {'tx_id': 'tx1', 'pass': True, 'reason': 'OK', 'agent': 'cyber'}

# 2. Flood: send 7 requests fast from the same source -> later ones DROP
cyber_agent.reset_state()
for i in range(7):
    cmd = make_command(f"tx-flood-{i}", time.time(), SRC, 6, 2, 45.0 + i)
    result = cyber_agent.check(cmd)
    print(f"2.{i} Flood request:", result)
# EXPECTED: first 5 -> pass: True, requests 6 and 7 -> pass: False, reason 'RATE_LIMIT_EXCEEDED'

# 3. Untrusted source -> expect DROP
cyber_agent.reset_state()
cmd = make_command("tx2", time.time(), "10.0.0.99", 6, 2, 45.0)
print("3. Untrusted source:", cyber_agent.check(cmd))
# EXPECTED: {'tx_id': 'tx2', 'pass': False, 'reason': 'UNTRUSTED_SOURCE', 'agent': 'cyber'}

# 4. Invalid function code -> expect DROP
cmd = make_command("tx3", time.time(), SRC, 99, 2, 45.0)
print("4. Bad function code:", cyber_agent.check(cmd))
# EXPECTED: {'tx_id': 'tx3', 'pass': False, 'reason': 'INVALID_FUNCTION_CODE', 'agent': 'cyber'}

# 5. Replay: same exact payload sent twice -> second one DROP
cyber_agent.reset_state()
cmd = make_command("tx4", time.time(), SRC, 6, 2, 45.0)
print("5a. First send:", cyber_agent.check(cmd))
cmd2 = make_command("tx5", time.time(), SRC, 6, 2, 45.0)  # identical payload
print("5b. Replayed send:", cyber_agent.check(cmd2))
# EXPECTED: 5a pass: True, 5b pass: False, reason 'REPLAY_DETECTED'