# -*- coding: utf-8 -*-
"""Демо цеха одной командой: маленькая книга Excel с примерами вместо рабочей книги заказчика.

    python3 seed.py          # демо-пользователи (один раз)
    python3 demo_cex.py      # создать демо-книгу и заполнить примерами
    python3 server.py --port 8787
    открыть /cex/   (компания Ц-01, логин boss, пароль 123456)

Рабочую книгу заказчика это не трогает: путь к книге хранится в data/цех_источник.txt,
и скрипт его переписывает. Чтобы вернуться на рабочую книгу: `python3 demo_cex.py --back`
(или впишите её путь в data/цех_источник.txt сами). Все данные здесь выдуманные.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import cex_api as api
import cex_store as store

BASE = Path(__file__).resolve().parent
DEMO = store.DATA / "demo_цех.xlsx"
BACKUP_PTR = store.DATA / "цех_источник.до_демо.txt"
ME = {"логин": "boss", "фио": "Асанов Эрлан", "роль": "admin"}

_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
       '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
       '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
         '</Relationships>')
_WB = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
       '<sheets><sheet name="Демо" sheetId="1" r:id="rId1"/></sheets></workbook>')
_WB_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="/xl/worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="/xl/styles.xml"/>'
            '</Relationships>')
_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
           '</styleSheet>')
_SHEET = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<sheetData/></worksheet>')


def make_book(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CT)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("xl/workbook.xml", _WB)
        zf.writestr("xl/_rels/workbook.xml.rels", _WB_RELS)
        zf.writestr("xl/styles.xml", _STYLES)
        zf.writestr("xl/worksheets/sheet1.xml", _SHEET)


def _order(num: int, model: str, category: str, color: str, sizes: dict, status: str) -> list[dict]:
    return [{"№ заказа": num, "дата": "05.11.2026", "клиент": "Свой цех", "источник": api.OWN,
             "категория": category, "модель": model, "цвет": color, "размер": size,
             "количество": qty, "срок": "20.11.2026", "статус": status, "создал": "boss"}
            for size, qty in sizes.items()]


def fill() -> None:
    api.ensure_sheets()

    # справочники
    sizes = ["40", "42", "44", "46", "48"]
    api.store.write_sheets([
        (api.MODELS[0], api.MODELS[1], [
            {"категория": "Брюки", "модель": "477", "название": "Брюки 477 (футер)",
             "размерная сетка": "числовая", "цена": 1200, "активна": 1},
            {"категория": "Платья", "модель": "П1", "название": "Платье П1",
             "размерная сетка": "числовая", "цена": 1800, "активна": 1}]),
        (api.COLORS[0], api.COLORS[1], [{"цвет": c, "код тона": "", "активен": 1} for c in
                                        ("бежевый", "светло-серый меланж", "чёрный", "красный")]),
        (api.SIZES[0], api.SIZES[1], [{"сетка": "числовая", "размер": s, "порядок": i * 10}
                                      for i, s in enumerate(sizes, start=1)]),
    ])

    # три заказа на разных шагах: у конструктора / у снабженца / у технолога
    rows = (_order(101, "477", "Брюки", "бежевый", {"42": 60, "44": 60, "46": 40}, api.DESIGN)
            + _order(102, "477", "Брюки", "светло-серый меланж", {"42": 30, "44": 30, "46": 20, "48": 10},
                     api.DESIGN)
            + _order(103, "П1", "Платья", "красный", {"42": 20, "44": 20, "46": 10}, api.DESIGN)
            + _order(104, "477", "Брюки", "чёрный", {"42": 40, "44": 40, "46": 20}, api.DESIGN))
    api.store.write_sheets([(api.ORDERS[0], api.ORDERS[1], rows)])

    # справочник товара: сколько сырья на 1 шт; для больших размеров норма своя
    api.save_bom(ME, {"модель": "477", "строки": [
        {"материал": "Футер", "цвет": "", "норма": 320, "ед": "г", "запас": 5,
         "по_размерам": {"46": 345, "48": 370}},
        {"материал": "Резинка", "цвет": "чёрный", "норма": 0.4, "ед": "м"},
        {"материал": "Нитки", "цвет": "", "норма": 0.05, "ед": "кг"}]})
    api.save_bom(ME, {"модель": "П1", "строки": [
        {"материал": "Штапель", "цвет": "", "норма": 1.6, "ед": "м", "запас": 3},
        {"материал": "Молния", "цвет": "красный", "норма": 1, "ед": "шт"},
        {"материал": "Нитки", "цвет": "", "норма": 0.03, "ед": "кг"}]})

    # склад («холодильник»): приход «по факту»
    for mat, color, qty, unit in (("Футер", "бежевый", 90, "кг"), ("Футер", "светло-серый меланж", 6, "кг"),
                                  ("Футер", "чёрный", 60, "кг"),
                                  ("Резинка", "чёрный", 300, "м"), ("Нитки", "", 4, "кг"),
                                  ("Штапель", "красный", 80, "м"), ("Молния", "красный", 25, "шт")):
        api.wh_receive(ME, {"материал": mat, "цвет": color, "количество": qty, "ед": unit,
                            "комментарий": "демо: стартовый остаток"})
    api.wh_item(ME, {"материал": "Футер", "цвет": "светло-серый меланж", "мин": 10})

    def card(num, model, color, items):
        return {"номер": num, "готово": True, "позиции": [
            {"модель": model, "цвет": color, "размер": s, "итог": q} for s, q in items.items()]}

    # заказ 104 прошёл весь путь и принят технологом → партия ждёт кроя (при крое сырьё спишется)
    api.save_design(ME, card("104", "477", "чёрный", {"42": 40, "44": 40, "46": 20}))
    api.save_supply(ME, {"номер": "104", "готово": True, "строки": [
        {"материал": "Футер", "цвет": "чёрный", "ед": "г", "нужно": 34000, "есть": 34000,
         "статус": "есть на складе"}]})
    api.apply_decision(ME, {"номер": "104", "позиции": [
        {"модель": "477", "цвет": "чёрный", "размер": s, "количество": q}
        for s, q in (("42", 40), ("44", 40), ("46", 20))]})

    # заказ 102 прошёл карту → у снабженца (там видно, что серого футера не хватает)
    api.save_design(ME, card("102", "477", "светло-серый меланж", {"42": 30, "44": 30, "46": 20, "48": 10}))
    # заказ 103 прошёл карту и снабжение → ждёт технолога; заказ 101 остаётся у конструктора
    api.save_design(ME, card("103", "П1", "красный", {"42": 20, "44": 20, "46": 10}))
    api.save_supply(ME, {"номер": "103", "готово": True, "строки": [
        {"материал": "Штапель", "цвет": "красный", "ед": "м", "нужно": 85, "есть": 80, "статус": "заказано"}]})


def back() -> None:
    if BACKUP_PTR.exists():
        store.SRC_FILE.write_text(BACKUP_PTR.read_text(encoding="utf-8"), encoding="utf-8")
        BACKUP_PTR.unlink()
        print("Источник возвращён:", store.source_path())
    elif store.SRC_FILE.exists() and Path(store.SRC_FILE.read_text("utf-8").strip()) == DEMO:
        store.SRC_FILE.unlink()  # дальше сервер сам возьмёт рабочую книгу (или копию из workbook/)
        print("Демо отключено. Источник:", store.source_path())
    else:
        print("Нечего возвращать: демо не запускалось.")


def main(argv: list[str]) -> int:
    if "--back" in argv:
        back()
        return 0
    if store.SRC_FILE.exists() and not BACKUP_PTR.exists() and store.SRC_FILE.read_text("utf-8").strip() \
            and Path(store.SRC_FILE.read_text("utf-8").strip()) != DEMO:
        BACKUP_PTR.write_text(store.SRC_FILE.read_text("utf-8"), encoding="utf-8")
    if DEMO.exists():
        DEMO.unlink()
    make_book(DEMO)
    store.set_source(DEMO)
    fill()
    print("Готово. Демо-книга:", DEMO)
    print("Дальше: python3 server.py --port 8787 → открыть /cex/ (Ц-01 / boss / 123456)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
