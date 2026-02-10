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
`--preset` 预设运行模式（`quick|template|strict`，默认 `quick`，推荐入口）。
`--format-mode` 控制格式验收语义（`report|strict|off`，默认 `report`）。
`--format-baseline` 控制验收基线（`template|policy`，默认 `template`）。
`--format-fix-mode` 控制格式修复策略（`none|safe`，默认 `safe`；仅在非 off 模式生效）。
`--format-report` 控制终端格式摘要输出（`human|json|both`，默认 `human`）。
`--export-suggested-policy PATH` 导出建议策略 YAML（可用于后续 policy 调优）。

`report`：产出文档与报告，格式问题只告警不拦截。  
`strict`：格式不通过则返回退出码 `4`。  
`off`：跳过格式修复与验收，保留模板风格。

`template`：按模板本来样子验收（模板有表格则允许，缩进按模板主流值）。  
`policy`：按 `policy.yaml` 进行严格验收。
`none`：只报告不修复，尽量保留模板格式。  
`safe`：仅做段落级轻修复（首行缩进/行距），不改文本/字体/表格结构。  
`off` 模式下总是跳过 fix 与 validate。
`human`：终端打印可读格式摘要。  
`json`：终端不打印格式摘要，并抑制 WARNING（仍写四件套 JSON）。  
`both`：打印可读摘要并保留现有 WARNING 行。
human 摘要在 run 结束（四件套写盘后）统一打印一次。
`WARNING(format)` 仅表示存在 `error` 级格式问题；`warn` 级问题只在 human 摘要与 JSON 报告中展示。

`quick`：`report + template baseline + safe fix + human summary`。  
`template`：`report + template baseline + no fix + human summary`。  
`strict`：`strict + policy baseline + safe fix + human summary`。
`preset` 与高级参数（`--format-mode/--format-baseline/--format-fix-mode/--format-report`）不可混用。

`out.format_report.json` 的 `summary` 包含：
`template_observed` / `rendered_observed` / `diff` / `baseline` / `effective_policy_overrides` / `diagnostics`。
其中 `diagnostics` 在 `report` 与 `strict` 模式下提供按 issue code 聚合的定位示例与建议。

固定输出四件套（`--out-dir` 下）：
`out.docx`
`out.replace_log.json`
`out.missing_fields.json`
`out.format_report.json`

可选调试输出：
`out.debug.json`

示例：
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset quick`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset template`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset strict`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode strict --format-baseline policy`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode strict --format-baseline policy --format-fix-mode none`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-report json`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode off`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --export-suggested-policy ./suggested_policy.yaml`

## API
启动（示例）：
`poetry run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`

健康检查：
`curl -s http://127.0.0.1:8000/healthz`

quick 运行（默认静默，返回 zip）：
```bash
curl -sS -X POST "http://127.0.0.1:8000/v1/run" \
  -F "template=@./template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "task=@./task.json;type=application/json" \
  -F "skill=meeting_notice" \
  -o result.zip -D headers.txt
```

strict 运行并读取 exit_code：
```bash
curl -sS -X POST "http://127.0.0.1:8000/v1/run" \
  -F "template=@./template.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "task=@./task.json;type=application/json" \
  -F "skill=meeting_notice" \
  -F "preset=strict" \
  -o result.zip -D headers.txt
grep -i "X-Docops-Exit-Code" headers.txt
```

API 返回说明：
`200` 返回 zip，响应头 `X-Docops-Exit-Code` 表示执行结果（`0/2/3/4`）。
`strict` 格式失败时仍返回 zip（`X-Docops-Exit-Code: 4`）。
zip 固定包含：
`out.docx`
`out.replace_log.json`
`out.missing_fields.json`
`out.format_report.json`
`api_result.json`
可选包含：
`out.suggested_policy.yaml`

API 默认静默：默认 `format_report=json`，不输出 human 摘要/WARNING 到服务日志。
统一错误体：
`{"error_code":"...","message":"...","detail":{...}}`

默认限制：
上传大小 `25MB`（环境变量：`DOCOPS_MAX_UPLOAD_BYTES`）
请求超时 `60s`（环境变量：`DOCOPS_REQUEST_TIMEOUT_SECONDS`）
超时会终止执行子进程，不会在后台继续运行。

退出码：
`0` 成功
`2` 缺必填字段
`3` 模板不支持（如跨 run 占位符）
`4` 格式验收失败
`1` 其他错误
