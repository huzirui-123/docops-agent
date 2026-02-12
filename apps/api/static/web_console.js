"use strict";

// DocOps Web Console JS
(() => {
  const STORAGE_KEY_SETTINGS = "docops.web.console.settings.v1";
  const STORAGE_KEY_HISTORY = "docops.web.console.history.v1";
  const HISTORY_LIMIT = 10;

  const apiBaseEl = document.getElementById("api-base-url");
  const loadMetaBtn = document.getElementById("load-meta-btn");
  const metaLinkEl = document.getElementById("meta-link");
  const metaStatusEl = document.getElementById("meta-status");
  const metaWarningEl = document.getElementById("meta-warning");

  const skillSelectEl = document.getElementById("skill-select");
  const skillInputEl = document.getElementById("skill-input");
  const taskTypeSelectEl = document.getElementById("task-type-select");
  const presetSelectEl = document.getElementById("preset-select");
  const strictEl = document.getElementById("strict");
  const templateFileEl = document.getElementById("template-file");
  const taskJsonEl = document.getElementById("task-json");
  const policyYamlEl = document.getElementById("policy-yaml");
  const exportSuggestedEl = document.getElementById("export-suggested-policy");
  const importTaskFileEl = document.getElementById("import-task-file");
  const exportTaskBtn = document.getElementById("export-task-btn");

  const runBtn = document.getElementById("run-btn");
  const runStateEl = document.getElementById("run-state");

  const resultStatusEl = document.getElementById("result-status");
  const resultRequestIdEl = document.getElementById("result-request-id");
  const resultDurationEl = document.getElementById("result-duration");
  const resultExitCodeEl = document.getElementById("result-exit-code");
  const copyRequestIdBtn = document.getElementById("copy-request-id");
  const successAreaEl = document.getElementById("success-area");
  const errorAreaEl = document.getElementById("error-area");
  const downloadLinkEl = document.getElementById("download-link");
  const errorLinesEl = document.getElementById("error-lines");
  const errorJsonEl = document.getElementById("error-json");
  const copyCurlBtn = document.getElementById("copy-curl-btn");
  const reproduceCurlEl = document.getElementById("reproduce-curl");
  const historyListEl = document.getElementById("history-list");

  let downloadUrl = null;
  let persistTimer = null;
  let requestHistory = [];

  function normalizeBaseUrl(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return "";
    }
    return trimmed.replace(/\/+$/, "");
  }

  function effectiveBaseUrl() {
    return normalizeBaseUrl(apiBaseEl.value) || window.location.origin;
  }

  function apiUrl(path) {
    const base = normalizeBaseUrl(apiBaseEl.value);
    return base ? `${base}${path}` : path;
  }

  function updateMetaLink() {
    metaLinkEl.href = apiUrl("/v1/meta");
  }

  function setRunState(message, cls = "hint") {
    runStateEl.className = cls;
    runStateEl.textContent = message;
  }

  function setMetaStatus(message, warning = "") {
    metaStatusEl.textContent = message;
    metaWarningEl.textContent = warning;
  }

  function clearResultAreas() {
    successAreaEl.classList.add("hidden");
    errorAreaEl.classList.add("hidden");
    errorLinesEl.textContent = "";
    errorJsonEl.textContent = "";
    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
      downloadUrl = null;
    }
    downloadLinkEl.removeAttribute("href");
  }

  function setResultMeta({ status, requestId, durationMs, exitCode }) {
    resultStatusEl.textContent = String(status ?? "-");
    resultRequestIdEl.value = requestId || "";
    resultDurationEl.textContent = Number.isFinite(durationMs) ? String(durationMs) : "-";
    resultExitCodeEl.textContent = exitCode ?? "-";
  }

  function fillSelect(selectEl, values, fallbackValue) {
    const unique = Array.from(
      new Set((values || []).filter((value) => typeof value === "string" && value.trim() !== "")),
    );
    selectEl.innerHTML = "";
    if (unique.length === 0) {
      const option = document.createElement("option");
      option.value = fallbackValue;
      option.textContent = fallbackValue;
      selectEl.appendChild(option);
      return;
    }
    for (const value of unique) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      selectEl.appendChild(option);
    }
  }

  function parseTaskJson() {
    try {
      const parsed = JSON.parse(taskJsonEl.value);
      if (!parsed || typeof parsed !== "object") {
        return { ok: false, message: "task JSON must be an object." };
      }
      return { ok: true, value: parsed };
    } catch (error) {
      return { ok: false, message: `task JSON parse error: ${String(error)}` };
    }
  }

  function selectedSkill() {
    const manual = skillInputEl.value.trim();
    return manual || skillSelectEl.value.trim();
  }

  function validateTaskConsistency(taskObject) {
    const taskType = typeof taskObject.task_type === "string" ? taskObject.task_type : "";
    const skill = selectedSkill();
    const selectedTaskType = taskTypeSelectEl.value;

    if (!skill) {
      return { ok: false, message: "skill is required." };
    }
    if (!taskType) {
      return { ok: false, message: "task_type in task JSON is required." };
    }
    if (selectedTaskType && selectedTaskType !== taskType) {
      return {
        ok: false,
        message: `Selected task_type (${selectedTaskType}) must match task JSON task_type (${taskType}).`,
      };
    }
    if (skill !== taskType) {
      return {
        ok: false,
        message: `skill (${skill}) must match task JSON task_type (${taskType}).`,
      };
    }
    return { ok: true, skill, taskType };
  }

  function labeledErrorLines(payload) {
    if (!payload || typeof payload !== "object") {
      return ["error: non-JSON error response"];
    }

    const lines = [];
    const keys = ["error", "error_code", "code", "message", "exit_code", "failures"];
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        lines.push(`${key}: ${JSON.stringify(payload[key])}`);
      }
    }

    if (Object.prototype.hasOwnProperty.call(payload, "detail")) {
      const detail = payload.detail;
      lines.push(`detail: ${JSON.stringify(detail)}`);
      if (detail && typeof detail === "object" && detail.request_id) {
        lines.push(`detail.request_id: ${detail.request_id}`);
      }
    }

    if (lines.length === 0) {
      lines.push("error: response JSON does not include expected fields");
    }

    return lines;
  }

  function buildReproduceCurl() {
    const baseUrl = effectiveBaseUrl();
    const skill = selectedSkill() || "meeting_notice";
    const preset = presetSelectEl.value || "quick";
    const strict = strictEl.checked ? "true" : "false";
    const exportSuggested = exportSuggestedEl.checked ? "true" : "false";
    const policyHint =
      policyYamlEl.value.trim() !== ""
        ? "# Note: policy_yaml is set in UI. Add a matching -F policy_yaml='...' if needed.\n"
        : "";

    const taskBody = taskJsonEl.value.trim() || "{}";

    return [
      "# Save task payload",
      "cat > /tmp/task.json <<'JSON'",
      taskBody,
      "JSON",
      "",
      policyHint.trimEnd(),
      "curl -sS -X POST \"" + baseUrl + "/v1/run\" \\",
      "  -F \"template=@/path/to/template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document\" \\",
      "  -F \"task=@/tmp/task.json;type=application/json\" \\",
      "  -F \"skill=" + skill + "\" \\",
      "  -F \"preset=" + preset + "\" \\",
      "  -F \"strict=" + strict + "\" \\",
      "  -F \"export_suggested_policy=" + exportSuggested + "\" \\",
      "  -D headers.txt \\",
      "  -o docops_outputs.zip",
      "grep -i \"X-Docops-Request-Id\" headers.txt",
    ]
      .filter((line) => line !== "")
      .join("\n");
  }

  function renderReproduceCurl() {
    reproduceCurlEl.textContent = buildReproduceCurl();
  }

  function schedulePersist() {
    if (persistTimer !== null) {
      clearTimeout(persistTimer);
    }
    persistTimer = window.setTimeout(() => {
      persistTimer = null;
      persistSettings();
    }, 300);
  }

  function persistSettings() {
    const payload = {
      apiBaseUrl: apiBaseEl.value,
      skillInput: skillInputEl.value,
      preset: presetSelectEl.value,
      strict: strictEl.checked,
      exportSuggestedPolicy: exportSuggestedEl.checked,
      taskJson: taskJsonEl.value,
      policyYaml: policyYamlEl.value,
    };
    localStorage.setItem(STORAGE_KEY_SETTINGS, JSON.stringify(payload));
  }

  function restoreSettings() {
    const raw = localStorage.getItem(STORAGE_KEY_SETTINGS);
    if (!raw) {
      return;
    }
    try {
      const payload = JSON.parse(raw);
      if (payload && typeof payload === "object") {
        if (typeof payload.apiBaseUrl === "string") {
          apiBaseEl.value = payload.apiBaseUrl;
        }
        if (typeof payload.skillInput === "string") {
          skillInputEl.value = payload.skillInput;
        }
        if (typeof payload.preset === "string") {
          presetSelectEl.value = payload.preset;
        }
        if (typeof payload.strict === "boolean") {
          strictEl.checked = payload.strict;
        }
        if (typeof payload.exportSuggestedPolicy === "boolean") {
          exportSuggestedEl.checked = payload.exportSuggestedPolicy;
        }
        if (typeof payload.taskJson === "string") {
          taskJsonEl.value = payload.taskJson;
        }
        if (typeof payload.policyYaml === "string") {
          policyYamlEl.value = payload.policyYaml;
        }
      }
    } catch (error) {
      console.warn("Failed to restore web console settings", error);
    }
  }

  function loadHistory() {
    const raw = localStorage.getItem(STORAGE_KEY_HISTORY);
    if (!raw) {
      return [];
    }
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return [];
      }
      return parsed.filter((item) => item && typeof item === "object").slice(0, HISTORY_LIMIT);
    } catch (error) {
      console.warn("Failed to parse web console history", error);
      return [];
    }
  }

  function saveHistory() {
    localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(requestHistory.slice(0, HISTORY_LIMIT)));
  }

  function renderHistory() {
    historyListEl.innerHTML = "";
    if (requestHistory.length === 0) {
      const li = document.createElement("li");
      li.className = "hint";
      li.textContent = "No recent runs.";
      historyListEl.appendChild(li);
      return;
    }

    for (const item of requestHistory) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history-button";

      const requestId = item.request_id || "-";
      const stamp = item.timestamp || "unknown-time";
      const status = item.http_status ?? "-";
      const duration = item.duration_ms ?? "-";
      const baseUrl = item.base_url || "(same-origin)";

      button.textContent = `${stamp} | status=${status} | duration=${duration}ms | request_id=${requestId}`;
      button.title = `base_url=${baseUrl}`;
      button.addEventListener("click", () => {
        resultRequestIdEl.value = String(requestId);
        document.getElementById("result-metrics").scrollIntoView({ behavior: "smooth", block: "start" });
      });

      li.appendChild(button);
      historyListEl.appendChild(li);
    }
  }

  function pushHistory(entry) {
    requestHistory = [entry]
      .concat(
        requestHistory.filter((item) => {
          return !(
            item.request_id === entry.request_id &&
            item.http_status === entry.http_status &&
            item.timestamp === entry.timestamp
          );
        }),
      )
      .slice(0, HISTORY_LIMIT);
    saveHistory();
    renderHistory();
  }

  async function copyTextToClipboard(text) {
    await navigator.clipboard.writeText(text);
  }

  async function loadMeta() {
    updateMetaLink();
    const url = apiUrl("/v1/meta");
    setMetaStatus(`Loading meta from ${url} ...`);

    try {
      const response = await fetch(url, { method: "GET" });
      const requestId = response.headers.get("X-Docops-Request-Id") || "unknown";
      if (!response.ok) {
        const text = await response.text();
        setMetaStatus(
          `Meta unavailable (status=${response.status}, request_id=${requestId}).`,
          "Fallback to manual skill input.",
        );
        if (text) {
          console.warn("/v1/meta body:", text);
        }
        return;
      }

      const meta = await response.json();
      fillSelect(skillSelectEl, meta.supported_skills, "meeting_notice");
      fillSelect(taskTypeSelectEl, [""].concat(meta.supported_task_types || []), "");
      if (taskTypeSelectEl.options.length > 0) {
        taskTypeSelectEl.options[0].value = "";
        taskTypeSelectEl.options[0].textContent = "(from task JSON)";
      }
      fillSelect(presetSelectEl, meta.supported_presets, "quick");

      if (!skillInputEl.value.trim()) {
        skillInputEl.value = skillSelectEl.value;
      }

      setMetaStatus(`Meta loaded (request_id=${requestId}).`);
      renderReproduceCurl();
      schedulePersist();
    } catch (error) {
      const hint = normalizeBaseUrl(apiBaseEl.value)
        ? "Fallback to manual skill input. For cross-origin calls, both DOCOPS_WEB_CONNECT_SRC and DOCOPS_ENABLE_CORS=1 with DOCOPS_CORS_ALLOW_ORIGINS are required."
        : "Fallback to manual skill input. Check server availability.";
      setMetaStatus(`Meta request failed: ${String(error)}`, hint);
    }
  }

  async function handleTaskImport() {
    const file = importTaskFileEl.files && importTaskFileEl.files[0];
    if (!file) {
      return;
    }

    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      taskJsonEl.value = JSON.stringify(parsed, null, 2);
      setRunState("task.json imported.", "hint");
      renderReproduceCurl();
      schedulePersist();
    } catch (error) {
      setRunState(`task.json import failed: ${String(error)}`, "err");
    } finally {
      importTaskFileEl.value = "";
    }
  }

  function handleTaskExport() {
    const parsedTask = parseTaskJson();
    if (!parsedTask.ok) {
      setRunState(`Cannot export: ${parsedTask.message}`, "err");
      return;
    }

    const blob = new Blob([JSON.stringify(parsedTask.value, null, 2)], {
      type: "application/json",
    });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = "task.json";
    a.click();
    URL.revokeObjectURL(href);
    setRunState("task.json exported.", "hint");
  }

  async function runRequest() {
    clearResultAreas();
    setResultMeta({ status: "-", requestId: "", durationMs: NaN, exitCode: "-" });

    if (!templateFileEl.files || templateFileEl.files.length === 0) {
      setRunState("Please choose a template .docx file.", "err");
      return;
    }

    const parsedTask = parseTaskJson();
    if (!parsedTask.ok) {
      setRunState(parsedTask.message, "err");
      return;
    }

    const consistency = validateTaskConsistency(parsedTask.value);
    if (!consistency.ok) {
      setRunState(consistency.message, "err");
      return;
    }

    const form = new FormData();
    const templateFile = templateFileEl.files[0];
    form.append("template", templateFile, templateFile.name || "template.docx");
    form.append("task", new Blob([taskJsonEl.value], { type: "application/json" }), "task.json");
    form.append("skill", consistency.skill);
    form.append("preset", presetSelectEl.value);
    form.append("strict", strictEl.checked ? "true" : "false");
    form.append("export_suggested_policy", exportSuggestedEl.checked ? "true" : "false");

    const policyText = policyYamlEl.value.trim();
    if (policyText) {
      form.append("policy_yaml", policyText);
    }

    const url = apiUrl("/v1/run");
    const started = performance.now();
    setRunState(`Running request to ${url} ...`, "hint");

    try {
      const response = await fetch(url, { method: "POST", body: form });
      const durationMs = Math.round(performance.now() - started);
      const requestId = response.headers.get("X-Docops-Request-Id") || "";
      const exitCode = response.headers.get("X-Docops-Exit-Code") || "-";

      setResultMeta({
        status: response.status,
        requestId,
        durationMs,
        exitCode,
      });

      pushHistory({
        timestamp: new Date().toISOString(),
        http_status: response.status,
        request_id: requestId,
        duration_ms: durationMs,
        base_url: normalizeBaseUrl(apiBaseEl.value) || "",
      });

      const contentType = (response.headers.get("content-type") || "").toLowerCase();

      if (response.ok && !contentType.includes("application/json")) {
        const blob = await response.blob();
        downloadUrl = URL.createObjectURL(blob);
        downloadLinkEl.href = downloadUrl;
        successAreaEl.classList.remove("hidden");
        setRunState("Run finished successfully.", "ok");
        return;
      }

      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        const text = await response.text();
        payload = { message: text || String(error) };
      }

      if (response.ok) {
        successAreaEl.classList.remove("hidden");
        errorLinesEl.textContent = "Success response is JSON; see payload below.";
        errorJsonEl.textContent = JSON.stringify(payload, null, 2);
        errorAreaEl.classList.remove("hidden");
        setRunState("Run finished with JSON response.", "ok");
        return;
      }

      errorLinesEl.textContent = labeledErrorLines(payload).join("\n");
      errorJsonEl.textContent = JSON.stringify(payload, null, 2);
      errorAreaEl.classList.remove("hidden");
      setRunState("Run failed. See details below.", "err");
    } catch (error) {
      const durationMs = Math.round(performance.now() - started);
      setResultMeta({ status: "network", requestId: "", durationMs, exitCode: "-" });
      errorLinesEl.textContent = [
        `network_error: ${String(error)}`,
        "Cross-origin calls require BOTH:",
        "1) DOCOPS_WEB_CONNECT_SRC includes your API origin",
        "2) DOCOPS_ENABLE_CORS=1 and DOCOPS_CORS_ALLOW_ORIGINS includes your web origin",
      ].join("\n");
      errorJsonEl.textContent = "";
      errorAreaEl.classList.remove("hidden");
      setRunState("Run failed before receiving response.", "err");

      pushHistory({
        timestamp: new Date().toISOString(),
        http_status: "network",
        request_id: "",
        duration_ms: durationMs,
        base_url: normalizeBaseUrl(apiBaseEl.value) || "",
      });
    }
  }

  function bindPersistenceEvents() {
    const watched = [
      apiBaseEl,
      skillInputEl,
      presetSelectEl,
      strictEl,
      exportSuggestedEl,
      taskJsonEl,
      policyYamlEl,
      taskTypeSelectEl,
      skillSelectEl,
    ];

    for (const element of watched) {
      element.addEventListener("input", () => {
        updateMetaLink();
        renderReproduceCurl();
        schedulePersist();
      });
      element.addEventListener("change", () => {
        updateMetaLink();
        renderReproduceCurl();
        schedulePersist();
      });
    }
  }

  skillSelectEl.addEventListener("change", () => {
    if (!skillInputEl.value.trim() || skillInputEl.value.trim() === skillSelectEl.value) {
      skillInputEl.value = skillSelectEl.value;
      renderReproduceCurl();
      schedulePersist();
    }
  });

  importTaskFileEl.addEventListener("change", handleTaskImport);
  exportTaskBtn.addEventListener("click", handleTaskExport);

  apiBaseEl.addEventListener("input", updateMetaLink);
  loadMetaBtn.addEventListener("click", loadMeta);
  runBtn.addEventListener("click", runRequest);

  copyRequestIdBtn.addEventListener("click", async () => {
    const value = resultRequestIdEl.value.trim();
    if (!value) {
      return;
    }
    try {
      await copyTextToClipboard(value);
      setRunState("Request ID copied.", "hint");
    } catch (error) {
      resultRequestIdEl.select();
      setRunState(`Copy failed: ${String(error)}`, "err");
    }
  });

  copyCurlBtn.addEventListener("click", async () => {
    const snippet = reproduceCurlEl.textContent || "";
    if (!snippet.trim()) {
      return;
    }
    try {
      await copyTextToClipboard(snippet);
      setRunState("curl snippet copied.", "hint");
    } catch (error) {
      setRunState(`Copy failed: ${String(error)}`, "err");
    }
  });

  restoreSettings();
  requestHistory = loadHistory();
  renderHistory();
  bindPersistenceEvents();
  updateMetaLink();
  renderReproduceCurl();
  loadMeta();
})();
