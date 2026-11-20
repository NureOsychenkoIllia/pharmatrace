// PharmaTrace dApp: chain state, custody actions, model decision and audit.

const BATCH_ABI = [
  "function batchCount() view returns (uint256)",
  "function getBatches(uint256 offset, uint256 limit) view returns (tuple(uint256 id, bytes32 productId, uint64 serial, address manufacturer, address custodian, uint64 expiry, uint64 createdAt, uint8 state, uint128 quantity, uint128 parentId, bytes32 metadataHash, bytes2 originCity, bool flagged, uint16 anomalyScore)[])",
  "function getBatch(uint256 tokenId) view returns (tuple(bytes32 productId, bytes32 metadataHash, bytes32 modelVersion, bytes32 dataHash, address manufacturer, uint64 serial, uint16 anomalyScore, bool flagged, uint8 state, address custodian, uint64 expiry, bytes2 originCity, address pendingRecipient, uint64 createdAt, uint128 quantity, uint128 parentId))",
  "function anomalyOf(uint256 tokenId) view returns (uint16 scoreBps, bool flagged, bytes32 modelVersion, bytes32 dataHash)",
  "function verifySerial(bytes32 productId, uint64 serial) view returns (uint256)",
  "function initiateCustody(uint256 tokenId, address to, bytes2 city)",
  "function acceptCustody(uint256 tokenId)",
  "function rejectCustody(uint256 tokenId)",
  "function split(uint256 tokenId, uint128[] quantities) returns (uint256[])",
  "function dispense(uint256 tokenId, bytes32 commitment)",
  "function recall(uint256 tokenId, bytes32 reasonHash)",
  "event AnomalyRecorded(uint256 indexed tokenId, uint16 scoreBps, bytes32 modelVersion, bytes32 dataHash, uint8 anomalyType)",
  "event CustodyAccepted(uint256 indexed tokenId, address indexed from, address indexed to)",
  "event BatchSplit(uint256 indexed parentId, uint256[] childIds, uint128[] quantities, address indexed custodian)",
  "error NotManufacturer(address account)",
  "error NotCustodian(uint256 tokenId, address account)",
  "error InvalidRecipient(address account)",
  "error InvalidQuantity()",
  "error InvalidExpiry()",
  "error DuplicateSerial(bytes32 productId, uint64 serial)",
  "error BatchNotFound(uint256 tokenId)",
  "error InvalidState(uint256 tokenId, uint8 state)",
  "error NotPendingRecipient(uint256 tokenId, address account)",
  "error NotPharmacy(address account)",
  "error InvalidScore(uint16 scoreBps)",
  "error InvalidSplit()",
  "error NotRecallable(uint256 tokenId)",
  "error UseCustodyWorkflow()",
  "error InvalidThreshold(uint16 thresholdBps)",
  "error AccessControlUnauthorizedAccount(address account, bytes32 neededRole)",
];

const REGISTRY_ABI = [
  "function participantOf(address account) view returns (uint8 kind, uint8 status, bytes32 licenseHash, bytes2 city, uint64 registeredAt)",
  "function kindOf(address account) view returns (uint8)",
  "error NotRegistered(address account)",
  "error WrongStatus(address account, uint8 status)",
];

const INCIDENT_ABI = [
  "function incidentCount() view returns (uint256)",
  "function getIncident(uint256 incidentId) view returns (tuple(uint256 batchId, uint8 kind, uint8 severity, uint8 status, address reporter, uint64 createdAt, uint16 scoreBps, bytes32 modelVersion, bytes32 dataHash, bytes32 noteHash))",
  "function incidentsByBatch(uint256 batchId) view returns (uint256[])",
  "function confirmIncident(uint256 incidentId)",
  "function dismissIncident(uint256 incidentId)",
  "function resolveIncident(uint256 incidentId)",
  "error NotParticipant(address account)",
  "error IncidentNotFound(uint256 incidentId)",
  "error InvalidTransition(uint256 incidentId, uint8 status)",
  "error InvalidScore(uint16 scoreBps)",
  "error BatchNotFound(uint256 batchId)",
  "error AccessControlUnauthorizedAccount(address account, bytes32 neededRole)",
];

