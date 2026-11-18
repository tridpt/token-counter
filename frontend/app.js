"use strict";

const API = "/api";

const scanBtn = document.getElementById("scanBtn");
const statusEl = document.getElementById("status");
const scanSummary = document.getElementById("scanSummary");
const sourceList = document.getElementById("sourceList");
const recordRows = document.getElementById("recordRows");
const emptyRecords = document.getElementById("emptyRecords");

const totalTokens = document.getElementById("totalTokens");
const inputTokens = document.getElementById("inputTokens");
const outputTokens = document.getElementById("outputTokens");
const creditsUsed = document.getElementById("creditsUsed");

const modelSelect = document.getElementById("modelSelect");
const inputText = document.getElementById("inputText");
const outputText = document.getElementById("outputText");
const countBtn = document.getElementById("countBtn");
const clearBtn = document.getElementById("clearBtn");
const manualInputTokens = document.getElementById("manualInputTokens");
const manualOutputTokens = document.getElementById("manualOutputTokens");
const manualTotalTokens = document.getElementById("manualTotalTokens");
const inputChars = document.getElementById("inputChars");
const outputChars = document.getElementById("outputChars");
const encodingName = document.getElementById("encodingName");

const usageJson = document.getElementById("usageJson");
const parseUsageBtn = document.getElementById("parseUsageBtn");
const actualInput = document.getElementById("actualInput");
const actualOutput = document.getElementById("actualOutput");
const actualTotal = document.getElementById("actualTotal");
const usageError = document.getElementById("usageError");

let debounceTimer = 0;

function setStatus(text, kind = "neutral") {
  statusEl.textContent = text;
  statusEl.dataset.kind = kind;
}

function formatNumber(value, digits = 0) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
  }).format(number);
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

async function scanUsage() {
  try {
    setStatus("Scanning");
    scanBtn.disabled = true;
    const data = await api("/usage/scan");
    renderScan(data);
    setStatus("Ready", "ok");
  } catch (err) {
    setStatus("Error", "error");
    scanSummary.textContent = err.message;
  } finally {
    scanBtn.disabled = false;
  }
}

function renderScan(data) {
  const totals = data.totals || {};
  totalTokens.textContent = formatNumber(totals.total_tokens);
  inputTokens.textContent = formatNumber(totals.input_tokens);
  outputTokens.textContent = formatNumber(totals.output_tokens);
  creditsUsed.textContent = formatNumber(totals.credits, 4);
  scanSummary.textContent = `${formatNumber(totals.records)} records from ${formatNumber(totals.files_scanned)} files.`;

  sourceList.innerHTML = "";
  for (const source of data.sources || []) {
    const el = document.createElement("article");
    el.className = "source-card";
    el.innerHTML = `
      <div>
        <div class="source-title">
          <strong>${escapeHtml(source.name)}</strong>
          <span class="badge ${escapeHtml(source.status)}">${escapeHtml(source.status)}</span>
        </div>
        <p>${escapeHtml(source.note || "")}</p>
        <small>${escapeHtml((source.paths || []).join(" | ") || "Path not found")}</small>
      </div>
      <div class="source-stats">
        <span>${formatNumber(source.files_scanned)} files</span>
        <span>${formatNumber(source.records)} records</span>
      </div>
    `;
    sourceList.appendChild(el);
  }

  recordRows.innerHTML = "";
  const records = data.records || [];
  emptyRecords.classList.toggle("hidden", records.length > 0);
  for (const record of records.slice(0, 250)) {
    const tr = document.createElement("tr");
    tr.title = record.path || "";
    tr.innerHTML = `
      <td>${escapeHtml(formatTime(record.timestamp))}</td>
      <td>${escapeHtml(record.source || "-")}</td>
      <td>${escapeHtml(record.model || "-")}</td>
      <td>${formatNumber(record.input_tokens)}</td>
      <td>${formatNumber(record.output_tokens)}</td>
      <td>${formatNumber(record.total_tokens)}</td>
      <td>${record.credits ? formatNumber(record.credits, 4) : "-"}</td>
      <td>${record.context_percent === null || record.context_percent === undefined ? "-" : `${formatNumber(record.context_percent, 2)}%`}</td>
    `;
    recordRows.appendChild(tr);
  }
}

