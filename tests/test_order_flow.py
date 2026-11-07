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
    """Расход сырья (модель 477): общая норма и нормы по размерам; считает снабженец,
    читают технолог и закройщик."""

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

    def spec(self):
        return cex_api.supply_state()["очередь"][0]

    def by_size_bom(self):
        """Футер: общая 320 г, но на 44-й 340 г; резинка на 46-й 0,5 м вместо 0,4."""
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "цвет": "", "норма": 320, "ед": "г", "запас": 5,
             "по_размерам": {"44": 340, "46": 360}},
            {"материал": "Резинка", "цвет": "чёрный", "норма": 0.4, "ед": "м",
             "по_размерам": {"46": 0.5}}]})

    # ---- общая норма (как раньше)
    def test_common_norm_in_grams_with_waste(self):
        rows = {r["материал"]: r for r in cex_api.consumption("477")}
        self.assertEqual(rows["Футер"]["на_1_шт"], 336.0)       # 320 г + 5 % отходов
        self.assertEqual(rows["Нитки"]["граммы"], 50.0)         # 0,05 кг = 50 г
        self.assertIsNone(rows["Резинка"]["граммы"])            # метры в граммы не переводим

    def test_supply_need_uses_waste_and_colour_of_product(self):
        need = {(x["материал"], x["цвет"]): x for x in self.spec()["сырьё"]}
        self.assertEqual(need[("Футер", "бежевый")]["нужно"], 33600.0)             # 336 × 100
        self.assertEqual(need[("Футер", "светло-серый меланж")]["нужно"], 16800.0)  # 336 × 50
        self.assertEqual(need[("Футер", "бежевый")]["граммы"], 33600.0)
        self.assertEqual(need[("Резинка", "чёрный")]["нужно"], 60.0)               # 0,4 × 150

    # ---- нормы по размерам
    def test_size_norm_replaces_common_for_that_size_only(self):
        self.by_size_bom()
        table = {r["материал"]: r["по_размерам"] for r in
                 cex_api.piece_table("477", ["42", "44", "46"], cex_api.boms())}
        self.assertEqual([table["Футер"][s]["на_1_шт"] for s in ("42", "44", "46")],
                         [336.0, 357.0, 378.0])                   # 320/340/360 г + 5 %
        self.assertEqual([table["Резинка"][s]["на_1_шт"] for s in ("42", "44", "46")],
                         [0.4, 0.4, 0.5])

    def test_supply_need_counts_each_size_with_its_own_norm(self):
        self.by_size_bom()
        need = {(x["материал"], x["цвет"]): x["нужно"] for x in self.spec()["сырьё"]}
        self.assertEqual(need[("Футер", "бежевый")], 33600.0)                  # 42-й: 336 × 100
        self.assertEqual(need[("Футер", "светло-серый меланж")], 17850.0)      # 44-й: 357 × 50
        self.assertEqual(need[("Резинка", "чёрный")], 60.0)                    # 0,4 × 150

    def test_model_specs_by_size_and_total(self):
        self.by_size_bom()
        spec = self.spec()["расход"]
        self.assertEqual(len(spec), 1)
        m = spec[0]
        self.assertEqual((m["модель"], m["штук"]), ("477", 150))
        self.assertEqual([(x["размер"], x["штук"]) for x in m["размеры"]], [("42", 100), ("44", 50)])
        felt = next(r for r in m["строки"] if r["материал"] == "Футер")
        self.assertEqual(felt["по_размерам"]["42"]["на_1_шт"], 336.0)
        self.assertEqual(felt["по_размерам"]["44"]["на_1_шт"], 357.0)
        self.assertEqual(felt["всего"], 51450.0)                  # 336×100 + 357×50
        self.assertEqual(felt["всего_г"], 51450.0)
        self.assertEqual(m["без_нормы"], [])

    def test_size_without_any_norm_is_reported(self):
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "ед": "г", "по_размерам": {"42": 300}}]})   # нормы для 44 нет
        order = self.spec()
        self.assertIn("477, размер 44", order["без_спецификации"])
        self.assertEqual(order["расход"][0]["без_нормы"], ["44"])
        need = {(x["материал"], x["цвет"]) for x in order["сырьё"]}
        self.assertEqual(need, {("Футер", "бежевый")})            # серый меланж (44) не посчитан

    def test_model_without_bom_is_flagged(self):
        spec = cex_api.model_specs([{"модель": "999", "цвет": "х", "размер": "42", "итог": 5}],
                                   cex_api.boms())
        self.assertTrue(spec[0]["нет_спецификации"])
        self.assertEqual(spec[0]["строки"], [])
        need, missing = cex_api.supply_need([{"модель": "999", "цвет": "х", "размер": "42", "итог": 5}],
                                            cex_api.boms())
        self.assertEqual((need, missing), ([], ["999"]))

    def test_save_bom_validation(self):
        def bad(row, text):
            with self.assertRaises(ValueError, msg=text):
                cex_api.save_bom(ME, {"модель": "477", "строки": [row]})
        bad({"материал": "Футер", "норма": 320, "ед": "г", "запас": 150}, "запас больше 100")
        bad({"материал": "Футер", "норма": 320, "ед": "г", "запас": -1}, "запас меньше 0")
        bad({"материал": "Футер", "ед": "г"}, "нет ни общей нормы, ни по размерам")
        bad({"материал": "Футер", "ед": "г", "по_размерам": {"44": 0}}, "норма размера = 0")
        bad({"материал": "Футер", "ед": "г", "норма": "0"}, "общая норма = 0")
        with self.assertRaises(ValueError):                       # один материал в двух строках
            cex_api.save_bom(ME, {"модель": "477", "строки": [
                {"материал": "Футер", "норма": 320, "ед": "г"},
                {"материал": "футер", "норма": 300, "ед": "г"}]})
        # пустая норма размера — не ошибка: действует общая
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "норма": 320, "ед": "г", "по_размерам": {"44": "", "46": 360}}]})
        sizes = {b["размер"] for b in cex_api.boms()["477"]}
        self.assertEqual(sizes, {"", "46"})

    def test_old_bom_rows_without_size_and_waste_columns_still_work(self):
        # книга, созданная до колонок «размер» и «запас %»: общая норма, запас 0
        self.st.sheets[cex_api.BOM[0]] = [{"модель": "480", "материал": "Футер", "цвет": "",
                                           "норма на 1 шт": 200, "ед.": "г", "параметры": ""}]
        row = cex_api.consumption("480", size="46")[0]
        self.assertEqual((row["запас"], row["на_1_шт"]), (0, 200.0))

    def test_model_sizes_from_orders_cards_and_bom(self):
        self.by_size_bom()
        self.assertEqual(cex_api.model_sizes()["477"], ["42", "44", "46"])

    # ---- закройщик
    def test_cutter_sees_per_size_plan_and_rest(self):
        self.by_size_bom()
        party = {"модель": "477", "строки": [
            {"цвет": "бежевый", "размер": "42", "план": 100, "раскроено": 40, "остаток": 60},
            {"цвет": "светло-серый меланж", "размер": "44", "план": 50, "раскроено": 50, "остаток": 0}]}
        res = cex_api.party_consumption(party, cex_api.boms())
        self.assertEqual(res["размеры"], ["42", "44"])
        felt = next(r for r in res["на_1_шт"] if r["материал"] == "Футер")
        self.assertEqual((felt["по_размерам"]["42"]["на_1_шт"], felt["по_размерам"]["44"]["на_1_шт"]),
                         (336.0, 357.0))
        plan = {(x["материал"], x["цвет"]): x["граммы"] for x in res["план"]}
        rest = {(x["материал"], x["цвет"]): x["граммы"] for x in res["остаток"]}
        self.assertEqual(plan[("Футер", "бежевый")], 33600.0)
        self.assertEqual(plan[("Футер", "светло-серый меланж")], 17850.0)   # 357 × 50
        self.assertEqual(rest[("Футер", "бежевый")], 20160.0)               # 336 × 60 ещё не раскроено
        self.assertNotIn(("Футер", "светло-серый меланж"), rest)

    # ---- рулоны
    def test_roll_hint_matches_material_and_colour(self):
        cex_api.save_supply(ME, {"номер": "9", "строки": []})
        cex_api.add_roll(ME, {"код": "R-5", "материал": "Футер", "цвет": "бежевый", "граммы": 240,
                              "вес": 30, "заказ": "9"})
        cex_api.add_roll(ME, {"код": "R-6", "материал": "Футер", "цвет": "бежевый", "вес": 20})
        lines = self.spec()["сырьё"]
        beige = next(x for x in lines if (x["материал"], x["цвет"]) == ("Футер", "бежевый"))
        self.assertEqual((beige["рулоны"]["рулонов"], beige["рулоны"]["кг"], beige["рулоны"]["под_заказ_кг"]),
                         (2, 50.0, 30.0))
        grey = next(x for x in lines if x["цвет"] == "светло-серый меланж")
        self.assertIsNone(grey["рулоны"])                         # такого рулона не заносили
        elastic = next(x for x in lines if x["материал"] == "Резинка")
        self.assertIsNone(elastic["рулоны"])                      # метры — подсказки нет


if __name__ == "__main__":
    unittest.main()
