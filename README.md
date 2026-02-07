# docops-agent

Document Ops Agent MVP（无 LLM）。

## 开发者约束/门禁
请严格遵守 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) 中的硬约束与可持续开发规则。

## 开发/本地运行
1. 安装依赖：`poetry install`
2. 质量门禁：`poetry run ruff check .`、`poetry run mypy .`、`poetry run pytest`

## CLI
运行单次生成：
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out`

覆盖控制：
`--force` 覆盖已有输出（默认行为，若覆盖会打印 INFO）。
`--no-overwrite` 禁止覆盖，若输出已存在则返回退出码 `1`。
`--debug-dump` 输出 `out.debug.json`，用于定位可疑符号/字体来源。

固定输出四件套（`--out-dir` 下）：
`out.docx`
`out.replace_log.json`
`out.missing_fields.json`
`out.format_report.json`

可选调试输出：
`out.debug.json`

退出码：
`0` 成功
`2` 缺必填字段
`3` 模板不支持（如跨 run 占位符）
`4` 格式验收失败
`1` 其他错误
