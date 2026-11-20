"""Feature engineering and leak-free train/validation/test split."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC = [
    "distance_km",
    "transit_hours",
    "speed_kmh",
    "quantity_sent",
    "quantity_received",
    "quantity_delta",
    "quantity_ratio",
    "temperature_c",
    "temp_deviation",
    "hour",
    "weekday",
    "is_night",
    "route_step",
    "route_length",
    "batch_age_hours",
    "cumulative_distance_km",
    "scans_24h",
    "scan_distance_km",
    "same_serial_cities_24h",
    "license_status_code",
    "license_age_days",
    "detour_ratio",
    "scan_velocity",
    "cold_chain",
]

CATEGORICAL = ["event_type", "product_category"]

LICENSE_CODES = {"active": 0, "expiring": 1, "suspended": 2, "revoked": 3}


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["speed_kmh"] = out["distance_km"] / out["transit_hours"].replace(0, np.nan)
    out["quantity_delta"] = out["quantity_sent"] - out["quantity_received"]
    out["quantity_ratio"] = out["quantity_received"] / out["quantity_sent"].replace(0, np.nan)
    target = np.where(out["cold_chain"] == 1, 5.0, 20.0)
    out["temp_deviation"] = (out["temperature_c"] - target).abs()
    out["hour"] = out["timestamp"].dt.hour
    out["weekday"] = out["timestamp"].dt.weekday
    out["is_night"] = ((out["hour"] < 6) | (out["hour"] >= 22)).astype(int)
    out["scan_distance_km"] = haversine(
        out["to_lat"], out["to_lon"], out["scan_lat"], out["scan_lon"]
    )
    out["license_status_code"] = out["license_status"].map(LICENSE_CODES).fillna(0)
    step_distance = out["cumulative_distance_km"] / out["route_step"].replace(0, np.nan)
    out["detour_ratio"] = out["distance_km"] / step_distance.replace(0, np.nan)
    out["scan_velocity"] = out["same_serial_cities_24h"] / out["scans_24h"].clip(lower=1)
    return out


def split_by_batch_time(df: pd.DataFrame, train: float = 0.7, val: float = 0.15):
    bounds = df.groupby("batch_id")["timestamp"].agg(start="min", end="max").sort_values("start")
    val_start = bounds.iloc[int(len(bounds) * train)]["start"]
    test_start = bounds.iloc[int(len(bounds) * (train + val))]["start"]
    # A batch crossing a boundary is excluded as a whole so its history stays intact.
    groups = [
        bounds["end"] < val_start,
        (bounds["start"] >= val_start) & (bounds["end"] < test_start),
        bounds["start"] >= test_start,
    ]
    return [df[df["batch_id"].isin(bounds.index[group])].reset_index(drop=True) for group in groups]


def build_preprocessor() -> ColumnTransformer:
    numeric = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
            ),
        ]
    )
    return ColumnTransformer(
        [
            ("num", numeric, NUMERIC),
            ("cat", categorical, CATEGORICAL),
        ],
        sparse_threshold=0,
    )


def prepare(root: Path = Path("."), seed: int = 42):
    df = engineer(pd.read_csv(root / "data/events.csv"))
    train, val, test = split_by_batch_time(df)
    pre = build_preprocessor()
    x_train = pre.fit_transform(train[NUMERIC + CATEGORICAL])
    x_val = pre.transform(val[NUMERIC + CATEGORICAL])
    x_test = pre.transform(test[NUMERIC + CATEGORICAL])
    names = list(pre.get_feature_names_out())
    return {
        "train": train,
        "val": val,
        "test": test,
        "x_train": x_train,
        "x_val": x_val,
        "x_test": x_test,
        "y_train": train["is_anomaly"].to_numpy(),
        "y_val": val["is_anomaly"].to_numpy(),
        "y_test": test["is_anomaly"].to_numpy(),
        "preprocessor": pre,
        "feature_names": names,
    }


def rule_baseline(df: pd.DataFrame) -> np.ndarray:
    """Allowed-transition rules: custody order, license state and quantity balance."""
    ordered = df.sort_values(["batch_id", "timestamp"]).copy()
    previous = ordered.groupby("batch_id")["event_type"].shift(1)
    allowed = {
        (None, "ship"),
        ("ship", "receive"),
        ("receive", "scan"),
        ("scan", "ship"),
    }
    pair = list(zip(previous.fillna("__start__").tolist(), ordered["event_type"].tolist()))
    sequence_bad = np.array([(None if a == "__start__" else a, b) not in allowed for a, b in pair])

    step_prev = ordered.groupby("batch_id")["route_step"].shift(1)
    step_bad = (ordered["route_step"] < step_prev).fillna(False).to_numpy()
    license_bad = ordered["license_status_code"].fillna(0).to_numpy() >= 2
    quantity_bad = ordered["quantity_ratio"].fillna(1).to_numpy() < 0.99
    flag = sequence_bad | step_bad | license_bad | quantity_bad
    result = pd.Series(flag.astype(int), index=ordered.index)
    return result.reindex(df.index).to_numpy()
