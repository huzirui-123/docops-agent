"""Typer CLI entrypoint for docops-agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from docx import Document

from apps.cli.io import (
    OutputPaths,
    build_output_paths,
    existing_output_files,
    write_fallback_json_atomic,
    write_render_output_atomic,
)
from core.format.policy_loader import load_policy
from core.orchestrator.pipeline import run_task
from core.render.models import RenderOutput
from core.skills.base import Skill
from core.skills.meeting_notice import MeetingNoticeSkill
from core.skills.models import TaskSpec
from core.utils.errors import MissingRequiredFieldsError, TemplateError

app = typer.Typer(help="Document Ops Agent CLI", rich_markup_mode=None)
UnsupportedMode = Literal["error", "warn"]


@app.callback()
def cli_callback() -> None:
    """CLI root callback to keep `docops run` as explicit command form."""


@app.command("run")
def run_command(
    template: Annotated[Path, typer.Option(..., exists=True, dir_okay=False, file_okay=True)],
    task: Annotated[Path, typer.Option(..., exists=True, dir_okay=False, file_okay=True)],
    skill: Annotated[str, typer.Option(...)],
    out_dir: Annotated[Path, typer.Option()] = Path("."),
    policy: Annotated[Path | None, typer.Option()] = None,
    unsupported_mode: Annotated[str, typer.Option()] = "error",
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite outputs when they already exist.")
    ] = False,
    no_overwrite: Annotated[
        bool,
        typer.Option(
            "--no-overwrite",
            help="Fail when outputs already exist.",
        ),
    ] = False,
) -> None:
    """Execute one document generation run and write fixed output artifacts."""

    paths = build_output_paths(out_dir)
    explicit_overwrite = True
    normalized_mode = unsupported_mode.lower().strip()
    if normalized_mode not in {"error", "warn"}:
        typer.echo("ERROR: --unsupported-mode must be one of: error, warn.")
        _safe_write_exit1_fallback(
            paths,
            "ArgumentValidationError",
            "invalid unsupported_mode",
            "args",
        )
        raise typer.Exit(code=1)
    unsupported_mode_typed = cast(UnsupportedMode, normalized_mode)

    if force and no_overwrite:
        typer.echo("ERROR: --force and --no-overwrite cannot be used together.")
        _safe_write_exit1_fallback(paths, "ArgumentConflict", "conflicting overwrite flags", "args")
        raise typer.Exit(code=1)

    if no_overwrite:
        explicit_overwrite = False
    elif force:
        explicit_overwrite = True

    existing = existing_output_files(paths)
    if existing and explicit_overwrite:
        names = ", ".join(path.name for path in existing)
        typer.echo(f"INFO: overwriting existing outputs: {names}")

    if existing and not explicit_overwrite:
        typer.echo("ERROR: outputs already exist and --no-overwrite is enabled.")
        _safe_write_exit1_fallback(
            paths,
            "OverwriteDisabled",
            "output files already exist",
            "precheck",
        )
        raise typer.Exit(code=1)

    output: RenderOutput | None = None
    exit_code = 1
    reason = "unexpected error"
    generic_error: Exception | None = None
    failure_stage = "unknown"

    try:
        failure_stage = "load_task"
        task_spec = _load_task_spec(task)
        failure_stage = "resolve_skill"
        selected_skill = _resolve_skill(skill)
        failure_stage = "load_policy"
        policy_model = load_policy(policy)
        failure_stage = "load_template"
        document = Document(str(template))
        failure_stage = "pipeline"

        output = run_task(
            task_spec=task_spec,
            template_document=document,
            skill=selected_skill,
            policy=policy_model,
            unsupported_mode=unsupported_mode_typed,
        )

        if output.replace_report.summary.had_unsupported and unsupported_mode_typed == "warn":
            typer.echo(
                "WARNING: unsupported placeholders detected "
                f"(count={output.replace_report.summary.unsupported_count}, mode=warn)."
            )

        if not output.format_report.passed:
            exit_code = 4
            reason = "format validation failed"
        else:
            exit_code = 0
            reason = "success"

    except TemplateError as exc:
        output = exc.render_output
        exit_code = 3
        reason = "template unsupported placeholders"
        typer.echo(f"ERROR: {reason}")
    except MissingRequiredFieldsError as exc:
        output = exc.render_output
        exit_code = 2
        reason = "missing required fields"
        typer.echo(f"ERROR: {reason}")
        if (
            output is not None
            and output.replace_report.summary.had_unsupported
            and unsupported_mode_typed == "warn"
        ):
            typer.echo(
                "WARNING: unsupported placeholders detected "
                f"(count={output.replace_report.summary.unsupported_count}, mode=warn)."
            )
    except Exception as exc:  # noqa: BLE001
        generic_error = exc
        exit_code = 1
        reason = "internal error"
        typer.echo(f"ERROR: {type(exc).__name__}: {exc}")

    docx_write_error: str | None = None

    if output is not None:
        try:
            write_render_output_atomic(paths, output)
        except Exception as write_exc:  # noqa: BLE001
            docx_write_error = str(write_exc)
            exit_code = 1
            reason = "write output failed"
            typer.echo(f"ERROR: {reason}: {docx_write_error}")
            _safe_write_exit1_fallback(
                paths,
                error_type=type(write_exc).__name__,
                error_message=str(write_exc),
                stage="write_docx",
                docx_write_error=docx_write_error,
                base_output=output,
            )
    else:
        error_type = type(generic_error).__name__ if generic_error is not None else "UnknownError"
        error_message = str(generic_error) if generic_error is not None else reason
        _safe_write_exit1_fallback(
            paths,
            error_type=error_type,
            error_message=error_message,
            stage=failure_stage,
            docx_write_error=docx_write_error,
        )

    if exit_code == 0:
        typer.echo("INFO: success")
    elif exit_code == 4:
        typer.echo("ERROR: format validation failed")

    raise typer.Exit(code=exit_code)


def _load_task_spec(path: Path) -> TaskSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Task JSON must be an object")
    return TaskSpec.model_validate(raw)


def _resolve_skill(skill_name: str) -> Skill:
    if skill_name == "meeting_notice":
        return MeetingNoticeSkill()
    raise ValueError(f"Unsupported skill: {skill_name}")


def _safe_write_exit1_fallback(
    paths: OutputPaths,
    error_type: str,
    error_message: str,
    stage: str,
    docx_write_error: str | None = None,
    base_output: RenderOutput | None = None,
) -> None:
    try:
        write_fallback_json_atomic(
            paths,
            error_type=error_type,
            error_message=error_message,
            stage=stage,
            docx_write_error=docx_write_error,
            base_output=base_output,
        )
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    """Poetry script entrypoint."""

    app()


if __name__ == "__main__":
    main()
