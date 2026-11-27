"""Configuration validation tests — database-free.

The bot must start with nothing more than a Discord token and an AI provider
configuration; there is deliberately no database configuration to validate.
"""

from __future__ import annotations

import unittest

import config


def base_environ(**overrides):
    """Minimal valid configuration for validation tests."""

    environ = {
        "AI_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen3:4b",
        "DISCORD_TOKEN": "test-token",
    }
    environ.update(overrides)
    return environ


class ConfigTests(unittest.TestCase):
    def test_ollama_does_not_require_a_cloud_api_key(self):
        config.validate_config(
            environ=base_environ(),
        )

    def test_invalid_ollama_url_is_rejected(self):
        with self.assertRaises(RuntimeError):
            config.validate_config(
                environ=base_environ(
                    OLLAMA_BASE_URL="localhost:11434",
                ),
            )

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(RuntimeError):
            config.validate_config(
                environ=base_environ(
                    AI_PROVIDER="unknown",
                ),
            )

    def test_groq_with_minimal_config_is_valid(self):
        config.validate_config(
            environ=base_environ(
                AI_PROVIDER="groq",
                GROQ_API_KEY="test-key",
            ),
        )

    def test_openai_with_key_is_valid(self):
        config.validate_config(
            environ=base_environ(
                AI_PROVIDER="openai",
                OPENAI_API_KEY="test-key",
            ),
        )


class NoDatabaseConfigTests(unittest.TestCase):
    def test_validation_needs_no_database_settings(self):
        """The core requirement: a valid config without any database vars."""

        environ = base_environ()
        for banned in (
            "DATABASE_URL",
            "DATABASE_BACKEND",
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "DB_POOL_MIN_SIZE",
            "DB_POOL_MAX_SIZE",
            "DB_MIGRATE_ON_STARTUP",
        ):
            self.assertNotIn(banned, environ)

        config.validate_config(environ=environ)

    def test_database_settings_are_simply_ignored(self):
        """Legacy .env files with old database vars must not break anything."""

        config.validate_config(
            environ=base_environ(
                DATABASE_URL="postgresql://user:pass@localhost:5432/db",
                DATABASE_BACKEND="postgres",
                SUPABASE_URL="https://example.supabase.co",
                SUPABASE_KEY="anon",
            ),
        )

    def test_config_module_defines_no_database_settings(self):
        for banned in (
            "DATABASE_URL",
            "DATABASE_BACKEND",
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "VALID_DATABASE_BACKENDS",
        ):
            self.assertNotIn(banned, config.__dict__)

    def test_data_dir_setting_exists(self):
        self.assertTrue(config.DATA_DIR)


class CloudProviderConfigTests(unittest.TestCase):
    """Every registered cloud provider validates exactly its own key."""

    def test_each_provider_needs_its_own_api_key(self):
        from ai.providers.registry import CLOUD_PRESETS

        for name, preset in CLOUD_PRESETS.items():
            with self.subTest(provider=name):
                config.validate_config(
                    environ=base_environ(
                        AI_PROVIDER=name,
                        **{preset.api_key_env: "test-key"},
                    ),
                )

                with self.assertRaises(RuntimeError) as ctx:
                    config.validate_config(environ=base_environ(AI_PROVIDER=name))
                self.assertIn(preset.api_key_env, str(ctx.exception))
                self.assertIn("Missing required environment variables", str(ctx.exception))

    def test_unknown_provider_message_lists_new_providers(self):
        from ai.providers.registry import CLOUD_PRESETS

        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(
                environ=base_environ(AI_PROVIDER="does-not-exist"),
            )
        for name in CLOUD_PRESETS:
            self.assertIn(name, str(ctx.exception))

    def test_model_defaults_match_the_registry(self):
        import os

        from ai.providers.registry import CLOUD_PRESETS

        for preset in CLOUD_PRESETS.values():
            if os.getenv(preset.model_env) is None:
                with self.subTest(model_env=preset.model_env):
                    self.assertEqual(
                        getattr(config, preset.model_env),
                        preset.default_model,
                    )


if __name__ == "__main__":
    unittest.main()
