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


class WarehouseTests(unittest.TestCase):
    """Склад сырья («холодильник»): приход, остаток, резерв и автосписание при крое по норме размера."""

    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()
        base = {"№ заказа": 9, "дата": "07.11.2026", "клиент": "Свой цех", "источник": cex_api.OWN,
                "категория": "Брюки", "модель": "477", "цвет": "бежевый", "статус": cex_api.DESIGN}
        self.st.sheets[cex_api.ORDERS[0]] = [dict(base, размер="42", количество=100)]
        cex_api.save_design(ME, {"номер": "9", "готово": True, "позиции": [
            {"модель": "477", "цвет": "бежевый", "размер": "42", "итог": 100},
            {"модель": "477", "цвет": "светло-серый", "размер": "44", "итог": 50}]})
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "норма": 320, "ед": "г", "запас": 5, "по_размерам": {"44": 340}},
            {"материал": "Резинка", "цвет": "чёрный", "норма": 0.4, "ед": "м"},
            {"материал": "Нитки", "норма": 0.05, "ед": "кг"}]})
        cex_api.save_supply(ME, {"номер": "9", "готово": True, "строки": []})

    def tearDown(self):
        cex_api.store = self._old

    # ---- помощники
    def stock_up(self):
        for mat, color, qty, unit in (("Футер", "бежевый", 100, "кг"), ("Футер", "светло-серый", 100, "кг"),
                                      ("Нитки", "", 10, "кг"), ("Резинка", "чёрный", 100, "м")):
            cex_api.wh_receive(ME, {"материал": mat, "цвет": color, "количество": qty, "ед": unit})

    def accept(self):
        cex_api.apply_decision(ME, {"номер": "9", "позиции": [
            {"модель": "477", "цвет": "бежевый", "размер": "42", "количество": 100},
            {"модель": "477", "цвет": "светло-серый", "размер": "44", "количество": 50}]})
        return next(p for p in cex_api.cut_state()["партии"] if p["заказ"] == "9")["номер"]

    def have(self, material, color=""):
        pos = {(x["материал"], x["цвет"]): x for x in cex_api.wh_state()["позиции"]}
        return pos[(material, color)]

    # ---- приход и остаток
    def test_receive_converts_units_and_creates_item(self):
        cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 100, "ед": "кг"})
        cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 5000, "ед": "г"})
        pos = self.have("Футер", "бежевый")
        self.assertEqual((pos["остаток"], pos["ед"]), (105.0, "кг"))
        with self.assertRaises(ValueError):                       # метры в килограммы не переводим
            cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 3, "ед": "м"})
        with self.assertRaises(ValueError):
            cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 0})

    def test_adjust_writes_difference(self):
        cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 100, "ед": "кг"})
        res = cex_api.wh_adjust(ME, {"материал": "Футер", "цвет": "бежевый", "остаток": 90})
        self.assertEqual((res["изменение"], res["остаток"]), (-10.0, 90.0))
        journal = cex_api.wh_state()["движения"]
        self.assertEqual([j["тип"] for j in journal], ["корректировка", "приход"])
        with self.assertRaises(ValueError):
            cex_api.wh_adjust(ME, {"материал": "Футер", "цвет": "бежевый", "остаток": -1})

    def test_roll_registry_feeds_stock(self):
        res = cex_api.add_roll(ME, {"код": "R-1", "материал": "Футер", "цвет": "бежевый", "вес": 25})
        self.assertTrue(res["склад"]["записан"])
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 25.0)
        res = cex_api.add_roll(ME, {"код": "R-2", "вес": 10})     # материал не указан
        self.assertFalse(res["склад"]["записан"])
        self.assertEqual(len(cex_api.wh_state()["движения"]), 1)

    # ---- снабжение видит склад
    def test_supply_line_shows_stock_and_shortage(self):
        cex_api.wh_receive(ME, {"материал": "Футер", "цвет": "бежевый", "количество": 30, "ед": "кг"})
        order = cex_api.supply_state()["очередь"]
        self.assertEqual(order, [])                               # заказ уже ушёл технологу
        # вернём заказ снабженцу и посмотрим строки
        for r in self.st.sheets[cex_api.ORDERS[0]]:
            r["статус"] = cex_api.SUPPLYING
        lines = {(x["материал"], x["цвет"]): x for x in cex_api.supply_state()["очередь"][0]["сырьё"]}
        felt = lines[("Футер", "бежевый")]["склад"]
        self.assertEqual((felt["остаток"], felt["нужно_в_ед"], felt["не_хватает"]), (30.0, 33.6, 3.6))
        self.assertFalse(lines[("Футер", "светло-серый")]["склад"]["позиция"])   # такого на складе нет

    def test_colourless_material_is_shared_between_colours_of_order(self):
        """Нитки без цвета на складе одни на все цвета заказа: хватает не каждой строке отдельно."""
        cex_api.wh_receive(ME, {"материал": "Нитки", "количество": 6, "ед": "кг"})
        for r in self.st.sheets[cex_api.ORDERS[0]]:
            r["статус"] = cex_api.SUPPLYING
        threads = [x for x in cex_api.supply_state()["очередь"][0]["сырьё"] if x["материал"] == "Нитки"]
        self.assertEqual(len(threads), 2)                       # бежевый 5 кг и светло-серый 2,5 кг
        short = sorted(x["склад"]["не_хватает"] for x in threads)
        self.assertEqual(short, [0.0, 1.5])                     # 6 кг: первой строке хватило, второй не хватает 1,5

    # ---- автосписание при крое
    def test_cut_writes_off_by_size_norm(self):
        self.stock_up()
        num = self.accept()
        res = cex_api.save_cut(ME, {"партия": num, "позиции": [
            {"цвет": "бежевый", "размер": "42", "факт": 40},
            {"цвет": "светло-серый", "размер": "44", "факт": 50}]})
        self.assertEqual(res["склад"]["предупреждения"], [])
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 86.56)          # 100 − 0,336 × 40
        self.assertEqual(self.have("Футер", "светло-серый")["остаток"], 82.15)     # 100 − 0,357 × 50 (норма 44-го)
        self.assertEqual(self.have("Нитки")["остаток"], 5.5)                        # 0,05 кг × 90 шт, без цвета
        self.assertEqual(self.have("Резинка", "чёрный")["остаток"], 64.0)           # 0,4 м × 90 шт
        used = {(x["материал"], x["цвет"]): x["количество"] for x in res["склад"]["списано"]}
        self.assertEqual(used[("Футер", "бежевый")], 13.44)
        rows = [m for m in cex_api.wh_state()["движения"] if m["тип"] == "расход"]
        self.assertTrue(rows and all(m["партия"] == num and m["изменение"] < 0 for m in rows))

    def test_cut_without_stock_goes_negative_and_is_visible(self):
        num = self.accept()
        cex_api.save_cut(ME, {"партия": num, "позиции": [{"цвет": "бежевый", "размер": "42", "факт": 10}]})
        pos = self.have("Футер", "бежевый")
        self.assertEqual(pos["остаток"], -3.36)
        self.assertTrue(pos["минус"])

    def test_unit_mismatch_is_reported_not_written(self):
        cex_api.wh_item(ME, {"материал": "Резинка", "цвет": "чёрный", "ед": "кг"})   # на складе в кг, в справочнике в м
        num = self.accept()
        res = cex_api.save_cut(ME, {"партия": num, "позиции": [{"цвет": "бежевый", "размер": "42", "факт": 10}]})
        self.assertTrue(any("Резинка" in w and "не списано" in w for w in res["склад"]["предупреждения"]))
        self.assertEqual(self.have("Резинка", "чёрный")["остаток"], 0.0)

    def test_size_without_norm_is_not_written_off(self):
        cex_api.save_bom(ME, {"модель": "477", "строки": [
            {"материал": "Футер", "ед": "г", "по_размерам": {"42": 300}}]})        # для 44-го нормы нет
        self.stock_up()
        num = self.accept()
        res = cex_api.save_cut(ME, {"партия": num, "позиции": [
            {"цвет": "бежевый", "размер": "42", "факт": 10}, {"цвет": "светло-серый", "размер": "44", "факт": 10}]})
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 97.0)
        self.assertEqual(self.have("Футер", "светло-серый")["остаток"], 100.0)
        self.assertTrue(any("477, размер 44" in w for w in res["склад"]["предупреждения"]))

    # ---- резерв
    def test_reserve_follows_unfinished_parties(self):
        self.stock_up()
        self.accept()
        pos = self.have("Футер", "бежевый")
        self.assertEqual((pos["остаток"], pos["резерв"], pos["свободно"]), (100.0, 33.6, 66.4))
        num = next(p for p in cex_api.cut_state()["партии"] if p["заказ"] == "9")["номер"]
        cex_api.save_cut(ME, {"партия": num, "позиции": [{"цвет": "бежевый", "размер": "42", "факт": 40}]})
        pos = self.have("Футер", "бежевый")
        self.assertEqual((pos["остаток"], pos["резерв"]), (86.56, 20.16))           # осталось раскроить 60 шт

    # ---- исправление технолога
    def test_fix_cut_returns_or_takes_more(self):
        self.stock_up()
        num = self.accept()
        cex_api.save_cut(ME, {"партия": num, "позиции": [{"цвет": "бежевый", "размер": "42", "факт": 40}]})
        nas = cex_api.cut_state()["партии"][0]["настилы"][0]["настил"]
        cex_api.fix_cut(ME, {"партия": num, "строки": [{"настил": nas, "цвет": "бежевый", "размер": "42", "факт": 30}]})
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 89.92)           # вернули 10 шт × 0,336
        self.assertIn("возврат", [m["тип"] for m in cex_api.wh_state()["движения"]])
        cex_api.fix_cut(ME, {"партия": num, "строки": [{"настил": nas, "цвет": "бежевый", "размер": "42", "факт": 35}]})
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 88.24)           # докинули 5 шт

    def test_fix_of_old_cut_without_writeoff_does_not_inflate_stock(self):
        self.stock_up()
        num = self.accept()
        cex_api.save_cut(ME, {"партия": num, "позиции": [{"цвет": "бежевый", "размер": "42", "факт": 40}]})
        self.st.sheets[cex_api.WH_MOVES[0]] = [m for m in self.st.sheets[cex_api.WH_MOVES[0]] if m["тип"] == "приход"]
        nas = cex_api.cut_state()["партии"][0]["настилы"][0]["настил"]
        res = cex_api.fix_cut(ME, {"партия": num, "строки": [{"настил": nas, "цвет": "бежевый", "размер": "42", "факт": 30}]})
        self.assertEqual(res["склад"]["движений"], 0)
        self.assertEqual(self.have("Футер", "бежевый")["остаток"], 100.0)


if __name__ == "__main__":
    unittest.main()
