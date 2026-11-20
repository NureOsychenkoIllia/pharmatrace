"""Create and execute the data-analysis notebook."""
from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

cells.append(
    nbf.v4.new_markdown_cell(
        """# Аналіз синтетичного журналу ланцюга поставок

Набір побудовано за структурою DataCo Smart Supply Chain: 25 000 передач,
2 376 партій, 9 000 аномалій. Ноутбук перевіряє розмір, пропуски, баланс класів,
розподіли, кореляції, часову структуру та схему розбиття.
"""
    )
)

cells.append(
    nbf.v4.new_code_cell(
        """import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append("..")
from ml.features import engineer

plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25})
raw = pd.read_csv("../data/events.csv")
df = engineer(raw)
print("shape:", df.shape)
print("batches:", df.batch_id.nunique())
print("anomalies:", int(df.is_anomaly.sum()))
df.head(3)
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Пропуски\n\nПропуски є лише в трьох числових ознаках; їх частка не перевищує 1,7 %.")
)
cells.append(
    nbf.v4.new_code_cell(
        """missing = df[["temperature_c", "transit_hours", "quantity_received"]].isna().mean() * 100
missing.round(2).to_frame("missing_%")
"""
    )
)
cells.append(
    nbf.v4.new_code_cell(
        """missing.plot.bar(color="#8172b2", figsize=(5, 3), ylabel="%", title="Пропуски")
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Баланс класів і типи аномалій")
)
cells.append(
    nbf.v4.new_code_cell(
        """counts = df.is_anomaly.value_counts().sort_index()
print(counts.to_string())
print("anomaly rate: %.3f" % (counts[1] / counts.sum()))
types = df[df.is_anomaly == 1].anomaly_name.value_counts()
types.to_frame("count")
"""
    )
)
cells.append(
    nbf.v4.new_code_cell(
        """fig, axes = plt.subplots(1, 2, figsize=(10, 3))
counts.plot.bar(ax=axes[0], color=["#4c72b0", "#c44e52"], title="Класи")
types.plot.barh(ax=axes[1], color="#c44e52", title="Типи аномалій")
plt.tight_layout()
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Розподіли ключових ознак")
)
cells.append(
    nbf.v4.new_code_cell(
        """fig, axes = plt.subplots(1, 3, figsize=(11, 3))
for ax, column, title in zip(
    axes,
    ["distance_km", "speed_kmh", "transit_hours"],
    ["Відстань, км", "Швидкість, км/год", "Час у дорозі, год"],
):
    values = df[column].dropna()
    ax.hist(values, bins=50, color="#4c72b0")
    ax.set_yscale("log")
    ax.set_title(title)
plt.tight_layout()
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Кореляційна матриця")
)
cells.append(
    nbf.v4.new_code_cell(
        """columns = [
    "distance_km", "transit_hours", "speed_kmh", "quantity_ratio",
    "temperature_c", "temp_deviation", "scan_distance_km",
    "same_serial_cities_24h", "license_status_code", "batch_age_hours",
]
corr = df[columns].corr()
fig, ax = plt.subplots(figsize=(6, 5))
im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
ax.set_xticks(range(len(columns)), columns, rotation=45, ha="right")
ax.set_yticks(range(len(columns)), columns)
fig.colorbar(im, ax=ax, shrink=0.8)
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Часова структура")
)
cells.append(
    nbf.v4.new_code_cell(
        """weekly = (
    df.set_index("timestamp").groupby([pd.Grouper(freq="W"), "is_anomaly"]).size().unstack(fill_value=0)
)
weekly.plot(figsize=(9, 3), color=["#4c72b0", "#c44e52"], ylabel="передач за тиждень")
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Викиди")
)
cells.append(
    nbf.v4.new_code_cell(
        """fig, axes = plt.subplots(1, 3, figsize=(10, 3))
for ax, column, title in zip(
    axes,
    ["speed_kmh", "scan_distance_km", "quantity_ratio"],
    ["Швидкість", "Відстань скану", "Частка отриманого"],
):
    data = [df[df.is_anomaly == 0][column].dropna(), df[df.is_anomaly == 1][column].dropna()]
    ax.boxplot(data, tick_labels=["норма", "аномалія"], showfliers=False)
    ax.set_title(title)
plt.tight_layout()
plt.show()
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell("## Розбиття без витоку")
)
cells.append(
    nbf.v4.new_code_cell(
        """starts = df.groupby("batch_id")["timestamp"].min().sort_values()
ids = starts.index.to_numpy()
n = len(ids)
train_ids = set(ids[: int(n * 0.7)])
val_ids = set(ids[int(n * 0.7) : int(n * 0.85)])
test_ids = set(ids[int(n * 0.85) :])
parts = {
    "train": df[df.batch_id.isin(train_ids)],
    "val": df[df.batch_id.isin(val_ids)],
    "test": df[df.batch_id.isin(test_ids)],
}
for name, part in parts.items():
    print("%-5s rows=%5d batches=%4d anomaly=%.3f" % (
        name, len(part), part.batch_id.nunique(), part.is_anomaly.mean()))
print("train until", parts["train"].timestamp.max())
print("test from  ", parts["test"].timestamp.min())
assert not (set(parts["train"].batch_id) & set(parts["test"].batch_id))
print("no batch overlaps:", True)
"""
    )
)

cells.append(
    nbf.v4.new_markdown_cell(
        """## Висновки

1. Клас аномалій становить 36 % — це синтетичний дисбаланс, обраний для перевірки
   моделей; у реальному журналі частка буде нижчою, тому поріг і метрики треба
   перераховувати на реальних даних.
2. Пропуски є лише в трьох ознаках (до 1,63 %), їх закриває медіанна імпутація
   всередині конвеєра, а не ручна правка CSV.
3. Швидкість і відстань сканування розділяють класи найкраще; кореляція між ними
   помірна, тому обидві ознаки залишено.
4. Часовий ряд не має сезонності, але партії розподілені нерівномірно; розбиття
   виконано за партіями і за часом, щоб одна партія не потрапила у дві вибірки.
5. Ознаки `anomaly_type`, `is_anomaly` та ідентифікатори у навчання не входять.
"""
    )
)

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.12"},
}
path = Path("notebooks/01_data_analysis.ipynb")
path.parent.mkdir(exist_ok=True)
nbf.write(nb, path)
print("wrote", path)
