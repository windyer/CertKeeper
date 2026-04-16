from __future__ import annotations

from certkeeper.config import SchedulerConfig
from certkeeper.core.scheduler import SchedulerRuntime, build_service_command


def test_build_service_command_for_windows_install() -> None:
    plan = build_service_command(
        action="install",
        service_name="CertKeeper",
        python_executable="python",
        config_path="certkeeper.yaml",
        platform_name="Windows",
    )

    assert plan.platform == "Windows"
    assert plan.command[:3] == ["sc.exe", "create", "CertKeeper"]
    assert plan.command[3].startswith('binPath= "')
    assert "certkeeper.cli" in plan.command[3]
    assert "certkeeper.yaml" in plan.command[3]


def test_scheduler_runtime_adds_job_for_daily_schedule() -> None:
    runtime = SchedulerRuntime(SchedulerConfig(enabled=True, interval="daily", time="03:15"))

    scheduler = runtime.configure(lambda: None)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].trigger.fields[5].expressions[0].first == 3
    assert jobs[0].trigger.fields[6].expressions[0].first == 15
