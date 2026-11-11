# -*- coding: utf-8 -*-
"""Автосинхронизация FBS: сервер сам забирает новые заказы WB по расписанию.

Интервал — `config.json → wb_autosync_minutes` (по умолчанию 5, 0 — выключено).
Меньше 2 минут не ставим: у WB лимиты на запросы.
Кнопка «Обновить из WB» и автообновление не пересекаются — их разводит замок в wb_sync.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config.json"
DEFAULT_MINUTES = 5
MIN_MINUTES = 2
FIRST_DELAY = 30  # секунд после старта сервера: дать прогреться складу

_state = {
    "минут": 0,
    "включено": False,
    "последний_запуск": "",
    "следующий_запуск": "",
    "последний_итог": None,
    "ошибка": "",
    "запусков": 0,
}
_state_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None


def interval_minutes() -> int:
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8")).get("wb_autosync_minutes", DEFAULT_MINUTES)
        minutes = int(raw)
    except Exception:
        minutes = DEFAULT_MINUTES
    if minutes <= 0:
        return 0
    return max(MIN_MINUTES, minutes)


def _has_tokens() -> bool:
    import cabinets_store
    return any(c["active"] and c["token_set"] for c in cabinets_store.cabinets())


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def run_once() -> dict | None:
    """Один проход. None — пропущен (нет ни одного кабинета с токеном)."""
    if not _has_tokens():
        with _state_lock:
            _state["ошибка"] = "нет кабинетов с токеном"
        return None
    import wb_sync
    started = time.time()
    try:
        res = wb_sync.sync(actor="автообновление")
        errors = "; ".join(f"{e['кабинет']}: {e['ошибка']}" for e in res.get("ошибки") or [])
    except Exception as exc:  # noqa: BLE001
        res, errors = None, str(exc)
    with _state_lock:
        _state["последний_запуск"] = _stamp(started)
        _state["последний_итог"] = (
            {k: res.get(k, 0) for k in ("создано", "обновлено", "отправлено", "собирается", "отменено")}
            if res else None)
        _state["ошибка"] = errors
        _state["запусков"] += 1
    return res


def _loop() -> None:
    if _stop.wait(FIRST_DELAY):
        return
    while not _stop.is_set():
        minutes = interval_minutes()
        with _state_lock:
            _state["минут"] = minutes
            _state["включено"] = bool(minutes)
        if minutes:
            try:
                run_once()
            except Exception as exc:  # noqa: BLE001
                with _state_lock:
                    _state["ошибка"] = str(exc)
        wait = (minutes or DEFAULT_MINUTES) * 60  # выключено — просто перечитываем настройку
        with _state_lock:
            _state["следующий_запуск"] = _stamp(time.time() + wait) if minutes else ""
        if _stop.wait(wait):
            return


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    minutes = interval_minutes()
    with _state_lock:
        _state["минут"] = minutes
        _state["включено"] = bool(minutes)
        _state["следующий_запуск"] = _stamp(time.time() + FIRST_DELAY) if minutes else ""
    _thread = threading.Thread(target=_loop, name="wb-autosync", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def status() -> dict:
    with _state_lock:
        return dict(_state)
