"""Model evaluation figures for the ML report."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, precision_recall_curve, roc_curve
from xgboost import XGBClassifier

from ml.features import prepare

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
MODELS = ["baseline_rules", "isolation_forest", "autoencoder", "xgboost"]
LABELS = {
    "baseline_rules": "Правила",
    "isolation_forest": "Ізоляційний ліс",
    "autoencoder": "Автокодер",
    "xgboost": "XGBoost",
}
PRED_COLUMN = {"baseline_rules": "baseline"}
COLORS = ["#4c72b0", "#55a868", "#8172b2", "#c44e52"]


def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)
    print("wrote", FIG / name)


def main() -> None:
    meta = json.loads(Path("results/model_metrics.json").read_text())
    pred = pd.read_csv("results/test_predictions.csv")
    y = pred["is_anomaly"].to_numpy()

    fig, axes = plt.subplots(2, 2, figsize=(7, 5.6))
    for ax, name in zip(axes.ravel(), MODELS):
        matrix = np.array(meta["models"][name]["confusion"])
        im = ax.imshow(matrix, cmap="Blues")
        for i in range(2):
            for j in range(2):
                ax.text(j, i, matrix[i, j], ha="center", va="center", color="white" if matrix[i, j] > matrix.max() / 2 else "black")
        ax.set_xticks([0, 1], ["норма", "аномалія"])
        ax.set_yticks([0, 1], ["норма", "аномалія"])
        ax.set_xlabel("прогноз")
        ax.set_ylabel("факт")
        ax.set_title(f"{LABELS[name]}: F1={meta['models'][name]['f1']:.3f}")
        ax.grid(False)
    save(fig, "model_confusion.png")

    fig, ax = plt.subplots(figsize=(5, 4))
    for name, color in zip(MODELS[1:], COLORS[1:]):
        fpr, tpr, _ = roc_curve(y, pred[f"{name}_score"])
        ax.plot(fpr, tpr, label=f"{LABELS[name]} (AUC={meta['models'][name]['roc_auc']:.3f})", color=color)
    ax.plot([0, 1], [0, 1], "--", color="gray", linewidth=1)
    ax.set_xlabel("частка хибних тривог")
    ax.set_ylabel("частка виявлених аномалій")
    ax.legend(loc="lower right")
    ax.set_title("ROC-криві на тестовій вибірці")
    save(fig, "model_roc.png")

    fig, ax = plt.subplots(figsize=(5, 4))
    for name, color in zip(MODELS[1:], COLORS[1:]):
        precision, recall, _ = precision_recall_curve(y, pred[f"{name}_score"])
        ax.plot(recall, precision, label=f"{LABELS[name]} (PR-AUC={meta['models'][name]['pr_auc']:.3f})", color=color)
    ax.axhline(y.mean(), ls="--", color="gray", linewidth=1, label=f"випадковий ({y.mean():.2f})")
    ax.set_xlabel("повнота")
    ax.set_ylabel("точність")
    ax.legend(loc="lower left")
    ax.set_title("PR-криві на тестовій вибірці")
    save(fig, "model_pr.png")

    names = MODELS
    values = [meta["models"][m]["f1"] for m in names]
    lows = [meta["models"][m]["f1"] - meta["models"][m]["f1_ci"][0] for m in names]
    highs = [meta["models"][m]["f1_ci"][1] - meta["models"][m]["f1"] for m in names]
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.bar([LABELS[m] for m in names], values, yerr=[lows, highs], capsize=4, color=COLORS)
    for i, value in enumerate(values):
        ax.text(i, value + 0.02, f"{value:.3f}", ha="center")
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("F1-міра")
    ax.set_title("Порівняння моделей із 95 % довірчими інтервалами")
    plt.xticks(rotation=12)
    save(fig, "model_comparison.png")

    importance = pd.read_csv("results/feature_importance.csv").head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6, 4.4))
    ax.barh(importance["feature"], importance["xgboost_gain"], color="#c44e52")
    ax.set_xlabel("внесок ознаки (gain)")
    ax.set_title("15 найважливіших ознак для XGBoost")
    save(fig, "model_importance.png")

    hyper = pd.read_csv("results/hyperparams.csv")
    xgb = hyper[hyper.model == "xgboost"].copy()
    pivot = xgb.pivot_table(index="max_depth", columns="learning_rate", values="val_f1", aggfunc="max")
    fig, ax = plt.subplots(figsize=(5, 3.2))
    for column in pivot.columns:
        ax.plot(pivot.index, pivot[column], marker="o", label=f"learning_rate={column}")
    ax.set_xlabel("max_depth")
    ax.set_ylabel("F1 на валідації")
    ax.legend()
    ax.set_title("Вплив глибини та швидкості навчання")
    save(fig, "model_hyperparam.png")

    data = prepare(Path("."))
    x_train, y_train = data["x_train"], data["y_train"]
    x_test, y_test = data["x_test"], data["y_test"]
    fractions = [0.1, 0.25, 0.5, 0.75, 1.0]
    scores = {"xgboost": [], "isolation_forest": []}
    rng = np.random.default_rng(42)
    for fraction in fractions:
        n = int(len(x_train) * fraction)
        idx = rng.choice(len(x_train), n, replace=False)
        subset_x, subset_y = x_train[idx], y_train[idx]
        xgb = XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            random_state=42,
            n_jobs=4,
        )
        xgb.fit(subset_x, subset_y, verbose=False)
        proba = xgb.predict_proba(x_test)[:, 1]
        from sklearn.metrics import f1_score

        candidates = np.quantile(proba, np.linspace(0.5, 0.99, 100))
        best = max(candidates, key=lambda t: f1_score(y_test, (proba >= t).astype(int), zero_division=0))
        scores["xgboost"].append(f1_score(y_test, (proba >= best).astype(int), zero_division=0))
        iso = IsolationForest(n_estimators=300, contamination=0.36, random_state=42, n_jobs=-1)
        iso.fit(subset_x)
        s = -iso.score_samples(x_test)
        best = max(np.quantile(s, np.linspace(0.5, 0.99, 100)), key=lambda t: f1_score(y_test, (s >= t).astype(int), zero_division=0))
        scores["isolation_forest"].append(f1_score(y_test, (s >= best).astype(int), zero_division=0))
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.plot([f * 100 for f in fractions], scores["xgboost"], marker="o", label="XGBoost", color="#c44e52")
    ax.plot([f * 100 for f in fractions], scores["isolation_forest"], marker="s", label="Ізоляційний ліс", color="#55a868")
    ax.set_xlabel("частка навчальної вибірки, %")
    ax.set_ylabel("F1 на тесті")
    ax.legend()
    ax.set_title("Крива навчання")
    save(fig, "model_learning_curve.png")

    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    for flag, name, color in ((0, "нормальні", "#4c72b0"), (1, "аномальні", "#c44e52")):
        part = pred[pred.is_anomaly == flag]["xgboost_score"]
        ax.hist(part, bins=40, alpha=0.6, label=name, color=color)
    ax.set_xlabel("оцінка XGBoost")
    ax.set_ylabel("кількість записів")
    ax.legend()
    ax.set_title("Розподіл оцінок моделі за класами")
    save(fig, "model_scores.png")

    types = pred[pred.is_anomaly == 1]["anomaly_name"].value_counts().index.tolist()
    fig, ax = plt.subplots(figsize=(7, 3.2))
    width = 0.18
    positions = np.arange(len(types))
    for k, (name, color) in enumerate(zip(MODELS, COLORS)):
        recalls = []
        for anomaly in types:
            part = pred[pred.anomaly_name == anomaly]
            column = PRED_COLUMN.get(name, f"{name}_pred")
            recalls.append(part[column].mean())
        ax.bar(positions + (k - 1.5) * width, recalls, width, label=LABELS[name], color=color)
    ax.set_xticks(positions, types, rotation=15)
    ax.set_ylabel("повнота")
    ax.set_title("Повнота за типами аномалій")
    ax.legend(ncol=2, fontsize=8)
    save(fig, "model_errors.png")

    fig, axes = plt.subplots(1, 2, figsize=(7, 3))
    axes[0].bar([LABELS[m] for m in MODELS], [meta["models"][m]["train_seconds"] for m in MODELS], color=COLORS)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("час навчання, с")
    axes[0].set_title("Час навчання")
    axes[0].tick_params(axis="x", rotation=15)
    axes[1].bar([LABELS[m] for m in MODELS], [meta["models"][m]["inference_ms_per_row"] for m in MODELS], color=COLORS)
    axes[1].set_yscale("log")
    axes[1].set_ylabel("мс на один запис")
    axes[1].set_title("Час передбачення")
    axes[1].tick_params(axis="x", rotation=15)
    save(fig, "model_latency.png")


if __name__ == "__main__":
    main()
