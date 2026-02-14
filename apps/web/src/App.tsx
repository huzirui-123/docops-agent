import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  apiUrl,
  defaultApiBaseUrl,
  loadMeta,
  normalizeApiBaseUrl,
  precheckDocOps,
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

type ApiHealthState = "checking" | "ok" | "down";
type ResultTone = "neutral" | "success" | "warning" | "error";

const HISTORY_LIMIT = 10;

const DEFAULT_TASK_JSON = JSON.stringify(
  {
    task_type: "meeting_notice",
    payload: {
      meeting_title: "XX 项目安全例会（演示）",
      meeting_date: "2026-02-20",
      meeting_time: "14:00-15:30",
      meeting_location: "会议室 B（2F）",
      organizer: "工程管理部",
      attendees: ["张三", "李四", "王五", "赵六"],
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

const EXAMPLE_TASKS: Record<string, Record<string, unknown>> = {
  meeting_notice: {
    task_type: "meeting_notice",
    payload: {
      meeting_title: "XX 项目安全例会（演示）",
      meeting_date: "2026-02-20",
      meeting_time: "14:00-15:30",
      meeting_location: "会议室 B（2F）",
      organizer: "工程管理部",
      attendees: ["张三", "李四", "王五", "赵六"],
    },
  },
  training_notice: {
    task_type: "training_notice",
    payload: {
      training_title: "消防安全培训通知",
      training_date: "2026-02-21",
      training_time: "09:30-11:00",
      training_location: "一楼报告厅",
      trainer: "王老师",
      organizer: "人事部",
      attendees: ["生产部", "工程部", "行政部"],
    },
  },
  inspection_record: {
    task_type: "inspection_record",
    payload: {
      inspection_subject: "消防通道巡检记录",
      inspection_date: "2026-02-22",
      inspector: "张三",
      department: "工程管理部",
      issue_summary: "2号楼通道堆放杂物，存在阻塞风险",
      action_required: "当日18:00前完成清理并拍照回传",
      deadline: "2026-02-22 18:00",
    },
  },
};

function safeParseTask(taskJson: string):
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; message: string } {
  try {
    const parsed = JSON.parse(taskJson);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "task JSON 必须是对象（object）" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (error) {
    return { ok: false, message: `task JSON 解析失败：${String(error)}` };
  }
}

function labelErrorPayload(payload: unknown): string[] {
  if (!payload || typeof payload !== "object") {
    return ["错误：返回内容不是 JSON"];
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
  }
  if (lines.length === 0) {
    lines.push("错误：返回 JSON 中没有可识别字段");
  }
  return lines;
}

function labelPrecheckPayload(payload: unknown): string[] {
  if (!payload || typeof payload !== "object") {
    return ["预检：返回内容不是 JSON"];
  }
  const dict = payload as Record<string, unknown>;
  const summary =
    dict.summary && typeof dict.summary === "object"
      ? (dict.summary as Record<string, unknown>)
      : undefined;

  const lines: string[] = [];
  if ("expected_exit_code" in dict) {
    lines.push(`expected_exit_code: ${JSON.stringify(dict.expected_exit_code)}`);
  }
  if ("ok" in dict) {
    lines.push(`ok: ${JSON.stringify(dict.ok)}`);
  }
  if (summary) {
    if ("unsupported_count" in summary) {
      lines.push(`unsupported_count: ${JSON.stringify(summary.unsupported_count)}`);
    }
    if ("missing_required_count" in summary) {
      lines.push(`missing_required_count: ${JSON.stringify(summary.missing_required_count)}`);
    }
    if ("missing_optional_count" in summary) {
      lines.push(`missing_optional_count: ${JSON.stringify(summary.missing_optional_count)}`);
    }
  }
  if (Array.isArray(dict.missing_required)) {
    lines.push(`missing_required: ${JSON.stringify(dict.missing_required)}`);
  }
  if (Array.isArray(dict.missing_optional)) {
    lines.push(`missing_optional: ${JSON.stringify(dict.missing_optional)}`);
  }
  if (lines.length === 0) {
    lines.push("预检：返回 JSON 中没有可识别字段");
  }
  return lines;
}

function buildReproduceCurl(settings: ConsoleSettings, baseUrl: string): string {
  const policyHint = settings.policyYaml.trim()
    ? "# 如需策略文本可追加 -F policy_yaml='...'"
    : "# 当前未包含 policy_yaml";

  const taskBody = settings.taskJson.trim() || "{}";

  return [
    "cat > /tmp/task.json <<'JSON'",
    taskBody,
    "JSON",
    "",
    policyHint,
    `curl -sS -X POST "${baseUrl}/v1/run" \\`,
    '  -F "template=@/path/to/template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \\',
    '  -F "task=@/tmp/task.json;type=application/json" \\',
    `  -F "skill=${settings.skill}" \\`,
    `  -F "preset=${settings.preset}" \\`,
    `  -F "strict=${settings.strict ? "true" : "false"}" \\`,
    `  -F "export_suggested_policy=${settings.exportSuggestedPolicy ? "true" : "false"}" \\`,
    "  -D headers.txt \\",
    "  -o docops_outputs.zip",
    'grep -i "X-Docops-Request-Id" headers.txt',
  ].join("\n");
}

function explainExitCode(exitCode: string): string {
  if (exitCode === "0") {
    return "解释：执行成功，已生成结果文档。";
  }
  if (exitCode === "2") {
    return "解释：缺少必填字段，请先补齐 missing_required 再运行。";
  }
  if (exitCode === "3") {
    return "解释：模板中有不支持占位符，建议先调整模板或字段映射。";
  }
  if (exitCode === "4") {
    return "解释：严格模式下格式校验失败，请查看格式报告。";
  }
  if (exitCode === "-" || exitCode.length === 0) {
    return "解释：当前没有可用的 exit_code。";
  }
  return "解释：收到其他退出码，请结合下方错误详情排查。";
}

function getResultTone(result: ResultState): ResultTone {
  if (result.status === "network") {
    return "error";
  }

  const statusCode = Number(result.status);
  if (Number.isFinite(statusCode) && statusCode >= 400) {
    return "error";
  }

  if (result.exitCode === "0" && result.downloadUrl) {
    return "success";
  }

  if (result.exitCode === "2" || result.exitCode === "3" || result.exitCode === "4") {
    return "warning";
  }

  if (result.errorLines.length > 0) {
    return "warning";
  }

  return "neutral";
}

function resultToneLabel(tone: ResultTone): string {
  if (tone === "success") {
    return "成功";
  }
  if (tone === "warning") {
    return "需处理";
  }
  if (tone === "error") {
    return "失败";
  }
  return "等待结果";
}

export default function App() {
  const [settings, setSettings] = useState<ConsoleSettings>(() => loadSettings(DEFAULT_SETTINGS));
  const [taskTypeSelect, setTaskTypeSelect] = useState<string>("");
  const [meta, setMeta] = useState<MetaState>({
    status: "idle",
    skills: ["meeting_notice"],
    presets: ["quick", "template", "strict"],
    taskTypes: ["meeting_notice"],
    message: "尚未加载元数据。",
    warning: "",
  });
  const [runState, setRunState] = useState<string>("空闲");
  const [apiHealth, setApiHealth] = useState<ApiHealthState>("checking");
  const [resultHighlight, setResultHighlight] = useState<boolean>(false);
  const [result, setResult] = useState<ResultState>(DEFAULT_RESULT);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const persistTimer = useRef<number | null>(null);

  const normalizedBaseUrl = useMemo(() => normalizeApiBaseUrl(settings.apiBaseUrl), [settings.apiBaseUrl]);
  const effectiveBaseUrl = normalizedBaseUrl || window.location.origin;
  const reproduceCurl = useMemo(
    () => buildReproduceCurl(settings, effectiveBaseUrl),
    [settings, effectiveBaseUrl],
  );
  const resultTone = useMemo(() => getResultTone(result), [result]);

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

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch(apiUrl(settings.apiBaseUrl, "/healthz"), { method: "GET" });
        setApiHealth(response.ok ? "ok" : "down");
      } catch {
        setApiHealth("down");
      }
    };
    setApiHealth("checking");
    void checkHealth();
  }, [settings.apiBaseUrl]);

  const updateSetting = <K extends keyof ConsoleSettings>(key: K, value: ConsoleSettings[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const applyExample = (skill: string) => {
    const example = EXAMPLE_TASKS[skill];
    if (!example) {
      return;
    }
    updateSetting("skill", skill);
    setTaskTypeSelect(skill);
    updateSetting("taskJson", JSON.stringify(example, null, 2));
    setRunState(`已填入 ${skill} 示例，请上传模板后先预检再运行。`);
  };

  const loadMetaClick = async () => {
    setMeta((prev) => ({ ...prev, status: "loading", message: "正在加载 /v1/meta ...", warning: "" }));
    try {
      const response = await loadMeta(settings.apiBaseUrl);
      if (response.status !== 200 || !response.payload || typeof response.payload !== "object") {
        setMeta((prev) => ({
          ...prev,
          status: "error",
          message: `元数据不可用（status=${response.status}, request_id=${response.requestId || "n/a"}）`,
          warning:
            "你可以手动输入 skill。若跨域调用，请同时配置 DOCOPS_WEB_CONNECT_SRC 与 CORS（DOCOPS_ENABLE_CORS=1 + DOCOPS_CORS_ALLOW_ORIGINS）。",
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
        message: `元数据加载成功（request_id=${response.requestId || "n/a"}）。`,
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
        message: `元数据请求失败：${String(error)}`,
        warning:
          "你可以手动输入 skill。若跨域调用，请同时配置 DOCOPS_WEB_CONNECT_SRC 与 CORS。",
      }));
    }
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
      setRunState("task.json 导入成功");
    } catch (error) {
      setRunState(`task.json 导入失败：${String(error)}`);
    } finally {
      event.target.value = "";
    }
  };

  const exportTaskJson = () => {
    const parsed = safeParseTask(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`无法导出：${parsed.message}`);
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

  const formatTaskJson = () => {
    const parsed = safeParseTask(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`格式化失败：${parsed.message}`);
      return;
    }
    updateSetting("taskJson", JSON.stringify(parsed.value, null, 2));
    setRunState("Task JSON 已格式化");
  };

  const validateTaskJson = () => {
    const parsed = safeParseTask(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`校验失败：${parsed.message}`);
      return;
    }
    setRunState("Task JSON 校验通过");
  };

  const copyRequestId = async () => {
    if (!result.requestId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.requestId);
      setRunState("Request ID 已复制");
    } catch (error) {
      setRunState(`复制失败：${String(error)}`);
    }
  };

  const copyCurl = async () => {
    try {
      await navigator.clipboard.writeText(reproduceCurl);
      setRunState("curl 复现命令已复制");
    } catch (error) {
      setRunState(`复制失败：${String(error)}`);
    }
  };

  const copyIssueBundle = async () => {
    const lines = [
      `status: ${result.status}`,
      `request_id: ${result.requestId || "-"}`,
      `exit_code: ${result.exitCode}`,
      `duration_ms: ${result.durationMs ?? "-"}`,
      "",
      "reproduce:",
      reproduceCurl,
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setRunState("问题排查信息已复制");
    } catch (error) {
      setRunState(`复制失败：${String(error)}`);
    }
  };

  const appendHistory = (entry: HistoryEntry) => {
    setHistory((prev) => [entry, ...prev].slice(0, HISTORY_LIMIT));
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
      setRunState("请先选择模板 .docx 文件");
      return;
    }

    const parsedTask = safeParseTask(settings.taskJson);
    if (!parsedTask.ok) {
      setRunState(parsedTask.message);
      return;
    }

    const taskType = typeof parsedTask.value.task_type === "string" ? parsedTask.value.task_type : "";
    if (!taskType) {
      setRunState("task JSON 中必须包含 task_type");
      return;
    }
    if (settings.skill.trim() !== taskType) {
      setRunState(`skill（${settings.skill}）必须与 task_type（${taskType}）一致`);
      return;
    }
    if (taskTypeSelect && taskTypeSelect !== taskType) {
      setRunState(`所选 task type（${taskTypeSelect}）必须与 task JSON（${taskType}）一致`);
      return;
    }

    setRunState("正在运行...");
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
        setRunState("运行完成（成功返回 ZIP）");
      } else {
        nextResult.errorLines = labelErrorPayload(apiResult.payload);
        nextResult.errorJson = apiResult.payload
          ? JSON.stringify(apiResult.payload, null, 2)
          : "(empty response body)";
        setRunState(apiResult.status >= 400 ? "运行失败" : "运行完成（返回 JSON）");
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
          "开发环境建议优先使用同源或代理。",
          "前后端分离部署时，请同时配置 DOCOPS_WEB_CONNECT_SRC 与 CORS（DOCOPS_ENABLE_CORS=1 + DOCOPS_CORS_ALLOW_ORIGINS）。",
        ],
        errorJson: "",
      });
      setRunState("请求在收到响应前失败");
      appendHistory({
        timestamp: new Date().toISOString(),
        httpStatus: "network",
        requestId: "",
        durationMs,
        baseUrl: settings.apiBaseUrl,
      });
    }
  };

  const precheckClick = async () => {
    resetResult();

    const templateFile = (document.getElementById("template-file") as HTMLInputElement).files?.[0];
    if (!templateFile) {
      setRunState("请先选择模板 .docx 文件");
      return;
    }

    const parsedTask = safeParseTask(settings.taskJson);
    if (!parsedTask.ok) {
      setRunState(parsedTask.message);
      return;
    }

    const taskType = typeof parsedTask.value.task_type === "string" ? parsedTask.value.task_type : "";
    if (!taskType) {
      setRunState("task JSON 中必须包含 task_type");
      return;
    }
    if (settings.skill.trim() !== taskType) {
      setRunState(`skill（${settings.skill}）必须与 task_type（${taskType}）一致`);
      return;
    }
    if (taskTypeSelect && taskTypeSelect !== taskType) {
      setRunState(`所选 task type（${taskTypeSelect}）必须与 task JSON（${taskType}）一致`);
      return;
    }

    setRunState("预检中...");
    const started = performance.now();

    try {
      const apiResult: ApiResult = await precheckDocOps({
        baseUrl: settings.apiBaseUrl,
        templateFile,
        taskJson: settings.taskJson,
        skill: settings.skill,
      });
      const durationMs = Math.round(performance.now() - started);
      const payload = apiResult.payload as Record<string, unknown> | null;
      const expectedExitCode =
        payload && "expected_exit_code" in payload ? String(payload.expected_exit_code) : "-";

      setResult({
        status: String(apiResult.status),
        requestId: apiResult.requestId,
        durationMs,
        exitCode: expectedExitCode,
        downloadUrl: "",
        errorLines:
          apiResult.status === 200 ? labelPrecheckPayload(apiResult.payload) : labelErrorPayload(apiResult.payload),
        errorJson: apiResult.payload ? JSON.stringify(apiResult.payload, null, 2) : "(empty response body)",
      });

      setRunState(apiResult.status === 200 ? "预检完成" : "预检失败");
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
          "开发环境建议优先使用同源或代理。",
          "前后端分离部署时，请同时配置 DOCOPS_WEB_CONNECT_SRC 与 CORS（DOCOPS_ENABLE_CORS=1 + DOCOPS_CORS_ALLOW_ORIGINS）。",
        ],
        errorJson: "",
      });
      setRunState("预检请求在收到响应前失败");
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
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">文书工坊（DocOps Web Console）</h1>
              <p className="mt-2 text-sm text-slate-600">
                面向普通用户的文书生成控制台：看提示、按步骤操作即可完成文档生成。
              </p>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-slate-500">后端状态</p>
              <p
                className={`mt-1 inline-flex items-center gap-2 text-sm font-semibold ${
                  apiHealth === "ok" ? "text-emerald-700" : apiHealth === "down" ? "text-rose-700" : "text-amber-700"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    apiHealth === "ok" ? "bg-emerald-500" : apiHealth === "down" ? "bg-rose-500" : "bg-amber-500"
                  }`}
                />
                {apiHealth === "ok" ? "API 正常" : apiHealth === "down" ? "API 不可用" : "检测中..."}
              </p>
            </div>
          </div>
        </header>

        <section className="mb-4 rounded-xl border border-indigo-100 bg-indigo-50 p-6 shadow-sm">
          <h2 className="mb-3 text-lg font-semibold text-indigo-900">新手快速开始（3 步）</h2>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-indigo-900">
            <li>点击“加载 Meta”，自动读取后端支持的业务类型和参数。</li>
            <li>上传模板文件（.docx），再导入 task.json 或点击“填入示例”。</li>
            <li>先做“预检”，确认无缺失后点击“运行”，下载 ZIP 成果。</li>
          </ol>
          <p className="mt-3 text-xs text-indigo-700">
            不懂技术也没关系：先用示例跑通，再把示例里的文字改成你的真实业务内容。
          </p>
        </section>

        <section className="step-card">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">
            <span className="step-chip mr-2">步骤 1</span>
            连接服务
          </h2>
          <div className="grid gap-4 md:grid-cols-[1fr_auto]">
            <label className="text-sm text-slate-700">
              API 地址（留空表示同源）
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                type="text"
                value={settings.apiBaseUrl}
                onChange={(event) => updateSetting("apiBaseUrl", event.target.value)}
                placeholder="例如：http://127.0.0.1:8000"
              />
            </label>
            <div className="flex items-end gap-2">
              <button className="btn" onClick={loadMetaClick} type="button">
                加载 Meta
              </button>
              <a className="link" href={apiUrl(settings.apiBaseUrl, "/v1/meta")} target="_blank" rel="noreferrer">
                打开 /v1/meta
              </a>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">{meta.message}</p>
          {meta.warning && <p className="mt-1 text-sm text-amber-700">{meta.warning}</p>}
        </section>

        <section className="step-card">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">
            <span className="step-chip mr-2">步骤 2</span>
            填写内容
          </h2>
          <div className="mb-3 flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={() => applyExample("meeting_notice")}>
              填入示例：会议通知
            </button>
            <button type="button" className="btn" onClick={() => applyExample("training_notice")}>
              填入示例：培训通知
            </button>
            <button type="button" className="btn" onClick={() => applyExample("inspection_record")}>
              填入示例：检查记录
            </button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-700">
              Skill
              <div className="mt-1 flex gap-2">
                <select
                  className="flex-1 rounded-md border border-slate-300 px-3 py-2"
                  value={meta.skills.includes(settings.skill) ? settings.skill : ""}
                  onChange={(event) => updateSetting("skill", event.target.value)}
                >
                  {!meta.skills.includes(settings.skill) && <option value="">（手动输入值）</option>}
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
              Task Type（可选下拉）
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={taskTypeSelect}
                onChange={(event) => setTaskTypeSelect(event.target.value)}
              >
                <option value="">（以 task JSON 为准）</option>
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
              严格模式（Strict）
            </label>

            <label className="text-sm text-slate-700">
              模板文件（.docx）
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
              导出建议策略
            </label>
          </div>

          <label className="mt-4 block text-sm text-slate-700">
            任务 JSON
            <textarea
              className="mt-1 h-52 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
              value={settings.taskJson}
              onChange={(event) => updateSetting("taskJson", event.target.value)}
            />
          </label>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="btn cursor-pointer">
              导入 task.json
              <input type="file" accept=".json,application/json" className="hidden" onChange={importTaskJson} />
            </label>
            <button type="button" className="btn" onClick={exportTaskJson}>
              导出 task.json
            </button>
            <button type="button" className="btn" onClick={formatTaskJson}>
              格式化 JSON
            </button>
            <button type="button" className="btn" onClick={validateTaskJson}>
              校验 JSON
            </button>
            <span className="text-xs text-slate-500">浏览器不会保存模板文件，请每次重新选择。</span>
          </div>

          <label className="mt-4 block text-sm text-slate-700">
            policy_yaml（可选）
            <textarea
              className="mt-1 h-28 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
              value={settings.policyYaml}
              onChange={(event) => updateSetting("policyYaml", event.target.value)}
            />
          </label>
        </section>

        <section className="step-card">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">
            <span className="step-chip mr-2">步骤 3</span>
            执行与预检
          </h2>
          <p className="mb-3 text-sm text-slate-600">
            预检不会生成文件，只检查模板和字段是否可用；运行才会真正生成文档并返回 ZIP。
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary-lg" onClick={runClick} type="button">
              运行（Run）
            </button>
            <button className="btn-lg" onClick={precheckClick} type="button">
              预检（Precheck）
            </button>
            <span className="text-sm text-slate-600">{runState}</span>
          </div>
        </section>

        <section
          id="result-block"
          className={`step-card transition ${
            resultHighlight ? "ring-2 ring-indigo-400 ring-offset-2" : ""
          }`}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold text-slate-900">D. 执行结果</h2>
            <span
              className={
                resultTone === "success"
                  ? "status-pill-success"
                  : resultTone === "warning"
                    ? "status-pill-warning"
                    : resultTone === "error"
                      ? "status-pill-error"
                      : "status-pill-neutral"
              }
            >
              {resultToneLabel(resultTone)}
            </span>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="label">HTTP 状态码</p>
              <p className="value">{result.status}</p>
            </div>
            <div>
              <p className="label">Request ID</p>
              <div className="flex items-center gap-2">
                <input className="input-lite" readOnly value={result.requestId} />
                <button className="btn" onClick={copyRequestId} type="button">
                  复制
                </button>
              </div>
            </div>
            <div>
              <p className="label">耗时（ms）</p>
              <p className="value">{result.durationMs ?? "-"}</p>
            </div>
            <div>
              <p className="label">Exit Code</p>
              <p className="value">{result.exitCode}</p>
            </div>
          </div>
          <p className="mt-2 text-xs text-slate-600">{explainExitCode(result.exitCode)}</p>
          {resultTone === "warning" && (
            <p className="mt-1 text-xs text-amber-700">建议先根据详情补字段或修模板，再重新预检/运行。</p>
          )}
          {resultTone === "error" && (
            <p className="mt-1 text-xs text-rose-700">请求失败，请先检查 API 地址、网络连通性和错误详情。</p>
          )}

          {result.downloadUrl && (
            <div className="mt-4 rounded-md bg-emerald-50 p-3 text-emerald-700">
              <p className="font-medium">已收到 ZIP 响应。</p>
              <a className="link" href={result.downloadUrl} download="docops_outputs.zip">
                下载 ZIP
              </a>
            </div>
          )}

          {result.errorLines.length > 0 && (
            <div className="mt-4 rounded-md bg-rose-50 p-3 text-rose-800">
              <p className="font-medium">响应详情</p>
              <pre className="pre">{result.errorLines.join("\n")}</pre>
              <pre className="pre">{result.errorJson}</pre>
            </div>
          )}

          <div className="mt-4">
            <h3 className="text-base font-semibold text-slate-900">复现命令（curl）</h3>
            <div className="mt-2 flex items-center gap-2">
              <button className="btn" onClick={copyCurl} type="button">
                复制 curl
              </button>
              <button className="btn" onClick={copyIssueBundle} type="button">
                复制问题排查信息
              </button>
            </div>
            <pre className="pre mt-2">{reproduceCurl}</pre>
          </div>
        </section>

        <section className="step-card">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">E. 最近请求记录</h2>
          {history.length === 0 ? (
            <p className="text-sm text-slate-600">暂无最近请求记录。</p>
          ) : (
            <ul className="space-y-2">
              {history.map((entry, idx) => (
                <li key={`${entry.timestamp}-${idx}`}>
                  <button
                    type="button"
                    className="history-row"
                    onClick={() => {
                      setResult((prev) => ({ ...prev, requestId: entry.requestId }));
                      setResultHighlight(true);
                      window.setTimeout(() => setResultHighlight(false), 900);
                      document.getElementById("result-block")?.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    <span>{entry.timestamp}</span>
                    <span>状态={entry.httpStatus}</span>
                    <span>耗时={entry.durationMs}ms</span>
                    <span>请求ID={entry.requestId || "-"}</span>
                    <span>地址={entry.baseUrl || "（同源）"}</span>
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