const STATES = ["Немає", "Створено", "У дорозі", "Доставлено", "Відпущено", "Відкликано", "Знищено"];
const STATE_BADGE = ["badge-muted", "badge-active", "badge-warn", "badge-success", "badge-violet", "badge-failed", "badge-muted"];
const KINDS = ["Фальсифікат", "Аномалія маршруту", "Фальсифікат", "Запит на відкликання", "Спір про передачу"];
const SEVERITIES = ["—", "низький", "середній", "високий", "критичний"];
const INCIDENT_STATES = ["Немає", "Відкрито", "Рішення моделі", "Підтверджено", "Відхилено", "Закрито"];
const ROLES = ["Без ролі", "Виробник", "Дистриб'ютор", "Аптека", "Регулятор"];
const ROLE_BADGE = ["badge-muted", "badge-active", "badge-warn", "badge-success", "badge-violet"];

const ERROR_TEXT = {
  NotManufacturer: "Дію може виконати лише виробник партії",
  NotCustodian: "Ви не є поточним розпорядником партії",
  InvalidRecipient: "Отримувач не має активної ліцензії потрібного типу",
  InvalidQuantity: "Некоректна кількість",
  InvalidExpiry: "Термін придатності вже минув",
  DuplicateSerial: "Партія з таким серійним номером уже існує",
  BatchNotFound: "Партію не знайдено",
  InvalidState: "Дія неможлива в цьому стані партії",
  NotPendingRecipient: "Ви не є очікуваним отримувачем",
  NotPharmacy: "Відпускати ліки може лише аптека",
  InvalidScore: "Оцінка моделі поза діапазоном",
  InvalidSplit: "Некоректний поділ партії",
  NotRecallable: "Партію не можна відкликати в цьому стані",
  UseCustodyWorkflow: "Прямий переказ NFT заборонено; використовуйте передачу відповідальності",
  InvalidThreshold: "Поріг аномалії поза діапазоном",
  AccessControlUnauthorizedAccount: "Недостатньо прав для цієї дії",
  NotRegistered: "Учасника не зареєстровано",
  WrongStatus: "Неприпустимий статус учасника",
  NotParticipant: "Звіт може подати лише зареєстрований учасник",
  IncidentNotFound: "Інцидент не знайдено",
  InvalidTransition: "Неприпустимий перехід стану інциденту",
  EnforcedPause: "Систему зупинено адміністратором",
  OwnableUnauthorizedAccount: "Недостатньо прав",
};

let config, provider, signer, account, roleKind = 0;
let batchContract, registryContract, incidentContract;
let batches = [];
let incidents = [];
let timer = null;