async function loadModels() {
  const data = await api("/models");
  modelSelect.innerHTML = "";

  for (const item of data.models || []) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.label} (${item.encoding})`;
    modelSelect.appendChild(option);
  }

  modelSelect.value = "gpt-4o-mini";
}

async function countTokens() {
  inputChars.textContent = formatNumber(inputText.value.length);
  outputChars.textContent = formatNumber(outputText.value.length);

  try {
    const data = await api("/count", {
      method: "POST",
      body: JSON.stringify({
        model: modelSelect.value,
        input_text: inputText.value,
        output_text: outputText.value,
      }),
    });

    manualInputTokens.textContent = formatNumber(data.input_tokens);
    manualOutputTokens.textContent = formatNumber(data.output_tokens);
    manualTotalTokens.textContent = formatNumber(data.total_tokens);
    encodingName.textContent = data.encoding || "-";
  } catch (err) {
    encodingName.textContent = err.message;
  }
}

function scheduleCount() {
  inputChars.textContent = formatNumber(inputText.value.length);
  outputChars.textContent = formatNumber(outputText.value.length);
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(countTokens, 220);
}

function clearManual() {
  inputText.value = "";
  outputText.value = "";
  scheduleCount();
}

function looksLikeUsage(value) {
  const keys = Object.keys(value || {});
  return keys.some((key) =>
    [
      "usage",
      "usageMetadata",
      "input_tokens",
      "output_tokens",
      "prompt_tokens",
      "completion_tokens",
      "total_tokens",
      "inputTokenCount",
      "outputTokenCount",
      "promptTokenCount",
      "candidatesTokenCount",
      "totalTokenCount",
    ].includes(key)
  );
}

function findUsage(value) {
  if (!value || typeof value !== "object") return null;
  if (value.usage && looksLikeUsage(value.usage)) return value.usage;
  if (value.usageMetadata && looksLikeUsage(value.usageMetadata)) return value.usageMetadata;
  if (looksLikeUsage(value)) return value;

  for (const child of Object.values(value)) {
    if (child && typeof child === "object") {
      const found = findUsage(child);
      if (found) return found;
    }
  }
  return null;
}

function pickNumber(obj, keys) {
  for (const key of keys) {
    if (Number.isFinite(Number(obj[key]))) return Number(obj[key]);
  }
  return null;
}

function parseUsageJson() {
  usageError.classList.add("hidden");

  try {
    const raw = usageJson.value.trim();
    if (!raw) throw new Error("JSON is empty");

    const parsed = JSON.parse(raw);
    const usage = findUsage(parsed);
    if (!usage) throw new Error("No usage object found");

    const input = pickNumber(usage, ["input_tokens", "prompt_tokens", "inputTokenCount", "promptTokenCount"]);
    const output = pickNumber(usage, [
      "output_tokens",
      "completion_tokens",
      "outputTokenCount",
      "candidatesTokenCount",
      "completionTokenCount",
    ]);
    const total =
      pickNumber(usage, ["total_tokens", "totalTokenCount", "totalTokens"]) ??
      ((input ?? 0) + (output ?? 0));

    actualInput.textContent = input === null ? "-" : formatNumber(input);
    actualOutput.textContent = output === null ? "-" : formatNumber(output);
    actualTotal.textContent = formatNumber(total);
  } catch (err) {
    actualInput.textContent = "-";
    actualOutput.textContent = "-";
    actualTotal.textContent = "-";
    usageError.textContent = err.message;
    usageError.classList.remove("hidden");
  }
}

scanBtn.addEventListener("click", scanUsage);
countBtn.addEventListener("click", countTokens);
clearBtn.addEventListener("click", clearManual);
parseUsageBtn.addEventListener("click", parseUsageJson);
modelSelect.addEventListener("change", countTokens);
inputText.addEventListener("input", scheduleCount);
outputText.addEventListener("input", scheduleCount);
usageJson.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(parseUsageJson, 220);
});

loadModels()
  .then(() => Promise.all([countTokens(), scanUsage()]))
  .catch((err) => {
    setStatus("Error", "error");
    scanSummary.textContent = err.message;
  });
