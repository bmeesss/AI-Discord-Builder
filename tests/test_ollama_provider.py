import unittest

from ai.providers.ollama import OllamaProvider, normalize_ollama_url


class FakeHTTP:
    def __init__(self):
        self.posts = []

    async def get(self, path, timeout=None):
        self.posts.append(("GET", path, timeout))
        return {"models": [{"name": "qwen3:4b"}]}

    async def post(self, path, payload, timeout=None):
        self.posts.append(("POST", path, payload, timeout))
        if path == "/api/chat":
            return {"message": {"content": '{"summary":"ok","actions":[]}'}}
        return {"status": "success"}


class OllamaProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_model_detection(self):
        http = FakeHTTP()
        provider = OllamaProvider(
            "http://localhost:11434/",
            "qwen3:4b",
            http_client=http,
        )
        health = await provider.healthcheck()
        self.assertTrue(health.ok)
        self.assertTrue(health.model_available)
        self.assertTrue(await provider.model_available())

    async def test_generate_uses_json_chat_contract(self):
        http = FakeHTTP()
        provider = OllamaProvider(
            "http://ollama:11434",
            "qwen3:4b",
            http_client=http,
        )
        response = await provider.generate("system", "user")
        self.assertIn("actions", response)
        method, path, payload, _timeout = http.posts[-1]
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertEqual(payload["model"], "qwen3:4b")
        self.assertEqual(payload["format"], "json")
        self.assertFalse(payload["stream"])

    async def test_pull_and_model_smoke_test(self):
        http = FakeHTTP()
        provider = OllamaProvider(
            "http://localhost:11434",
            "qwen3:4b",
            http_client=http,
        )
        await provider.pull_model()
        result = await provider.test_model()
        self.assertTrue(result.ok)
        self.assertTrue(any(entry[1] == "/api/pull" for entry in http.posts))

    def test_url_validation(self):
        self.assertEqual(
            normalize_ollama_url("http://localhost:11434/"),
            "http://localhost:11434",
        )
        with self.assertRaises(ValueError):
            normalize_ollama_url("localhost:11434")


if __name__ == "__main__":
    unittest.main()
