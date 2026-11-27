"""Storage facade tests — the bot creates its storage without any database
configuration.  Everything is backed by local JSON files.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage import (
    Storage,
    close_storage,
    create_json_storage,
    get_storage,
    initialize_storage,
    set_storage,
)
from storage.interfaces import (
    ActionRepository,
    AnalysisRepository,
    ConversationRepository,
    MemoryRepository,
    TemplateRepository,
)


class JsonStorageFactoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"

    def tearDown(self):
        self._tmp.cleanup()

    async def asyncTearDown(self):
        await close_storage()

    def test_create_json_storage_needs_no_configuration(self):
        storage = create_json_storage(self.data_dir)
        self.assertIsInstance(storage, Storage)
        self.assertEqual(storage.backend, "json")

    def test_repositories_satisfy_the_protocols(self):
        storage = create_json_storage(self.data_dir)
        self.assertIsInstance(storage.actions, ActionRepository)
        self.assertIsInstance(storage.conversations, ConversationRepository)
        self.assertIsInstance(storage.memories, MemoryRepository)
        self.assertIsInstance(storage.analysis, AnalysisRepository)
        self.assertIsInstance(storage.templates, TemplateRepository)

    async def test_initialize_creates_data_dir(self):
        storage = create_json_storage(self.data_dir)
        await storage.initialize()
        self.assertTrue(self.data_dir.is_dir())

    async def test_get_storage_defaults_to_json(self):
        await close_storage()
        storage = get_storage()
        self.assertEqual(storage.backend, "json")

    async def test_set_storage_injects_and_resets(self):
        fake = create_json_storage(self.data_dir)
        set_storage(fake)
        self.assertIs(get_storage(), fake)
        set_storage(None)

    async def test_initialize_storage_uses_the_singleton(self):
        await close_storage()
        set_storage(create_json_storage(self.data_dir))
        storage = await initialize_storage()
        self.assertIs(get_storage(), storage)
        self.assertTrue(self.data_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
