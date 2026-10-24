import tempfile
import unittest
from pathlib import Path

from talk_core.history import HistoryManager


class HistorySqliteTests(unittest.TestCase):
    def test_add_and_recent_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "hist.db"
            mgr = HistoryManager(db_path=db)
            mgr.add("first", "echo 1")
            mgr.add("second", "echo 2")
            recent = mgr.get_recent(10)
            self.assertEqual([e.prompt for e in recent], ["first", "second"])

    def test_search_finds_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "hist.db"
            mgr = HistoryManager(db_path=db)
            mgr.add("disk", "df -h")
            mgr.add("list", "ls")
            hits = mgr.search("df")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].command, "df -h")


if __name__ == "__main__":
    unittest.main()
