import tempfile
import unittest
from pathlib import Path

from setup.hardware import HardwareInfo
from setup.installer import InstallResult
from setup.local_ai import LocalAISetupManager, SetupState
from setup.model_selection import choose_model
from setup.ollama import OllamaStatus


class FakeInstaller:
    def __init__(self):
        self.approved = False

    def install_ollama(self, approved=False):
        self.approved = approved
        return InstallResult(
            success=True,
            changed=True,
            platform="linux",
            message="fake install",
        )


class FakeOllama:
    def __init__(self):
        self.running = False
        self.models = set()
        self.pull_calls = []
        self.start_calls = 0
        self.test_calls = []

    def status(self):
        return OllamaStatus(
            base_url="http://localhost:11434",
            installed=self.running,
            running=self.running,
            version="fake",
            models=tuple(sorted(self.models)),
        )

    def start(self):
        self.start_calls += 1
        self.running = True

    def pull_model(self, model):
        self.pull_calls.append(model)
        self.models.add(model)

    def test_model(self, model):
        self.test_calls.append(model)
        return "OK"


class LocalAISetupTests(unittest.TestCase):
    def setUp(self):
        self.hardware = HardwareInfo(
            os_name="linux",
            os_version="test",
            architecture="x86_64",
            cpu_count=4,
            ram_gb=16.0,
            free_disk_gb=20.0,
            gpu_name=None,
            docker_installed=False,
            docker_running=False,
            docker_version=None,
        )

    def test_model_selection_warns_when_hardware_is_unknown(self):
        hardware = HardwareInfo(
            os_name="linux",
            os_version="test",
            architecture="unknown",
            cpu_count=None,
            ram_gb=None,
            free_disk_gb=None,
            gpu_name=None,
            docker_installed=False,
            docker_running=False,
            docker_version=None,
        )
        selection = choose_model(hardware)
        self.assertEqual(selection.model, "qwen3:4b")
        self.assertTrue(selection.warnings)

    def test_detect_only_does_not_install_or_start(self):
        ollama = FakeOllama()
        installer = FakeInstaller()
        manager = LocalAISetupManager(
            hardware_detector=lambda: self.hardware,
            ollama_manager=ollama,
            installer=installer,
        )
        report = manager.inspect()
        self.assertEqual(report.state, SetupState.NEEDS_INSTALL)
        self.assertFalse(installer.approved)
        self.assertEqual(ollama.start_calls, 0)
        self.assertEqual(ollama.pull_calls, [])

    def test_setup_requires_explicit_approvals(self):
        ollama = FakeOllama()
        installer = FakeInstaller()
        manager = LocalAISetupManager(
            hardware_detector=lambda: self.hardware,
            ollama_manager=ollama,
            installer=installer,
        )
        report = manager.setup()
        self.assertEqual(report.state, SetupState.NEEDS_INSTALL)
        self.assertFalse(report.success)
        self.assertFalse(installer.approved)
        self.assertEqual(ollama.pull_calls, [])

    def test_setup_installs_pulls_tests_and_writes_only_local_config(self):
        ollama = FakeOllama()
        installer = FakeInstaller()
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DISCORD_TOKEN=keep-me\nAI_PROVIDER=groq\n",
                encoding="utf-8",
            )
            manager = LocalAISetupManager(
                hardware_detector=lambda: self.hardware,
                ollama_manager=ollama,
                installer=installer,
                env_path=env_file,
            )
            report = manager.setup(
                allow_install=True,
                allow_download=True,
                write_config=True,
            )
            self.assertEqual(report.state, SetupState.READY)
            self.assertTrue(report.success)
            self.assertTrue(installer.approved)
            self.assertEqual(ollama.pull_calls, ["qwen3:4b"])
            self.assertEqual(ollama.test_calls, ["qwen3:4b"])
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("DISCORD_TOKEN=keep-me", content)
            self.assertIn("AI_PROVIDER=ollama", content)
            self.assertIn("OLLAMA_MODEL=qwen3:4b", content)


if __name__ == "__main__":
    unittest.main()
