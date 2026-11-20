# PharmaTrace

Прототип простежуваності ліків і виявлення підробок. Партія представлена токеном ERC-721, а передавання відповідальності фіксується в блокчейні. Оракул XGBoost записує оцінку аномальності, версію моделі та хеш вхідних даних. Регулятор переглядає інциденти й підтверджує відкликання партій.

Для тестування використовували локальний Anvil і тестову мережу Sepolia. У [результатах експериментів](results/experiments.json) збережено по п’ять локальних прогонів наскрізного сценарію та кожного рівня навантаження.

## Локальний запуск

Потрібні Foundry та `uv`. У корені репозиторію встановіть залежності й запустіть Anvil.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
forge install --no-git foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
anvil
```

Другий термінал використовує стандартні тестові акаунти Anvil. Команда бере поріг аномальності з метрик навченої моделі.

```sh
mnemonic='test test test test test test test test test test test junk'
deployer_key=$(cast wallet private-key "$mnemonic" 0)
oracle_key=$(cast wallet private-key "$mnemonic" 4)
threshold=$(.venv/bin/python -c 'import json; print(round(json.load(open("results/model_metrics.json"))["models"]["xgboost"]["threshold"] * 10000))')
PRIVATE_KEY="$deployer_key" THRESHOLD_BPS="$threshold" \
  VERIFIER=0x70997970C51812dc3A010C7d01b50e0d17dc79C8 \
  ORACLE=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65 \
  forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast
./scripts/seed.sh
.venv/bin/python scripts/write_config.py
ORACLE_PRIVATE_KEY="$oracle_key" .venv/bin/python -m ml.oracle --token 1 --clone
.venv/bin/uvicorn ml.api:app --host 127.0.0.1 --port 8000
```

[Відкрити локальний інтерфейс](http://127.0.0.1:8000/app/index.html). `seed.sh` імпортує метадані в SQLite. Перед показом API звіряє хеш документа з блокчейном. Оракул реєструє SHA-256 моделі в `IncidentRegistry` і зберігає підписані транзакції, щоб відновити запис за тим самим хешем після збою.

## Перевірки та експерименти

```sh
forge test
forge coverage --report summary --exclude-tests
slither . --filter-paths 'lib|test|script'
.venv/bin/python -m pytest
```

Для відтворення експериментів після клонування виконайте `.venv/bin/python -m ml.train` перед розгортанням контрактів і запуском API. Команда відтворює артефакт Isolation Forest. Навчальна, валідаційна й тестова вибірки мають окремі часові вікна, а партії на межах вилучаються. Під час вимірювань залиште Anvil і API запущеними.

```sh
.venv/bin/python -m ml.experiments
.venv/bin/python -m ml.plots_experiments
python3 scripts/cost_report.py
```

Контракти та їхні інтерфейси містяться в [src/](src/), архітектурні діаграми — у [diagrams/](diagrams/), метрики й графіки — у [results/](results/). Опис моделі та її обмежень є в [картці моделі](artifacts/model_card.md).

## Модель загроз

| Компонент | Загроза | Захист і залишковий ризик |
|---|---|---|
| Серійний номер | Клон упаковки | Перевірка партії й оцінка аномальності. Клон може лишитися непоміченим до першого спостереження. |
| Передавання партії | Запис без згоди отримувача | Двоетапна передача й перевірка ролей. Учасник із дійсним ключем може підтвердити хибні дані. |
| Ланцюг постачання | Змова учасників | Публічна історія й розгляд регулятором. Узгоджені хибні записи можуть пройти перевірки. |
| Оракул | Компрометація ключа | Окрема роль, ротація ключа й рішення регулятора. Хибні оцінки до ротації зберігаються в історії. |
| Інциденти | Повтор рішення | Контроль стану й повторне надсилання тієї самої транзакції. Оракул усе ще може створювати нові інциденти. |
| SQLite | Підміна метаданих | Звірення хешу з контрактом. Достовірність початкових даних залежить від автора запису. |
| Контракт партії | Надмірний поділ | Ліміт дочірніх партій. Великі дозволені поділи потребують більше газу. |
| Журнал подій | Розкриття чутливих даних | Хеші й криптографічні зобов’язання. Передбачувані вхідні дані вразливі до підбору. |