const $ = (id) => document.getElementById(id);
const apiGet = (url) => fetch(url, { cache: "no-store" });
const short = (value) => (value ? value.slice(0, 6) + "…" + value.slice(-4) : "");
const txLink = (hash) => {
  if (!/^0x[0-9a-f]{64}$/i.test(hash)) return "—";
  const url = Number(config.chainId) === 11155111
    ? `https://sepolia.etherscan.io/tx/${hash}`
    : `/api/transactions/${hash}`;
  return `<a href="${url}" target="_blank" rel="noopener noreferrer" title="${hash}">${short(hash)}</a>`;
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hex = (value) => (value ? "0x" + BigInt(value).toString(16).padStart(64, "0").slice(-64) : "—");
const city = (value) => {
  if (!value || value === "0x0000") return "—";
  const raw = value.slice(2, 6);
  return String.fromCharCode(parseInt(raw.slice(0, 2), 16), parseInt(raw.slice(2, 4), 16));
};
const bytes2 = (value) =>
  "0x" + Array.from(value.toUpperCase()).slice(0, 2).map((ch) => ch.charCodeAt(0).toString(16).padStart(2, "0")).join("");

function toast(kind, text) {
  const node = document.createElement("div");
  node.className = "toast " + kind;
  node.textContent = text;
  $("toasts").appendChild(node);
  setTimeout(() => node.remove(), 6000);
}

function openModal(title, body) {
  $("modal-title").textContent = title;
  $("modal-body").textContent = typeof body === "string" ? body : JSON.stringify(body, null, 2);
  $("modal").classList.remove("hidden");
}

function closeModal() { $("modal").classList.add("hidden"); }

function decodeError(error) {
  const data =
    error?.data ||
    error?.info?.error?.data ||
    error?.error?.data ||
    error?.revert?.data;
  if (data && typeof data === "string") {
    for (const contract of [batchContract, incidentContract, registryContract]) {
      try {
        const parsed = contract.interface.parseError(data);
        if (parsed) return ERROR_TEXT[parsed.name] || parsed.name;
      } catch (_) { /* selector belongs to another contract */ }
    }
  }
  return error?.shortMessage || error?.reason || error?.message || "Невідома помилка";
}

async function init() {
  config = await (await fetch("config.json")).json();
  batchContract = new ethers.Contract(config.batch, BATCH_ABI);
  registryContract = new ethers.Contract(config.registry, REGISTRY_ABI);
  incidentContract = new ethers.Contract(config.incidents, INCIDENT_ABI);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      tab.classList.add("active");
      $(`tab-${tab.dataset.tab}`).classList.add("active");
      if (tab.dataset.tab === "audit" || tab.dataset.tab === "model") refreshAudit();
    });
  });

  $("connect").addEventListener("click", connect);
  $("refresh").addEventListener("click", refresh);
  $("audit-refresh").addEventListener("click", refreshAudit);
  $("account-select").addEventListener("change", (event) => connectDev(event.target.value));
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (event) => { if (event.target.id === "modal") closeModal(); });
  $("verify-form").addEventListener("submit", onVerify);
  $("model-form").addEventListener("submit", onAnalyze);
  $("batches").addEventListener("click", onBatchClick);
  $("incident-rows").addEventListener("click", onIncidentClick);

  fillAccounts();
  if (window.ethereum) {
    $("network").textContent = "MetaMask не підключено";
    const accounts = await window.ethereum.request({ method: "eth_accounts" }).catch(() => []);
    if (accounts.length) await connect();
  } else {
    $("banner").classList.remove("hidden");
    $("banner").textContent =
      "MetaMask не знайдено. Увімкнено локальний гаманець anvil: транзакції підписує сам вузол.";
    await connectDev(config.accounts[0].address);
  }
  timer = setInterval(() => { if (account) { refresh(); if ($("tab-audit").classList.contains("active")) refreshAudit(); } }, 5000);
}

function fillAccounts() {
  const select = $("account-select");
  select.innerHTML = "";
  for (const item of config.accounts) {
    const option = document.createElement("option");
    option.value = item.address;
    option.textContent = `${item.label} · ${short(item.address)}`;
    select.appendChild(option);
  }
}

async function connect() {
  try {
    provider = new ethers.BrowserProvider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    $("account-select").classList.add("hidden");
    $("connect").classList.add("hidden");
    const network = await provider.getNetwork();
    if (network.chainId !== BigInt(config.chainId)) {
      $("network").textContent = `мережа ${network.chainId} (очікується ${config.chainId})`;
      $("network").className = "badge badge-failed";
      return;
    }
    await setSigner(await provider.getSigner());
  } catch (error) {
    toast("error", decodeError(error));
  }
}

async function connectDev(address) {
  provider = new ethers.JsonRpcProvider(config.rpcUrl);
  const chosen = address || (await provider.send("eth_accounts", []))[0] || config.accounts[0].address;
  $("account-select").classList.remove("hidden");
  $("connect").classList.add("hidden");
  $("network").textContent = `локальна мережа ${config.chainId}`;
  $("network").className = "badge badge-success";
  await setSigner(await provider.getSigner(chosen));
}

