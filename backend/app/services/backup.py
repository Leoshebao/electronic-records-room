"""备份服务：PostgreSQL 逻辑/物理导出 + 文件存储打包。

策略：
- 备份产物落到 settings.backup_path，文件名含时间戳，避免覆盖；
- 优先调用 pg_dump（一致性最好）；当前环境无 pg_dump 时降级为 SQLAlchemy 逐表 JSON 导出，
  保证"总有可用备份"，并在 error_msg 中写明降级原因；
- 每次备份写 BackupRecord + 审计；
- 按 BACKUP_KEEP_DAYS 清理过期备份（只删备份目录内的文件，不触碰 storage）。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.workflow import BackupRecord

logger = logging.getLogger("erecords.backup")

CHUNK = 1024 * 1024


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _pg_dump_to(path: Path) -> tuple[bool, str | None]:
    """调用 pg_dump 生成自定义格式备份。返回 (是否成功, 失败原因)。"""
    exe = shutil.which("pg_dump")
    if not exe:
        return False, "未找到 pg_dump，已降级为逻辑 JSON 导出"
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD or ""
    cmd = [
        exe, "-h", settings.POSTGRES_HOST, "-p", str(settings.POSTGRES_PORT),
        "-U", settings.POSTGRES_USER, "-d", settings.POSTGRES_DB,
        "-Fc", "-f", str(path),
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=1800)
    except Exception as exc:  # noqa: BLE001
        return False, f"pg_dump 执行异常：{exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "ignore")[:300]
        return False, f"pg_dump 失败：{detail}"
    return True, None


def _logical_dump(db: Session, path: Path) -> None:
    """无 pg_dump 时的降级方案：逐表导出 JSON（行数受规模限制，足够小库恢复）。"""
    from app.db.session import Base  # 延迟导入，避免循环依赖

    payload: dict[str, list[dict]] = {}
    for table in Base.metadata.sorted_tables:
        rows = db.execute(select(table)).mappings().all()
        payload[table.name] = [
            {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(r).items()}
            for r in rows
        ]
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def _zip_storage(target: Path) -> int:
    """打包 storage 目录，返回写入字节数。跳过 _watermark 临时目录。"""
    root = settings.storage_path
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file() and "_watermark" not in p.parts:
                    zf.write(p, p.relative_to(root).as_posix())
                    count += 1
    return count


def run_backup(db: Session, *, backup_type: str = "full", created_by: int | None = None) -> BackupRecord:
    """执行一次备份。backup_type: full / db / files。"""
    root = settings.backup_path
    root.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    record = BackupRecord(
        filename=f"backup_{backup_type}_{stamp}.zip",
        file_path="",
        backup_type=backup_type,
        status="running",
        started_at=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(record)
    db.commit()

    final = root / record.filename
    tmp_dir = root / f".tmp_{stamp}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    try:
        if backup_type in {"full", "db"}:
            dump_path = tmp_dir / "database.dump"
            ok, reason = _pg_dump_to(dump_path)
            if not ok:
                notes.append(reason or "pg_dump 不可用")
                json_path = tmp_dir / "database.json"
                _logical_dump(db, json_path)
                dump_path = json_path
            record.size_bytes += dump_path.stat().st_size

        if backup_type in {"full", "files"}:
            files_zip = tmp_dir / "storage.zip"
            _zip_storage(files_zip)
            record.size_bytes += files_zip.stat().st_size

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app": settings.APP_NAME,
            "backup_type": backup_type,
            "database": {
                "host": settings.POSTGRES_HOST, "port": settings.POSTGRES_PORT,
                "db": settings.POSTGRES_DB, "user": settings.POSTGRES_USER,
            },
            "notes": notes,
        }
        (tmp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in tmp_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, p.name)
        record.size_bytes = final.stat().st_size
        record.file_path = str(final)
        record.status = "success"
        record.error_msg = "；".join(notes) or None
        record.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("备份完成：%s（%.1f MB）", final.name, record.size_bytes / 1024 / 1024)
        return record
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record.status = "failed"
        record.error_msg = str(exc)[:500]
        record.finished_at = datetime.now(timezone.utc)
        db.add(record)
        db.commit()
        logger.exception("备份失败")
        return record
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def cleanup_old_backups(db: Session, keep_days: int | None = None) -> dict:
    """删除超过保留期的备份文件与记录。"""
    days = keep_days if keep_days is not None else settings.BACKUP_KEEP_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(
        select(BackupRecord).where(
            BackupRecord.created_at < cutoff,
            BackupRecord.status.in_(["success", "failed"]),
        )
    ).all()
    removed = 0
    for r in rows:
        p = Path(r.file_path) if r.file_path else None
        if p and p.exists() and settings.backup_path in p.resolve().parents:
            p.unlink(missing_ok=True)
        db.delete(r)
        removed += 1
    db.commit()
    return {"removed": removed, "keep_days": days}
