"""Print the cost estimate used in the final report."""
import json
from pathlib import Path

d = json.loads(Path("results/experiments.json").read_text())
gas = d["chain_scenario"]["total_gas"]
steps = len(d["chain_scenario"]["steps"])
avg = gas / steps
eth = 3000
print("main scenario: %d gas in %d transactions" % (gas, steps))
print("average per transaction: %.0f gas" % avg)
print()
print("scenario cost")
for gwei in (20, 60):
    eth_cost = gas * gwei * 1e-9
    print("  %2d gwei: %.6f ETH = $%.2f" % (gwei, eth_cost, eth_cost * eth))
print()
monthly_gas = avg * 1000 * 30
print("monthly, 1000 operations/day, average transaction")
for label, gwei in (("mainnet 20 gwei", 20), ("mainnet 60 gwei", 60), ("L2 0.1 gwei", 0.1)):
    eth_cost = monthly_gas * gwei * 1e-9
    print("  %-14s %.4f ETH = $%.0f" % (label, eth_cost, eth_cost * eth))