async function setSigner(value) {
  signer = value;
  account = (await signer.getAddress()).toLowerCase();
  $("account").textContent = short(account);
  $("account").classList.remove("hidden");
  batchContract = batchContract.connect(signer);
  registryContract = registryContract.connect(signer);
  incidentContract = incidentContract.connect(signer);
  try {
    const info = await registryContract.participantOf(account);
    roleKind = Number(info.kind);
  } catch (_) {
    roleKind = 0;
  }
  const label = roleKind ? ROLES[roleKind] : (config.accounts.find((a) => a.address.toLowerCase() === account)?.label || "Без ролі");
  $("role").textContent = label;
  $("role").className = "badge " + (roleKind ? ROLE_BADGE[roleKind] : "badge-muted");
  $("role").classList.remove("hidden");
  const selected = $("account-select");
  const match = [...selected.options].find((option) => option.value.toLowerCase() === account);
  if (match) selected.value = match.value;
  await refresh();
}

async function refresh() {
  if (!account) return;
  try {
    const count = Number(await batchContract.batchCount());
    const page = count ? await batchContract.getBatches(0, Math.min(count, 60)) : [];
    batches = [];
    for (const item of page) {
      const detail = await batchContract.getBatch(item.id);
      batches.push({
        id: Number(item.id),
        serial: Number(item.serial),
        state: Number(item.state),
        quantity: item.quantity.toString(),
        parentId: Number(item.parentId),
        metadataHash: item.metadataHash,
        originCity: city(item.originCity),
        flagged: item.flagged,
        score: Number(item.anomalyScore),
        manufacturer: item.manufacturer,
        custodian: item.custodian,
        pending: detail.pendingRecipient,
        modelVersion: detail.modelVersion,
      });
    }
    const countIncidents = Number(await incidentContract.incidentCount());
    incidents = [];
    for (let i = countIncidents; i >= 1 && incidents.length < 50; i--) {
      const raw = await incidentContract.getIncident(i);
      incidents.push({
        id: i,
        batchId: Number(raw.batchId),
        kind: Number(raw.kind),
        severity: Number(raw.severity),
        status: Number(raw.status),
        score: Number(raw.scoreBps),
        modelVersion: raw.modelVersion,
      });
    }
    $("stat-batches").textContent = count;
    $("stat-flagged").textContent = batches.filter((b) => b.flagged).length;
    $("stat-incidents").textContent = countIncidents;
    $("stat-model").textContent = batches.find((b) => b.modelVersion !== ethers.ZeroHash)?.modelVersion?.slice(0, 10) || "v1";
    $("batches-note").textContent = `${batches.length} записів · оновлення кожні 5 с`;
    renderBatches();
  } catch (error) {
    toast("error", decodeError(error));
  }
}

function stateBadge(state) {
  return `<span class="badge ${STATE_BADGE[state]}">${STATES[state]}</span>`;
}

