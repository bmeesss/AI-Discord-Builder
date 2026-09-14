"""Local machine and runtime detection for the optional local-AI setup.

Detection is read-only.  It never installs software, starts processes, or
changes configuration.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    os_name: str
    os_version: str
    architecture: str
    cpu_count: int | None
    ram_gb: float | None
    free_disk_gb: float | None
    gpu_name: str | None
    docker_installed: bool
    docker_running: bool
    docker_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def detect_hardware(path: str | Path = ".") -> HardwareInfo:
    """Collect conservative, best-effort host information."""

    system = platform.system().lower()
    os_name = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
    }.get(system, system or "unknown")

    docker_installed, docker_running, docker_version = detect_docker()

    return HardwareInfo(
        os_name=os_name,
        os_version=platform.version(),
        architecture=platform.machine() or "unknown",
        cpu_count=os.cpu_count(),
        ram_gb=detect_ram_gb(),
        free_disk_gb=detect_free_disk_gb(path),
        gpu_name=detect_gpu_name(),
        docker_installed=docker_installed,
        docker_running=docker_running,
        docker_version=docker_version,
    )


def detect_ram_gb() -> float | None:
    """Return physical RAM when it can be read reliably enough."""

    system = platform.system().lower()

    if system == "linux":
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kib = int(line.split()[1])
                    return round(kib / 1024 / 1024, 2)
        except (OSError, ValueError, IndexError):
            return None

    if system == "windows":
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullTotalPhys / 1024 / 1024 / 1024, 2)
        except (AttributeError, OSError, TypeError):
            return None

    # macOS and unusual environments intentionally return unknown unless an
    # optional psutil installation is already available.
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 2)
    except (ImportError, AttributeError, OSError):
        return None


def detect_free_disk_gb(path: str | Path = ".") -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return round(usage.free / 1024 / 1024 / 1024, 2)


def detect_gpu_name(
    runner: Callable[[Sequence[str], int], CommandResult] | None = None,
) -> str | None:
    """Detect a GPU only when a vendor tool gives a clear answer.

    No inference is made from CPU model names or environment variables.  An
    unknown GPU is represented as ``None`` and callers must choose conservatively.
    """

    run = runner or _run_command

    if shutil.which("nvidia-smi"):
        result = run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            3,
        )
        name = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
        if result.returncode == 0 and name:
            return name

    if shutil.which("rocm-smi"):
        result = run(["rocm-smi", "--showproductname"], 3)
        name = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
        if result.returncode == 0 and name:
            return name

    return None


def detect_docker(
    runner: Callable[[Sequence[str], int], CommandResult] | None = None,
) -> tuple[bool, bool, str | None]:
    """Return ``(installed, running, version)`` for Docker."""

    executable = shutil.which("docker")
    if not executable:
        return False, False, None

    run = runner or _run_command
    version_result = run(
        ["docker", "version", "--format", "{{.Client.Version}}"],
        5,
    )
    # The Docker CLI can be installed while the daemon is stopped.  Keep those
    # states separate instead of reporting "not installed" for a daemon error.
    installed = True
    version = version_result.stdout.strip() or None

    info_result = run(["docker", "info", "--format", "{{.ServerVersion}}"], 5)
    running = info_result.returncode == 0
    if not version and info_result.stdout.strip():
        version = info_result.stdout.strip()

    return installed, running, version


def _run_command(command: Sequence[str], timeout: int) -> CommandResult:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(returncode=1, stdout="", stderr=str(exc))

    return CommandResult(
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )
