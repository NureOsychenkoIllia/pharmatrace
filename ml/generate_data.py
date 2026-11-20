"""Generate a synthetic supply-chain event log modelled on DataCo Smart Supply Chain."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

CITIES = {
    "Kyiv": (50.4501, 30.5234),
    "Lviv": (49.8397, 24.0297),
    "Odesa": (46.4825, 30.7233),
    "Kharkiv": (49.9935, 36.2304),
    "Dnipro": (48.4647, 35.0462),
    "Zaporizhzhia": (47.8388, 35.1396),
    "Vinnytsia": (49.2331, 28.4682),
    "Poltava": (49.5883, 34.5514),
    "Chernivtsi": (48.2915, 25.9352),
    "Uzhhorod": (48.6208, 22.2879),
    "Warsaw": (52.2297, 21.0122),
    "Krakow": (50.0647, 19.9450),
    "Bucharest": (44.4268, 26.1025),
    "Chisinau": (47.0105, 28.8638),
}

PRODUCTS = [
    ("AMOX-500", "antibiotic", False),
    ("AZITHRO-250", "antibiotic", False),
    ("INSULIN-100", "insulin", True),
    ("VACCINE-FLU", "vaccine", True),
    ("IBUPROFEN-400", "analgesic", False),
    ("ONCO-500", "oncology", True),
]

ANOMALY_NAMES = {
    0: "normal",
    1: "route_deviation",
    2: "clone_scan",
    3: "time_anomaly",
    4: "quantity_mismatch",
    5: "license_anomaly",
}

LICENSE_CODES = {"active": 0, "expiring": 1, "suspended": 2, "revoked": 3}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


def build_participants(rng: np.random.Generator, n_dist: int = 24, n_pharm: int = 48) -> pd.DataFrame:
    rows = []
    cities = list(CITIES)
    for i in range(6):
        city = cities[i % len(cities)]
        rows.append(("M%02d" % i, "manufacturer", city, "active", int(rng.integers(400, 1800))))
    for i in range(n_dist):
        city = cities[int(rng.integers(0, len(cities)))]
        status = "active" if rng.random() > 0.06 else str(rng.choice(["expiring", "suspended"]))
        rows.append(("D%02d" % i, "distributor", city, status, int(rng.integers(60, 1200))))
    for i in range(n_pharm):
        city = cities[int(rng.integers(0, len(cities)))]
        status = "active" if rng.random() > 0.05 else str(rng.choice(["expiring", "suspended"]))
        rows.append(("P%02d" % i, "pharmacy", city, status, int(rng.integers(30, 900))))
    rows.append(("R00", "regulator", "Kyiv", "active", 2500))
    return pd.DataFrame(
        rows, columns=["participant_id", "kind", "city", "license_status", "license_age_days"]
    )


def build_events(rng: np.random.Generator, target: int) -> pd.DataFrame:
    participants = build_participants(rng)
    manufacturers = participants[participants.kind == "manufacturer"]
    distributors = participants[participants.kind == "distributor"]
    pharmacies = participants[participants.kind == "pharmacy"]

    rows: list[dict] = []
    batch_id = 0
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    while len(rows) < target:
        batch_id += 1
        product_id, category, cold = PRODUCTS[int(rng.integers(0, len(PRODUCTS)))]
        manufacturer = manufacturers.iloc[int(rng.integers(0, len(manufacturers)))]
        quantity = int(rng.integers(200, 2000))
        serial = 100_000 + batch_id
        t = start + pd.Timedelta(hours=float(rng.uniform(0, 24 * 170)))
        batch_start = t
        route = [manufacturer]
        for _ in range(int(rng.integers(1, 3))):
            route.append(distributors.iloc[int(rng.integers(0, len(distributors)))])
        route.append(pharmacies.iloc[int(rng.integers(0, len(pharmacies)))])
        route.append(pharmacies.iloc[int(rng.integers(0, len(pharmacies)))])

        cumulative = 0.0
        remaining = quantity
        for step, (src, dst) in enumerate(zip(route[:-1], route[1:]), start=1):
            lat1, lon1 = CITIES[src.city]
            lat2, lon2 = CITIES[dst.city]
            distance = haversine(lat1, lon1, lat2, lon2)
            transit = distance / float(rng.uniform(45, 75)) + float(rng.uniform(1, 6))
            ship_qty = max(10, int(remaining * rng.uniform(0.55, 1.0)))
            for event_type in ("ship", "receive", "scan"):
                t = t + pd.Timedelta(hours=transit / 3 + float(rng.uniform(0.2, 4)))
                cumulative += distance / 3
                temp = float(rng.normal(5 if cold else 20, 1.2))
                rows.append(
                    {
                        "event_id": len(rows) + 1,
                        "timestamp": t,
                        "batch_id": batch_id,
                        "product_id": product_id,
                        "product_category": category,
                        "cold_chain": int(cold),
                        "serial": serial,
                        "event_type": event_type,
                        "route_step": step,
                        "from_id": src.participant_id,
                        "to_id": dst.participant_id,
                        "from_city": src.city,
                        "to_city": dst.city,
                        "from_lat": lat1,
                        "from_lon": lon1,
                        "to_lat": lat2,
                        "to_lon": lon2,
                        "distance_km": round(distance, 2),
                        "transit_hours": round(transit, 3),
                        "quantity_sent": ship_qty,
                        "quantity_received": ship_qty,
                        "temperature_c": round(temp, 2),
                        "license_status": dst.license_status,
                        "license_age_days": int(dst.license_age_days),
                        "route_city": dst.city,
                        "scan_city": dst.city,
                        "scan_lat": lat2,
                        "scan_lon": lon2,
                        "scans_24h": int(rng.integers(0, 4)),
                        "same_serial_cities_24h": 1,
                        "batch_age_hours": round((t - batch_start).total_seconds() / 3600, 2),
                        "cumulative_distance_km": round(cumulative, 2),
                        "route_length": len(route) - 1,
                    }
                )
            remaining = ship_qty
            if remaining <= 10:
                break
        if len(rows) > target:
            rows = rows[:target]
            break

    df = pd.DataFrame(rows)
    df["event_id"] = np.arange(1, len(df) + 1)
    return df


def inject_anomalies(df: pd.DataFrame, rng: np.random.Generator, count: int) -> pd.DataFrame:
    idx = rng.choice(len(df), size=count, replace=False)
    types = np.concatenate(
        [
            np.full(int(count * 0.28), 1),
            np.full(int(count * 0.22), 2),
            np.full(int(count * 0.22), 3),
            np.full(int(count * 0.17), 4),
        ]
    )
    types = np.concatenate([types, np.full(count - len(types), 5)])
    rng.shuffle(types)

    df["is_anomaly"] = 0
    df["anomaly_type"] = 0
    for row, kind in zip(idx, types):
        df.loc[row, "is_anomaly"] = 1
        df.loc[row, "anomaly_type"] = int(kind)
        if kind == 1:
            far = CITIES[list(CITIES)[int(rng.integers(0, len(CITIES)))]]
            df.loc[row, "distance_km"] = round(float(rng.uniform(800, 2200)), 2)
            df.loc[row, "transit_hours"] = round(float(rng.uniform(0.5, 3.0)), 3)
            df.loc[row, "to_city"] = df.loc[row, "route_city"]
            df.loc[row, "to_lat"], df.loc[row, "to_lon"] = far
        elif kind == 2:
            far_city = list(CITIES)[int(rng.integers(0, len(CITIES)))]
            df.loc[row, "scan_city"] = far_city
            df.loc[row, "scan_lat"], df.loc[row, "scan_lon"] = CITIES[far_city]
            df.loc[row, "scans_24h"] = int(rng.integers(6, 20))
            df.loc[row, "same_serial_cities_24h"] = int(rng.integers(2, 5))
        elif kind == 3:
            if rng.random() < 0.5:
                df.loc[row, "transit_hours"] = round(float(rng.uniform(0.1, 1.0)), 3)
            else:
                df.loc[row, "transit_hours"] = round(float(rng.uniform(180, 600)), 3)
        elif kind == 4:
            sent = int(df.loc[row, "quantity_sent"])
            df.loc[row, "quantity_received"] = int(sent * float(rng.uniform(0.5, 0.95)))
        else:
            df.loc[row, "license_status"] = str(rng.choice(["suspended", "revoked"]))
    df["anomaly_name"] = df["anomaly_type"].map(ANOMALY_NAMES)
    return df


def add_missing(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    for column, rate in (("temperature_c", 0.015), ("transit_hours", 0.008), ("quantity_received", 0.01)):
        mask = rng.random(len(df)) < rate
        df.loc[mask, column] = np.nan
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=25_000)
    parser.add_argument("--anomalies", type=int, default=9_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/events.csv"))
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    df = build_events(rng, args.events)
    df = inject_anomalies(df, rng, args.anomalies)
    df = add_missing(df, rng)
    df.to_csv(args.out, index=False)
    print(f"rows={len(df)} batches={df.batch_id.nunique()} anomalies={int(df.is_anomaly.sum())}")
    print(df.anomaly_name.value_counts().to_string())


if __name__ == "__main__":
    main()
