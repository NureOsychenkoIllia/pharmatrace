"""Train the rule baseline, Isolation Forest, autoencoder and XGBoost; save metrics."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPRegressor
from xgboost import XGBClassifier

from ml.features import NUMERIC, prepare, rule_baseline

SEED = 42
ROOT = Path(".")
RESULTS = ROOT / "results"
ARTIFACTS = ROOT / "artifacts"
RESULTS.mkdir(exist_ok=True)
ARTIFACTS.mkdir(exist_ok=True)


def score_metrics(y: np.ndarray, score: np.ndarray, threshold: float) -> dict:
    pred = (score >= threshold).astype(int)
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "accuracy": float(accuracy_score(y, pred)),
        "roc_auc": float(roc_auc_score(y, score)),
        "pr_auc": float(average_precision_score(y, score)),
        "alert_rate": float(pred.mean()),
        "confusion": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
    }


def best_threshold(y: np.ndarray, score: np.ndarray) -> float:
    candidates = np.quantile(score, np.linspace(0.5, 0.999, 300))
    best, best_f1 = candidates[0], -1.0
    for t in candidates:
        value = f1_score(y, (score >= t).astype(int), zero_division=0)
        if value > best_f1:
            best, best_f1 = float(t), value
    return best


def bootstrap_f1(y: np.ndarray, pred: np.ndarray, n: int = 1000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    values = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        values.append(f1_score(y[idx], pred[idx], zero_division=0))
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def save_model(name: str, model) -> tuple[Path, str, int]:
    path = ARTIFACTS / f"{name}.joblib"
    joblib.dump(model, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (ARTIFACTS / f"{name}.sha256").write_text("0x" + digest + "\n")
    return path, "0x" + digest, path.stat().st_size


def main() -> None:
    data = prepare(ROOT, SEED)
    x_train, x_val, x_test = data["x_train"], data["x_val"], data["x_test"]
    y_train, y_val, y_test = data["y_train"], data["y_val"], data["y_test"]
    train_df, val_df, test_df = data["train"], data["val"], data["test"]
    print("split", len(train_df), len(val_df), len(test_df))
    print("anomaly rate", y_train.mean(), y_val.mean(), y_test.mean())

    metrics: dict[str, dict] = {}
    hyper_rows: list[dict] = []
    models: dict[str, object] = {}
    scores_val: dict[str, np.ndarray] = {}
    scores_test: dict[str, np.ndarray] = {}

    started = time.perf_counter()
    base_val = rule_baseline(val_df)
    base_test = rule_baseline(test_df)
    metrics["baseline_rules"] = {
        **score_metrics(y_test, base_test.astype(float), 0.5),
        "threshold": 0.5,
        "train_seconds": 0.0,
        "inference_ms_per_row": 0.0,
        "size_bytes": 0,
        "hash": "",
        "family": "rules",
    }
    metrics["baseline_rules"]["f1_ci"] = bootstrap_f1(y_test, base_test)
    print("baseline rules", metrics["baseline_rules"]["f1"])

    iforest_grid = [
        {"n_estimators": 100, "max_samples": 0.5, "contamination": 0.20},
        {"n_estimators": 100, "max_samples": 1.0, "contamination": 0.36},
        {"n_estimators": 300, "max_samples": 0.5, "contamination": 0.20},
        {"n_estimators": 300, "max_samples": 1.0, "contamination": 0.36},
        {"n_estimators": 300, "max_samples": 0.7, "contamination": 0.30},
        {"n_estimators": 500, "max_samples": 0.7, "contamination": 0.36},
    ]
    best_if, best_if_f1 = None, -1.0
    for params in iforest_grid:
        model = IsolationForest(random_state=SEED, n_jobs=-1, **params)
        t0 = time.perf_counter()
        model.fit(x_train)
        elapsed = time.perf_counter() - t0
        score = -model.score_samples(x_val)
        threshold = best_threshold(y_val, score)
        f1 = f1_score(y_val, (score >= threshold).astype(int), zero_division=0)
        hyper_rows.append({"model": "isolation_forest", **params, "val_f1": f1})
        if f1 > best_if_f1:
            best_if, best_if_f1 = (model, threshold, elapsed), f1
    if_model, if_threshold, if_time = best_if
    models["isolation_forest"] = if_model
    scores_val["isolation_forest"] = -if_model.score_samples(x_val)
    t0 = time.perf_counter()
    scores_test["isolation_forest"] = -if_model.score_samples(x_test)
    if_infer = (time.perf_counter() - t0) / len(x_test) * 1000
    _, if_hash, if_size = save_model("isolation_forest", if_model)
    metrics["isolation_forest"] = {
        **score_metrics(y_test, scores_test["isolation_forest"], if_threshold),
        "train_seconds": if_time,
        "inference_ms_per_row": if_infer,
        "size_bytes": if_size,
        "hash": if_hash,
        "family": "bagging",
    }
    metrics["isolation_forest"]["f1_ci"] = bootstrap_f1(
        y_test, (scores_test["isolation_forest"] >= if_threshold).astype(int)
    )
    print("isolation forest", metrics["isolation_forest"]["f1"])

    ae_grid = [
        {"hidden_layer_sizes": (16, 8, 16), "alpha": 1e-4},
        {"hidden_layer_sizes": (32, 16, 32), "alpha": 1e-4},
        {"hidden_layer_sizes": (32, 16, 32), "alpha": 1e-3},
        {"hidden_layer_sizes": (64, 24, 64), "alpha": 1e-3},
    ]
    n_numeric = len(NUMERIC)

    def ae_score(model, x):
        recon = model.predict(x)
        return np.mean((x[:, :n_numeric] - recon[:, :n_numeric]) ** 2, axis=1)

    normal_train = x_train[y_train == 0]
    best_ae, best_ae_f1 = None, -1.0
    for params in ae_grid:
        model = MLPRegressor(
            activation="relu",
            solver="adam",
            learning_rate_init=5e-4,
            batch_size=128,
            max_iter=600,
            early_stopping=True,
            n_iter_no_change=20,
            validation_fraction=0.1,
            random_state=SEED,
            **params,
        )
        t0 = time.perf_counter()
        model.fit(normal_train, normal_train)
        elapsed = time.perf_counter() - t0
        recon = ae_score(model, x_val)
        threshold = best_threshold(y_val, recon)
        f1 = f1_score(y_val, (recon >= threshold).astype(int), zero_division=0)
        hyper_rows.append(
            {
                "model": "autoencoder",
                "hidden_layer_sizes": str(params["hidden_layer_sizes"]),
                "alpha": params["alpha"],
                "val_f1": f1,
            }
        )
        if f1 > best_ae_f1:
            best_ae, best_ae_f1 = (model, threshold, elapsed), f1
    ae_model, ae_threshold, ae_time = best_ae
    models["autoencoder"] = ae_model
    t0 = time.perf_counter()
    scores_test["autoencoder"] = ae_score(ae_model, x_test)
    ae_infer = (time.perf_counter() - t0) / len(x_test) * 1000
    _, ae_hash, ae_size = save_model("autoencoder", ae_model)
    metrics["autoencoder"] = {
        **score_metrics(y_test, scores_test["autoencoder"], ae_threshold),
        "train_seconds": ae_time,
        "inference_ms_per_row": ae_infer,
        "size_bytes": ae_size,
        "hash": ae_hash,
        "family": "neural_network",
    }
    metrics["autoencoder"]["f1_ci"] = bootstrap_f1(
        y_test, (scores_test["autoencoder"] >= ae_threshold).astype(int)
    )
    print("autoencoder", metrics["autoencoder"]["f1"])

    scale = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    xgb_grid = [
        {"max_depth": 3, "learning_rate": 0.05, "n_estimators": 200},
        {"max_depth": 3, "learning_rate": 0.1, "n_estimators": 300},
        {"max_depth": 4, "learning_rate": 0.05, "n_estimators": 300},
        {"max_depth": 4, "learning_rate": 0.1, "n_estimators": 300},
        {"max_depth": 6, "learning_rate": 0.05, "n_estimators": 400},
        {"max_depth": 6, "learning_rate": 0.1, "n_estimators": 300},
    ]
    best_xgb, best_xgb_f1 = None, -1.0
    for params in xgb_grid:
        model = XGBClassifier(
            **params,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=scale,
            eval_metric="logloss",
            early_stopping_rounds=30,
            random_state=SEED,
            n_jobs=4,
        )
        t0 = time.perf_counter()
        model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
        elapsed = time.perf_counter() - t0
        proba = model.predict_proba(x_val)[:, 1]
        threshold = best_threshold(y_val, proba)
        f1 = f1_score(y_val, (proba >= threshold).astype(int), zero_division=0)
        hyper_rows.append({"model": "xgboost", **params, "val_f1": f1})
        if f1 > best_xgb_f1:
            best_xgb, best_xgb_f1 = (model, threshold, elapsed), f1
    xgb_model, xgb_threshold, xgb_time = best_xgb
    models["xgboost"] = xgb_model
    t0 = time.perf_counter()
    scores_test["xgboost"] = xgb_model.predict_proba(x_test)[:, 1]
    xgb_infer = (time.perf_counter() - t0) / len(x_test) * 1000
    _, xgb_hash, xgb_size = save_model("xgboost", xgb_model)
    metrics["xgboost"] = {
        **score_metrics(y_test, scores_test["xgboost"], xgb_threshold),
        "train_seconds": xgb_time,
        "inference_ms_per_row": xgb_infer,
        "size_bytes": xgb_size,
        "hash": xgb_hash,
        "family": "boosting",
    }
    metrics["xgboost"]["f1_ci"] = bootstrap_f1(
        y_test, (scores_test["xgboost"] >= xgb_threshold).astype(int)
    )
    print("xgboost", metrics["xgboost"]["f1"])

    pd.DataFrame(hyper_rows).to_csv(RESULTS / "hyperparams.csv", index=False)

    predictions = test_df[["event_id", "batch_id", "anomaly_type", "anomaly_name", "is_anomaly"]].copy()
    predictions["baseline"] = base_test
    for name, score in scores_test.items():
        predictions[f"{name}_score"] = score
        predictions[f"{name}_pred"] = (
            score >= metrics[name]["threshold"]
        ).astype(int)
    predictions.to_csv(RESULTS / "test_predictions.csv", index=False)

    importance = pd.DataFrame(
        {
            "feature": data["feature_names"],
            "xgboost_gain": xgb_model.feature_importances_,
        }
    ).sort_values("xgboost_gain", ascending=False)
    recon_err = (x_test - ae_model.predict(x_test)) ** 2
    ae_importance = recon_err[y_test == 1].mean(axis=0) - recon_err[y_test == 0].mean(axis=0)
    importance["autoencoder_delta"] = ae_importance
    importance.to_csv(RESULTS / "feature_importance.csv", index=False)

    total = time.perf_counter() - started
    payload = {
        "dataset": {
            "rows": len(train_df) + len(val_df) + len(test_df),
            "train_rows": len(train_df),
            "val_rows": len(val_df),
            "test_rows": len(test_df),
            "anomaly_rate": float(
                (len(train_df) + len(val_df) + len(test_df))
                and (y_train.sum() + y_val.sum() + y_test.sum())
                / (len(train_df) + len(val_df) + len(test_df))
            ),
            "seed": SEED,
        },
        "split": {
            "train_batches": int(train_df.batch_id.nunique()),
            "val_batches": int(val_df.batch_id.nunique()),
            "test_batches": int(test_df.batch_id.nunique()),
            "train_until": str(train_df.timestamp.max()),
            "val_from": str(val_df.timestamp.min()),
            "val_until": str(val_df.timestamp.max()),
            "test_from": str(test_df.timestamp.min()),
        },
        "models": metrics,
        "best_model": max(metrics, key=lambda k: metrics[k]["f1"]),
        "feature_names": data["feature_names"],
        "total_seconds": total,
    }
    (RESULTS / "model_metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    joblib.dump(data["preprocessor"], ARTIFACTS / "preprocessor.joblib")
    print("done in %.1fs" % total)
    print(json.dumps({k: round(v["f1"], 4) for k, v in metrics.items()}, indent=2))


if __name__ == "__main__":
    main()
