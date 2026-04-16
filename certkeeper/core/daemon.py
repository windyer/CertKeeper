"""守护进程管理：PID 文件与后台进程启动。"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DaemonResult:
    success: bool
    message: str


def pid_file_path(config_path: Path) -> Path:
    """PID 文件路径，放在配置文件同级 data 目录下。"""
    return config_path.parent / "data" / "certkeeper.pid"


def read_pid(pid_path: Path) -> int | None:
    """读取 PID 文件中的进程号。"""
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None


def write_pid(pid_path: Path) -> None:
    """将当前进程 PID 写入文件。"""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))


def remove_pid(pid_path: Path) -> None:
    """删除 PID 文件。"""
    if pid_path.exists():
        pid_path.unlink()


def is_process_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否仍在运行。"""
    if sys.platform == "win32":
        # Windows 上 os.kill(pid, 0) 对 detached 进程不可靠，使用原生 API
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _log_file_path(config_path: Path) -> Path:
    """守护进程日志文件路径。"""
    return config_path.parent / "data" / "certkeeper-daemon.log"


def spawn_daemon(python_executable: str, config_path: Path, pid_path: Path) -> DaemonResult:
    """以后台守护进程方式启动 CertKeeper。"""

    existing_pid = read_pid(pid_path)
    if existing_pid is not None and is_process_alive(existing_pid):
        return DaemonResult(False, f"CertKeeper 已在运行中（PID: {existing_pid}）。")

    # 清理过期的 PID 文件
    remove_pid(pid_path)

    # 使用绝对路径，避免子进程工作目录不同导致找不到配置文件
    abs_config = config_path.resolve()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = _log_file_path(config_path)

    cmd = [
        python_executable, "-m", "certkeeper.cli",
        "--config", str(abs_config),
        "start", "--_serve",
    ]

    if sys.platform == "win32":
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        with open(log_file, "a", encoding="utf-8") as log_fh:
            subprocess.Popen(
                cmd,
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                close_fds=True,
                stdout=log_fh,
                stderr=log_fh,
            )
    else:
        with open(log_file, "a", encoding="utf-8") as log_fh:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=log_fh,
                stderr=log_fh,
            )

    return DaemonResult(True, f"CertKeeper 守护进程已启动。日志: {log_file}")


def stop_daemon(pid_path: Path) -> DaemonResult:
    """停止守护进程。"""

    pid = read_pid(pid_path)
    if pid is None:
        return DaemonResult(False, "CertKeeper 未在运行（找不到 PID 文件）。")

    if not is_process_alive(pid):
        remove_pid(pid_path)
        return DaemonResult(False, "CertKeeper 未在运行（进程已退出）。")

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    remove_pid(pid_path)
    return DaemonResult(True, f"CertKeeper 已停止（PID: {pid}）。")


def daemon_status(pid_path: Path) -> DaemonResult:
    """查看守护进程状态。"""

    pid = read_pid(pid_path)
    if pid is None:
        return DaemonResult(False, "CertKeeper 未在运行。")

    if is_process_alive(pid):
        return DaemonResult(True, f"CertKeeper 正在运行（PID: {pid}）。")

    remove_pid(pid_path)
    return DaemonResult(False, "CertKeeper 未在运行（进程已退出）。")
