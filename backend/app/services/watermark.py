"""水印服务：在预览 / 下载时对 PDF 动态叠加使用者信息。

设计取舍：
- 不落盘、不改原文件：每次请求按当前用户实时生成，避免多用户共享同一份水印副本；
- 仅处理 PDF：图片 / Office 由前端预览时叠加 CSS 水印，Office 转 PDF 成本过高且需外部组件；
- 三层水印：斜向平铺（防截图裁剪）+ 四角页脚（可追溯到人）+ 顶部提示语（合规告知）；
- 任意环节异常都退回原文件，绝不因水印失败阻断业务。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.models.user import User

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - 环境缺库时降级
    fitz = None

# 水印文本使用的内置字体：helv 无法渲染中文，故统一走 PyMuPDF 自带的中日韩字体
CJK_FONT = "china-s"


def _stamp_text(user: User, when: datetime) -> str:
    dept = getattr(user, "department", None)
    dept_name = getattr(dept, "name", "") if dept else ""
    parts = [f"{user.username}"]
    if user.full_name:
        parts.append(user.full_name)
    if dept_name:
        parts.append(dept_name)
    parts.append(when.strftime("%Y-%m-%d %H:%M"))
    return "  ".join(parts)


def apply_pdf_watermark(
    src: Path,
    user: User,
    *,
    notice: str = "内部资料 · 仅供工作使用 · 禁止外传",
) -> BytesIO | None:
    """返回带水印的 PDF 内存流；不可处理或失败时返回 None（调用方退回原文件）。"""
    if fitz is None:
        logger.warning("PyMuPDF 不可用，跳过 PDF 水印")
        return None
    try:
        doc = fitz.open(str(src))
    except Exception as exc:  # 损坏或加密
        logger.warning("PDF 打开失败，跳用水印：%s", exc)
        return None

    try:
        now = datetime.now()
        stamp = _stamp_text(user, now)
        # insert_text 的 rotate 只接受 0/90/180/270，任意角度需走 morph 旋转矩阵
        rot45 = fitz.Matrix(45)
        for page in doc:
            rect = page.rect
            # 1) 斜向平铺：45°，低透明度，覆盖整页
            text = f"{stamp}"
            fontsize = 11
            step_x, step_y = 260, 150
            y = 60
            while y < rect.height:
                x = -40 if (int(y) // step_y) % 2 else -170
                while x < rect.width:
                    pt = fitz.Point(x, y)
                    try:
                        page.insert_text(
                            pt, text, fontsize=fontsize, fontname=CJK_FONT,
                            color=(0.55, 0.55, 0.55), overlay=True,
                            fill_opacity=0.18, morph=(pt, rot45),
                        )
                    except Exception:  # noqa: BLE001 - 旋转不可用时退化为水平平铺
                        page.insert_text(
                            pt, text, fontsize=fontsize, fontname=CJK_FONT,
                            color=(0.55, 0.55, 0.55), overlay=True,
                            fill_opacity=0.18,
                        )
                    x += step_x
                y += step_y

            # 2) 顶部合规提示
            page.insert_text(
                (28, 26), notice, fontsize=9, fontname=CJK_FONT,
                color=(0.75, 0.2, 0.2), overlay=True, fill_opacity=0.85,
            )
            # 3) 页脚追溯信息
            footer = f"下载人：{stamp}    文档编号追溯：{now:%Y%m%d%H%M%S}"
            page.insert_text(
                (28, rect.height - 16), footer, fontsize=8, fontname=CJK_FONT,
                color=(0.45, 0.45, 0.45), overlay=True, fill_opacity=0.75,
            )

        out = BytesIO()
        out.write(doc.tobytes(garbage=3, deflate=True))
        out.seek(0)
        return out
    except Exception as exc:  # 任何渲染异常都不阻断下载
        logger.warning("PDF 水印生成失败，退回原文件：%s", exc)
        return None
    finally:
        doc.close()


def write_watermarked_temp(src: Path, user: User) -> Path | None:
    """落一份临时水印文件（供 StreamingResponse 使用），失败返回 None。"""
    stream = apply_pdf_watermark(src, user)
    if stream is None:
        return None
    from app.core.config import settings

    tmp_dir = settings.storage_path / "_watermark"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"wm_{user.id}_{datetime.now():%Y%m%d%H%M%S%f}.pdf"
    with tmp.open("wb") as fh:
        shutil.copyfileobj(stream, fh)
    return tmp
