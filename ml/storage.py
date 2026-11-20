"""Off-chain document storage: canonical JSON with a SHA-256 content address."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def canonical_bytes(path: Path) -> bytes:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return path.read_bytes()


def digest(path: Path) -> str:
    return "0x" + hashlib.sha256(canonical_bytes(path)).hexdigest()


def put(path: Path) -> str:
    return digest(path)


def verify(path: Path, expected: str) -> bool:
    actual = digest(path)
    ok = actual.lower() == expected.lower()
    print(f"file     {path}")
    print(f"sha256   {actual}")
    print(f"on-chain {expected}")
    print("MATCH" if ok else "MISMATCH")
    return ok


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"put", "verify"}:
        print("usage: python -m ml.storage put <file> | verify <file> <hash>", file=sys.stderr)
        return 2
    if argv[1] == "put":
        print(put(Path(argv[2])))
        return 0
    if len(argv) != 4:
        return 2
    return 0 if verify(Path(argv[2]), argv[3]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
