export type RunRequest = {
  baseUrl: string;
  templateFile: File;
  taskJson: string;
  skill: string;
  preset: string;
  strict: boolean;
  exportSuggestedPolicy: boolean;
  policyYaml: string;
};

export type PrecheckRequest = {
  baseUrl: string;
  templateFile: File;
  taskJson: string;
  skill: string;
};

export type ApiResult = {
  status: number;
  requestId: string;
  exitCode: string;
  contentType: string;
  payload: unknown | null;
  blob: Blob | null;
};

function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (trimmed.length === 0) {
    return "";
  }
  return trimmed.replace(/\/+$/, "");
}

function buildUrl(baseUrl: string, path: string): string {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized) {
    return path;
  }
  return `${normalized}${path}`;
}

export async function loadMeta(baseUrl: string): Promise<ApiResult> {
  const response = await fetch(buildUrl(baseUrl, "/v1/meta"), { method: "GET" });
  const contentType = response.headers.get("content-type") ?? "";
  const requestId = response.headers.get("X-Docops-Request-Id") ?? "";
  const exitCode = response.headers.get("X-Docops-Exit-Code") ?? "";

  let payload: unknown | null = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  return {
    status: response.status,
    requestId,
    exitCode,
    contentType,
    payload,
    blob: null,
  };
}

export async function runDocOps(request: RunRequest): Promise<ApiResult> {
  const formData = new FormData();
  formData.append("template", request.templateFile, request.templateFile.name || "template.docx");
  formData.append("task", new Blob([request.taskJson], { type: "application/json" }), "task.json");
  formData.append("skill", request.skill);
  formData.append("preset", request.preset);
  formData.append("strict", request.strict ? "true" : "false");
  formData.append("export_suggested_policy", request.exportSuggestedPolicy ? "true" : "false");
  if (request.policyYaml.trim()) {
    formData.append("policy_yaml", request.policyYaml);
  }

  const response = await fetch(buildUrl(request.baseUrl, "/v1/run"), {
    method: "POST",
    body: formData,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const requestId = response.headers.get("X-Docops-Request-Id") ?? "";
  const exitCode = response.headers.get("X-Docops-Exit-Code") ?? "";

  if (response.ok && !contentType.toLowerCase().includes("application/json")) {
    return {
      status: response.status,
      requestId,
      exitCode,
      contentType,
      payload: null,
      blob: await response.blob(),
    };
  }

  let payload: unknown | null = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  return {
    status: response.status,
    requestId,
    exitCode,
    contentType,
    payload,
    blob: null,
  };
}

export async function precheckDocOps(request: PrecheckRequest): Promise<ApiResult> {
  const formData = new FormData();
  formData.append("template", request.templateFile, request.templateFile.name || "template.docx");
  formData.append("task", new Blob([request.taskJson], { type: "application/json" }), "task.json");
  formData.append("skill", request.skill);

  const response = await fetch(buildUrl(request.baseUrl, "/v1/precheck"), {
    method: "POST",
    body: formData,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const requestId = response.headers.get("X-Docops-Request-Id") ?? "";
  const exitCode = response.headers.get("X-Docops-Exit-Code") ?? "";

  let payload: unknown | null = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  return {
    status: response.status,
    requestId,
    exitCode,
    contentType,
    payload,
    blob: null,
  };
}

export function defaultApiBaseUrl(): string {
  return "";
}

export function normalizeApiBaseUrl(baseUrl: string): string {
  return normalizeBaseUrl(baseUrl);
}

export function apiUrl(baseUrl: string, path: string): string {
  return buildUrl(baseUrl, path);
}
