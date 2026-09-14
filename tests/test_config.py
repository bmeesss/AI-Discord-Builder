import unittest

import config


def base_environ(**overrides):
    """Minimal valid configuration for validation tests."""

    environ = {
        "AI_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen3:4b",
        "DISCORD_TOKEN": "test-token",
        "DATABASE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/builder",
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

    def test_groq_with_postgres_backend_is_valid(self):
        config.validate_config(
            environ=base_environ(
                AI_PROVIDER="groq",
                GROQ_API_KEY="test-key",
            ),
        )


class DatabaseConfigTests(unittest.TestCase):
    def test_postgres_backend_requires_database_url(self):
        environ = base_environ()
        del environ["DATABASE_URL"]
        # DATABASE_BACKEND explicitly postgres: no auto-fallback.
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("DATABASE_URL", str(ctx.exception))

    def test_missing_url_and_backend_defaults_to_postgres(self):
        environ = base_environ()
        del environ["DATABASE_URL"]
        del environ["DATABASE_BACKEND"]
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("DATABASE_URL", str(ctx.exception))

    def test_invalid_database_url_is_rejected(self):
        with self.assertRaises(RuntimeError):
            config.validate_config(
                environ=base_environ(DATABASE_URL="not-a-dsn"),
            )

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(
                environ=base_environ(DATABASE_BACKEND="mysql"),
            )
        self.assertIn("DATABASE_BACKEND", str(ctx.exception))

    def test_supabase_backend_requires_both_settings(self):
        environ = base_environ(
            DATABASE_BACKEND="supabase",
            SUPABASE_URL="https://example.supabase.co",
        )
        del environ["DATABASE_URL"]
        with self.assertRaises(RuntimeError) as ctx:
            config.validate_config(environ=environ)
        self.assertIn("SUPABASE_KEY", str(ctx.exception))

    def test_supabase_backend_is_valid_with_both_settings(self):
        config.validate_config(
            environ=base_environ(
                DATABASE_BACKEND="supabase",
                SUPABASE_URL="https://example.supabase.co",
                SUPABASE_KEY="anon-key",
            ),
        )

    def test_supabase_backend_needs_no_database_url(self):
        environ = base_environ(
            DATABASE_BACKEND="supabase",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_KEY="anon-key",
        )
        del environ["DATABASE_URL"]
        config.validate_config(environ=environ)

    def test_legacy_supabase_only_deployment_auto_detects(self):
        """Existing installs with only Supabase keys keep working."""

        environ = base_environ(
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_KEY="anon-key",
        )
        del environ["DATABASE_BACKEND"]
        del environ["DATABASE_URL"]
        config.validate_config(environ=environ)

    def test_require_database_can_be_disabled_for_tooling(self):
        environ = base_environ()
        del environ["DATABASE_URL"]
        del environ["DATABASE_BACKEND"]
        config.validate_config(environ=environ, require_database=False)


if __name__ == "__main__":
    unittest.main()