function renderBatches() {
  if (!batches.length) {
    $("batches").innerHTML = '<div class="empty">Партій ще немає. Виконайте seed-скрипт.</div>';
    return;
  }
  const me = account;
  $("batches").innerHTML = batches
    .slice()
    .reverse()
    .map((b) => {
      const isCustodian = b.custodian.toLowerCase() === me;
      const isManufacturer = b.manufacturer.toLowerCase() === me;
      const actions = [];
      if (isCustodian && (roleKind === 1 || roleKind === 2) && (b.state === 1 || b.state === 3)) {
        actions.push(`<button class="btn btn-sm" data-action="transfer" data-id="${b.id}">Передати</button>`);
        actions.push(`<button class="btn btn-sm" data-action="split" data-id="${b.id}">Поділити</button>`);
      }
      if (b.state === 2 && b.pending.toLowerCase() === me) {
        actions.push(`<button class="btn btn-sm btn-primary" data-action="accept" data-id="${b.id}">Прийняти</button>`);
        actions.push(`<button class="btn btn-sm" data-action="reject" data-id="${b.id}">Відхилити</button>`);
      }
      if (isCustodian && roleKind === 3 && b.state === 3) {
        actions.push(`<button class="btn btn-sm btn-primary" data-action="dispense" data-id="${b.id}">Відпустити</button>`);
      }
      if ((isManufacturer || roleKind === 4) && b.state >= 1 && b.state <= 4) {
        actions.push(`<button class="btn btn-sm" data-action="recall" data-id="${b.id}">Відкликати</button>`);
      }
      actions.push(`<button class="btn btn-sm btn-ghost" data-action="integrity" data-id="${b.id}">Цілісність</button>`);
      const flag = b.flagged
        ? `<span class="badge badge-failed">аномалія ${(b.score / 100).toFixed(0)} %</span>`
        : '<span class="badge badge-success">норма</span>';
      return `
        <article class="card">
          <div class="card-head">
            <div>
              <div class="card-title">Партія #${b.id} · серія ${b.serial}</div>
              <div class="muted small">${b.parentId ? `дочірня від #${b.parentId}` : "коренева партія"} · ${b.originCity}</div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${stateBadge(b.state)}${flag}</div>
          </div>
          <div class="card-grid">
            <div><label>Кількість</label>${b.quantity}</div>
            <div><label>Розпорядник</label><span class="kv">${short(b.custodian)}</span></div>
            <div><label>Виробник</label><span class="kv">${short(b.manufacturer)}</span></div>
            <div><label>Хеш документа</label><span class="kv">${short(b.metadataHash)}</span></div>
          </div>
          <div class="actions">${actions.join("")}</div>
        </article>`;
    })
    .join("");
}

async function sendTx(label, call) {
  try {
    const tx = await call();
    toast("success", `${label}: надіслано ${short(tx.hash)}`);
    await tx.wait();
    toast("success", `${label}: підтверджено`);
    await refresh();
  } catch (error) {
    toast("error", decodeError(error));
  }
}

async function onBatchClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const id = Number(button.dataset.id);
  const item = batches.find((b) => b.id === id);
  if (!item) return;
  const action = button.dataset.action;
  if (action === "transfer") {
    const fallback = roleKind === 1
      ? config.accounts.find((a) => a.role === "distributor")?.address
      : config.accounts.find((a) => a.role === "pharmacy")?.address;
    const to = prompt("Адреса отримувача", fallback || "");
    if (!to) return;
    const code = prompt("Код міста отримувача (2 літери)", "LV");
    if (!code) return;
    await sendTx("Передача відповідальності", () => batchContract.initiateCustody(id, to, bytes2(code)));
  } else if (action === "accept") {
    await sendTx("Прийняття партії", () => batchContract.acceptCustody(id));
  } else if (action === "reject") {
    await sendTx("Відхилення партії", () => batchContract.rejectCustody(id));
  } else if (action === "split") {
    const raw = prompt("Кількості дочірніх партій через кому", "200,300");
    if (!raw) return;
    const quantities = raw.split(",").map((value) => Number(value.trim())).filter((value) => value > 0);
    if (!quantities.length) return toast("error", "Вкажіть хоча б одну кількість");
    await sendTx("Поділ партії", () => batchContract.split(id, quantities));
  } else if (action === "dispense") {
    const commitment = ethers.keccak256(ethers.toUtf8Bytes("patient-" + Date.now()));
    await sendTx("Відпуск ліків", () => batchContract.dispense(id, commitment));
  } else if (action === "recall") {
    const reason = prompt("Причина відкликання", "Виявлено клон серійного номера");
    if (!reason) return;
    await sendTx("Відкликання партії", () => batchContract.recall(id, ethers.keccak256(ethers.toUtf8Bytes(reason))));
  } else if (action === "integrity") {
    try {
      const result = await (await apiGet(`/api/integrity/${id}`)).json();
      openModal(`Цілісність партії #${id}`, result);
    } catch (error) {
      toast("error", "Сервіс API недоступний");
    }
  }
}

