"""Print the experiment summary used in the final report."""
import json
from pathlib import Path

d = json.loads(Path("results/experiments.json").read_text())
print("API latency, ms")
print("  GET  /api/batches  p50 %.2f  p95 %.2f" % (d["latency"]["batches_ms"]["p50"], d["latency"]["batches_ms"]["p95"]))
print("  POST /api/analyze  p50 %.2f  p95 %.2f" % (d["latency"]["analyze_ms"]["p50"], d["latency"]["analyze_ms"]["p95"]))
print("  model predict      p50 %.3f  p95 %.3f" % (d["model_latency"]["p50_ms"], d["model_latency"]["p95_ms"]))
print()
print("Load: users  throughput  p50 ms  p95 ms")
for row in d["load"]:
    print("      %3d   %6.1f rps  %6.0f  %6.0f" % (row["users"], row["throughput_rps"], row["p50_ms"], row["p95_ms"]))
print()
print("Chain scenario: %.3f s, %d gas" % (d["chain_scenario"]["total_seconds"], d["chain_scenario"]["total_gas"]))
print("Centralized SQLite: p50 %.2f ms, p95 %.2f ms, tamper detected = %s"
      % (d["centralized"]["p50_ms"], d["centralized"]["p95_ms"], d["centralized"]["tamper_detected"]))
print("Robustness:")
for row in d["robustness"]:
    print("  sigma %.1f  XGB %.3f  IF %.3f" % (row["noise_sigma"], row["xgboost_f1"], row["isolation_forest_f1"]))
print("Learning curve:")
for row in d["learning_curve"]:
    print("  %5d rows  F1 %.4f" % (row["train_rows"], row["f1"]))
