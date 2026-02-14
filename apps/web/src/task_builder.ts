import { getSkillSpec, type SkillFormSpec } from "./form_specs";

export type TaskBuildSuccess = {
  ok: true;
  task: { task_type: string; payload: Record<string, unknown> };
  taskJson: string;
};

export type TaskBuildFailure = {
  ok: false;
  message: string;
};

export type TaskBuildResult = TaskBuildSuccess | TaskBuildFailure;

function normalizeListValue(raw: string): string[] {
  return raw
    .split(/\n|,|，|;|；/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function valueFromForm(spec: SkillFormSpec, key: string, raw: string): unknown {
  const field = spec.fields.find((item) => item.key === key);
  if (!field) {
    return raw;
  }
  if (field.kind === "list") {
    return normalizeListValue(raw);
  }
  return raw;
}

export function missingRequiredLabels(skill: string, formValues: Record<string, string>): string[] {
  const spec = getSkillSpec(skill);
  if (!spec) {
    return [];
  }

  const missing: string[] = [];
  for (const field of spec.fields) {
    if (!field.required) {
      continue;
    }
    const raw = (formValues[field.key] ?? "").trim();
    if (raw.length === 0) {
      missing.push(field.label);
    }
  }
  return missing;
}

export function buildTaskFromForm(skill: string, formValues: Record<string, string>): TaskBuildResult {
  const spec = getSkillSpec(skill);
  if (!spec) {
    return {
      ok: false,
      message: "当前 skill 未配置表单规范，请切换到高级 JSON 模式。",
    };
  }

  const missing = missingRequiredLabels(skill, formValues);
  if (missing.length > 0) {
    return {
      ok: false,
      message: `请补全必填项：${missing.join("、")}`,
    };
  }

  const payload: Record<string, unknown> = {};
  for (const field of spec.fields) {
    const raw = (formValues[field.key] ?? "").trim();
    if (raw.length === 0) {
      continue;
    }

    const value = valueFromForm(spec, field.key, raw);
    if (Array.isArray(value) && value.length === 0) {
      continue;
    }
    payload[field.key] = value;
  }

  const task = { task_type: spec.skill, payload };
  return {
    ok: true,
    task,
    taskJson: JSON.stringify(task, null, 2),
  };
}

export function buildTaskPreviewFromForm(skill: string, formValues: Record<string, string>): {
  task: { task_type: string; payload: Record<string, unknown> };
  taskJson: string;
} {
  const spec = getSkillSpec(skill);
  if (!spec) {
    const task = { task_type: skill, payload: {} };
    return { task, taskJson: JSON.stringify(task, null, 2) };
  }

  const payload: Record<string, unknown> = {};
  for (const field of spec.fields) {
    const raw = (formValues[field.key] ?? "").trim();
    if (raw.length === 0) {
      continue;
    }

    const value = valueFromForm(spec, field.key, raw);
    if (Array.isArray(value) && value.length === 0) {
      continue;
    }
    payload[field.key] = value;
  }

  const task = { task_type: spec.skill, payload };
  return { task, taskJson: JSON.stringify(task, null, 2) };
}

export function parseTaskJson(taskJson: string):
  | { ok: true; task: { task_type?: unknown; payload?: unknown } }
  | { ok: false; message: string } {
  try {
    const parsed: unknown = JSON.parse(taskJson);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "任务 JSON 必须是对象。" };
    }
    return { ok: true, task: parsed as { task_type?: unknown; payload?: unknown } };
  } catch (error) {
    return { ok: false, message: `任务 JSON 解析失败：${String(error)}` };
  }
}

export function ensureTaskTypeMatch(skill: string, taskType: unknown): TaskBuildFailure | null {
  if (typeof taskType !== "string" || taskType.trim().length === 0) {
    return {
      ok: false,
      message: "任务 JSON 中必须包含 task_type。",
    };
  }

  if (taskType.trim() !== skill.trim()) {
    return {
      ok: false,
      message: `技能类型（${skill}）必须与 task_type（${String(taskType)}）一致。`,
    };
  }
  return null;
}

export function maybeTaskJsonFromPayload(skill: string, payload: unknown): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return JSON.stringify({ task_type: skill, payload: {} }, null, 2);
  }
  return JSON.stringify({ task_type: skill, payload }, null, 2);
}

export function taskPayloadToFormValues(skill: string, payload: unknown): Record<string, string> {
  const spec = getSkillSpec(skill);
  if (!spec || !payload || typeof payload !== "object" || Array.isArray(payload)) {
    return {};
  }

  const dict = payload as Record<string, unknown>;
  const values: Record<string, string> = {};
  for (const field of spec.fields) {
    const value = dict[field.key];
    if (Array.isArray(value)) {
      values[field.key] = value.map((item) => String(item)).join("\n");
    } else if (value == null) {
      values[field.key] = "";
    } else {
      values[field.key] = String(value);
    }
  }
  return values;
}
