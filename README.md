# PharmaTrace — простежуваність ліків і виявлення підробок

Система з трьох смарт-контрактів, ML-оракула, серверного API та вебінтерфейсу.
Партія ліків є NFT: виробник випускає її, дистриб'ютор і аптека передають
відповідальність, кожна дія пише подію в ланцюг. Оракул аналізує журнал передач
моделлю XGBoost, зберігає оцінку, версію моделі та хеш ознак у контрактах.

## Структура

```
project/
  src/                 контракти та інтерфейси
  test/                тести, газові стенди
  script/Deploy.s.sol  розгортання
  scripts/             seed, demo, атаки, перевірка цілісності
  ml/                  дані, ознаки, моделі, оракул, API
  notebooks/           аналіз даних
  web/                 вебінтерфейс (дві ролі)
  data/offchain/       позаланцюгові документи партій
  results/             метрики, графіки, журнали
  artifacts/           моделі та препроцесор
```

## Швидкий запуск

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
anvil
PRIVATE_KEY=<ключ anvil> VERIFIER=<адреса> ORACLE=<адреса> \
  forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast
./scripts/seed.sh
.venv/bin/python scripts/write_config.py
.venv/bin/uvicorn ml.api:app --host 127.0.0.1 --port 8000
```

Інтерфейс: `http://127.0.0.1:8000/app/index.html`.
Оракул: `ORACLE_PRIVATE_KEY=<ключ> .venv/bin/python -m ml.oracle --token 1 --clone`.

## Перевірки

```sh
forge test
forge coverage --report summary --exclude-tests
slither . --filter-paths "lib|test|script"
.venv/bin/python -m pytest
.venv/bin/python -m ml.generate_data
.venv/bin/python -m ml.train
.venv/bin/python -m ml.plots_data
.venv/bin/python -m ml.plots_models
.venv/bin/python -m ml.experiments
```

## Контракти

- `ParticipantRegistry` — ліцензії виробників, дистриб'юторів, аптек, регулятора.
- `BatchToken` — ERC-721, скінченний автомат партії, передача відповідальності,
  поділ, відпуск, відкликання, рішення оракула.
- `IncidentRegistry` — інциденти, рішення моделі, підтвердження та відкликання.

## Обмеження

Прототип не є медичним продуктом. Контракти неоновлювані, оракул є довіреною
точкою, Sepolia не використовувалася через відсутність фінансованого ключа.
Юридичні вимоги DSCSA, GDPR і національного регулювання не перевірялися.
