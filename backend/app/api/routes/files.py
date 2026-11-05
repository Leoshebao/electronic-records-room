"""文件下载、在线预览、缩略图。

下载与预览是两件事：
- 预览：浏览器内联打开，无需下载权限，但要记 DOC_VIEW 审计；
- 下载：需要 DOC_DOWNLOAD 权限，记 DOC_DOWNLOAD 审计并累加下载次数。
两者都逐请求校验密级，前端隐藏按钮不构成安全边界。
"""
from __future__ import annotations

import io
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.permissions import can_access_level, has_permission
from app.db.session import get_db
from app.models.document import Document, FileObject
from app.models.enums import AuditAction, Permission
from app.models.user import User
from app.services import storage
from app.services.audit import write_audit
from app.services.documents import ensure_doc_access
from app.services.watermark import apply_pdf_watermark

router = APIRouter(prefix="/files", tags=["files"])

INLINE_EXTS = {
    "pdf", "png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "txt", "csv", "json", "xml",
    "mp3", "wav", "mp4", "webm", "ogg", "md", "log",
}
THUMB_EXTS = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tiff"}
CHUNK = 512 * 1024


def _load(db: Session, file_id: int, user: User, need: str = "view") -> tuple[FileObject, Document]:
    fo = db.get(FileObject, file_id)
    if fo is None or fo.status != "stored":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    doc = db.get(Document, fo.document_id)
    if doc is None or doc.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    # 密级矩阵优先，其次由借阅授权按 view / download / print 位放行
    ensure_doc_access(db, user, doc, need)
    return fo, doc


def _abs(fo: FileObject) -> Path:
    p = storage.resolve_safe(fo.rel_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="物理文件缺失，请联系管理员")
    return p


def _maybe_watermark(path: Path, fo: FileObject, user: User):
    """PDF 走内存水印流；失败或非 PDF 返回 None，调用方回落原文件。"""
    if fo.ext.lower() != "pdf":
        return None
    return apply_pdf_watermark(path, user)


def _stream_response(buf, filename: str, media_type: str, inline: bool) -> Response:
    """内存水印流响应：水印版不做 Range 分段，直接整包下发。"""
    data = buf.getvalue()
    headers = {
        "Content-Disposition": _disposition("inline" if inline else "attachment", filename),
        "Content-Length": str(len(data)),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "X-Watermarked": "1",
    }
    return StreamingResponse(iter([data]), media_type=media_type, headers=headers)


def _disposition(kind: str, filename: str) -> str:
    return f"{kind}; filename=\"download.{Path(filename).suffix.lstrip('.')}\"; filename*=UTF-8''{quote(filename)}"


def _file_response(path: Path, filename: str, media_type: str, inline: bool, request: Request) -> Response:
    size = path.stat().st_size
    headers = {
        "Content-Disposition": _disposition("inline" if inline else "attachment", filename),
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header and range_header.startswith("bytes="):
        raw = range_header.split("=", 1)[1].split(",")[0].strip()
        start_s, _, end_s = raw.partition("-")
        try:
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
        except ValueError:
            start, end = 0, size - 1
        start = max(0, min(start, size - 1))
        end = max(start, min(end, size - 1))

        def _iter():
            with path.open("rb") as fh:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(_iter(), status_code=206, media_type=media_type, headers=headers)

    headers["Content-Length"] = str(size)

    def _full():
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(_full(), media_type=media_type, headers=headers)


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    fo, doc = _load(db, file_id, user, need="download")
    # 角色层面无下载权时，仅允许借阅授权开放了下载位的资料
    granted_by_borrow = not can_access_level(user.role, doc.secrecy_level)
    if not has_permission(user.role, Permission.DOC_DOWNLOAD) and not granted_by_borrow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有下载权限，如需下载请提交借阅申请",
        )
    path = _abs(fo)
    doc.download_count = (doc.download_count or 0) + 1
    db.commit()
    write_audit(
        action=AuditAction.DOC_DOWNLOAD, user=user, target_type="file", target_id=fo.id,
        detail={"doc_no": doc.doc_no, "filename": fo.original_name, "size": fo.size_bytes},
        request=request,
    )
    media = fo.mime_type or mimetypes.guess_type(fo.original_name)[0] or "application/octet-stream"
    wm = _maybe_watermark(path, fo, user)
    if wm is not None:
        return _stream_response(wm, fo.original_name, media, inline=False)
    return _file_response(path, fo.original_name, media, inline=False, request=request)


@router.get("/{file_id}/preview")
def preview_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    fo, doc = _load(db, file_id, user)
    path = _abs(fo)
    write_audit(
        action=AuditAction.DOC_VIEW, user=user, target_type="file", target_id=fo.id,
        detail={"doc_no": doc.doc_no, "filename": fo.original_name, "mode": "preview"},
        request=request,
    )
    inline = fo.ext.lower() in INLINE_EXTS
    media = fo.mime_type or mimetypes.guess_type(fo.original_name)[0] or "application/octet-stream"
    if fo.ext.lower() in {"txt", "csv", "json", "md", "log", "xml"}:
        media = "text/plain; charset=utf-8"
    wm = _maybe_watermark(path, fo, user)
    if wm is not None:
        return _stream_response(wm, fo.original_name, media, inline=inline)
    return _file_response(path, fo.original_name, media, inline=inline, request=request)


@router.get("/{file_id}/thumb")
def thumbnail(
    file_id: int,
    size: int = 240,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """图片缩略图。非图片或 Pillow 不可用时回退原文件，绝不报错中断列表展示。"""
    fo, _doc = _load(db, file_id, user)
    path = _abs(fo)
    size = max(64, min(size, 1024))
    if fo.ext.lower() not in THUMB_EXTS:
        media = fo.mime_type or "application/octet-stream"
        return FileResponse(path, media_type=media, filename=fo.original_name,
                            content_disposition_type="inline")
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return FileResponse(path, media_type=fo.mime_type or "image/jpeg")

    try:
        with Image.open(path) as im:
            im.draft("RGB", (size * 2, size * 2))
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=82, optimize=True)
            buf.seek(0)
        return Response(
            content=buf.getvalue(), media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=86400"},
        )
    except Exception:  # noqa: BLE001
        return FileResponse(path, media_type=fo.mime_type or "image/jpeg")
