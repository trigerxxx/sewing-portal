# -*- coding: utf-8 -*-
"""«Что докупить»: сырьё всех заказов снабжения против свободного остатка — одним списком."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import cex_api  # noqa: E402


def item(mat, color="", unit="кг", mn=0.0):
    return {"материал": mat, "цвет": color, "ед": unit, "мин": mn, "комментарий": ""}


def line(mat, color, need, unit="кг", status="", have=0.0):
    return {"материал": mat, "цвет": color, "ед": unit, "нужно": need, "статус": status, "есть": have}


def key(mat, color=""):
    return cex_api._wh_key(mat, color)


class PurchaseListTests(unittest.TestCase):
    def setUp(self):
        self.items = {key("Футер", "серый"): item("Футер", "серый", mn=10),
                      key("Нитки"): item("Нитки"),
                      key("Резинка", "чёрный"): item("Резинка", "чёрный", "м")}

    def calc(self, queue, bal, held=None):
        res = cex_api.purchase_list(queue, self.items, bal, held or {})
        return {(r["материал"], r["цвет"]): r for r in res}

    def test_free_stock_counted_once_across_orders(self):
        """Два заказа по 8 кг при 10 свободных: не хватает 6, а не 0 (по заказу «хватает» каждому)."""
        q = [{"номер": "1", "сырьё": [line("Футер", "серый", 8)]},
             {"номер": "2", "сырьё": [line("Футер", "серый", 8)]}]
        r = self.calc(q, {key("Футер", "серый"): 10})[("Футер", "серый")]
        self.assertEqual(r["нужно"], 16)
        self.assertEqual(r["не_хватает"], 6)
        self.assertEqual(r["докупить"], 16)  # + мин. остаток 10
        self.assertEqual([z["номер"] for z in r["заказы"]], ["1", "2"])

    def test_threads_without_color_and_grams(self):
        """Нитки без цвета на складе подходят ко всем цветам; граммы переводятся в кг склада."""
        q = [{"номер": "1", "сырьё": [line("Нитки", "серый", 1500, "г"), line("Нитки", "бежевый", 0.5)]}]
        r = self.calc(q, {key("Нитки"): 1.2})[("Нитки", "")]
        self.assertAlmostEqual(r["нужно"], 2.0)
        self.assertAlmostEqual(r["докупить"], 0.8)

    def test_reserve_and_negative_free_increase_purchase(self):
        q = [{"номер": "1", "сырьё": [line("Нитки", "", 1)]}]
        r = self.calc(q, {key("Нитки"): 2}, {key("Нитки"): 3})[("Нитки", "")]
        self.assertEqual(r["свободно"], -1)
        self.assertEqual(r["докупить"], 2)

    def test_already_ordered_is_subtracted(self):
        q = [{"номер": "1", "сырьё": [line("Резинка", "чёрный", 50, "м", status="заказано", have=30)]}]
        r = self.calc(q, {key("Резинка", "чёрный"): 5})[("Резинка", "чёрный")]
        self.assertEqual(r["заказано"], 30)
        self.assertEqual(r["докупить"], 15)
        q[0]["сырьё"][0]["статус"] = "не хватает"  # количество без статуса «заказано» не вычитается
        self.assertEqual(self.calc(q, {key("Резинка", "чёрный"): 5})[("Резинка", "чёрный")]["докупить"], 45)

    def test_enough_stock_not_listed_but_below_minimum_is(self):
        q = [{"номер": "1", "сырьё": [line("Резинка", "чёрный", 10, "м")]}]
        got = self.calc(q, {key("Резинка", "чёрный"): 100, key("Футер", "серый"): 4})
        self.assertNotIn(("Резинка", "чёрный"), got)
        self.assertEqual(got[("Футер", "серый")]["докупить"], 6)  # до мин. остатка 10
        self.assertEqual(got[("Футер", "серый")]["не_хватает"], 0)

    def test_unknown_material_and_unit_mismatch(self):
        q = [{"номер": "7", "сырьё": [line("Молния", "чёрный", 20, "шт"), line("Футер", "серый", 3, "м")]}]
        got = self.calc(q, {key("Футер", "серый"): 50})
        z = got[("Молния", "чёрный")]
        self.assertFalse(z["на_складе"])
        self.assertEqual((z["докупить"], z["ед"]), (20, "шт"))
        f = got[("Футер", "серый")]
        self.assertEqual(f["единицы_не_сходятся"], ["№7: 3 м"])
        self.assertEqual(f["нужно"], 0)

    def test_shortage_listed_first(self):
        q = [{"номер": "1", "сырьё": [line("Резинка", "чёрный", 10, "м")]}]
        res = cex_api.purchase_list(q, self.items, {key("Футер", "серый"): 4}, {})
        self.assertEqual([r["материал"] for r in res], ["Резинка", "Футер"])


if __name__ == "__main__":
    unittest.main()
