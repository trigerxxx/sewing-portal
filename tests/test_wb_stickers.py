# -*- coding: utf-8 -*-
"""Стикеры WB: только после подтверждения сборки, по одному на задание, ошибки по заказам."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import wb_api  # noqa: E402
import wb_sync  # noqa: E402
import test_fbs  # noqa: E402


class StickerTests(test_fbs.FbsTests):
    def setUp(self):
        super().setUp()
        self._old_stickers = wb_api.stickers
        self.asked = []

        def fake_stickers(token, ids, kind="svg", width=58, height=40):
            self.asked.append((token, list(ids), kind, width, height))
            return [{"orderId": i, "partA": "1234", "partB": "5678", "barcode": f"*{i}",
                     "file": "PHN2Zy8+"} for i in ids if i != 999]

        wb_api.stickers = fake_stickers

    def tearDown(self):
        wb_api.stickers = self._old_stickers
        super().tearDown()

    def _confirmed(self, ext="101"):
        wb_sync.sync()
        oid = [o for o in self.orders() if o["external_id"] == ext][0]["id"]
        wb_sync.pick(oid)
        wb_sync.confirm([oid])
        return oid

    def test_sticker_after_confirm(self):
        oid = self._confirmed()
        res = wb_sync.stickers([oid], "svg", "58x40", actor="sklad")
        self.assertEqual(res["ошибки"], [])
        self.assertEqual(len(res["стикеры"]), 1)
        st = res["стикеры"][0]
        self.assertEqual((st["задание"], st["номер"], st["кабинет"], st["mime"]),
                         (101, "101", "zhsk", "image/svg+xml"))
        self.assertEqual(self.asked, [("token-zhsk", [101], "svg", 58, 40)])

    def test_new_order_has_no_sticker_yet(self):
        wb_sync.sync()
        oid = [o for o in self.orders() if o["external_id"] == "102"][0]["id"]
        res = wb_sync.stickers([oid])
        self.assertEqual(res["стикеры"], [])
        self.assertIn("после подтверждения", res["ошибки"][0]["ошибка"])
        self.assertEqual(self.asked, [], "в WB не ходим за стикером неподтверждённого заказа")

    def test_bad_format_and_size(self):
        with self.assertRaises(ValueError):
            wb_sync.stickers(["x"], "pdf")
        with self.assertRaises(ValueError):
            wb_sync.stickers(["x"], "svg", "100x100")

    def test_missing_sticker_and_unknown_order_reported(self):
        oid = self._confirmed()
        self.con.execute("UPDATE order_items SET external_id='999' WHERE order_id=?", (oid,))
        self.con.commit()
        res = wb_sync.stickers([oid, "нет-такого"], "zplv", "40x30")
        self.assertEqual(res["стикеры"], [])
        self.assertEqual(len(res["ошибки"]), 2)
        self.assertEqual(self.asked[0][2:], ("zplv", 40, 30))

    def test_api_validates_and_batches(self):
        wb_api.stickers = self._old_stickers
        calls = []
        old_request = wb_api._request

        def fake_request(path, token, method="GET", payload=None):
            calls.append((path, len(payload["orders"])))
            return {"stickers": [{"orderId": i} for i in payload["orders"]]}

        wb_api._request = fake_request
        try:
            got = wb_api.stickers("t", list(range(1, 251)), "png", 40, 30)
            self.assertEqual(len(got), 250)
            self.assertEqual([n for _, n in calls], [100, 100, 50])
            self.assertIn("type=png&width=40&height=30", calls[0][0])
            with self.assertRaises(wb_api.WbError):
                wb_api.stickers("t", [1], "pdf")
        finally:
            wb_api._request = old_request


# унаследованные проверки FBS уже идут в test_fbs.py — здесь только стикеры
for _name in [n for n in dir(test_fbs.FbsTests) if n.startswith("test_")]:
    if _name not in StickerTests.__dict__:
        setattr(StickerTests, _name, None)


if __name__ == "__main__":
    unittest.main()
