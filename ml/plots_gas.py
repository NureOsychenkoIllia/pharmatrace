"""Gas charts from the forge gas report and the isolated benchmarks."""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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


def main() -> None:
    text = Path("reports/gas_report.txt").read_text(errors="ignore")
    contract = ""
    rows: dict[str, tuple[str, int]] = {}
    for line in text.splitlines():
        match = re.search(r"src/(\w+)\.sol:\w+ Contract", line)
        if match:
            contract = match.group(1)
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5 and contract and cells[1].isdigit() and cells[2].isdigit():
            name = cells[0]
            average = int(cells[2])
            if name not in rows or average > rows[name][1]:
                rows[name] = (contract, average)
    items = sorted(rows.items(), key=lambda item: item[1][1], reverse=True)[:14]
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.barh(
        [f"{name} ({contract})" for name, (contract, _) in items][::-1],
        [value for _, (_, value) in items][::-1],
        color="#4c72b0",
    )
    for i, (_, (_, value)) in enumerate(items[::-1]):
        ax.text(value + 1500, i, f"{value:,}".replace(",", " "), va="center", fontsize=8)
    ax.set_xlabel("середній газ")
    ax.set_title("Газ функцій, що змінюють стан")
    fig.savefig(FIG / "gas_functions.png")
    plt.close(fig)
    print("wrote", FIG / "gas_functions.png")

    fig, ax = plt.subplots(figsize=(5.4, 3))
    labels = ["Без пакування", "Пакування", "Пакування + immutable"]
    values = [271505, 251735, 249656]
    colors = ["#c44e52", "#8172b2", "#55a868"]
    ax.bar(labels, values, color=colors)
    for i, value in enumerate(values):
        ax.text(i, value + 2000, f"{value:,}".replace(",", " "), ha="center", fontsize=8)
    ax.set_ylim(220_000, 285_000)
    ax.set_ylabel("газ на mint")
    ax.set_title("Дві оптимізації газу")
    plt.xticks(rotation=8)
    fig.savefig(FIG / "gas_optimizations.png")
    plt.close(fig)
    print("wrote", FIG / "gas_optimizations.png")


if __name__ == "__main__":
    main()
