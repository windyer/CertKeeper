"""调度器与服务命令相关辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from certkeeper.config import SchedulerConfig


@dataclass(slots=True)
class ServiceCommandPlan:
    platform: str
    action: str
    command: list[str]


def build_service_command(
    *,
    action: str,
    service_name: str,
    python_executable: str,
    config_path: str | Path,
    platform_name: str,
) -> ServiceCommandPlan:
    config_arg = str(config_path)
    if platform_name.lower().startswith("win"):
        if action == "install":
            executable = f'"{python_executable}"'
            command_line = f'{executable} -m certkeeper.cli --config "{config_arg}" daemon'
            command = [
                "sc.exe",
                "create",
                service_name,
                f'binPath= "{command_line}"',
            ]
        else:
            command = ["sc.exe", "delete", service_name]
        return ServiceCommandPlan(platform="Windows", action=action, command=command)

    if action == "install":
        command = ["systemctl", "--user", "enable", "--now", f"{service_name}.service"]
    else:
        command = ["systemctl", "--user", "disable", "--now", f"{service_name}.service"]
    return ServiceCommandPlan(platform="Linux", action=action, command=command)


class SchedulerRuntime:
    """根据应用配置构建后台调度器。"""

    def __init__(self, config: SchedulerConfig) -> None:
        self.config = config
        self.scheduler = BackgroundScheduler()

    def configure(self, job_callable) -> BackgroundScheduler:
        if not self.config.enabled:
            return self.scheduler

        if self.config.interval == "daily":
            hour_text, minute_text = self.config.time.split(":", maxsplit=1)
            trigger = CronTrigger(hour=int(hour_text), minute=int(minute_text))
        else:
            trigger = IntervalTrigger(days=1)

        self.scheduler.add_job(job_callable, trigger=trigger, id="certkeeper-apply", replace_existing=True)
        return self.scheduler
