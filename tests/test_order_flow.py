# -*- coding: utf-8 -*-
"""Поток заказа: конструктор (карта + история) → снабженец (спецификация, сырьё, рулоны) → технолог."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import cex_api  # noqa: E402


class FakeStore:
    """Рабочая книга в памяти: настоящий Excel не трогается."""
    CexLocked = cex_api.store.CexLocked
    CexSourceError = cex_api.store.CexSourceError

    def __init__(self):
        self.sheets: dict[str, list[dict]] = {}

    def read_sheet(self, name):
        return [dict(r) for r in self.sheets.get(name, [])]

    def write_sheet(self, name, headers, rows):
        self.sheets[name] = [{h: r.get(h, "") for h in headers} for r in rows]

    def write_sheets(self, items):
        for name, headers, rows in items:
            self.write_sheet(name, headers, rows)

    def append_rows(self, name, headers, rows):
        self.write_sheet(name, headers, self.read_sheet(name) + list(rows))

    def ensure_sheets(self, specs):
        return []

    def first_row(self, name):
        return []


ME = {"логин": "boss", "фио": "Тест", "роль": "admin"}


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()
        base = {"№ заказа": 7, "дата": "01.11.2026", "клиент": "Свой цех", "источник": cex_api.OWN,
                "категория": "Платья", "модель": "П1", "цвет": "Красный", "статус": cex_api.DESIGN}
        self.st.sheets[cex_api.ORDERS[0]] = [dict(base, размер="42", количество=10),
                                             dict(base, размер="44", количество=5)]

    def tearDown(self):
        cex_api.store = self._old

    def order(self):
        return next(o for o in cex_api.orders() if o["номер"] == "7")

    def test_full_flow(self):
        # технолог заказ у конструктора пока не видит
        self.assertEqual(cex_api.queue(), [])

        cex_api.save_design(ME, {"номер": "7", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 12, "характеристики": "длина 110"},
            {"модель": "П1", "цвет": "Красный", "размер": "44", "итог": 3},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "итог": 4},
        ]})
        self.assertEqual(self.order()["статус"], cex_api.DESIGN)
        # второе сохранение — тоже в истории
        res = cex_api.save_design(ME, {"номер": "7", "готово": True, "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 13, "характеристики": "длина 110"},
            {"модель": "П1", "цвет": "Красный", "размер": "44", "итог": 3},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "итог": 4},
        ]})
        self.assertEqual(res["статус"], cex_api.SUPPLYING)
        o = self.order()
        self.assertEqual((o["заказано"], o["штук"]), (15, 20))  # исходное и итоговое — отдельно
        hist = cex_api.card_history(["7"])["7"]
        moves = [(h["размер"], h["было"], h["стало"]) for h in hist if h["размер"]]
        self.assertIn(("42", "10", "12"), moves)
        self.assertIn(("42", "12", "13"), moves)
        self.assertIn(("44", "5", "3"), moves)
        self.assertIn(("46", "0", "4"), moves)
        with self.assertRaises(ValueError):  # карта закрыта — заказ уже у снабженца
            cex_api.save_design(ME, {"номер": "7", "позиции": [{"модель": "П1", "цвет": "К", "итог": 1}]})

        cex_api.save_bom(ME, {"модель": "П1", "строки": [
            {"материал": "Ткань", "цвет": "", "норма": 1.5, "ед": "м"},
            {"материал": "Нитки", "цвет": "Белый", "норма": 0.1, "ед": "бобина"}]})
        st = cex_api.supply_state()
        need = {(x["материал"], x["цвет"]): x["нужно"] for x in st["очередь"][0]["сырьё"]}
        self.assertEqual(need[("Ткань", "Красный")], 30.0)  # 1.5 × 20, цвет изделия
        self.assertEqual(need[("Нитки", "Белый")], 2.0)

        cex_api.add_roll(ME, {"код": "R-1", "материал": "Ткань", "цвет": "Красный", "граммы": 180, "вес": 25})
        with self.assertRaises(ValueError):
            cex_api.add_roll(ME, {"код": "R-1", "вес": 1})
        self.assertIn("R-1", cex_api.roll_registry())

        cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [
            {"материал": "Ткань", "цвет": "Красный", "ед": "м", "нужно": 30, "есть": 30,
             "статус": "есть на складе"}]})
        self.assertEqual([q["номер"] for q in cex_api.queue()], ["7"])

        # технолог принимает по итогу карты — больше, чем было в заказе
        res = cex_api.apply_decision(ME, {"номер": "7", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "количество": 13},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "количество": 4}]})
        self.assertEqual(res["штук"], 17)
        self.assertEqual(res["статус"], "принят частично")

    def test_old_orders_stay_with_technologist(self):
        for r in self.st.sheets[cex_api.ORDERS[0]]:
            r["статус"] = cex_api.NEW
        self.assertEqual(self.order()["штук"], 15)
        self.assertEqual([q["номер"] for q in cex_api.queue()], ["7"])


class ConsumptionTests(unittest.TestCase):
    """Расход сырья на 1 шт (модель 477): снабженец считает, технолог и закройщик читают."""

    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()
        base = {"№ заказа": 9, "дата": "07.11.2026", "клиент": "Свой цех", "источник": cex_api.OWN,
                "категория": "Брюки", "модель": "477", "цвет": "бежевый", "статус": cex_api.DESIGN}
        self.st.sheets[cex_api.ORDERS[0]] = [dict(base, размер="42", количество=100)]
        cex_api.save_design(ME, {"номер": "9", "готово": True, "позиции": [
            {"модель": "477", "цвет": "бежевый", "размер": "42", "итог": 100},
            {"модель": "477", "цвет": "светло-серый меланж", "размер": "44", "итог": 50}]})
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "цвет": "", "норма": 320, "ед": "г", "запас": 5},
            {"материал": "Резинка", "цвет": "чёрный", "норма": 0.4, "ед": "м"},
            {"материал": "Нитки", "цвет": "", "норма": 0.05, "ед": "кг"}]})

    def tearDown(self):
        cex_api.store = self._old

    def test_per_piece_in_grams_with_waste(self):
        rows = {r["материал"]: r for r in cex_api.consumption("477")}
        self.assertEqual(rows["Футер"]["на_1_шт"], 336.0)       # 320 г + 5 % отходов
        self.assertEqual(rows["Футер"]["граммы"], 336.0)
        self.assertEqual(rows["Нитки"]["граммы"], 50.0)         # 0,05 кг = 50 г
        self.assertIsNone(rows["Резинка"]["граммы"])            # метры в граммы не переводим

    def test_supply_need_uses_waste_and_colour_of_product(self):
        lines = cex_api.supply_state()["очередь"][0]["сырьё"]
        need = {(x["материал"], x["цвет"]): x for x in lines}
        self.assertEqual(need[("Футер", "бежевый")]["нужно"], 33600.0)             # 336 × 100
        self.assertEqual(need[("Футер", "светло-серый меланж")]["нужно"], 16800.0)  # 336 × 50
        self.assertEqual(need[("Футер", "бежевый")]["граммы"], 33600.0)
        self.assertEqual(need[("Резинка", "чёрный")]["нужно"], 60.0)               # 0,4 × 150

    def test_model_specs_totals_for_order(self):
        spec = cex_api.supply_state()["очередь"][0]["расход"]
        self.assertEqual(len(spec), 1)
        self.assertEqual((spec[0]["модель"], spec[0]["штук"]), ("477", 150))
        total = {r["материал"]: r["всего_г"] for r in spec[0]["строки"]}
        self.assertEqual(total["Футер"], 50400.0)               # 336 г × 150 шт = 50,4 кг
        self.assertEqual(spec[0]["нет_спецификации"], False)

    def test_model_without_bom_is_flagged(self):
        spec = cex_api.model_specs([{"модель": "999", "цвет": "х", "размер": "42", "итог": 5}], cex_api.boms())
        self.assertTrue(spec[0]["нет_спецификации"])
        self.assertEqual(spec[0]["строки"], [])

    def test_waste_must_be_sane(self):
        with self.assertRaises(ValueError):
            cex_api.save_bom(ME, {"модель": "477", "строки": [
                {"материал": "Футер", "норма": 320, "ед": "г", "запас": 150}]})
        with self.assertRaises(ValueError):
            cex_api.save_bom(ME, {"модель": "477", "строки": [
                {"материал": "Футер", "норма": 320, "ед": "г", "запас": -1}]})

    def test_old_bom_without_waste_column_still_works(self):
        # книга, созданная до появления колонки «запас %»: поле пустое = 0 %
        self.st.sheets[cex_api.BOM[0]] = [{"модель": "480", "материал": "Футер", "цвет": "",
                                           "норма на 1 шт": 200, "ед.": "г", "параметры": ""}]
        row = cex_api.consumption("480")[0]
        self.assertEqual((row["запас"], row["на_1_шт"]), (0, 200.0))

    def test_cutter_sees_plan_and_rest(self):
        party = {"модель": "477", "строки": [
            {"цвет": "бежевый", "размер": "42", "план": 100, "раскроено": 40, "остаток": 60},
            {"цвет": "светло-серый меланж", "размер": "44", "план": 50, "раскроено": 50, "остаток": 0}]}
        res = cex_api.party_consumption(party, cex_api.boms())
        plan = {(x["материал"], x["цвет"]): x["граммы"] for x in res["план"]}
        rest = {(x["материал"], x["цвет"]): x["граммы"] for x in res["остаток"]}
        self.assertEqual(plan[("Футер", "бежевый")], 33600.0)
        self.assertEqual(rest[("Футер", "бежевый")], 20160.0)    # 336 × 60 ещё не раскроено
        self.assertNotIn(("Футер", "светло-серый меланж"), rest)  # уже раскроено целиком
        self.assertEqual(res["на_1_шт"][0]["материал"], "Футер")

    def test_roll_hint_matches_material_and_colour(self):
        cex_api.save_supply(ME, {"номер": "9", "строки": []})
        cex_api.add_roll(ME, {"код": "R-5", "материал": "Футер", "цвет": "бежевый", "граммы": 240,
                              "вес": 30, "заказ": "9"})
        cex_api.add_roll(ME, {"код": "R-6", "материал": "Футер", "цвет": "бежевый", "вес": 20})
        lines = cex_api.supply_state()["очередь"][0]["сырьё"]
        beige = next(x for x in lines if (x["материал"], x["цвет"]) == ("Футер", "бежевый"))
        self.assertEqual((beige["рулоны"]["рулонов"], beige["рулоны"]["кг"], beige["рулоны"]["под_заказ_кг"]),
                         (2, 50.0, 30.0))
        grey = next(x for x in lines if x["цвет"] == "светло-серый меланж")
        self.assertIsNone(grey["рулоны"])                         # такого рулона не заносили
        elastic = next(x for x in lines if x["материал"] == "Резинка")
        self.assertIsNone(elastic["рулоны"])                      # метры — подсказки нет


if __name__ == "__main__":
    unittest.main()
