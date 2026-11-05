"""借阅到期回收后台线程。

设计：与 OCR worker 同构 —— 单线程 daemon，固定间隔扫描；异常只记录日志不退出。
扫描间隔取 settings.BORROW_SWEEP_INTERVAL，默认 60 秒。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.enums import AuditAction
from app.services import borrow
from app.services.audit import write_audit

logger = logging.getLogger("erecords.borrow_sweeper")

_stop = threading.Event()
_thread: threading.Thread | None = None
_last_run: datetime | None = None
_last_result: dict = {}


def _run_once() -> dict:
    global _last_run, _last_result
    db = SessionLocal()
    try:
        result = borrow.sweep(db)
        db.commit()
        _last_run = datetime.now()
        _last_result = result
        if result["expired"] or result["purged_permissions"]:
            logger.info(
                "到期回收：借阅 %s 条，清理过期授权 %s 条",
                result["expired"], result["purged_permissions"],
            )
            for no in result["request_nos"]:
                write_audit(
                    action=AuditAction.BORROW_EXPIRE,
                    username="system",
                    target_type="borrow_request",
                    detail={"request_no": no, "by": "sweeper"},
                )
        return result
    finally:
        db.close()


def _loop(interval: int) -> None:
    logger.info("借阅到期回收线程启动，间隔 %s 秒", interval)
    while not _stop.is_set():
        try:
            _run_once()
        except Exception:  # noqa: BLE001 - 线程不可因单次异常退出
            logger.exception("借阅到期回收执行失败")
        _stop.wait(interval)
    logger.info("借阅到期回收线程已停止")


def start_worker() -> bool:
    global _thread
    if _thread and _thread.is_alive():
        return False
    _stop.clear()
    interval = max(10, int(getattr(settings, "BORROW_SWEEP_INTERVAL", 60)))
    _thread = threading.Thread(target=_loop, args=(interval,), name="borrow-sweeper", daemon=True)
    _thread.start()
    return True


def stop_worker() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


def worker_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def worker_status() -> dict:
    return {
        "alive": worker_alive(),
        "interval": int(getattr(settings, "BORROW_SWEEP_INTERVAL", 60)),
        "last_run": _last_run.isoformat() if _last_run else None,
        "last_result": _last_result,
    }


def run_once() -> dict:
    """供手动接口 / 验收脚本调用。"""
    return _run_once()
