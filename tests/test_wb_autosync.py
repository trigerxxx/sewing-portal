# -*- coding: utf-8 -*-
"""Автообновление заказов WB: интервал из config.json, пропуск без токенов, итог прохода."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import cabinets_store  # noqa: E402
import wb_autosync  # noqa: E402
import wb_sync  # noqa: E402


class AutosyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-autosync-"))
        self._old = (wb_autosync.CONFIG, cabinets_store.CABINETS, cabinets_store.TOKENS, wb_sync.sync)
        wb_autosync.CONFIG = self.tmp / "config.json"
        cabinets_store.CABINETS = self.tmp / "cabinets.json"
        cabinets_store.TOKENS = self.tmp / "tokens.json"
        cabinets_store.cabinets()
        self.calls = []

        def fake_sync(cabinet_id=None, actor=""):
            self.calls.append(actor)
            return {"создано": 2, "обновлено": 1, "отправлено": 0, "собирается": 0, "отменено": 0,
                    "ошибки": [{"кабинет": "kkm", "ошибка": "WB 401"}]}

        wb_sync.sync = fake_sync

    def tearDown(self):
        wb_autosync.CONFIG, cabinets_store.CABINETS, cabinets_store.TOKENS, wb_sync.sync = self._old

    def _config(self, **kw):
        wb_autosync.CONFIG.write_text(json.dumps(kw), encoding="utf-8")

    def test_interval_default_off_and_minimum(self):
        self.assertEqual(wb_autosync.interval_minutes(), wb_autosync.DEFAULT_MINUTES)  # нет файла
        self._config(wb_autosync_minutes=0)
        self.assertEqual(wb_autosync.interval_minutes(), 0)
        self._config(wb_autosync_minutes=1)
        self.assertEqual(wb_autosync.interval_minutes(), wb_autosync.MIN_MINUTES)
        self._config(wb_autosync_minutes="15")
        self.assertEqual(wb_autosync.interval_minutes(), 15)
        self._config(wb_autosync_minutes="abc")
        self.assertEqual(wb_autosync.interval_minutes(), wb_autosync.DEFAULT_MINUTES)

    def test_skipped_without_tokens(self):
        self.assertIsNone(wb_autosync.run_once())
        self.assertEqual(self.calls, [])
        self.assertIn("токен", wb_autosync.status()["ошибка"])

    def test_run_records_result_and_errors(self):
        cabinets_store.save_cabinet("zhsk", "ЖСК", token="token-zhsk")
        before = wb_autosync.status()["запусков"]
        res = wb_autosync.run_once()
        self.assertEqual(res["создано"], 2)
        self.assertEqual(self.calls, ["автообновление"])
        st = wb_autosync.status()
        self.assertEqual(st["запусков"], before + 1)
        self.assertEqual(st["последний_итог"]["создано"], 2)
        self.assertIn("kkm: WB 401", st["ошибка"])
        self.assertTrue(st["последний_запуск"])

    def test_sync_lock_serializes(self):
        """Ручная и автоматическая синхронизация не выполняются одновременно."""
        wb_sync.sync = self._old[3]
        inside = []
        orig = wb_sync._sync

        def slow(cabinet_id, actor):
            inside.append(wb_sync.SYNC_LOCK.locked())
            return {"ошибки": []}

        wb_sync._sync = slow
        try:
            self.assertTrue(wb_sync.SYNC_LOCK.acquire())
            t = threading.Thread(target=wb_sync.sync)
            t.start()
            t.join(0.2)
            self.assertTrue(t.is_alive())      # ждёт освобождения замка
            wb_sync.SYNC_LOCK.release()
            t.join(2)
            self.assertFalse(t.is_alive())
            self.assertEqual(inside, [True])
        finally:
            wb_sync._sync = orig


if __name__ == "__main__":
    unittest.main()
