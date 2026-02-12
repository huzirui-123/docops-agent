import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  apiUrl,
  defaultApiBaseUrl,
  loadMeta,
  normalizeApiBaseUrl,
  runDocOps,
  type ApiResult,
} from "./api";
import {
  loadHistory,
  loadSettings,
  saveHistory,
  saveSettings,
  type ConsoleSettings,
  type HistoryEntry,
} from "./storage";

type MetaState = {
  status: "idle" | "loading" | "ok" | "error";
  skills: string[];
  presets: string[];
  taskTypes: string[];
  message: string;
  warning: string;
};

type ResultState = {
  status: string;
  requestId: string;
  durationMs: number | null;
  exitCode: string;
  downloadUrl: string;
  errorLines: string[];
  errorJson: string;
};

const HISTORY_LIMIT = 10;
const DEFAULT_TASK_JSON = JSON.stringify(
  {
    task_type: "meeting_notice",
    payload: {
      meeting_title: "Weekly Meeting",
    },
  },
  null,
  2,
);

const DEFAULT_SETTINGS: ConsoleSettings = {
  apiBaseUrl: defaultApiBaseUrl(),
  skill: "meeting_notice",
  preset: "quick",
  strict: false,
  exportSuggestedPolicy: false,
  taskJson: DEFAULT_TASK_JSON,
  policyYaml: "",
};

const DEFAULT_RESULT: ResultState = {
  status: "-",
  requestId: "",
  durationMs: null,
  exitCode: "-",
  downloadUrl: "",
  errorLines: [],
  errorJson: "",
};

function labelErrorPayload(payload: unknown): string[] {
  if (!payload || typeof payload !== "object") {
    return ["error: non-JSON error response"];
  }

  const dict = payload as Record<string, unknown>;
  const lines: string[] = [];
  for (const key of ["error_code", "error", "code", "message", "exit_code", "failures"]) {
    if (key in dict) {
      lines.push(`${key}: ${JSON.stringify(dict[key])}`);
    }
  }
  if ("detail" in dict) {
    lines.push(`detail: ${JSON.stringify(dict.detail)}`);
    if (dict.detail && typeof dict.detail === "object") {
      const detail = dict.detail as Record<string, unknown>;
      if (typeof detail.request_id === "string") {
        lines.push(`detail.request_id: ${detail.request_id}`);
      }
    }
  }
  if (lines.length === 0) {
    lines.push("error: response JSON has no known fields");
  }
  return lines;
}

function safeParseTask(taskJson: string): { ok: true; value: Record<string, unknown> } | { ok: false; message: string } {
  try {
    const parsed = JSON.parse(taskJson);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "task JSON must be an object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (error) {
    return { ok: false, message: `task JSON parse error: ${String(error)}` };
  }
}

