# -*- coding: utf-8 -*-
"""Заказы магазина в общей таблице orders(type='shop'): создание, статусы, история, без дублей."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import db as sqldb  # noqa: E402
import shop_orders  # noqa: E402


def order(oid=1, status="новый", shipped=0, **kw):
    return {"id": oid, "дата": "11.11.2026 10:15", "клиент": "Айгуль", "статус": status,
            "позиции": [{"наименование": "Брюки/477/чёрный/42", "количество": 3, "отгружено": shipped},
                        {"наименование": "Юбка/12/синий/44", "количество": 1, "отгружено": 0}], **kw}


class ShopOrdersTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="v2-shop-")) / "db.sqlite"
        self._old = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old(self.path)

    def tearDown(self):
        sqldb.connect = self._old

    def q(self, sql, *args):
        con = sqldb.connect()
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def test_created_once_with_items(self):
        st = shop_orders.mirror([order()])
        self.assertEqual(st, {"заказов": 1, "создано": 1, "обновлено": 0})
        again = shop_orders.mirror([order()])
        self.assertEqual(again["создано"] + again["обновлено"], 0)
        rows = self.q("SELECT * FROM orders")
        self.assertEqual(len(rows), 1)
        o = rows[0]
        self.assertEqual((o["type"], o["status"], o["external_id"], o["customer_name"]),
                         ("shop", "new", "1", "Айгуль"))
        self.assertEqual(o["ts"], "2026-11-11 10:15:00")
        items = self.q("SELECT title, qty, shipped, product_id FROM order_items ORDER BY title")
        self.assertEqual([i["title"] for i in items], ["Брюки/477/чёрный/42", "Юбка/12/синий/44"])
        self.assertTrue(all(i["product_id"] for i in items))

    def test_status_flow_and_history(self):
        shop_orders.mirror([order()])
        shop_orders.mirror([order(shipped=2)])                      # частично собран
        shop_orders.mirror([order(status="собран", shipped=3, закрыт="11.11.2026 12:00")])
        o = self.q("SELECT id, status, closed_at FROM orders")[0]
        self.assertEqual(o["status"], "done")
        self.assertEqual(o["closed_at"], "2026-11-11 12:00:00")
        hist = shop_orders.history(o["id"])
        self.assertEqual([h["to_status"] for h in hist], ["new", "picking", "done"])
        shipped = self.q("SELECT shipped FROM order_items WHERE title LIKE 'Брюки%'")[0]["shipped"]
        self.assertEqual(shipped, 3)

    def test_cancelled_keeps_reason(self):
        shop_orders.mirror([order(status="отменён", отменил="Айгуль", причина="отменил клиент")])
        o = self.q("SELECT status, cancelled_by, reason FROM orders")[0]
        self.assertEqual((o["status"], o["cancelled_by"], o["reason"]),
                         ("cancelled", "Айгуль", "отменил клиент"))

    def test_same_key_as_importer(self):
        """Заказ, уже импортированный из книги (orders:<id>), не дублируется, а получает тип и статус."""
        con = sqldb.connect()
        sqldb.migrate(con)
        con.execute("INSERT INTO orders(id, ts, client, status, external_uuid) VALUES (?,?,?,?,?)",
                    (shop_orders._id("order", "orders:1"), "2026-11-11", "Айгуль", "новый", "orders:1"))
        con.close()
        shop_orders.mirror([order()])
        rows = self.q("SELECT status, type FROM orders")
        self.assertEqual(rows, [{"status": "new", "type": "shop"}])

    def test_unified_list(self):
        shop_orders.mirror([order(1), order(2, status="отменён")])
        res = shop_orders.list_orders("shop")
        self.assertEqual(res["по_типам"], {"shop": 2})
        self.assertEqual({r["status_label"] for r in res["data"]}, {"Новый", "Отменён"})
        self.assertEqual(len(shop_orders.list_orders("shop", "new")["data"]), 1)
        self.assertEqual(shop_orders.list_orders("fbs")["data"], [])


if __name__ == "__main__":
    unittest.main()
