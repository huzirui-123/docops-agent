# Contributing

本文档定义 docops-agent 的硬约束与可持续开发规则。所有后续任务卡必须遵守。

## 硬约束（必须）
1. 占位符格式唯一：【FIELD_NAME】，FIELD_NAME 仅允许 A-Z0-9_。
2. 替换仅支持“同一 run 内完整出现”的占位符；跨 run 一律 unsupported，必须报 TemplateError，并写 replace_log。
3. 不新增段落、不插表格、不启用自动编号；不得生成项目符号/自动编号。发现 w:numPr 必须报错或安全修复。
4. 输出四件套：out.docx + out.replace_log.json + out.missing_fields.json + out.format_report.json。
5. CLI 退出码：0 成功；2 缺必填字段；3 模板不支持（跨 run 等）；4 格式验收失败；其它 1。
6. 质量门禁：每张卡必须执行并通过 `poetry run ruff check . && poetry run mypy . && poetry run pytest` 才允许 commit。
7. core/ 纯逻辑层不得依赖 fastapi/typer；apps/ 只做入口。
8. 不允许为了“凑过测试”而删测试/放宽规则/降低校验。
9. 孤立 】 / 未闭合 【 只在 strict=True 才抛错；strict=False 只记录 unsupported 并继续解析。
10. numPr 仅检查/清理直接 pPr.numPr，不追溯样式继承。
11. 当 forbid_tables=true 时，validator 仅记录 TABLE_FORBIDDEN 且跳过 table cell 其它校验；fixer 不尝试修复 tables。
12. policy 中字体值必须是可写入 docx 的真实字体名；如存在历史 BUSINESS_DEFAULT_* 代号，必须在 policy loader 解析为真实字体后再进入 fixer/validator。

## 可持续开发强制规则（必须）
1. 任何对 docx XML 的操作必须封装在 core/utils/docx_xml.py。
2. 替换触碰点必须记录（touched_runs 或 run_id 级标记）。后续 validator/fixer 只能基于触碰点对“被替换 run”做字体/字号等强制修改；不得全局乱改。
