export type SkillName = "meeting_notice" | "training_notice" | "inspection_record";

export type FieldKind = "text" | "textarea" | "date" | "time" | "list";

export type FieldSpec = {
  key: string;
  label: string;
  required: boolean;
  kind: FieldKind;
  placeholder?: string;
  help?: string;
};

export type SkillFormSpec = {
  skill: SkillName;
  displayName: string;
  fields: FieldSpec[];
  requiredKeys: readonly string[];
  examplePayload: Record<string, unknown>;
};

const meetingNoticeSpec: SkillFormSpec = {
  skill: "meeting_notice",
  displayName: "会议通知",
  fields: [
    { key: "meeting_title", label: "会议主题", required: true, kind: "text", placeholder: "例如：XX项目安全例会" },
    { key: "meeting_date", label: "会议日期", required: true, kind: "date", help: "格式：YYYY-MM-DD" },
    { key: "meeting_time", label: "会议时间", required: true, kind: "time", placeholder: "例如：14:00-15:30" },
    { key: "meeting_location", label: "会议地点", required: true, kind: "text", placeholder: "例如：会议室 B（2F）" },
    { key: "organizer", label: "组织单位", required: true, kind: "text", placeholder: "例如：工程管理部" },
    { key: "attendees", label: "参会人员", required: false, kind: "list", placeholder: "每行一个姓名，或用逗号分隔", help: "支持换行或逗号分隔。" },
  ],
  requiredKeys: ["meeting_title", "meeting_date", "meeting_time", "meeting_location", "organizer"],
  examplePayload: {
    meeting_title: "XX 项目安全例会（演示）",
    meeting_date: "2026-02-20",
    meeting_time: "14:00-15:30",
    meeting_location: "会议室 B（2F）",
    organizer: "工程管理部",
    attendees: ["张三", "李四", "王五", "赵六"],
  },
};

const trainingNoticeSpec: SkillFormSpec = {
  skill: "training_notice",
  displayName: "培训通知",
  fields: [
    { key: "training_title", label: "培训主题", required: true, kind: "text", placeholder: "例如：消防安全培训通知" },
    { key: "training_date", label: "培训日期", required: true, kind: "date", help: "格式：YYYY-MM-DD" },
    { key: "training_time", label: "培训时间", required: true, kind: "time", placeholder: "例如：09:30-11:00" },
    { key: "training_location", label: "培训地点", required: true, kind: "text", placeholder: "例如：一楼报告厅" },
    { key: "trainer", label: "讲师", required: true, kind: "text", placeholder: "例如：王老师" },
    { key: "organizer", label: "主办单位", required: false, kind: "text", placeholder: "例如：人事部" },
    { key: "attendees", label: "参加对象", required: false, kind: "list", placeholder: "每行一个部门/人员", help: "支持换行或逗号分隔。" },
  ],
  requiredKeys: ["training_title", "training_date", "training_time", "training_location", "trainer"],
  examplePayload: {
    training_title: "消防安全培训通知",
    training_date: "2026-02-21",
    training_time: "09:30-11:00",
    training_location: "一楼报告厅",
    trainer: "王老师",
    organizer: "人事部",
    attendees: ["生产部", "工程部", "行政部"],
  },
};

const inspectionRecordSpec: SkillFormSpec = {
  skill: "inspection_record",
  displayName: "检查记录",
  fields: [
    { key: "inspection_subject", label: "检查主题", required: true, kind: "text", placeholder: "例如：消防通道巡检记录" },
    { key: "inspection_date", label: "检查日期", required: true, kind: "date", help: "格式：YYYY-MM-DD" },
    { key: "inspector", label: "检查人", required: true, kind: "text", placeholder: "例如：张三" },
    { key: "department", label: "责任部门", required: false, kind: "text", placeholder: "例如：工程管理部" },
    { key: "issue_summary", label: "问题概述", required: true, kind: "textarea", placeholder: "描述发现的问题" },
    { key: "action_required", label: "整改要求", required: false, kind: "textarea", placeholder: "描述整改动作和标准" },
    { key: "deadline", label: "整改期限", required: false, kind: "text", placeholder: "例如：2026-02-22 18:00" },
  ],
  requiredKeys: ["inspection_subject", "inspection_date", "inspector", "issue_summary"],
  examplePayload: {
    inspection_subject: "消防通道巡检记录",
    inspection_date: "2026-02-22",
    inspector: "张三",
    department: "工程管理部",
    issue_summary: "2号楼通道堆放杂物，存在阻塞风险",
    action_required: "当日18:00前完成清理并拍照回传",
    deadline: "2026-02-22 18:00",
  },
};

export const SKILL_FORM_SPECS: Record<SkillName, SkillFormSpec> = {
  meeting_notice: meetingNoticeSpec,
  training_notice: trainingNoticeSpec,
  inspection_record: inspectionRecordSpec,
};

export const DEFAULT_SKILL: SkillName = "meeting_notice";

export function isKnownSkill(value: string): value is SkillName {
  return value === "meeting_notice" || value === "training_notice" || value === "inspection_record";
}

export function getSkillSpec(skill: string): SkillFormSpec | null {
  if (!isKnownSkill(skill)) {
    return null;
  }
  return SKILL_FORM_SPECS[skill];
}

export function skillLabel(skill: string): string {
  const spec = getSkillSpec(skill);
  return spec ? spec.displayName : skill;
}

export function defaultFormValues(skill: string): Record<string, string> {
  const spec = getSkillSpec(skill);
  if (!spec) {
    return {};
  }

  const formValues: Record<string, string> = {};
  for (const field of spec.fields) {
    const value = spec.examplePayload[field.key];
    if (Array.isArray(value)) {
      formValues[field.key] = value.join("\n");
    } else if (value == null) {
      formValues[field.key] = "";
    } else {
      formValues[field.key] = String(value);
    }
  }
  return formValues;
}

export function allSkillSpecs(): SkillFormSpec[] {
  return [meetingNoticeSpec, trainingNoticeSpec, inspectionRecordSpec];
}
