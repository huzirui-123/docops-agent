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
  allSkillSpecs,
  defaultFormValues,
  fieldLabelByToken,
  getSkillSpec,
  skillLabel,
  type SkillFormSpec,
} from "./form_specs";
import {
  buildTaskFromForm,
  buildTaskPreviewFromForm,
  ensureTaskTypeMatch,
  maybeTaskJsonFromPayload,
  parseTaskJson,
  taskPayloadToFormValues,
} from "./task_builder";
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
type InputMode = "form" | "json";

type PrecheckSnapshot = {
  signature: string;
  status: number;
  requestId: string;
  expectedExitCode: string;
  ok: boolean | null;
  templateFields: string[];
  missingRequired: string[];
  missingOptional: string[];
  unsupportedCount: number;
  templateFieldCount: number;
  checkedAt: string;
};

type SelectedTemplateInfo = {
  name: string;
  size: number;
  lastModified: number;
};

const HISTORY_LIMIT = 10;
const DEFAULT_SKILL = "meeting_notice";

const DEFAULT_TASK_JSON = buildTaskPreviewFromForm(DEFAULT_SKILL, defaultFormValues(DEFAULT_SKILL)).taskJson;

const DEFAULT_SETTINGS: ConsoleSettings = {
  apiBaseUrl: defaultApiBaseUrl(),
  skill: DEFAULT_SKILL,
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

function presetLabel(preset: string): string {
  if (preset === "quick") {
    return "快速（quick）";
  }
  if (preset === "template") {
    return "模板优先（template）";
  }
  if (preset === "strict") {
    return "严格（strict）";
  }
  return preset;
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

function buildInitialFormValues(): Record<string, Record<string, string>> {
  const values: Record<string, Record<string, string>> = {};
  for (const spec of allSkillSpecs()) {
    values[spec.skill] = defaultFormValues(spec.skill);
  }
  return values;
}

function buildReproduceCurl(settings: ConsoleSettings, taskJson: string, baseUrl: string): string {
  const policyHint = settings.policyYaml.trim()
    ? "# 如需策略文本可追加 -F policy_yaml='...'"
    : "# 当前未包含 policy_yaml";

  const taskBody = taskJson.trim() || "{}";

  return [
    "cat > /tmp/task.json <<'JSON'",
    taskBody,
    "JSON",
    "",
    policyHint,
    `curl -sS -X POST \"${baseUrl}/v1/run\" \\\\`,
    '  -F "template=@/path/to/template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \\\\',
    '  -F "task=@/tmp/task.json;type=application/json" \\\\',
    `  -F "skill=${settings.skill}" \\\\`,
    `  -F "preset=${settings.preset}" \\\\`,
    `  -F "strict=${settings.strict ? "true" : "false"}" \\\\`,
    `  -F "export_suggested_policy=${settings.exportSuggestedPolicy ? "true" : "false"}" \\\\`,
    "  -D headers.txt \\\\",
    "  -o docops_outputs.zip",
    'grep -i "X-Docops-Request-Id" headers.txt',
  ].join("\n");
}

function modeLabel(mode: InputMode): string {
  return mode === "form" ? "表单模式（推荐）" : "高级 JSON 模式";
}

function tokenWithLabel(skill: string, token: string): string {
  const label = fieldLabelByToken(skill, token);
  return label ? `${token}（${label}）` : token;
}

function buildPrecheckSignature(
  templateFile: { name: string; size: number; lastModified: number },
  skill: string,
  taskJson: string,
  baseUrl: string,
): string {
  return [
    templateFile.name,
    templateFile.size,
    templateFile.lastModified,
    skill,
    baseUrl,
    taskJson,
  ].join("|");
}

function parsePrecheckSnapshot(
  response: ApiResult,
  signature: string,
): PrecheckSnapshot | null {
  if (!response.payload || typeof response.payload !== "object") {
    return null;
  }
  const payload = response.payload as Record<string, unknown>;
  const summary =
    payload.summary && typeof payload.summary === "object"
      ? (payload.summary as Record<string, unknown>)
      : undefined;

  const templateFields = Array.isArray(payload.template_fields)
    ? payload.template_fields.filter((value): value is string => typeof value === "string")
    : [];
  const missingRequired = Array.isArray(payload.missing_required)
    ? payload.missing_required.filter((value): value is string => typeof value === "string")
    : [];
  const missingOptional = Array.isArray(payload.missing_optional)
    ? payload.missing_optional.filter((value): value is string => typeof value === "string")
    : [];

  return {
    signature,
    status: response.status,
    requestId: response.requestId,
    expectedExitCode:
      "expected_exit_code" in payload ? String(payload.expected_exit_code ?? "-") : "-",
    ok: "ok" in payload && typeof payload.ok === "boolean" ? payload.ok : null,
    templateFields,
    missingRequired,
    missingOptional,
    unsupportedCount:
      summary && typeof summary.unsupported_count === "number" ? summary.unsupported_count : 0,
    templateFieldCount:
      summary && typeof summary.template_field_count === "number"
        ? summary.template_field_count
        : templateFields.length,
    checkedAt: new Date().toISOString(),
  };
}

export default function App() {
  const [settings, setSettings] = useState<ConsoleSettings>(() => loadSettings(DEFAULT_SETTINGS));
  const [taskTypeSelect, setTaskTypeSelect] = useState<string>("");
  const [meta, setMeta] = useState<MetaState>({
    status: "idle",
    skills: [DEFAULT_SKILL],
    presets: ["quick", "template", "strict"],
    taskTypes: [DEFAULT_SKILL],
    message: "尚未加载元数据。",
    warning: "",
  });
  const [runState, setRunState] = useState<string>("空闲");
  const [apiHealth, setApiHealth] = useState<ApiHealthState>("checking");
  const [resultHighlight, setResultHighlight] = useState<boolean>(false);
  const [result, setResult] = useState<ResultState>(DEFAULT_RESULT);
  const [precheckSnapshot, setPrecheckSnapshot] = useState<PrecheckSnapshot | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const [inputMode, setInputMode] = useState<InputMode>("form");
  const [jsonEditable, setJsonEditable] = useState<boolean>(false);
  const [templateInfo, setTemplateInfo] = useState<SelectedTemplateInfo | null>(null);
  const [formValuesBySkill, setFormValuesBySkill] = useState<Record<string, Record<string, string>>>(() =>
    buildInitialFormValues(),
  );

  const templateInputRef = useRef<HTMLInputElement>(null);
  const initializedRef = useRef<boolean>(false);
  const persistTimer = useRef<number | null>(null);

  const currentSpec = useMemo<SkillFormSpec | null>(() => getSkillSpec(settings.skill), [settings.skill]);
  const currentFormValues = formValuesBySkill[settings.skill] ?? {};
  const generatedFromForm = useMemo(
    () => buildTaskPreviewFromForm(settings.skill, currentFormValues),
    [settings.skill, currentFormValues],
  );

  const normalizedBaseUrl = useMemo(() => normalizeApiBaseUrl(settings.apiBaseUrl), [settings.apiBaseUrl]);
  const effectiveBaseUrl = normalizedBaseUrl || window.location.origin;
  const activeTaskJson = inputMode === "form" ? generatedFromForm.taskJson : settings.taskJson;
  const reproduceCurl = useMemo(
    () => buildReproduceCurl(settings, activeTaskJson, effectiveBaseUrl),
    [activeTaskJson, effectiveBaseUrl, settings],
  );
  const resultTone = useMemo(() => getResultTone(result), [result]);
  const currentPrecheckSignature = templateInfo
    ? buildPrecheckSignature(templateInfo, settings.skill, activeTaskJson, effectiveBaseUrl)
    : "";
  const precheckIsCurrent =
    Boolean(precheckSnapshot) &&
    currentPrecheckSignature.length > 0 &&
    precheckSnapshot?.signature === currentPrecheckSignature;

  const jsonConflictMessage = useMemo(() => {
    if (inputMode !== "json" || !jsonEditable || !currentSpec) {
      return "";
    }
    const parsed = parseTaskJson(settings.taskJson);
    if (!parsed.ok) {
      return "";
    }
    const generatedParsed = JSON.parse(generatedFromForm.taskJson) as { task_type?: unknown; payload?: unknown };
    const manualComparable = JSON.stringify(parsed.task);
    const generatedComparable = JSON.stringify(generatedParsed);
    if (manualComparable !== generatedComparable) {
      return "你正在使用手动 JSON，内容与表单不一致。运行时将以当前 JSON 文本为准。";
    }
    return "";
  }, [currentSpec, generatedFromForm.taskJson, inputMode, jsonEditable, settings.taskJson]);

  useEffect(() => {
    if (initializedRef.current) {
      return;
    }
    initializedRef.current = true;

    const parsed = parseTaskJson(settings.taskJson);
    if (!parsed.ok) {
      return;
    }

    const taskType = parsed.task.task_type;
    if (typeof taskType !== "string") {
      return;
    }
    const payloadValues = taskPayloadToFormValues(taskType, parsed.task.payload);
    if (Object.keys(payloadValues).length === 0) {
      return;
    }

    setFormValuesBySkill((prev) => ({
      ...prev,
      [taskType]: {
        ...(prev[taskType] ?? {}),
        ...payloadValues,
      },
    }));
  }, [settings.taskJson]);

  useEffect(() => {
    if (inputMode !== "form") {
      return;
    }
    const nextTaskJson = generatedFromForm.taskJson;
    setSettings((prev) => (prev.taskJson === nextTaskJson ? prev : { ...prev, taskJson: nextTaskJson }));
  }, [generatedFromForm.taskJson, inputMode]);

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

  const updateFormValue = (fieldKey: string, value: string) => {
    const skill = settings.skill;
    setFormValuesBySkill((prev) => ({
      ...prev,
      [skill]: {
        ...(prev[skill] ?? {}),
        [fieldKey]: value,
      },
    }));
  };

  const resetFormToExample = (skill: string) => {
    const values = defaultFormValues(skill);
    setFormValuesBySkill((prev) => ({
      ...prev,
      [skill]: values,
    }));
    setRunState(`已重置为“${skillLabel(skill)}”官方示例。`);
  };

  const fillRequiredFromExample = (skill: string) => {
    const spec = getSkillSpec(skill);
    if (!spec) {
      return;
    }
    const defaults = defaultFormValues(skill);
    setFormValuesBySkill((prev) => {
      const current = prev[skill] ?? {};
      const next: Record<string, string> = { ...current };
      for (const field of spec.fields) {
        if (!field.required) {
          continue;
        }
        if ((next[field.key] ?? "").trim().length > 0) {
          continue;
        }
        next[field.key] = defaults[field.key] ?? "";
      }
      return { ...prev, [skill]: next };
    });
    setRunState("已为必填字段补入示例值。");
  };

  const applyExample = (skill: string) => {
    updateSetting("skill", skill);
    setTaskTypeSelect(skill);
    setInputMode("form");
    setJsonEditable(false);
    resetFormToExample(skill);
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
        skills: skills.length ? skills : [DEFAULT_SKILL],
        presets: presets.length ? presets : ["quick", "template", "strict"],
        taskTypes: taskTypes.length ? taskTypes : [DEFAULT_SKILL],
        message: `元数据加载成功（request_id=${response.requestId || "n/a"}）。`,
        warning: "",
      });

      setSettings((prev) => {
        const nextSkill = skills.includes(prev.skill) ? prev.skill : (skills[0] ?? prev.skill);
        const nextPreset = presets.includes(prev.preset) ? prev.preset : (presets[0] ?? prev.preset);
        return { ...prev, skill: nextSkill, preset: nextPreset };
      });
    } catch (error) {
      setMeta((prev) => ({
        ...prev,
        status: "error",
        message: `元数据请求失败：${String(error)}`,
        warning: "你可以手动输入 skill。若跨域调用，请同时配置 DOCOPS_WEB_CONNECT_SRC 与 CORS。",
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
      const parsed = parseTaskJson(content);
      if (!parsed.ok) {
        setRunState(parsed.message);
        return;
      }
      updateSetting("taskJson", JSON.stringify(parsed.task, null, 2));
      setInputMode("json");
      setJsonEditable(true);
      const taskType = typeof parsed.task.task_type === "string" ? parsed.task.task_type : "";
      if (taskType.length > 0) {
        updateSetting("skill", taskType);
        setTaskTypeSelect(taskType);
      }
      if (typeof parsed.task.task_type === "string") {
        const nextFormValues = taskPayloadToFormValues(parsed.task.task_type, parsed.task.payload);
        if (Object.keys(nextFormValues).length > 0) {
          setFormValuesBySkill((prev) => ({
            ...prev,
            [parsed.task.task_type as string]: {
              ...(prev[parsed.task.task_type as string] ?? {}),
              ...nextFormValues,
            },
          }));
        }
      }
      setRunState("task.json 导入成功（已切换到高级 JSON 模式）");
    } catch (error) {
      setRunState(`task.json 导入失败：${String(error)}`);
    } finally {
      event.target.value = "";
    }
  };

  const onTemplateFileChanged = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      setTemplateInfo(null);
      return;
    }
    setTemplateInfo({
      name: file.name,
      size: file.size,
      lastModified: file.lastModified,
    });
  };

  const exportTaskJson = () => {
    const sourceJson = inputMode === "form" ? generatedFromForm.taskJson : settings.taskJson;
    const parsed = parseTaskJson(sourceJson);
    if (!parsed.ok) {
      setRunState(`无法导出：${parsed.message}`);
      return;
    }
    const blob = new Blob([JSON.stringify(parsed.task, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "task.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatTaskJson = () => {
    const parsed = parseTaskJson(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`格式化失败：${parsed.message}`);
      return;
    }
    updateSetting("taskJson", JSON.stringify(parsed.task, null, 2));
    setRunState("任务 JSON 已格式化");
  };

  const validateTaskJson = () => {
    const parsed = parseTaskJson(settings.taskJson);
    if (!parsed.ok) {
      setRunState(`校验失败：${parsed.message}`);
      return;
    }
    setRunState("任务 JSON 校验通过");
  };

  const copyRequestId = async () => {
    if (!result.requestId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.requestId);
      setRunState("请求 ID 已复制");
    } catch (error) {
      setRunState(`复制失败：${String(error)}`);
    }
  };

  const copyCurl = async () => {
    try {
      await navigator.clipboard.writeText(reproduceCurl);
      setRunState("复现命令已复制");
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

  const buildSubmissionTask = (): { ok: true; taskJson: string } | { ok: false; message: string } => {
    if (inputMode === "form") {
      const built = buildTaskFromForm(settings.skill, currentFormValues);
      if (!built.ok) {
        return { ok: false, message: built.message };
      }
      if (taskTypeSelect && taskTypeSelect !== built.task.task_type) {
        return {
          ok: false,
          message: `所选任务类型（${taskTypeSelect}）必须与任务（${built.task.task_type}）一致。`,
        };
      }
      return { ok: true, taskJson: built.taskJson };
    }

    const parsed = parseTaskJson(settings.taskJson);
    if (!parsed.ok) {
      return { ok: false, message: parsed.message };
    }

    const mismatch = ensureTaskTypeMatch(settings.skill, parsed.task.task_type);
    if (mismatch) {
      return { ok: false, message: mismatch.message };
    }

    const taskType = String(parsed.task.task_type);
    if (taskTypeSelect && taskTypeSelect !== taskType) {
      return {
        ok: false,
        message: `所选任务类型（${taskTypeSelect}）必须与任务 JSON（${taskType}）一致。`,
      };
    }

    return { ok: true, taskJson: maybeTaskJsonFromPayload(taskType, parsed.task.payload) };
  };

  const runClick = async () => {
    resetResult();

    const templateFile = templateInputRef.current?.files?.[0];
    if (!templateFile) {
      setRunState("请先选择模板 .docx 文件");
      return;
    }

    const task = buildSubmissionTask();
    if (!task.ok) {
      setRunState(task.message);
      return;
    }

    if (precheckIsCurrent && precheckSnapshot && precheckSnapshot.missingRequired.length > 0) {
      const missingLabels = precheckSnapshot.missingRequired.map((token) =>
        tokenWithLabel(settings.skill, token),
      );
      setResult({
        status: "blocked",
        requestId: precheckSnapshot.requestId,
        durationMs: null,
        exitCode: precheckSnapshot.expectedExitCode,
        downloadUrl: "",
        errorLines: [
          "已阻止运行：最近一次模板扫描显示存在必填占位符未覆盖。",
          `missing_required: ${missingLabels.join("、")}`,
          "请先补齐表单后再次预检。",
        ],
        errorJson: "",
      });
      setRunState("已阻止：请先补齐必填项并重新预检。");
      return;
    }

    if (precheckIsCurrent && precheckSnapshot && precheckSnapshot.unsupportedCount > 0) {
      setRunState("警告：模板包含不支持占位符，仍将继续运行...");
    } else {
      setRunState("正在运行...");
    }
    const started = performance.now();

    try {
      const apiResult: ApiResult = await runDocOps({
        baseUrl: settings.apiBaseUrl,
        templateFile,
        taskJson: task.taskJson,
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
      setPrecheckSnapshot(null);
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

    const templateFile = templateInputRef.current?.files?.[0];
    if (!templateFile) {
      setRunState("请先选择模板 .docx 文件");
      return;
    }

    const task = buildSubmissionTask();
    if (!task.ok) {
      setRunState(task.message);
      return;
    }

    const signature = buildPrecheckSignature(
      {
        name: templateFile.name,
        size: templateFile.size,
        lastModified: templateFile.lastModified,
      },
      settings.skill,
      task.taskJson,
      effectiveBaseUrl,
    );

    setRunState("预检中...");
    const started = performance.now();

    try {
      const apiResult: ApiResult = await precheckDocOps({
        baseUrl: settings.apiBaseUrl,
        templateFile,
        taskJson: task.taskJson,
        skill: settings.skill,
      });
      const durationMs = Math.round(performance.now() - started);
      const payload = apiResult.payload as Record<string, unknown> | null;
      const expectedExitCode =
        payload && "expected_exit_code" in payload ? String(payload.expected_exit_code) : "-";
      const snapshot = parsePrecheckSnapshot(apiResult, signature);
      setPrecheckSnapshot(snapshot);

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
              <p className="mt-2 text-sm text-slate-600">面向普通用户的文书生成控制台：看提示、按步骤操作即可完成文档生成。</p>
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
            <li>点击“加载元数据”，读取后端支持的业务类型和参数。</li>
            <li>上传模板文件（.docx），在表单中填写内容或使用官方示例。</li>
            <li>先做“预检”，确认无缺失后点击“开始生成”，下载 ZIP 成果。</li>
          </ol>
          <p className="mt-3 text-xs text-indigo-700">不懂技术也没关系：默认用“表单模式（推荐）”，系统会自动生成合法任务 JSON。</p>
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
                加载元数据
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

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button type="button" className={inputMode === "form" ? "btn-primary" : "btn"} onClick={() => setInputMode("form")}>
              表单模式（推荐）
            </button>
            <button type="button" className={inputMode === "json" ? "btn-primary" : "btn"} onClick={() => setInputMode("json")}>
              高级 JSON 模式
            </button>
            <span className="text-xs text-slate-500">当前模式：{modeLabel(inputMode)}</span>
          </div>

          <div className="mb-3 flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={() => applyExample("meeting_notice")}>
              官方示例：会议通知
            </button>
            <button type="button" className="btn" onClick={() => applyExample("training_notice")}>
              官方示例：培训通知
            </button>
            <button type="button" className="btn" onClick={() => applyExample("inspection_record")}>
              官方示例：检查记录
            </button>
            <button type="button" className="btn" onClick={() => resetFormToExample(settings.skill)}>
              重置当前表单
            </button>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-700">
              技能类型
              <div className="mt-1 flex gap-2">
                <select
                  className="flex-1 rounded-md border border-slate-300 px-3 py-2"
                  value={meta.skills.includes(settings.skill) ? settings.skill : ""}
                  onChange={(event) => updateSetting("skill", event.target.value)}
                >
                  {!meta.skills.includes(settings.skill) && <option value="">（手动输入）</option>}
                  {meta.skills.map((skill) => (
                    <option key={skill} value={skill}>
                      {skillLabel(skill)}
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
              任务类型（可选下拉）
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={taskTypeSelect}
                onChange={(event) => setTaskTypeSelect(event.target.value)}
              >
                <option value="">（以任务数据为准）</option>
                {meta.taskTypes.map((taskType) => (
                  <option key={taskType} value={taskType}>
                    {skillLabel(taskType)}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm text-slate-700">
              运行预设
              <select
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                value={settings.preset}
                onChange={(event) => updateSetting("preset", event.target.value)}
              >
                {meta.presets.map((preset) => (
                  <option key={preset} value={preset}>
                    {presetLabel(preset)}
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
              严格模式
            </label>

            <label className="text-sm text-slate-700">
              模板文件（.docx）
              <input
                ref={templateInputRef}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                type="file"
                accept=".docx"
                onChange={onTemplateFileChanged}
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

          {inputMode === "form" && currentSpec && (
            <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4">
              <p className="mb-3 text-sm font-semibold text-slate-800">表单输入（{currentSpec.displayName}）</p>
              <div className="grid gap-3 md:grid-cols-2">
                {currentSpec.fields.map((field) => {
                  const value = currentFormValues[field.key] ?? "";
                  const requiredMark = field.required ? " *" : "";
                  if (field.kind === "textarea" || field.kind === "list") {
                    return (
                      <label key={field.key} className="text-sm text-slate-700 md:col-span-2">
                        {field.label}
                        {requiredMark}
                        <textarea
                          className="mt-1 h-24 w-full rounded-md border border-slate-300 px-3 py-2"
                          placeholder={field.placeholder ?? ""}
                          value={value}
                          onChange={(event) => updateFormValue(field.key, event.target.value)}
                        />
                        {field.help && <p className="mt-1 text-xs text-slate-500">{field.help}</p>}
                      </label>
                    );
                  }

                  return (
                    <label key={field.key} className="text-sm text-slate-700">
                      {field.label}
                      {requiredMark}
                      <input
                        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                        type="text"
                        placeholder={field.placeholder ?? ""}
                        value={value}
                        onChange={(event) => updateFormValue(field.key, event.target.value)}
                      />
                      {field.help && <p className="mt-1 text-xs text-slate-500">{field.help}</p>}
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {currentSpec && (
            <div className="mt-4 rounded-md border border-indigo-200 bg-indigo-50 p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-indigo-900">
                  模板标签向导（{currentSpec.displayName}）
                </p>
                <button type="button" className="btn" onClick={() => fillRequiredFromExample(settings.skill)}>
                  一键补全必填示例
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-indigo-100 text-left text-indigo-900">
                      <th className="border border-indigo-200 px-2 py-1">模板标签</th>
                      <th className="border border-indigo-200 px-2 py-1">中文字段</th>
                      <th className="border border-indigo-200 px-2 py-1">当前值</th>
                      <th className="border border-indigo-200 px-2 py-1">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentSpec.fields.map((field) => {
                      const rawValue = (currentFormValues[field.key] ?? "").trim();
                      const isFilled = rawValue.length > 0;
                      const status = isFilled
                        ? "已填写"
                        : field.required
                          ? "必填未填"
                          : "可选未填";
                      const statusClass = isFilled
                        ? "text-emerald-700"
                        : field.required
                          ? "text-rose-700"
                          : "text-amber-700";
                      return (
                        <tr key={field.key} className="bg-white">
                          <td className="border border-indigo-200 px-2 py-1 font-mono">
                            【{field.templateToken}】
                          </td>
                          <td className="border border-indigo-200 px-2 py-1">
                            {field.label}
                            {field.required ? <span className="ml-1 text-rose-600">*</span> : null}
                          </td>
                          <td className="max-w-sm truncate border border-indigo-200 px-2 py-1 text-slate-700">
                            {rawValue || "（空）"}
                          </td>
                          <td className={`border border-indigo-200 px-2 py-1 font-medium ${statusClass}`}>
                            {status}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {inputMode === "json" && (
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4">
              <label className="mb-2 flex items-center gap-2 text-sm text-amber-800">
                <input type="checkbox" checked={jsonEditable} onChange={(event) => setJsonEditable(event.target.checked)} />
                我已了解风险，允许手动编辑 JSON
              </label>
              {jsonConflictMessage && <p className="mb-2 text-xs text-amber-800">{jsonConflictMessage}</p>}
            </div>
          )}

          <label className="mt-4 block text-sm text-slate-700">
            任务内容（JSON）{inputMode === "form" ? "（表单自动生成，只读）" : ""}
            <textarea
              className="mt-1 h-56 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
              value={inputMode === "form" ? generatedFromForm.taskJson : settings.taskJson}
              readOnly={inputMode === "form" || !jsonEditable}
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
            <button type="button" className="btn" onClick={formatTaskJson} disabled={inputMode === "form" || !jsonEditable}>
              一键格式化
            </button>
            <button type="button" className="btn" onClick={validateTaskJson}>
              语法校验
            </button>
            <span className="text-xs text-slate-500">浏览器不会保存模板文件，请每次重新选择。</span>
          </div>

          <label className="mt-4 block text-sm text-slate-700">
            策略文本（可选）
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
          <p className="mb-3 text-sm text-slate-600">预检不会生成文件，只检查模板和字段是否可用；开始生成会真正返回 ZIP 文件。</p>
          <div className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn" onClick={precheckClick} type="button">
                扫描模板占位符（预检）
              </button>
              {templateInfo ? (
                <span className="text-xs text-slate-600">
                  当前模板：{templateInfo.name}（{Math.max(1, Math.round(templateInfo.size / 1024))} KB）
                </span>
              ) : (
                <span className="text-xs text-amber-700">请先选择模板文件，再执行扫描。</span>
              )}
            </div>

            {precheckSnapshot && (
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="status-pill-neutral">模板字段：{precheckSnapshot.templateFieldCount}</span>
                  <span className="status-pill-warning">可选缺失：{precheckSnapshot.missingOptional.length}</span>
                  <span className="status-pill-error">必填缺失：{precheckSnapshot.missingRequired.length}</span>
                  <span
                    className={
                      precheckSnapshot.unsupportedCount > 0
                        ? "status-pill-warning"
                        : "status-pill-success"
                    }
                  >
                    不支持占位符：{precheckSnapshot.unsupportedCount}
                  </span>
                </div>
                <p className="text-xs text-slate-600">
                  最近扫描 request_id：{precheckSnapshot.requestId || "-"}，expected_exit_code：
                  {precheckSnapshot.expectedExitCode}
                  {precheckIsCurrent ? "（与当前输入一致）" : "（已过期，请重新扫描）"}
                </p>

                {precheckSnapshot.missingRequired.length > 0 && (
                  <p className="rounded-md bg-rose-50 px-3 py-2 text-rose-700">
                    必填占位符缺失：
                    {precheckSnapshot.missingRequired
                      .map((token) => tokenWithLabel(settings.skill, token))
                      .join("、")}
                  </p>
                )}
                {precheckSnapshot.unsupportedCount > 0 && (
                  <p className="rounded-md bg-amber-50 px-3 py-2 text-amber-700">
                    模板包含不支持占位符（{precheckSnapshot.unsupportedCount} 个）。系统会继续运行，但可能产生
                    `exit_code=3`，建议先修模板。
                  </p>
                )}

                {precheckSnapshot.templateFields.length > 0 && (
                  <details className="rounded-md border border-slate-200 bg-white p-2">
                    <summary className="cursor-pointer text-xs font-medium text-slate-700">
                      查看模板中识别到的占位符（{precheckSnapshot.templateFields.length}）
                    </summary>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {precheckSnapshot.templateFields.map((token) => (
                        <span key={token} className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-700">
                          {tokenWithLabel(settings.skill, token)}
                        </span>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary-lg" onClick={runClick} type="button">
              开始生成
            </button>
            <button className="btn-lg" onClick={precheckClick} type="button">
              刷新预检结果
            </button>
            <span className="text-sm text-slate-600">{runState}</span>
          </div>
        </section>

        <section
          id="result-block"
          className={`step-card transition ${resultHighlight ? "ring-2 ring-indigo-400 ring-offset-2" : ""}`}
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
              <p className="label">请求 ID</p>
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
              <p className="label">退出码</p>
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
            <h3 className="text-base font-semibold text-slate-900">复现命令</h3>
            <div className="mt-2 flex items-center gap-2">
              <button className="btn" onClick={copyCurl} type="button">
                复制复现命令
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
