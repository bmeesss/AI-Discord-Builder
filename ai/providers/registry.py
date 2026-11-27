"""Static registry of the supported cloud AI providers.

This module is intentionally dependency-light (stdlib only) so ``config``,
the provider factory, the setup CLI and the tests can all share one source
of truth for provider names, API-key environment variables and default
models without importing any SDK or application configuration.

Every cloud provider here speaks the OpenAI Chat Completions API shape;
``groq`` additionally has a dedicated SDK adapter but keeps the same
configuration surface.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Configuration for one cloud AI provider."""

    name: str
    display: str
    api_key_env: str
    model_env: str
    default_model: str
    base_url: str | None = None
    # False when the provider's API does not reliably support
    # response_format={"type": "json_object"} (it is ignored or rejected by
    # some OpenAI-compatible endpoints).  JSON output is then requested via
    # the prompt only.
    json_mode: bool = True


CLOUD_PRESETS: dict[str, ProviderPreset] = {
    preset.name: preset
    for preset in (
        ProviderPreset(
            name="groq",
            display="Groq",
            api_key_env="GROQ_API_KEY",
            model_env="GROQ_MODEL",
            default_model="llama-3.3-70b-versatile",
        ),
        ProviderPreset(
            name="openai",
            display="OpenAI",
            api_key_env="OPENAI_API_KEY",
            model_env="OPENAI_MODEL",
            default_model="gpt-4o-mini",
        ),
        ProviderPreset(
            name="gemini",
            display="Google Gemini",
            api_key_env="GEMINI_API_KEY",
            model_env="GEMINI_MODEL",
            default_model="gemini-4-hydrogen",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        ProviderPreset(
            name="mistral",
            display="Mistral",
            api_key_env="MISTRAL_API_KEY",
            model_env="MISTRAL_MODEL",
            default_model="mistral-small-latest",
            base_url="https://api.mistral.ai/v1",
        ),
        ProviderPreset(
            name="openrouter",
            display="OpenRouter",
            api_key_env="OPENROUTER_API_KEY",
            model_env="OPENROUTER_MODEL",
            default_model="openrouter/free",
            base_url="https://openrouter.ai/api/v1",
            json_mode=False,
        ),
        ProviderPreset(
            name="deepseek",
            display="DeepSeek",
            api_key_env="DEEPSEEK_API_KEY",
            model_env="DEEPSEEK_MODEL",
            default_model="deepseek-flash",
            base_url="https://api.deepseek.com",
        ),
        ProviderPreset(
            name="anthropic",
            display="Anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            model_env="ANTHROPIC_MODEL",
            default_model="claude-haiku-4-5",
            base_url="https://api.anthropic.com/v1/",
            # Anthropic's OpenAI-compatibility layer ignores response_format.
            json_mode=False,
        ),
        ProviderPreset(
            name="xai",
            display="xAI",
            api_key_env="XAI_API_KEY",
            model_env="XAI_MODEL",
            default_model="grok-4.3",
            base_url="https://api.x.ai/v1",
        ),
        ProviderPreset(
            name="together",
            display="Together AI",
            api_key_env="TOGETHER_API_KEY",
            model_env="TOGETHER_MODEL",
            default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            base_url="https://api.together.xyz/v1",
        ),
        ProviderPreset(
            name="perplexity",
            display="Perplexity",
            api_key_env="PERPLEXITY_API_KEY",
            model_env="PERPLEXITY_MODEL",
            default_model="sonar",
            base_url="https://api.perplexity.ai",
            # Sonar models do not reliably support response_format.
            json_mode=False,
        ),
    )
}

# Cloud providers that go through the shared OpenAI-compatible adapter.
# ``groq`` keeps its dedicated SDK adapter; ``ollama`` is the local backend.
OPENAI_COMPATIBLE_NAMES = frozenset(CLOUD_PRESETS) - {"groq"}

SUPPORTED_PROVIDERS = frozenset(CLOUD_PRESETS) | {"ollama"}

__all__ = [
    "CLOUD_PRESETS",
    "OPENAI_COMPATIBLE_NAMES",
    "ProviderPreset",
    "SUPPORTED_PROVIDERS",
]
