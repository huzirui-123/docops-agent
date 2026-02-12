"use strict";

// DocOps Web Console JS
(() => {
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

  let downloadUrl = null;

  function normalizeBaseUrl(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return "";
    }
    return trimmed.replace(/\/+$/, "");
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
      new Set((values || []).filter((v) => typeof v === "string" && v.trim() !== "")),
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
    } catch (error) {
      const hint = normalizeBaseUrl(apiBaseEl.value)
        ? "Check CORS/network/API Base URL settings."
        : "Check server availability.";
      setMetaStatus(
        `Meta request failed: ${String(error)}`,
        `Fallback to manual skill input. ${hint}`,
      );
    }
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
      const corsHint = normalizeBaseUrl(apiBaseEl.value)
        ? "Possible CORS block or network issue with API Base URL."
        : "Possible server/network issue.";
      errorLinesEl.textContent = `network_error: ${String(error)}\n${corsHint}`;
      errorJsonEl.textContent = "";
      errorAreaEl.classList.remove("hidden");
      setRunState("Run failed before receiving response.", "err");
    }
  }

  skillSelectEl.addEventListener("change", () => {
    if (!skillInputEl.value.trim() || skillInputEl.value.trim() === skillSelectEl.value) {
      skillInputEl.value = skillSelectEl.value;
    }
  });

  apiBaseEl.addEventListener("input", updateMetaLink);
  loadMetaBtn.addEventListener("click", loadMeta);
  runBtn.addEventListener("click", runRequest);

  copyRequestIdBtn.addEventListener("click", async () => {
    const value = resultRequestIdEl.value.trim();
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setRunState("Request ID copied.", "hint");
    } catch (error) {
      resultRequestIdEl.select();
      setRunState(`Copy failed: ${String(error)}`, "err");
    }
  });

  updateMetaLink();
  loadMeta();
})();
