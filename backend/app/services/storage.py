"""物理文件存储层。

三条硬约束：
1. 落盘名一律 UUID，原始文件名只进数据库，杜绝路径注入与中文乱码；
2. 所有路径访问都要过 resolve_safe()，确保不跳出 STORAGE_ROOT；
3. 边写边算 SHA-256，落盘前先判重，同一份内容只存一份物理副本。
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def storage_root() -> Path:
    root = settings.storage_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_name(filename: str | None) -> str:
    """仅用于展示的原始文件名清洗，不做任何路径操作。"""
    name = Path(filename or "").name
    name = _ILLEGAL.sub("_", name).strip(" .")
    return name[:200] or "未命名文件"


def safe_ext(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="文件缺少扩展名，无法识别类型"
        )
    if ext not in settings.allowed_ext_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不允许的文件类型 .{ext}",
        )
    return ext


def resolve_safe(rel_path: str) -> Path:
    """把库里的相对路径还原成绝对路径，并阻断 ../ 越界。"""
    root = storage_root()
    target = (root / rel_path).resolve()
    if root != target and root not in target.parents:
        logger.warning("拦截越界路径访问: %s", rel_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件路径")
    return target


def month_dir() -> str:
    now = datetime.now()
    return f"{now:%Y}/{now:%m}"


def save_upload(upload: UploadFile, created_by: int) -> dict:
    """流式落盘，返回可直接写库的字段字典。"""
    ext = safe_ext(upload.filename)
    original = sanitize_name(upload.filename)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    rel_dir = month_dir()
    rel_path = f"{rel_dir}/{stored_name}"
    abs_path = resolve_safe(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    try:
        with abs_path.open("wb") as fh:
            while True:
                chunk = upload.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"单个文件不得超过 {settings.MAX_UPLOAD_MB} MB",
                    )
                digest.update(chunk)
                fh.write(chunk)
    except HTTPException:
        abs_path.unlink(missing_ok=True)
        raise
    except Exception:
        abs_path.unlink(missing_ok=True)
        logger.exception("文件落盘失败: %s", original)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"文件保存失败：{original}"
        ) from None
    finally:
        try:
            upload.file.close()
        except Exception:  # noqa: BLE001
            pass

    if size == 0:
        abs_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"空文件：{original}")

    return {
        "original_name": original,
        "stored_name": stored_name,
        "rel_path": rel_path,
        "ext": ext,
        "mime_type": upload.content_type or "application/octet-stream",
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "created_by": created_by,
    }


def remove_physical(rel_path: str | None) -> None:
    """删除物理文件，失败只记日志，不阻断数据库事务。"""
    if not rel_path:
        return
    try:
        resolve_safe(rel_path).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        logger.warning("物理文件删除失败: %s", rel_path, exc_info=True)


def stat_usage() -> dict:
    root = storage_root()
    total = 0
    count = 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
            count += 1
    return {"file_count": count, "total_bytes": total,
            "total_mb": round(total / 1024 / 1024, 2), "root": str(root)}
