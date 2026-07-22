import unittest
from types import SimpleNamespace

from views.ticket_views import task_id_from_message


class LegacyButtonTests(unittest.TestCase):
    def test_task_id_is_read_from_embed_title(self):
        embed = SimpleNamespace(title="Hasil Tugas #42 Siap Direview", description=None,
                                footer=SimpleNamespace(text=""))
        message = SimpleNamespace(content="", embeds=[embed])
        self.assertEqual(task_id_from_message(message), 42)

    def test_missing_task_id_is_safe(self):
        message = SimpleNamespace(content="panel lama", embeds=[])
        self.assertIsNone(task_id_from_message(message))
