"""Dataset analysis figures for the design report."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ml.features import engineer

FIG = Path("results/figures")
FIG.mkdir(parents=True, exist_ok=True)
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
COLORS = {"normal": "#4c72b0", "anomaly": "#c44e52"}


def save(fig, name: str) -> None:
    fig.savefig(FIG / name)
    plt.close(fig)
    print("wrote", FIG / name)


def main() -> None:
    raw = pd.read_csv("data/events.csv")
    df = engineer(raw)

    counts = df["is_anomaly"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(4.2, 3))
    ax.bar(["нормальні", "аномальні"], counts.values, color=[COLORS["normal"], COLORS["anomaly"]])
    for i, value in enumerate(counts.values):
        ax.text(i, value + 200, f"{value:,}".replace(",", " "), ha="center")
    ax.set_ylabel("кількість передач")
    ax.set_title("Баланс класів")
    save(fig, "data_class_balance.png")

    types = df[df.is_anomaly == 1]["anomaly_name"].value_counts()
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.barh(types.index[::-1], types.values[::-1], color=COLORS["anomaly"])
    for i, value in enumerate(types.values[::-1]):
        ax.text(value + 20, i, str(value), va="center")
    ax.set_xlabel("кількість записів")
    ax.set_title("Типи аномалій")
    save(fig, "data_anomaly_types.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    bins = np.logspace(1, 3.6, 45)
    ax.hist(df[df.is_anomaly == 0]["distance_km"], bins=bins, alpha=0.65, label="нормальні", color=COLORS["normal"])
    ax.hist(df[df.is_anomaly == 1]["distance_km"], bins=bins, alpha=0.65, label="аномальні", color=COLORS["anomaly"])
    ax.set_xscale("log")
    ax.set_xlabel("відстань між містами, км (лог. шкала)")
    ax.set_ylabel("кількість передач")
    ax.legend()
    ax.set_title("Розподіл відстані")
    save(fig, "data_distance.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    bins = np.logspace(-1, 3.6, 45)
    ax.hist(df["speed_kmh"].dropna()[df.loc[df["speed_kmh"].notna(), "is_anomaly"] == 0], bins=bins, alpha=0.65, label="нормальні", color=COLORS["normal"])
    ax.hist(df["speed_kmh"].dropna()[df.loc[df["speed_kmh"].notna(), "is_anomaly"] == 1], bins=bins, alpha=0.65, label="аномальні", color=COLORS["anomaly"])
    ax.set_xscale("log")
    ax.set_xlabel("швидкість руху партії, км/год (лог. шкала)")
    ax.set_ylabel("кількість передач")
    ax.legend()
    ax.set_title("Розподіл швидкості")
    save(fig, "data_speed.png")

    fig, ax = plt.subplots(figsize=(5, 3))
    bins = np.logspace(-1, 2.9, 45)
    ax.hist(df["transit_hours"].dropna(), bins=bins, color="#55a868")
    ax.set_xscale("log")
    ax.set_xlabel("час у дорозі, год (лог. шкала)")
    ax.set_ylabel("кількість передач")
    ax.set_title("Розподіл часу передачі")
    save(fig, "data_transit.png")

    columns = [
        "distance_km",
        "transit_hours",
        "speed_kmh",
        "quantity_ratio",
        "temperature_c",
        "temp_deviation",
        "scan_distance_km",
        "same_serial_cities_24h",
        "license_status_code",
        "batch_age_hours",
    ]
    corr = df[columns].corr()
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels(columns, rotation=45, ha="right")
    ax.set_yticks(range(len(columns)))
    ax.set_yticklabels(columns)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Кореляційна матриця ознак")
    ax.grid(False)
    save(fig, "data_correlation.png")

    missing = df[["temperature_c", "transit_hours", "quantity_received"]].isna().mean() * 100
    fig, ax = plt.subplots(figsize=(4.6, 3))
    ax.bar(missing.index, missing.values, color="#8172b2")
    for i, value in enumerate(missing.values):
        ax.text(i, value + 0.02, f"{value:.2f} %", ha="center")
    ax.set_ylabel("частка пропусків, %")
    ax.set_title("Пропуски у ключових ознаках")
    save(fig, "data_missing.png")

    weekly = (
        df.set_index("timestamp")
        .groupby([pd.Grouper(freq="W"), "is_anomaly"])
        .size()
        .unstack(fill_value=0)
    )
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(weekly.index, weekly[0], label="нормальні", color=COLORS["normal"])
    ax.plot(weekly.index, weekly[1], label="аномальні", color=COLORS["anomaly"])
    ax.set_ylabel("передач за тиждень")
    ax.set_xlabel("2026 рік")
    ax.legend()
    ax.set_title("Передачі в часі")
    save(fig, "data_time_series.png")

    sample = df.sample(3000, random_state=42)
    fig, ax = plt.subplots(figsize=(5.4, 3.4))
    for flag, name, color in ((0, "нормальні", COLORS["normal"]), (1, "аномальні", COLORS["anomaly"])):
        part = sample[sample.is_anomaly == flag]
        ax.scatter(part["scan_distance_km"], part["speed_kmh"], s=8, alpha=0.5, label=name, color=color)
    ax.set_xlabel("відстань між отримувачем і місцем сканування, км")
    ax.set_ylabel("швидкість, км/год")
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 400)
    ax.legend()
    ax.set_title("Географія сканування проти швидкості")
    save(fig, "data_scan_scatter.png")

    fig, axes = plt.subplots(1, 3, figsize=(9, 3))
    for ax, column, title in zip(
        axes,
        ["speed_kmh", "scan_distance_km", "quantity_ratio"],
        ["швидкість, км/год", "відстань скану, км", "частка отриманого"],
    ):
        data = [df[df.is_anomaly == 0][column].dropna(), df[df.is_anomaly == 1][column].dropna()]
        ax.boxplot(data, tick_labels=["норма", "аномалія"], showfliers=False)
        ax.set_title(title)
    save(fig, "data_boxplots.png")

    print("missing share", (df.isna().mean() * 100).round(2).to_dict())


if __name__ == "__main__":
    main()
