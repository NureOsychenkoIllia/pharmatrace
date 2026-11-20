"""Final-lab figures: latency, load, gas, robustness, cost."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIG = Path("results/figures")
plt.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.bbox": "tight",
        "font.size": 9,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
COLORS = ["#4c72b0", "#55a868", "#8172b2", "#c44e52"]


def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)
    print("wrote", FIG / name)


def main() -> None:
    data = json.loads(Path("results/experiments.json").read_text())
    gas_curve = json.loads(Path("results/gas_curve.json").read_text())

    latency = data["latency"]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3))
    axes[0].hist(latency["raw"]["batches"], bins=20, color=COLORS[0])
    axes[0].axvline(latency["batches_ms"]["p95"], color=COLORS[3], ls="--", label=f"p95={latency['batches_ms']['p95']:.2f} мс")
    axes[0].set_xlabel("час відповіді, мс")
    axes[0].set_ylabel("кількість запитів")
    axes[0].set_title("GET /api/batches")
    axes[0].legend()
    axes[1].hist(latency["raw"]["analyze"], bins=20, color=COLORS[1])
    axes[1].axvline(latency["analyze_ms"]["p95"], color=COLORS[3], ls="--", label=f"p95={latency['analyze_ms']['p95']:.2f} мс")
    axes[1].set_xlabel("час відповіді, мс")
    axes[1].set_title("POST /api/analyze")
    axes[1].legend()
    save(fig, "exp_api_latency.png")

    load = data["load"]
    users = [row["users"] for row in load]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3))
    axes[0].plot(users, [row["throughput_rps"] for row in load], marker="o", color=COLORS[0])
    axes[0].set_xlabel("одночасних користувачів")
    axes[0].set_ylabel("запитів за секунду")
    axes[0].set_title("Пропускна здатність")
    axes[1].plot(users, [row["p95_ms"] for row in load], marker="s", color=COLORS[3])
    axes[1].set_xlabel("одночасних користувачів")
    axes[1].set_ylabel("p95, мс")
    axes[1].set_title("Затримка під навантаженням")
    save(fig, "exp_load.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    ax.plot(gas_curve["marks"], gas_curve["gas"], marker="o", color=COLORS[2])
    ax.set_xlabel("порядковий номер партії в контракті")
    ax.set_ylabel("газ на mint")
    ax.set_ylim(200_000, 300_000)
    ax.set_title("Газ не зростає з кількістю записів")
    save(fig, "exp_gas_records.png")

    steps = data["chain_scenario"]["steps"]
    names = [step["step"] for step in steps]
    seconds = [step["seconds"] * 1000 for step in steps]
    gas = [step["gas"] for step in steps]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.barh(names[::-1], seconds[::-1], color=COLORS[0])
    for i, (ms, g) in enumerate(zip(seconds[::-1], gas[::-1])):
        ax.text(ms + 2, i, f"{ms:.0f} мс · {g:,}".replace(",", " "), va="center", fontsize=8)
    ax.set_xlabel("час підтвердження, мс")
    ax.set_xlim(0, max(seconds) * 1.7)
    ax.set_title("Головний сценарій: час і газ за кроками")
    save(fig, "exp_scenario.png")

    robust = data["robustness"]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.plot([r["noise_sigma"] for r in robust], [r["xgboost_f1"] for r in robust], marker="o", label="XGBoost", color=COLORS[3])
    ax.plot([r["noise_sigma"] for r in robust], [r["isolation_forest_f1"] for r in robust], marker="s", label="Ізоляційний ліс", color=COLORS[1])
    ax.set_xlabel("рівень гауссового шуму (σ, стандартизовані ознаки)")
    ax.set_ylabel("F1 на тесті")
    ax.set_ylim(0.4, 1.02)
    ax.legend()
    ax.set_title("Стійкість до спотворених даних")
    save(fig, "exp_robustness.png")

    curve = data["learning_curve"]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.plot([r["train_rows"] for r in curve], [r["f1"] for r in curve], marker="o", color=COLORS[3])
    ax.set_xlabel("розмір навчальної вибірки, записів")
    ax.set_ylabel("F1 на тесті")
    ax.set_ylim(0.98, 1.0)
    ax.set_title("Якість від обсягу даних")
    save(fig, "exp_learning.png")

    centralized = data["centralized"]
    scenario_runs = data["chain_scenario"].get("runs", [data["chain_scenario"]])
    onchain_ms = [run["total_seconds"] * 1000 for run in scenario_runs]
    fig, ax = plt.subplots(figsize=(5, 3))
    labels = ["SQLite", "Блокчейн"]
    p50 = [centralized["p50_ms"], np.percentile(onchain_ms, 50)]
    p95 = [centralized["p95_ms"], np.percentile(onchain_ms, 95)] if len(onchain_ms) > 1 else [centralized["p95_ms"], np.nan]
    x = np.arange(2)
    ax.bar(x - 0.18, p50, 0.36, label="p50", color=COLORS[0])
    ax.bar(x + 0.18, p95, 0.36, label="p95", color=COLORS[3])
    ax.set_xticks(x, labels)
    ax.set_yscale("log")
    ax.set_ylabel("час сценарію, мс (лог. шкала)")
    ax.legend()
    ax.set_title("Централізоване рішення проти блокчейну")
    save(fig, "exp_centralized.png")

    scenario_gas = data["chain_scenario"]["total_gas"]
    fig, ax = plt.subplots(figsize=(5, 3))
    for label, series, color in zip(
        labels, [centralized.get("raw_ms", []), onchain_ms], COLORS
    ):
        if series:
            ordered = np.sort(series)
            ax.step(ordered, np.arange(1, len(ordered) + 1) / len(ordered), where="post", label=label, color=color)
    ax.set_xscale("log")
    ax.set_xlabel("час повного сценарію, мс (лог. шкала)")
    ax.set_ylabel("частка завершених прогонів")
    ax.legend()
    save(fig, "exp_centralized_distribution.png")

    if len(scenario_runs) > 1:
        fig, ax = plt.subplots(figsize=(6.4, 3.4))
        ax.boxplot([
            [run["steps"][i]["seconds"] * 1000 for run in scenario_runs]
            for i in range(len(names))
        ])
        ax.set_xticks(range(1, len(names) + 1), names, rotation=30, ha="right")
        ax.set_ylabel("час підтвердження, мс")
        ax.set_title("Розподіл затримок підтвердження в Anvil")
        save(fig, "exp_confirmation.png")

    monthly_ops = 1000 * 30
    avg_gas = scenario_gas / len(steps)
    monthly_gas = avg_gas * monthly_ops
    prices = {"Mainnet 20 gwei": 20, "Mainnet 60 gwei": 60, "L2 0.1 gwei": 0.1}
    eth_usd = 3000
    costs = {name: monthly_gas * gwei * 1e-9 * eth_usd for name, gwei in prices.items()}
    fig, ax = plt.subplots(figsize=(5.4, 3))
    ax.bar(list(costs), list(costs.values()), color=[COLORS[0], COLORS[3], COLORS[1]])
    for i, value in enumerate(costs.values()):
        ax.text(i, value * 1.2, f"${value:,.0f}".replace(",", " "), ha="center", fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("доларів на місяць (лог. шкала)")
    ax.set_title("Вартість 1000 операцій на день")
    plt.xticks(rotation=10)
    save(fig, "exp_cost.png")

    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    ax.barh(names[::-1], gas[::-1], color=COLORS[2])
    ax.set_xlabel("газ")
    ax.set_title("Газ за кроками сценарію")
    save(fig, "exp_gas_breakdown.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    labels = ["Відхилено", "Модель позначила"]
    values = [5, 1]
    ax.bar(labels, values, color=[COLORS[1], COLORS[3]])
    for i, value in enumerate(values):
        ax.text(i, value + 0.1, str(value), ha="center")
    ax.set_ylabel("кількість перевірок")
    ax.set_title("Результати шести зловмисних сценаріїв")
    save(fig, "exp_attacks.png")


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    main()
