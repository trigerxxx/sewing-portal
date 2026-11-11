# -*- coding: utf-8 -*-
"""Заказы магазина в общей таблице orders(type='shop').

Главный источник по-прежнему реестр склада (data/склад_реестр.json): на нём держатся
запись в Excel и офлайн-склад на телефонах. Здесь каждый заказ реестра отражается
в SQL вместе с позициями и историей статусов — так все заказы (FBS и магазин)
видны в одной таблице и одним запросом.

Отражение идемпотентно: ключ заказа тот же, что у sql/importer.py (`orders:<id>`),
поэтому повторный проход и импорт из книги не плодят дубли.
"""
from __future__ import annotations

import hashlib
import sys
import threading
from datetime import datetime
from pathlib import Path

_SQL = Path(__file__).resolve().parent / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))

import db as sqldb

# статусы реестра → общие коды (как у FBS, см. wb_sync.LABELS)
STATUS = {
    "новый": "new",
    "собирается": "picking",
    "собран": "done",
    "отменён": "cancelled",
}
LABELS = {"new": "Новый", "picking": "Собирается", "done": "Собран", "cancelled": "Отменён"}

_LOCK = threading.Lock()
_timer: threading.Timer | None = None
_timer_lock = threading.Lock()
DEBOUNCE = 1.5


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return 0.0


def _ts(raw: str) -> str:
    """«11.11.2026 14:05» → «2026-11-11 14:05:00» (как в остальных таблицах)."""
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return sqldb.now()


def _status(order: dict) -> str:
    raw = (order.get("статус") or "новый").strip()
    code = STATUS.get(raw, "new")
    if code == "new" and any(_num(p.get("отгружено")) > 0 for p in order.get("позиции") or []):
        code = "picking"
    return code


def _product(con, name: str) -> str:
    row = con.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    parts = [p.strip() for p in name.split("/")]
    pid = _id("product", name)
    con.execute(
        "INSERT INTO products(id, name, category, model, color, size, created_at) VALUES (?,?,?,?,?,?,?)",
        (pid, name, parts[0] if parts else "", parts[1] if len(parts) > 1 else "",
         parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else "", sqldb.now()))
    return pid


