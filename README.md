# docops-agent

Document Ops Agent MVP（无 LLM）。

## 开发者约束/门禁
请严格遵守 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) 中的硬约束与可持续开发规则。

## 开发/本地运行
1. 安装依赖：`poetry install`
2. 质量门禁：`poetry run ruff check .`、`poetry run mypy .`、`poetry run pytest`

## 部署
部署与运行形态说明见：`docs/DEPLOYMENT.md`

## CLI
运行单次生成：
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out`

当前支持的 skill：
`meeting_notice`
`training_notice`
`inspection_record`

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
`poetry run docops run --template ./template.docx --task ./task.json --skill training_notice --out-dir ./out`
`poetry run docops run --template ./template.docx --task ./task.json --skill inspection_record --out-dir ./out`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset quick`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset template`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --preset strict`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode strict --format-baseline policy`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode strict --format-baseline policy --format-fix-mode none`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-report json`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --format-mode off`
`poetry run docops run --template ./template.docx --task ./task.json --skill meeting_notice --out-dir ./out --export-suggested-policy ./suggested_policy.yaml`

最小 task.json 示例：

`meeting_notice`
```json
{"task_type":"meeting_notice","payload":{"meeting_title":"周例会"}}
```

`training_notice`
```json
{"task_type":"training_notice","payload":{"training_title":"安全培训"}}
```

`inspection_record`
```json
{"task_type":"inspection_record","payload":{"inspection_subject":"工地A"}}
```

## API
启动（示例）：
`poetry run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`
生产示例：
`poetry run gunicorn -k uvicorn.workers.UvicornWorker -w 2 apps.api.main:app`

健康检查：
`curl -s http://127.0.0.1:8000/healthz`

元数据（前端自举）：
`curl -s http://127.0.0.1:8000/v1/meta`

内置 Web 控制台：
`http://127.0.0.1:8000/web`

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
所有响应都包含 `X-Docops-Request-Id`（可用于排障关联）。
`/v1/meta` 返回 `supported_skills`、`supported_task_types`、`supported_presets`、`task_payload_schemas`，前端应以该接口为准，不应硬编码。
`strict` 格式失败时仍返回 zip（`X-Docops-Exit-Code: 4`）。
`skill` 参数当前支持：`meeting_notice`、`training_notice`、`inspection_record`。
传入不支持 skill 会返回 `400`，并在 `detail.supported_skills` 给出可用列表。
若 `skill` 与 `task.json` 的 `task_type` 不一致，会返回 `400 INVALID_ARGUMENT_CONFLICT`。
`strict` 是独立开关语义（仅强制 `format_mode=strict`），不等价于 preset 映射。
`strict` 不可与显式 `format_mode/format_baseline/format_fix_mode/format_report` 混用，混用返回 `400 INVALID_ARGUMENT_CONFLICT`。
zip 固定包含：
`out.docx`
`out.replace_log.json`
`out.missing_fields.json`
`out.format_report.json`
`api_result.json`
可选包含：
`out.suggested_policy.yaml`
`trace.json`（仅当 `DOCOPS_DEBUG_ARTIFACTS=1`）

API 默认静默：默认 `format_report=json`，不输出 human 摘要/WARNING 到服务日志。
zip 使用流式响应返回，避免一次性读入内存。
统一错误体：
`{"error_code":"...","message":"...","detail":{...}}`
所有响应（包括 404/405）都包含 `X-Docops-Request-Id`。

Web 控制台是内置调试/演示界面，不含鉴权。线上暴露前请通过反向代理增加鉴权与访问控制。

默认限制：
上传大小 `25MB`（环境变量：`DOCOPS_MAX_UPLOAD_BYTES`）
请求超时 `60s`（环境变量：`DOCOPS_REQUEST_TIMEOUT_SECONDS`）
超时会终止执行子进程，不会在后台继续运行。
进程内并发上限 `2`（环境变量：`DOCOPS_MAX_CONCURRENCY`）
并发等待超时 `0s`（环境变量：`DOCOPS_QUEUE_TIMEOUT_SECONDS`，`0` 表示立即拒绝并返回 `429`）
开启 `DOCOPS_DEBUG_ARTIFACTS=1` 时，zip 内会额外包含 `trace.json`。
调试入口开关：
`DOCOPS_ENABLE_WEB_CONSOLE`（默认 `1`）
`DOCOPS_ENABLE_META`（默认 `1`）
可选基础鉴权：
`DOCOPS_WEB_BASIC_AUTH="user:pass"`（作用于 `/web` 与 `/v1/meta`）

本地压测（需先启动真实服务，不使用 ASGITransport）：
`python scripts/load_test.py --base-url http://127.0.0.1:8000 --concurrency 8 --requests 20 --skill meeting_notice`
检测超时后是否存在子进程残留：
`python scripts/load_test.py --base-url http://127.0.0.1:8000 --concurrency 8 --requests 20 --check-subprocess-leaks --leak-grace-ms 1500 --tmp-root /tmp --write-summary /tmp/docops-load-summary.json --fail-on-leaks`
查看 tmp 水位：
`python scripts/check_tmp_watermark.py --root /tmp --json`
汇总结构化日志：
`python scripts/summarize_logs.py --json /var/log/docops-api.log`
CI 稳定性 smoke（本地可复现）：
`poetry run python scripts/ci_smoke.py --port 0 --repeat 3 --repeat-warmup 1 --requests 20 --concurrency 6 --skill meeting_notice --artifacts-dir artifacts`
详细说明与阈值配置见：`docs/DEPLOYMENT.md`
权威入口脚本路径：`scripts/ci_smoke.py`、`scripts/ci_thresholds.py`

`api_result.json` 新增：
- `request_id`
- `timing.total_ms`
- `timing.subprocess_ms`
- `timing.zip_ms`
- `timing.queue_wait_ms`

结构化日志补充：
- `event=done` 包含 `outcome`（`ok/missing_required/strict_failed/other_exit_code`）与 `http_status=200`
- `event=error` 包含 `outcome`（`bad_request/timeout/payload_too_large/rate_limited/internal_error`）
- `scripts/summarize_logs.py` 可聚合 `outcome_counts/http_status_counts` 与 `p50/p95`（含坏行容错 `parse_errors`）

中间件 500 兜底：
- 若请求在未捕获异常下进入中间件 500 分支，会执行已注册临时资源的 best-effort 清理。

退出码：
`0` 成功
`2` 缺必填字段
`3` 模板不支持（如跨 run 占位符）
`4` 格式验收失败
`1` 其他错误
