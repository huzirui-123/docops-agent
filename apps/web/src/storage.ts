export type ConsoleSettings = {
  apiBaseUrl: string;
  skill: string;
  preset: string;
  strict: boolean;
  exportSuggestedPolicy: boolean;
  taskJson: string;
  policyYaml: string;
};

export type HistoryEntry = {
  timestamp: string;
  httpStatus: number | string;
  requestId: string;
  durationMs: number;
  baseUrl: string;
};

const SETTINGS_KEY = "docops.web.settings.v2";
const LEGACY_SETTINGS_KEY = "docops.web.settings.v1";
const HISTORY_KEY = "docops.web.history.v1";

function migrateLegacySettings(defaults: ConsoleSettings): ConsoleSettings {
  const raw = localStorage.getItem(LEGACY_SETTINGS_KEY);
  if (!raw) {
    return defaults;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<ConsoleSettings>;
    return {
      apiBaseUrl: typeof parsed.apiBaseUrl === "string" ? parsed.apiBaseUrl : defaults.apiBaseUrl,
      skill: typeof parsed.skill === "string" ? parsed.skill : defaults.skill,
      preset: typeof parsed.preset === "string" ? parsed.preset : defaults.preset,
      strict: typeof parsed.strict === "boolean" ? parsed.strict : defaults.strict,
      exportSuggestedPolicy:
        typeof parsed.exportSuggestedPolicy === "boolean"
          ? parsed.exportSuggestedPolicy
          : defaults.exportSuggestedPolicy,
      // Do not migrate old taskJson to avoid keeping stale extra fields.
      taskJson: defaults.taskJson,
      policyYaml: typeof parsed.policyYaml === "string" ? parsed.policyYaml : defaults.policyYaml,
    };
  } catch {
    return defaults;
  }
}

export function loadSettings(defaults: ConsoleSettings): ConsoleSettings {
  const raw = localStorage.getItem(SETTINGS_KEY);
  if (!raw) {
    const migrated = migrateLegacySettings(defaults);
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(migrated));
    return migrated;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<ConsoleSettings>;
    return {
      apiBaseUrl: typeof parsed.apiBaseUrl === "string" ? parsed.apiBaseUrl : defaults.apiBaseUrl,
      skill: typeof parsed.skill === "string" ? parsed.skill : defaults.skill,
      preset: typeof parsed.preset === "string" ? parsed.preset : defaults.preset,
      strict: typeof parsed.strict === "boolean" ? parsed.strict : defaults.strict,
      exportSuggestedPolicy:
        typeof parsed.exportSuggestedPolicy === "boolean"
          ? parsed.exportSuggestedPolicy
          : defaults.exportSuggestedPolicy,
      taskJson: typeof parsed.taskJson === "string" ? parsed.taskJson : defaults.taskJson,
      policyYaml: typeof parsed.policyYaml === "string" ? parsed.policyYaml : defaults.policyYaml,
    };
  } catch {
    return defaults;
  }
}

export function saveSettings(settings: ConsoleSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export function loadHistory(): HistoryEntry[] {
  const raw = localStorage.getItem(HISTORY_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((entry) => entry && typeof entry === "object") as HistoryEntry[];
  } catch {
    return [];
  }
}

export function saveHistory(entries: HistoryEntry[]): void {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
}
