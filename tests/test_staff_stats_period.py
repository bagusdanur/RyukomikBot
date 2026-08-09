"""Regression tests for get_staff_stats period attribution (bug: double-count).

Bug: a paid assignment approved in month X but disbursed (paid_period) in month Y
used to appear in BOTH month X and month Y stats because the WHERE clause OR-ed
`approved_at LIKE` with `paid_period =`. Each assignment must be attributed to
exactly ONE effective period:
  - paid      -> paid_period
  - approved  -> month of approved_at
  - otherwise -> month of assigned_at
"""

import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database


class StaffStatsPeriodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "stats.db")
        self.patch = patch.object(database, "DB_PATH", self.path)
        self.patch.start()
        asyncio.run(database.setup_database())

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def _insert(self, **kw):
        cols = ("manga", "chapter", "staff_id", "role", "base_rate", "final_rate",
                "multiplier", "status", "assigned_at", "approved_at", "paid_period",
                "chapter_count", "rate_per_chapter", "chapters")
        defaults = dict(
            manga="M", chapter="1", staff_id=100, role="TS", base_rate=5000,
            final_rate=5000, multiplier=1.0, status="approved",
            assigned_at="2026-07-01 00:00:00", approved_at=None, paid_period=None,
            chapter_count=1, rate_per_chapter=5000, chapters='["1"]',
        )
        defaults.update(kw)
        connection = sqlite3.connect(self.path)
        placeholders = ",".join("?" for _ in cols)
        connection.execute(
            f"INSERT INTO assignments ({','.join(cols)}) VALUES ({placeholders})",
            tuple(defaults[c] for c in cols),
        )
        connection.commit()
        connection.close()

    def test_paid_across_months_counts_once_in_paid_period_only(self):
        # Approved in July, paid in August -> must count ONLY in August.
        self._insert(status="paid", approved_at="2026-07-15 10:00:00",
                     paid_period="2026-08", final_rate=11000)

        july = asyncio.run(database.get_staff_stats(100, "2026-07"))
        august = asyncio.run(database.get_staff_stats(100, "2026-08"))

        self.assertEqual(july["total"], 0, "paid task must NOT appear in approval month")
        self.assertEqual(august["total"], 1, "paid task must appear in its paid_period")
        self.assertEqual(august["total_paid"], 11000)
        self.assertEqual(july["total_paid"], 0)

    def test_sum_per_period_equals_grand_total(self):
        # Mix of statuses/months; per-period totals must sum to the grand total
        # with no duplication and no omission.
        self._insert(status="paid", approved_at="2026-07-15 10:00:00",
                     paid_period="2026-08", final_rate=10000)
        self._insert(status="approved", approved_at="2026-07-20 10:00:00",
                     final_rate=5000)
        self._insert(status="claimed", assigned_at="2026-08-02 10:00:00")

        july = asyncio.run(database.get_staff_stats(100, "2026-07"))
        august = asyncio.run(database.get_staff_stats(100, "2026-08"))

        self.assertEqual(july["total"] + august["total"], 3)
        # July: only the approved (approved in July, not yet paid)
        self.assertEqual(july["total"], 1)
        # August: the paid one (paid_period) + the still-claimed one (assigned Aug)
        self.assertEqual(august["total"], 2)

    def test_approved_uses_approval_month_not_assignment_month(self):
        # Assigned in June, approved in July -> counts in July.
        self._insert(status="approved", assigned_at="2026-06-01 00:00:00",
                     approved_at="2026-07-05 00:00:00", final_rate=7000)

        june = asyncio.run(database.get_staff_stats(100, "2026-06"))
        july = asyncio.run(database.get_staff_stats(100, "2026-07"))

        self.assertEqual(june["total"], 0)
        self.assertEqual(july["total"], 1)
        self.assertEqual(july["total_earned"], 7000)


if __name__ == "__main__":
    unittest.main()
