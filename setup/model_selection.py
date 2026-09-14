"""Conservative and extensible local-model selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from setup.hardware import HardwareInfo


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    advisory_ram_gb: float | None
    advisory_disk_gb: float | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelSelection:
    model: str
    profile: ModelProfile | None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "profile": self.profile.to_dict() if self.profile else None,
            "warnings": list(self.warnings),
        }


# Advisory values only.  They are deliberately not presented as guarantees:
# model memory use depends on quantization, context length and Ollama version.
MODEL_CATALOG: dict[str, ModelProfile] = {
    "qwen3:4b": ModelProfile(
        name="qwen3:4b",
        advisory_ram_gb=8.0,
        advisory_disk_gb=4.0,
        description="Conservative general-purpose local starting point.",
    ),
    "qwen3:8b": ModelProfile(
        name="qwen3:8b",
        advisory_ram_gb=16.0,
        advisory_disk_gb=6.0,
        description="Higher-quality option for machines with more resources.",
    ),
    "qwen3:1.7b": ModelProfile(
        name="qwen3:1.7b",
        advisory_ram_gb=4.0,
        advisory_disk_gb=2.0,
        description="Smaller fallback when the user explicitly chooses it.",
    ),
}

DEFAULT_LOCAL_MODEL = "qwen3:4b"


def get_model_profile(model: str) -> ModelProfile | None:
    return MODEL_CATALOG.get(model.strip())


def choose_model(
    hardware: HardwareInfo,
    requested_model: str | None = None,
    auto_select: bool = True,
) -> ModelSelection:
    """Choose a model without making unsupported hardware promises.

    A user-provided model always wins.  Automatic selection currently uses the
    conservative default and emits warnings when hardware information is below
    advisory values.  Adding a smarter selector later only requires extending
    ``MODEL_CATALOG`` and this function.
    """

    selected = (requested_model or DEFAULT_LOCAL_MODEL).strip()
    profile = get_model_profile(selected)
    warnings: list[str] = []

    if not auto_select and requested_model is None:
        warnings.append(
            "Automatic model selection is disabled; using the configured default."
        )

    if profile is None:
        warnings.append(
            f"Model {selected} is not in the built-in catalog; resource requirements are unknown."
        )
        return ModelSelection(selected, None, tuple(warnings))

    if hardware.ram_gb is None:
        warnings.append(
            "RAM could not be detected reliably; model suitability is uncertain."
        )
    elif profile.advisory_ram_gb and hardware.ram_gb < profile.advisory_ram_gb:
        warnings.append(
            f"Detected RAM ({hardware.ram_gb:.1f} GB) is below the advisory "
            f"value for {selected} ({profile.advisory_ram_gb:.1f} GB)."
        )

    if hardware.free_disk_gb is None:
        warnings.append(
            "Available disk space could not be detected reliably."
        )
    elif profile.advisory_disk_gb and hardware.free_disk_gb < profile.advisory_disk_gb:
        warnings.append(
            f"Free disk space ({hardware.free_disk_gb:.1f} GB) is below the "
            f"advisory value for {selected} ({profile.advisory_disk_gb:.1f} GB)."
        )

    if hardware.gpu_name is None:
        warnings.append(
            "No GPU was reliably detected; Ollama will use the available CPU/GPU path."
        )

    return ModelSelection(selected, profile, tuple(warnings))