async function onVerify(event) {
  event.preventDefault();
  try {
    const productHash = ethers.keccak256(ethers.toUtf8Bytes($("verify-product").value.trim()));
    const serial = Number($("verify-serial").value);
    const tokenId = Number(await batchContract.verifySerial(productHash, serial));
    const box = $("verify-result");
    box.classList.remove("hidden");
    if (!tokenId) {
      box.innerHTML = `<div class="result-row"><span class="badge badge-failed">не знайдено</span><b>Серійний номер ${serial} відсутній у ланцюгу</b></div>
        <p class="muted">Упаковка не зареєстрована виробником або номер підроблено.</p>`;
      return;
    }
    const item = batches.find((b) => b.id === tokenId) || { state: 0 };
    const detail = await batchContract.getBatch(tokenId);
    box.innerHTML = `
      <div class="result-row">
        <span class="badge badge-success">знайдено</span>
        <b>Партія #${tokenId}</b>
        ${stateBadge(Number(detail.state))}
        ${detail.flagged ? '<span class="badge badge-failed">позначена моделлю</span>' : ""}
      </div>
      <div class="card-grid">
        <div><label>Серія</label>${Number(detail.serial)}</div>
        <div><label>Розпорядник</label><span class="kv">${short(detail.custodian)}</span></div>
        <div><label>Кількість</label>${detail.quantity.toString()}</div>
        <div><label>Хеш документа</label><span class="kv">${short(detail.metadataHash)}</span></div>
      </div>`;
  } catch (error) {
    toast("error", decodeError(error));
  }
}

async function onAnalyze(event) {
  event.preventDefault();
  const lviv = $("f-scan-city").value === "Lviv";
  const distance = Number($("f-distance").value);
  const payload = {
    distance_km: distance,
    transit_hours: Number($("f-transit").value),
    quantity_sent: 500,
    quantity_received: 500,
    temperature_c: 20,
    cold_chain: 0,
    event_type: "scan",
    product_category: "antibiotic",
    license_status: $("f-license").value,
    license_age_days: 500,
    scans_24h: Number($("f-scans").value),
    same_serial_cities_24h: Number($("f-cities").value),
    batch_age_hours: 48,
    route_step: 2,
    route_length: 3,
    cumulative_distance_km: distance,
    to_lat: 50.4501,
    to_lon: 30.5234,
    scan_lat: lviv ? 49.8397 : 50.4501,
    scan_lon: lviv ? 24.0297 : 30.5234,
    timestamp: new Date().toISOString(),
  };
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error("API " + response.status);
    const result = await response.json();
    const max = Math.max(...result.top_factors.map((f) => Math.abs(f.contribution)), 1e-9);
    const factors = result.top_factors
      .map((factor) => {
        const width = (Math.abs(factor.contribution) / max) * 100;
        const label = factor.feature.replace("num__", "").replace("cat__", "");
        return `<div class="factor ${factor.contribution < 0 ? "neg" : ""}">
          <span>${esc(label)}</span>
          <span class="bar"><span style="width:${width.toFixed(1)}%"></span></span>
          <span class="mono">${factor.contribution.toFixed(3)}</span>
        </div>`;
      })
      .join("");
    $("model-result").classList.remove("hidden");
    $("model-result").innerHTML = `
      <div class="result-row">
        <span class="score">${(result.score * 100).toFixed(2)} %</span>
        <span class="badge ${result.is_anomaly ? "badge-failed" : "badge-success"}">${result.is_anomaly ? "аномалія" : "норма"}</span>
        <span class="muted">поріг ${(result.threshold * 100).toFixed(1)} %</span>
      </div>
      <div class="card-grid">
        <div><label>Версія моделі</label><span class="kv">${short(result.model_version)}</span></div>
        <div><label>Хеш ознак</label><span class="kv">${short(result.data_hash)}</span></div>
      </div>
      <h3 style="margin-top:14px">Чинники рішення</h3>
      <div class="factors">${factors}</div>
      <p class="muted small" style="margin-top:10px">Додатні внески підвищують оцінку аномальності, від'ємні — знижують.</p>`;
  } catch (error) {
    toast("error", "Не вдалося отримати рішення моделі: " + error.message);
  }
}

