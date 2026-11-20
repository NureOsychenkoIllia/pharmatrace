"""Off-chain document storage: canonical JSON with a SHA-256 content address."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def canonical_bytes(path: Path) -> bytes:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return path.read_bytes()


def digest(path: Path) -> str:
    return digest_bytes(canonical_bytes(path))


def digest_bytes(payload: bytes) -> str:
    return "0x" + hashlib.sha256(payload).hexdigest()


def import_documents(database: Path, paths: list[Path]) -> None:
    records = [(str(int(path.stem.removeprefix("batch-"))), canonical_bytes(path)) for path in paths]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS documents (serial TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        conn.executemany(
            "INSERT INTO documents VALUES (?, ?) ON CONFLICT(serial) DO UPDATE SET payload=excluded.payload",
            records,
        )


def load_document(directory: Path, serial: int) -> tuple[str, bytes] | None:
    database = directory / "metadata.sqlite"
    if database.exists():
        with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT payload FROM documents WHERE serial=?", (str(serial),)).fetchone()
        return (f"data/offchain/{database.name}#{serial}", row[0]) if row else None
    # Existing local checkouts may still use legacy JSON fixtures before the first seed.
    path = directory / f"batch-{serial}.json"
    return (f"data/offchain/{path.name}", canonical_bytes(path)) if path.is_file() else None


def verify(path: Path, expected: str) -> bool:
    actual = digest(path)
    ok = actual.lower() == expected.lower()
    print(f"file     {path}")
    print(f"sha256   {actual}")
    print(f"on-chain {expected}")
    print("MATCH" if ok else "MISMATCH")
    return ok


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "import":
        import_documents(Path(argv[2]), [Path(path) for path in argv[3:]])
        return 0
    if len(argv) < 3 or argv[1] not in {"put", "verify"}:
        print("usage: python -m ml.storage put <file> | verify <file> <hash> | import <db> <files...>", file=sys.stderr)
        return 2
    if argv[1] == "put":
        print(digest(Path(argv[2])))
        return 0
    if len(argv) != 4:
        return 2
    return 0 if verify(Path(argv[2]), argv[3]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
