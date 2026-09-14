"""Explicit, platform-aware Ollama installation helpers.

No installer method runs unless ``approved=True`` is passed by the interactive
setup flow.  Detection and help output are always safe and read-only.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

OLLAMA_LINUX_INSTALL_URL = "https://ollama.com/install.sh"


@dataclass(frozen=True, slots=True)
class InstallResult:
    success: bool
    changed: bool
    platform: str
    message: str
    command: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["command"] = list(self.command)
        return value


class OllamaInstaller:
    """Install Ollama using an explicit, user-approved platform action."""

    def __init__(
        self,
        os_name: str | None = None,
        command_runner: Callable[[Sequence[str], int], tuple[int, str, str]] | None = None,
        script_downloader: Callable[[str, Path], None] | None = None,
    ) -> None:
        self.os_name = (os_name or platform.system()).lower()
        self._command_runner = command_runner or _run_command
        self._script_downloader = script_downloader or _download_script

    def available_method(self) -> str | None:
        if self.os_name == "linux":
            return "official Ollama Linux installer"
        if self.os_name == "windows" and shutil.which("winget"):
            return "Windows winget"
        if self.os_name in {"darwin", "macos"} and shutil.which("brew"):
            return "Homebrew"
        return None

    def install_ollama(self, approved: bool = False) -> InstallResult:
        if not approved:
            return InstallResult(
                success=False,
                changed=False,
                platform=self.os_name,
                message="Installation was not started because explicit approval was not given.",
            )

        if self.os_name == "linux":
            return self._install_linux()
        if self.os_name == "windows":
            return self._install_windows()
        if self.os_name in {"darwin", "macos"}:
            return self._install_macos()

        return InstallResult(
            success=False,
            changed=False,
            platform=self.os_name,
            message="Automatic Ollama installation is not implemented for this OS.",
        )

    def _install_linux(self) -> InstallResult:
        script_path: Path | None = None
        command = ("sh", str(Path("<temporary Ollama install script>")))
        try:
            with tempfile.NamedTemporaryFile(
                prefix="ollama-install-",
                suffix=".sh",
                delete=False,
            ) as temporary:
                script_path = Path(temporary.name)

            self._script_downloader(OLLAMA_LINUX_INSTALL_URL, script_path)
            result = self._command_runner(["sh", str(script_path)], 900)
            if result[0] != 0:
                return InstallResult(
                    success=False,
                    changed=False,
                    platform=self.os_name,
                    message=(
                        "The official Ollama installer exited unsuccessfully. "
                        "Check permissions and the installer output."
                    ),
                    command=("sh", "<temporary Ollama install script>"),
                )
            return InstallResult(
                success=True,
                changed=True,
                platform=self.os_name,
                message="Ollama was installed using the official Linux installer.",
                command=command,
            )
        except (OSError, TimeoutError) as exc:
            return InstallResult(
                success=False,
                changed=False,
                platform=self.os_name,
                message=f"Ollama installation could not be completed: {exc}",
                command=("sh", "<temporary Ollama install script>"),
            )
        finally:
            if script_path:
                try:
                    script_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _install_windows(self) -> InstallResult:
        if not shutil.which("winget"):
            return InstallResult(
                success=False,
                changed=False,
                platform=self.os_name,
                message="winget is not available. Install Ollama manually from ollama.com.",
            )

        command = (
            "winget",
            "install",
            "--id",
            "Ollama.Ollama",
            "--exact",
            "--accept-source-agreements",
            "--accept-package-agreements",
        )
        result = self._command_runner(command, 900)
        return InstallResult(
            success=result[0] == 0,
            changed=result[0] == 0,
            platform=self.os_name,
            message=(
                "Ollama was installed using winget."
                if result[0] == 0
                else "winget could not install Ollama."
            ),
            command=command,
        )

    def _install_macos(self) -> InstallResult:
        if not shutil.which("brew"):
            return InstallResult(
                success=False,
                changed=False,
                platform=self.os_name,
                message="Homebrew is not available. Install Ollama manually from ollama.com.",
            )

        command = ("brew", "install", "--cask", "ollama")
        result = self._command_runner(command, 900)
        return InstallResult(
            success=result[0] == 0,
            changed=result[0] == 0,
            platform=self.os_name,
            message=(
                "Ollama was installed using Homebrew."
                if result[0] == 0
                else "Homebrew could not install Ollama."
            ),
            command=command,
        )


def _download_script(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "AI-Discord-Builder setup"})
    with urlopen(request, timeout=30) as response:  # nosec B310 - fixed HTTPS URL
        if response.status < 200 or response.status >= 300:
            raise OSError(f"Installer download returned HTTP {response.status}.")
        destination.write_bytes(response.read())


def _run_command(command: Sequence[str], timeout: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout or "", result.stderr or ""