function buildReproduceCurl(settings: ConsoleSettings, baseUrl: string): string {
  const policyHint = settings.policyYaml.trim()
    ? "# Add -F policy_yaml='...' if needed"
    : "# policy_yaml omitted";

  const taskBody = settings.taskJson.trim() || "{}";

  return [
    "cat > /tmp/task.json <<'JSON'",
    taskBody,
    "JSON",
    "",
    policyHint,
    `curl -sS -X POST \"${baseUrl}/v1/run\" \\\`,
    "  -F \"template=@/path/to/template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document\" \\\",
    "  -F \"task=@/tmp/task.json;type=application/json\" \\\",
    `  -F \"skill=${settings.skill}\" \\\",
    `  -F \"preset=${settings.preset}\" \\\",
    `  -F \"strict=${settings.strict ? "true" : "false"}\" \\\",
    `  -F \"export_suggested_policy=${settings.exportSuggestedPolicy ? "true" : "false"}\" \\\",
    "  -D headers.txt \\\",
    "  -o docops_outputs.zip",
    "grep -i \"X-Docops-Request-Id\" headers.txt",
  ].join("\n");
}

export default function App() {
  const [settings, setSettings] = useState<ConsoleSettings>(() => loadSettings(DEFAULT_SETTINGS));
  const [taskTypeSelect, setTaskTypeSelect] = useState<string>("");
  const [meta, setMeta] = useState<MetaState>({
    status: "idle",
    skills: ["meeting_notice"],
    presets: ["quick", "template", "strict"],
    taskTypes: ["meeting_notice"],
    message: "Meta not loaded.",
    warning: "",
  });
  const [runState, setRunState] = useState<string>("Idle");
  const [result, setResult] = useState<ResultState>(DEFAULT_RESULT);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const persistTimer = useRef<number | null>(null);

  const normalizedBaseUrl = useMemo(() => normalizeApiBaseUrl(settings.apiBaseUrl), [settings.apiBaseUrl]);
  const effectiveBaseUrl = normalizedBaseUrl || window.location.origin;
  const reproduceCurl = useMemo(
    () => buildReproduceCurl(settings, effectiveBaseUrl),
    [settings, effectiveBaseUrl],
  );

  useEffect(() => {
    if (persistTimer.current !== null) {
      window.clearTimeout(persistTimer.current);
    }
    persistTimer.current = window.setTimeout(() => {
      saveSettings(settings);
      persistTimer.current = null;
    }, 300);

    return () => {
      if (persistTimer.current !== null) {
        window.clearTimeout(persistTimer.current);
        persistTimer.current = null;
      }
    };
  }, [settings]);

  useEffect(() => {
    saveHistory(history);
  }, [history]);

  useEffect(() => {
    return () => {
      if (result.downloadUrl) {
        URL.revokeObjectURL(result.downloadUrl);
      }
    };
  }, [result.downloadUrl]);

  const loadMetaClick = async () => {
    setMeta((prev) => ({ ...prev, status: "loading", message: "Loading /v1/meta ...", warning: "" }));
    try {
      const response = await loadMeta(settings.apiBaseUrl);
      if (response.status !== 200 || !response.payload || typeof response.payload !== "object") {
        setMeta((prev) => ({
          ...prev,
          status: "error",
          message: `Meta unavailable (status=${response.status}, request_id=${response.requestId || "n/a"})`,
          warning:
            "Manual skill input is available. For cross-origin calls, prefer same-origin/proxy first; if split deployment is required, configure both DOCOPS_WEB_CONNECT_SRC and CORS (DOCOPS_ENABLE_CORS=1 + DOCOPS_CORS_ALLOW_ORIGINS).",
        }));
        return;
      }

      const payload = response.payload as Record<string, unknown>;
      const skills = Array.isArray(payload.supported_skills)
        ? payload.supported_skills.filter((x): x is string => typeof x === "string")
        : [];
      const presets = Array.isArray(payload.supported_presets)
        ? payload.supported_presets.filter((x): x is string => typeof x === "string")
        : [];
      const taskTypes = Array.isArray(payload.supported_task_types)
        ? payload.supported_task_types.filter((x): x is string => typeof x === "string")
        : [];

      setMeta({
        status: "ok",
        skills: skills.length ? skills : ["meeting_notice"],
        presets: presets.length ? presets : ["quick", "template", "strict"],
        taskTypes: taskTypes.length ? taskTypes : ["meeting_notice"],
        message: `Meta loaded (request_id=${response.requestId || "n/a"}).`,
        warning: "",
      });

      setSettings((prev) => ({
        ...prev,
        skill: skills.includes(prev.skill) ? prev.skill : (skills[0] ?? prev.skill),
        preset: presets.includes(prev.preset) ? prev.preset : (presets[0] ?? prev.preset),
      }));
    } catch (error) {
      setMeta((prev) => ({
        ...prev,
        status: "error",
        message: `Meta request failed: ${String(error)}`,
        warning:
          "Manual skill input is available. For cross-origin calls, configure DOCOPS_WEB_CONNECT_SRC and CORS together.",
      }));
    }
  };

  const updateSetting = <K extends keyof ConsoleSettings>(key: K, value: ConsoleSettings[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const importTaskJson = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    try {
      const content = await file.text();
      const parsed = JSON.parse(content);
      updateSetting("taskJson", JSON.stringify(parsed, null, 2));
      setRunState("task.json imported");
    } catch (error) {
      setRunState(`task.json import failed: ${String(error)}`);
    } finally {
      event.target.value = "";
    }
  };

  const exportTaskJson = () => {
    const parsed = safeParseTask(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`Cannot export: ${parsed.message}`);
      return;
    }
    const blob = new Blob([JSON.stringify(parsed.value, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "task.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyRequestId = async () => {
    if (!result.requestId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.requestId);
      setRunState("Request ID copied");
    } catch (error) {
      setRunState(`Copy failed: ${String(error)}`);
    }
  };

  const copyCurl = async () => {
    try {
      await navigator.clipboard.writeText(reproduceCurl);
      setRunState("curl snippet copied");
    } catch (error) {
      setRunState(`Copy failed: ${String(error)}`);
    }
  };

  const appendHistory = (entry: HistoryEntry) => {
    setHistory((prev) => {
      const deduped = prev.filter(
        (item) =>
          !(
            item.timestamp === entry.timestamp &&
            item.requestId === entry.requestId &&
            item.httpStatus === entry.httpStatus
          ),
      );
      return [entry, ...deduped].slice(0, HISTORY_LIMIT);
    });
  };

  const resetResult = () => {
    if (result.downloadUrl) {
      URL.revokeObjectURL(result.downloadUrl);
    }
    setResult(DEFAULT_RESULT);
  };

  const runClick = async () => {
    resetResult();
    const templateFile = (document.getElementById("template-file") as HTMLInputElement).files?.[0];
    if (!templateFile) {
      setRunState("Please choose a template .docx file");
      return;
    }

    const parsedTask = safeParseTask(settings.taskJson);
    if (!parsedTask.ok) {
      setRunState(parsedTask.message);
      return;
    }

    const taskType = typeof parsedTask.value.task_type === "string" ? parsedTask.value.task_type : "";
    if (!taskType) {
      setRunState("task_type in task JSON is required");
      return;
    }
    if (settings.skill.trim() !== taskType) {
      setRunState(`skill (${settings.skill}) must match task_type (${taskType})`);
      return;
    }
    if (taskTypeSelect && taskTypeSelect !== taskType) {
      setRunState(`Selected task type (${taskTypeSelect}) must match task JSON (${taskType})`);
      return;
    }

    setRunState("Running ...");
    const started = performance.now();

    try {
      const apiResult: ApiResult = await runDocOps({
        baseUrl: settings.apiBaseUrl,
        templateFile,
        taskJson: settings.taskJson,
        skill: settings.skill,
        preset: settings.preset,
        strict: settings.strict,
        exportSuggestedPolicy: settings.exportSuggestedPolicy,
        policyYaml: settings.policyYaml,
      });
      const durationMs = Math.round(performance.now() - started);

      const nextResult: ResultState = {
        status: String(apiResult.status),
        requestId: apiResult.requestId,
        durationMs,
        exitCode: apiResult.exitCode || "-",
        downloadUrl: "",
        errorLines: [],
        errorJson: "",
      };

      if (apiResult.blob) {
        nextResult.downloadUrl = URL.createObjectURL(apiResult.blob);
        setRunState("Run completed successfully");
      } else {
        nextResult.errorLines = labelErrorPayload(apiResult.payload);
        nextResult.errorJson = apiResult.payload
          ? JSON.stringify(apiResult.payload, null, 2)
          : "(empty response body)";
        setRunState(apiResult.status >= 400 ? "Run failed" : "Run completed with JSON payload");
      }

      setResult(nextResult);
      appendHistory({
        timestamp: new Date().toISOString(),
        httpStatus: apiResult.status,
        requestId: apiResult.requestId,
        durationMs,
        baseUrl: settings.apiBaseUrl,
      });
    } catch (error) {
      const durationMs = Math.round(performance.now() - started);
      setResult({
        status: "network",
        requestId: "",
        durationMs,
        exitCode: "-",
        downloadUrl: "",
        errorLines: [
          `network_error: ${String(error)}`,
          "Prefer same-origin/proxy in dev.",
          "For split deployment, configure both DOCOPS_WEB_CONNECT_SRC and CORS (DOCOPS_ENABLE_CORS=1 + DOCOPS_CORS_ALLOW_ORIGINS).",
        ],
        errorJson: "",
      });
      setRunState("Request failed before receiving response");
      appendHistory({
        timestamp: new Date().toISOString(),
        httpStatus: "network",
        requestId: "",
        durationMs,
        baseUrl: settings.apiBaseUrl,
      });
    }
  };

  return (
    <main className="min-h-screen bg-slate-100 py-8">
      <div className="mx-auto max-w-6xl px-4">
        <header className="mb-6 rounded-xl bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">DocOps Web Console</h1>
          <p className="mt-2 text-sm text-slate-600">
            Debug/demo UI for <code>/v1/run</code>. Use same-origin or proxy by default.
          </p>
        </header>

        <section className="mb-4 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">A. Server Info</h2>
          <div className="grid gap-4 md:grid-cols-[1fr_auto]">
            <label className="text-sm text-slate-700">
              API Base URL (empty = same-origin)
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                type="text"
                value={settings.apiBaseUrl}
                onChange={(event) => updateSetting("apiBaseUrl", event.target.value)}
                placeholder="http://127.0.0.1:8000"
              />
            </label>
            <div className="flex items-end gap-2">
              <button className="btn" onClick={loadMetaClick} type="button">
                Load Meta
              </button>
              <a className="link" href={apiUrl(settings.apiBaseUrl, "/v1/meta")} target="_blank" rel="noreferrer">
                Open /v1/meta
              </a>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">{meta.message}</p>
          {meta.warning && <p className="mt-1 text-sm text-amber-700">{meta.warning}</p>}
        </section>

        <section className="mb-4 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">B. Inputs</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-700">
              Skill
              <div className="mt-1 flex gap-2">
                <select
                  className="flex-1 rounded-md border border-slate-300 px-3 py-2"
                  value={meta.skills.includes(settings.skill) ? settings.skill : ""}
                  onChange={(event) => updateSetting("skill", event.target.value)}
                >
                  {!meta.skills.includes(settings.skill) && <option value="">(manual value)</option>}
                  {meta.skills.map((skill) => (
                    <option key={skill} value={skill}>
                      {skill}
                    </option>
                  ))}
                </select>
                <input
                  className="w-48 rounded-md border border-slate-300 px-3 py-2"
                  type="text"
                  value={settings.skill}
                  onChange={(event) => updateSetting("skill", event.target.value)}
                />
              </div>
            </label>

            <label className="text-sm text-slate-700">
              Task Type (optional selector)
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={taskTypeSelect}
                onChange={(event) => setTaskTypeSelect(event.target.value)}
              >
                <option value="">(from task JSON)</option>
                {meta.taskTypes.map((taskType) => (
                  <option key={taskType} value={taskType}>
                    {taskType}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm text-slate-700">
              Preset
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={settings.preset}
                onChange={(event) => updateSetting("preset", event.target.value)}
              >
                {meta.presets.map((preset) => (
                  <option key={preset} value={preset}>
                    {preset}
                  </option>
                ))}
              </select>
            </label>

            <label className="mt-6 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={settings.strict}
                onChange={(event) => updateSetting("strict", event.target.checked)}
              />
              Strict mode
            </label>

            <label className="text-sm text-slate-700">
              Template (.docx)
              <input
                id="template-file"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                type="file"
                accept=".docx"
              />
            </label>

            <label className="mt-6 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={settings.exportSuggestedPolicy}
                onChange={(event) => updateSetting("exportSuggestedPolicy", event.target.checked)}
              />
              Export suggested policy
            </label>
          </div>

          <label className="mt-4 block text-sm text-slate-700">
            Task JSON
            <textarea
              className="mt-1 h-52 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
              value={settings.taskJson}
              onChange={(event) => updateSetting("taskJson", event.target.value)}
            />
          </label>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="btn cursor-pointer">
              Import task.json
              <input type="file" accept=".json,application/json" className="hidden" onChange={importTaskJson} />
            </label>
            <button type="button" className="btn" onClick={exportTaskJson}>
              Export task.json
            </button>
            <span className="text-xs text-slate-500">Template file is not persisted by browser storage.</span>
          </div>

          <label className="mt-4 block text-sm text-slate-700">
            policy_yaml (optional)
            <textarea
              className="mt-1 h-28 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
              value={settings.policyYaml}
              onChange={(event) => updateSetting("policyYaml", event.target.value)}
            />
          </label>
        </section>

        <section className="mb-4 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">C. Run</h2>
          <div className="flex items-center gap-3">
            <button className="btn-primary" onClick={runClick} type="button">
              Run
            </button>
            <span className="text-sm text-slate-600">{runState}</span>
          </div>
        </section>

        <section id="result-block" className="mb-4 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">D. Result</h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="label">HTTP status</p>
              <p className="value">{result.status}</p>
            </div>
            <div>
              <p className="label">Request ID</p>
              <div className="flex items-center gap-2">
                <input className="input-lite" readOnly value={result.requestId} />
                <button className="btn" onClick={copyRequestId} type="button">
                  Copy
                </button>
              </div>
            </div>
            <div>
              <p className="label">Duration (ms)</p>
              <p className="value">{result.durationMs ?? "-"}</p>
            </div>
            <div>
              <p className="label">Exit Code</p>
              <p className="value">{result.exitCode}</p>
            </div>
          </div>

          {result.downloadUrl && (
            <div className="mt-4 rounded-md bg-emerald-50 p-3 text-emerald-700">
              <p className="font-medium">ZIP response received.</p>
              <a className="link" href={result.downloadUrl} download="docops_outputs.zip">
                Download ZIP
              </a>
            </div>
          )}

          {result.errorLines.length > 0 && (
            <div className="mt-4 rounded-md bg-rose-50 p-3 text-rose-800">
              <p className="font-medium">Response details</p>
              <pre className="pre">{result.errorLines.join("\n")}</pre>
              <pre className="pre">{result.errorJson}</pre>
            </div>
          )}

          <div className="mt-4">
            <h3 className="text-base font-semibold text-slate-900">Reproduce (curl)</h3>
            <div className="mt-2 flex items-center gap-2">
              <button className="btn" onClick={copyCurl} type="button">
                Copy curl
              </button>
            </div>
            <pre className="pre mt-2">{reproduceCurl}</pre>
          </div>
        </section>

        <section className="rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">E. Recent History</h2>
          {history.length === 0 ? (
            <p className="text-sm text-slate-600">No recent runs.</p>
          ) : (
            <ul className="space-y-2">
              {history.map((entry, idx) => (
                <li key={`${entry.timestamp}-${idx}`}>
                  <button
                    type="button"
                    className="history-row"
                    onClick={() => {
                      setResult((prev) => ({ ...prev, requestId: entry.requestId }));
                      document.getElementById("result-block")?.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    <span>{entry.timestamp}</span>
                    <span>status={entry.httpStatus}</span>
                    <span>duration={entry.durationMs}ms</span>
                    <span>request_id={entry.requestId || "-"}</span>
                    <span>base={entry.baseUrl || "(same-origin)"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