async function refreshAudit() {
  try {
    const [audit, incidentList] = await Promise.all([
      apiGet("/api/audit").then((r) => r.json()),
      apiGet("/api/incidents").then((r) => r.json()),
    ]);
    const decision = audit[0];
    const chainResult = $("chain-model-result");
    chainResult.classList.toggle("hidden", !decision);
    chainResult.innerHTML = decision
      ? `<h3>Останнє рішення в блокчейні</h3>
        <p>Партія #${Number(decision.tokenId)} · ${(decision.scoreBps / 100).toFixed(2)} % ·
        модель ${esc(short(decision.modelVersion))} · транзакція ${txLink(decision.txHash)}</p>`
      : "";
    $("audit-rows").innerHTML = audit.length
      ? audit.map((row) => `<tr>
          <td>#${row.tokenId}</td>
          <td><b>${(row.scoreBps / 100).toFixed(2)} %</b></td>
          <td>${row.anomalyType === 2 ? "клон" : row.anomalyType === 3 ? "фальсифікат" : "маршрут"}</td>
          <td class="mono">${short(row.modelVersion)}</td>
          <td class="mono">${txLink(row.txHash)}</td>
        </tr>`).join("")
      : '<tr><td colspan="5" class="muted">Рішень ще немає</td></tr>';
    $("incident-rows").innerHTML = incidentList.length
      ? incidentList.map((row) => {
          const actions = [];
          if (roleKind === 4 && row.status === 2) {
            actions.push(`<button class="btn btn-sm btn-primary" data-incident="confirm" data-id="${row.id}">Підтвердити</button>`);
            actions.push(`<button class="btn btn-sm" data-incident="dismiss" data-id="${row.id}">Відхилити</button>`);
          }
          if (roleKind === 4 && row.status === 3) {
            actions.push(`<button class="btn btn-sm" data-incident="resolve" data-id="${row.id}">Закрити</button>`);
          }
          return `<tr>
            <td>#${row.id}</td>
            <td>#${row.batchId}</td>
            <td>${KINDS[row.kind] || "—"}</td>
            <td>${SEVERITIES[row.severity] || "—"}</td>
            <td><span class="badge ${row.status === 3 ? "badge-failed" : row.status === 5 ? "badge-success" : "badge-warn"}">${INCIDENT_STATES[row.status]}</span></td>
            <td>${(row.scoreBps / 100).toFixed(2)} %</td>
            <td>${actions.join(" ")}</td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="7" class="muted">Інцидентів немає</td></tr>';
  } catch (error) {
    $("audit-rows").innerHTML = `<tr><td colspan="5" class="muted">API недоступний: ${esc(error.message)}</td></tr>`;
  }
}

async function onIncidentClick(event) {
  const button = event.target.closest("button[data-incident]");
  if (!button) return;
  const id = Number(button.dataset.id);
  const action = button.dataset.incident;
  if (action === "confirm") await sendTx("Підтвердження інциденту", () => incidentContract.confirmIncident(id));
  if (action === "dismiss") await sendTx("Відхилення інциденту", () => incidentContract.dismissIncident(id));
  if (action === "resolve") await sendTx("Закриття інциденту", () => incidentContract.resolveIncident(id));
  await refreshAudit();
}

window.addEventListener("DOMContentLoaded", init);
