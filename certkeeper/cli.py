"""CertKeeper 的命令行入口。"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import click
import uvicorn

from certkeeper.acme_client.account import AcmeAccountService
from certkeeper.config import load_config
from certkeeper.core.daemon import daemon_status, pid_file_path, spawn_daemon, stop_daemon, write_pid, remove_pid
from certkeeper.core.manager import ApplySummary
from certkeeper.core.scheduler import SchedulerRuntime, build_service_command
from certkeeper.exceptions import CertKeeperError, ConfigurationError
from certkeeper.runtime import build_runtime
from certkeeper.web.app import create_app


class Context:
    """在命令之间共享的 CLI 上下文。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group()
@click.option(
    "--config",
    "config_path",
    default="certkeeper.yaml",
    show_default=True,
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.pass_context
def main(ctx: click.Context, config_path: Path) -> None:
    """CertKeeper 证书生命周期管理命令行。"""

    ctx.obj = Context(config_path=config_path)


@main.command()
@pass_context
def init(context: Context) -> None:
    """生成示例配置文件。"""

    if context.config_path.exists():
        raise click.ClickException(f"Config already exists: {context.config_path}")

    sample = (
        "acme:\n"
        "  directory: https://acme-v02.api.letsencrypt.org/directory\n"
        "  email: admin@example.com\n"
        "  account_key: ./data/account.key\n\n"
        "scheduler:\n"
        "  enabled: true\n"
        "  interval: daily\n"
        "  time: \"03:00\"\n\n"
        "certificates: []\n"
    )
    context.config_path.write_text(sample, encoding="utf-8")
    click.echo(f"Sample config written to {context.config_path}")


@main.command()
@pass_context
def register(context: Context) -> None:
    """注册 ACME 账户。"""

    config = load_config(context.config_path)
    account_service = AcmeAccountService()
    account_key_path = account_service.ensure_account_key(_resolve_path(context.config_path, config.acme.account_key))
    click.echo(f"ACME account key ready at {account_key_path}")


@main.command()
@click.option("--force", is_flag=True, help="Force renewal for all configured certificates.")
@pass_context
def apply(context: Context, force: bool) -> None:
    """对已配置证书执行续期与部署。"""

    runtime = build_runtime(context.config_path)
    summary = runtime.manager.apply(force=force)
    _print_summary(summary)
    raise click.exceptions.Exit(summary.exit_code)


@main.command()
@click.argument("domain")
@pass_context
def renew(context: Context, domain: str) -> None:
    """续期指定证书。"""

    runtime = build_runtime(context.config_path)
    summary = runtime.manager.apply(force=True, domain=domain)
    _print_summary(summary)
    raise click.exceptions.Exit(summary.exit_code)


@main.command()
@click.argument("domain")
@pass_context
def deploy(context: Context, domain: str) -> None:
    """将现有证书部署到配置目标。"""

    runtime = build_runtime(context.config_path)
    summary = runtime.manager.deploy(domain=domain)
    _print_summary(summary)
    raise click.exceptions.Exit(summary.exit_code)


@main.command(name="list")
@pass_context
def list_command(context: Context) -> None:
    """列出配置中证书的状态。"""

    runtime = build_runtime(context.config_path)
    checks = runtime.manager.check_certificates()
    if not checks:
        click.echo("No certificates configured.")
        return

    for item in checks:
        expiry = item.status.days_until_expiry if item.status.days_until_expiry is not None else "unknown"
        click.echo(f"{item.domain}\t{item.reason}\texpires_in={expiry}")


@main.command()
@pass_context
def check(context: Context) -> None:
    """干跑即将到期的证书检查。"""

    runtime = build_runtime(context.config_path)
    checks = runtime.manager.check_certificates()
    if not checks:
        click.echo("No certificates configured.")
        return

    for item in checks:
        click.echo(f"{item.domain}\tneeds_renewal={item.needs_renewal}\treason={item.reason}")


@main.command()
@click.option("--install", is_flag=True, help="Install daemon as a service.")
@click.option("--uninstall", is_flag=True, help="Remove daemon service.")
@pass_context
def daemon(context: Context, install: bool, uninstall: bool) -> None:
    """运行或管理 CertKeeper 守护进程。"""

    if install and uninstall:
        raise click.ClickException("Use either --install or --uninstall, not both.")

    if install:
        plan = build_service_command(
            action="install",
            service_name="CertKeeper",
            python_executable=sys.executable,
            config_path=context.config_path,
            platform_name=platform.system(),
        )
        click.echo(f"Service install command: {' '.join(plan.command)}")
        return
    if uninstall:
        plan = build_service_command(
            action="uninstall",
            service_name="CertKeeper",
            python_executable=sys.executable,
            config_path=context.config_path,
            platform_name=platform.system(),
        )
        click.echo(f"Service uninstall command: {' '.join(plan.command)}")
        return

    app_runtime = build_runtime(context.config_path)

    def _daemon_job():
        app_runtime.manager.send_expiry_reminders()
        app_runtime.manager.apply()

    runtime = SchedulerRuntime(app_runtime.config.scheduler)
    scheduler = runtime.configure(_daemon_job)
    click.echo(f"Daemon configured with {len(scheduler.get_jobs())} scheduled job(s).")


@main.command()
@pass_context
def web(context: Context) -> None:
    """启动 Web UI 服务。"""

    runtime = build_runtime(context.config_path)
    app = create_app(context.config_path)
    uvicorn.run(app, host=runtime.config.web_ui.host, port=runtime.config.web_ui.port)


@main.command()
@click.option("--daemon", "run_as_daemon", is_flag=True, help="以守护进程模式启动（后台运行）。")
@click.option("--stop", "stop_running", is_flag=True, help="停止守护进程。")
@click.option("--status", "show_status", is_flag=True, help="查看守护进程状态。")
@click.option("--_serve", "_internal_serve", is_flag=True, hidden=True)
@pass_context
def start(
    context: Context,
    run_as_daemon: bool,
    stop_running: bool,
    show_status: bool,
    _internal_serve: bool,
) -> None:
    """一键启动：Web UI + 后台定时任务。"""

    pid_path = pid_file_path(context.config_path)

    # --status：查看守护进程状态
    if show_status:
        result = daemon_status(pid_path)
        click.echo(result.message)
        raise click.exceptions.Exit(0 if result.success else 1)

    # --stop：停止守护进程
    if stop_running:
        result = stop_daemon(pid_path)
        click.echo(result.message)
        raise click.exceptions.Exit(0 if result.success else 1)

    # --daemon：以后台守护进程方式启动
    if run_as_daemon:
        result = spawn_daemon(sys.executable, context.config_path, pid_path)
        click.echo(result.message)
        raise click.exceptions.Exit(0 if result.success else 1)

    # --_serve：由 spawn_daemon 启动的后台进程，运行服务并写 PID
    if _internal_serve:
        write_pid(pid_path)

    config = load_config(context.config_path)
    runtime = build_runtime(context.config_path)

    # 配置后台调度器：先发到期提醒，再执行续期+部署
    def _scheduled_job():
        runtime.manager.send_expiry_reminders()
        runtime.manager.apply()

    scheduler_runtime = SchedulerRuntime(config.scheduler)
    scheduler = scheduler_runtime.configure(_scheduled_job)

    if config.scheduler.enabled:
        scheduler.start()
        jobs = scheduler.get_jobs()
        click.echo(f"调度器已启动，共 {len(jobs)} 个定时任务。")
    else:
        click.echo("调度器未启用（scheduler.enabled = false）。")

    # 创建 FastAPI 应用，并将调度器挂载到 app.state
    app = create_app(context.config_path)
    app.state.scheduler = scheduler if config.scheduler.enabled else None
    host = config.web_ui.host
    port = config.web_ui.port
    click.echo(f"Web UI 启动于 http://{host}:{port}")

    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            click.echo("调度器已停止。")
        if _internal_serve:
            remove_pid(pid_path)


def _print_summary(summary: ApplySummary) -> None:
    for result in summary.results:
        status = "ok" if not result.errors else "failed"
        click.echo(
            f"{result.domain}\trenewed={result.renewed}\tdeployed={','.join(result.deployed_targets) or '-'}\tstatus={status}"
        )


def _resolve_path(config_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return config_path.parent / candidate


if __name__ == "__main__":
    try:
        main()
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc
    except CertKeeperError as exc:
        raise click.ClickException(str(exc)) from exc
