"""Write web/config.json from the local deployment."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENT = ROOT / "deployments/31337.json"

ACCOUNTS = [
    ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "Виробник", "manufacturer"),
    ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "Регулятор", "regulator"),
    ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "Дистриб'ютор", "distributor"),
    ("0x90F79bf6EB2c4f870365E785982E1f101E93b906", "Аптека", "pharmacy"),
    ("0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65", "Оракул", "oracle"),
    ("0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc", "Аптека №2", "pharmacy"),
]


def main() -> None:
    deployment = json.loads(DEPLOYMENT.read_text())
    config = {
        "chainId": deployment["chainId"],
        "rpcUrl": "http://127.0.0.1:8545",
        "registry": deployment["registry"],
        "batch": deployment["batch"],
        "incidents": deployment["incidents"],
        "oracle": deployment["oracle"],
        "accounts": [
            {"address": address, "label": label, "role": role}
            for address, label, role in ACCOUNTS
        ],
    }
    (ROOT / "web/config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print("wrote web/config.json")


if __name__ == "__main__":
    main()
