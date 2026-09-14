import unittest

import config


class ConfigTests(unittest.TestCase):
    def test_ollama_does_not_require_a_cloud_api_key(self):
        config.validate_config(
            environ={
                "AI_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": "http://localhost:11434",
                "OLLAMA_MODEL": "qwen3:4b",
                "DISCORD_TOKEN": "test-token",
            }
        )

    def test_invalid_ollama_url_is_rejected(self):
        with self.assertRaises(RuntimeError):
            config.validate_config(
                environ={
                    "AI_PROVIDER": "ollama",
                    "OLLAMA_BASE_URL": "localhost:11434",
                    "OLLAMA_MODEL": "qwen3:4b",
                    "DISCORD_TOKEN": "test-token",
                }
            )

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(RuntimeError):
            config.validate_config(
                environ={
                    "AI_PROVIDER": "unknown",
                    "DISCORD_TOKEN": "test-token",
                }
            )


if __name__ == "__main__":
    unittest.main()
