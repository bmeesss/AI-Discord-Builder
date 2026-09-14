"""Orchestration for optional local-AI setup.

This module separates inspection from side effects.  ``inspect`` is always
read-only.  ``setup`` receives explicit approvals for installation, model
download and configuration writing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import config
from setup.config_writer import build_local_ai_config, update_env_file
from setup.hardware import HardwareInfo, detect_hardware
from setup.installer import InstallResult, OllamaInstaller
from setup.model_selection import ModelSelection, choose_model
from setup.ollama import OllamaManager, OllamaSetupError, OllamaStatus


class SetupState(str, Enum):
    DETECTING = "detecting"
    NEEDS_INSTALL = "needs_install"
    NEEDS_START = "needs_start"
    NEEDS_MODEL = "needs_model"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class LocalAIReport:
    state: SetupState
    success: bool
    hardware: HardwareInfo | None = None
    ollama: OllamaStatus | None = None
    model_selection: ModelSelection | None = None
    config: dict[str, str] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    installation: InstallResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "success": self.success,
            "hardware": self.hardware.to_dict() if self.hardware else None,
            "ollama": self.ollama.to_dict() if self.ollama else None,
            "model_selection": (
                self.model_selection.to_dict() if self.model_selection else None
            ),
            "config": dict(self.config),
            "messages": list(self.messages),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "installation": (
                self.installation.to_dict() if self.installation else None
            ),
        }


class LocalAISetupManager:
    """Inspect and prepare an Ollama installation."""

    def __init__(
        self,
        base_url: str | None = None,
        env_path: str | Path = ".env",
        hardware_detector: Callable[[], HardwareInfo] | None = None,
        ollama_manager: OllamaManager | None = None,
        installer: OllamaInstaller | None = None,
    ) -> None:
        self.base_url = base_url or config.OLLAMA_BASE_URL
        self.env_path = Path(env_path)
        self._hardware_detector = hardware_detector or detect_hardware
        self._ollama = ollama_manager or OllamaManager(self.base_url)
        self._installer = installer

    def inspect(
        self,
        requested_model: str | None = None,
        auto_select_model: bool = True,
    ) -> LocalAIReport:
        hardware = self._hardware_detector()
        selection = choose_model(
            hardware,
            requested_model=requested_model,
            auto_select=auto_select_model,
        )
        status = self._ollama.status()
        warnings = list(selection.warnings)
        messages = [
            f"Detected OS: {hardware.os_name} ({hardware.architecture}).",
            f"Ollama endpoint: {self.base_url}",
        ]
        errors: list[str] = []

        if not status.running:
            if status.installed:
                state = SetupState.NEEDS_START
                messages.append("Ollama is installed but not running.")
            else:
                state = SetupState.NEEDS_INSTALL
                messages.append("Ollama was not detected at the configured endpoint.")
        elif selection.model not in status.models:
            state = SetupState.NEEDS_MODEL
            messages.append(
                f"Ollama is running, but model {selection.model} is not available."
            )
        else:
            state = SetupState.READY
            messages.append("Ollama and the selected model are available.")

        if status.error:
            warnings.append(status.error)

        return LocalAIReport(
            state=state,
            success=not errors,
            hardware=hardware,
            ollama=status,
            model_selection=selection,
            messages=messages,
            warnings=warnings,
            errors=errors,
        )

    def setup(
        self,
        requested_model: str | None = None,
        auto_select_model: bool = True,
        allow_install: bool = False,
        allow_download: bool = False,
        allow_start: bool = True,
        write_config: bool = False,
    ) -> LocalAIReport:
        """Run setup actions after explicit caller approval.

        ``allow_install`` and ``allow_download`` default to False by design.
        ``allow_start`` only starts an already installed local executable; it
        never installs software.
        """

        report = self.inspect(requested_model, auto_select_model)
        report.state = SetupState.DETECTING
        selection = report.model_selection
        if not selection:
            report.state = SetupState.FAILED
            report.success = False
            report.errors.append("No local model could be selected.")
            return report

        status = report.ollama
        if not status:
            report.state = SetupState.FAILED
            report.success = False
            report.errors.append("Ollama status could not be determined.")
            return report

        if not status.running:
            if not status.installed:
                if not allow_install:
                    report.state = SetupState.NEEDS_INSTALL
                    report.success = False
                    report.errors.append(
                        "Ollama is not installed. Re-run setup and explicitly approve installation."
                    )
                    return report

                installer = self._installer or OllamaInstaller(
                    os_name=report.hardware.os_name if report.hardware else None,
                )
                installation = installer.install_ollama(approved=True)
                report.installation = installation
                report.messages.append(installation.message)
                if not installation.success:
                    report.state = SetupState.FAILED
                    report.success = False
                    report.errors.append(installation.message)
                    return report

            if not allow_start:
                report.state = SetupState.NEEDS_START
                report.success = False
                report.errors.append(
                    "Ollama is installed but was not started because start was disabled."
                )
                return report

            try:
                self._ollama.start()
            except OllamaSetupError as exc:
                report.state = SetupState.FAILED
                report.success = False
                report.errors.append(str(exc))
                return report

            report.messages.append("Ollama is running.")

        # Refresh after starting/installing, including Docker/remote endpoints.
        status = self._ollama.status()
        report.ollama = status

        if not status.running:
            report.state = SetupState.FAILED
            report.success = False
            report.errors.append(
                "Ollama is still not reachable after the setup attempt."
            )
            return report

        if selection.model not in status.models:
            if not allow_download:
                report.state = SetupState.NEEDS_MODEL
                report.success = False
                report.errors.append(
                    f"Model {selection.model} is not pulled. Re-run setup and explicitly approve the download."
                )
                return report
            try:
                self._ollama.pull_model(selection.model)
                report.messages.append(f"Downloaded model {selection.model}.")
            except OllamaSetupError as exc:
                report.state = SetupState.FAILED
                report.success = False
                report.errors.append(str(exc))
                return report

        try:
            status = self._ollama.status()
            report.ollama = status
            if selection.model not in status.models:
                raise OllamaSetupError(
                    f"Model {selection.model} is still not visible after download."
                )
            self._ollama.test_model(selection.model)
        except OllamaSetupError as exc:
            report.state = SetupState.FAILED
            report.success = False
            report.errors.append(str(exc))
            return report

        report.config = build_local_ai_config(
            self.base_url,
            selection.model,
            auto_select_model=auto_select_model,
        )
        if write_config:
            try:
                update_env_file(self.env_path, report.config)
                report.messages.append(f"Updated local AI configuration in {self.env_path}.")
            except (OSError, ValueError) as exc:
                report.state = SetupState.FAILED
                report.success = False
                report.errors.append(f"Could not write configuration: {exc}")
                return report

        report.state = SetupState.READY
        report.success = True
        report.messages.append("Local AI setup is ready.")
        return report