def _upsert(con, order: dict) -> str:
    """Возвращает 'created' | 'updated' | 'same'."""
    oid = int(order.get("id") or 0)
    ext = f"orders:{oid}"
    sid = _id("order", ext)
    status = _status(order)
    client = str(order.get("клиент") or "—")
    ts = _ts(order.get("дата") or "")
    closed = _ts(order["закрыт"]) if order.get("закрыт") else None
    row = con.execute("SELECT status, type FROM orders WHERE id = ?", (sid,)).fetchone()
    outcome = "same"
    if not row:
        con.execute(
            """INSERT INTO orders(id, ts, client, status, closed_at, cancelled_by, reason, external_uuid,
                   type, external_id, customer_name, source, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, ts, client, status, closed, order.get("отменил"), order.get("причина"), ext,
             "shop", str(oid), client, "app", sqldb.now()))
        con.execute(
            "INSERT INTO order_status_history(order_id, from_status, to_status, actor, at, comment) "
            "VALUES (?,?,?,?,?,?)", (sid, None, "new", client, ts, "заказ из магазина"))
        if status != "new":
            con.execute(
                "INSERT INTO order_status_history(order_id, from_status, to_status, actor, at, comment) "
                "VALUES (?,?,?,?,?,?)",
                (sid, "new", status, order.get("отменил") or "склад", closed or sqldb.now(),
                 order.get("причина") or ""))
        outcome = "created"
    else:
        if row["status"] != status or row["type"] != "shop":
            con.execute(
                """UPDATE orders SET status=?, type='shop', external_id=?, customer_name=?, closed_at=?,
                       cancelled_by=?, reason=?, updated_at=? WHERE id=?""",
                (status, str(oid), client, closed, order.get("отменил"), order.get("причина"),
                 sqldb.now(), sid))
            if row["status"] != status:
                con.execute(
                    "INSERT INTO order_status_history(order_id, from_status, to_status, actor, at, comment) "
                    "VALUES (?,?,?,?,?,?)",
                    (sid, row["status"], status, order.get("отменил") or "склад", sqldb.now(),
                     order.get("причина") or ""))
            outcome = "updated"

    for pos in order.get("позиции") or []:
        name = str(pos.get("наименование") or "").strip()
        if not name:
            continue
        item_id = _id("order_item", ext, name)
        qty, shipped = _num(pos.get("количество")), _num(pos.get("отгружено"))
        cur = con.execute("SELECT qty, shipped FROM order_items WHERE id = ?", (item_id,)).fetchone()
        if not cur:
            con.execute(
                "INSERT INTO order_items(id, order_id, product_id, qty, shipped, title) VALUES (?,?,?,?,?,?)",
                (item_id, sid, _product(con, name), qty, shipped, name))
            outcome = "updated" if outcome == "same" else outcome
        elif cur["qty"] != qty or (cur["shipped"] or 0) != shipped:
            con.execute("UPDATE order_items SET qty=?, shipped=?, title=? WHERE id=?",
                        (qty, shipped, name, item_id))
            outcome = "updated" if outcome == "same" else outcome
    return outcome


def mirror(orders: list[dict] | None = None) -> dict:
    """Отражает все заказы реестра в SQL. Без аргумента берёт их из реестра склада."""
    if orders is None:
        import warehouse
        orders = warehouse.orders()
    stats = {"заказов": 0, "создано": 0, "обновлено": 0}
    with _LOCK:
        con = sqldb.connect()
        try:
            sqldb.migrate(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                for order in orders:
                    if not order.get("id"):
                        continue
                    outcome = _upsert(con, order)
                    stats["заказов"] += 1
                    stats["создано"] += outcome == "created"
                    stats["обновлено"] += outcome == "updated"
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
    return stats


def _run_safely() -> None:
    try:
        mirror()
    except Exception as exc:  # noqa: BLE001
        print("заказы магазина не отражены в SQL:", exc)


def schedule() -> None:
    """Отразить чуть позже (серия записей реестра — один проход). Ошибки не мешают складу."""
    global _timer
    with _timer_lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DEBOUNCE, _run_safely)
        _timer.daemon = True
        _timer.start()


def list_orders(type_: str | None = None, status: str | None = None, limit: int = 300) -> dict:
    """Единый список заказов (магазин + FBS) из SQL, с позициями и счётчиками по типам."""
    import wb_sync
    labels = {**wb_sync.LABELS, **LABELS}
    con = sqldb.connect()
    try:
        sql = """SELECT o.*, (SELECT COUNT(*) FROM order_items i WHERE i.order_id = o.id) AS items
                 FROM orders o WHERE o.type IN ('shop', 'fbs')"""
        args: list = []
        if type_:
            sql += " AND o.type = ?"
            args.append(type_)
        if status:
            sql += " AND o.status = ?"
            args.append(status)
        sql += " ORDER BY o.ts DESC LIMIT ?"
        args.append(limit)
        rows = []
        for r in con.execute(sql, args):
            d = dict(r)
            d["status_label"] = labels.get(d["status"], d["status"])
            d["items_detail"] = [dict(i) for i in con.execute(
                "SELECT title, qty, shipped, price, product_id FROM order_items WHERE order_id = ?",
                (d["id"],))]
            rows.append(d)
        counts = {r["type"]: r["c"] for r in con.execute(
            "SELECT type, COUNT(*) c FROM orders WHERE type IN ('shop','fbs') GROUP BY type")}
        return {"data": rows, "по_типам": counts}
    finally:
        con.close()


def history(order_id: str) -> list[dict]:
    con = sqldb.connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT from_status, to_status, actor, at, comment FROM order_status_history "
            "WHERE order_id = ? ORDER BY id", (order_id,))]
    finally:
        con.close()
