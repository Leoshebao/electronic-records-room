"""文本提取与 OCR。

策略（离线可用优先）：
1. 电子文档优先读取文本层（PDF / DOCX / XLSX / PPTX / TXT），速度快、准确率 100%；
2. 文本层为空或低于阈值时，才把页面渲染成图片交给 OCR 引擎（PaddleOCR）；
3. OCR 引擎缺失或初始化失败时不阻塞入库，返回 skipped 并说明原因，后续可用 /api/ocr 接口补跑。

所有函数均不抛业务异常，失败通过 ExtractResult.error 返回，由 worker 决定状态流转。
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("erecords.ocr")

TEXT_EXTS = {"txt", "md", "csv", "log", "json", "xml", "html", "htm"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "bmp", "tif", "tiff", "webp"}
ARCHIVE_EXTS = {"zip", "rar", "7z", "gz", "tar"}
OFFICE_EXTS = {"doc", "xls", "ppt"}  # 旧版二进制格式，无纯 Python 解析器
_SLIDE_TEXT = re.compile(r"<a:t>(.*?)</a:t>", re.S)


@dataclass
class ExtractResult:
    """一次文件解析的结果。"""

    text: str = ""
    pages: int = 0
    method: str = "none"        # text_layer / ocr / mixed / skipped
    engine: str = ""            # pymupdf / openpyxl / paddleocr ...
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


# ---------------------------------------------------------------- 文本层解析
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _read_plain(path: Path) -> ExtractResult:
    raw = path.read_bytes()
    text = _decode(raw)
    return ExtractResult(text=text, method="text_layer", engine="builtin")


def _read_pdf(path: Path, allow_ocr: bool) -> ExtractResult:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        return ExtractResult(error=f"PyMuPDF 未安装: {exc}")

    chunks: list[str] = []
    ocr_pages = 0
    text_pages = 0
    engine = "pymupdf"
    try:
        with fitz.open(path) as doc:
            pages = doc.page_count
            for index in range(min(pages, settings.OCR_MAX_PAGES)):
                page = doc.load_page(index)
                page_text = (page.get_text("text") or "").strip()
                if len(page_text) >= settings.OCR_TEXT_LAYER_MIN_CHARS:
                    text_pages += 1
                    chunks.append(page_text)
                    continue
                if not allow_ocr:
                    if page_text:
                        text_pages += 1
                        chunks.append(page_text)
                    continue
                image_text = _ocr_pdf_page(page)
                if image_text:
                    ocr_pages += 1
                    engine = "paddleocr"
                    chunks.append(image_text)
                elif page_text:
                    text_pages += 1
                    chunks.append(page_text)
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(error=f"PDF 解析失败: {exc}", engine=engine)

    text = "\n".join(c for c in chunks if c)
    if ocr_pages and text_pages:
        method = "mixed"
    elif ocr_pages:
        method = "ocr"
    else:
        method = "text_layer"
    note = None
    if not text.strip():
        if get_ocr_engine() is None:
            return ExtractResult(
                pages=pages, method="skipped", engine=engine,
                error="PDF 无文本层且 OCR 引擎不可用（PaddleOCR 未安装）",
            )
        return ExtractResult(
            pages=pages, method="ocr", engine="paddleocr", error="PDF 未识别出文字"
        )
    return ExtractResult(
        text=text, pages=pages, method=method, engine=engine, error=note,
        meta={"ocr_pages": ocr_pages, "text_pages": text_pages},
    )


def _ocr_pdf_page(page) -> str:
    """把 PDF 页渲染为图片后送入 OCR 引擎。引擎不可用时返回空串。"""
    if get_ocr_engine() is None:
        return ""
    try:
        pix = page.get_pixmap(dpi=settings.OCR_IMAGE_DPI)
        return ocr_image_bytes(pix.tobytes("png"))
    except Exception:  # noqa: BLE001
        logger.exception("PDF 页面 OCR 失败")
        return ""


def _read_docx(path: Path) -> ExtractResult:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        return ExtractResult(error=f"python-docx 未安装: {exc}")
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(error=f"DOCX 解析失败: {exc}")

    parts = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append("\t".join(cells))
    return ExtractResult(text="\n".join(parts), pages=1, method="text_layer", engine="python-docx")


def _read_xlsx(path: Path) -> ExtractResult:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        return ExtractResult(error=f"openpyxl 未安装: {exc}")
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(error=f"XLSX 解析失败: {exc}")

    parts: list[str] = []
    try:
        for ws in wb.worksheets:
            parts.append(f"# {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if cells:
                    parts.append("\t".join(cells))
    finally:
        wb.close()
    return ExtractResult(
        text="\n".join(parts), pages=1, method="text_layer", engine="openpyxl"
    )


def _read_pptx(path: Path) -> ExtractResult:
    """不引入 python-pptx：直接读 OOXML 里的 <a:t> 文本节点。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                key=lambda n: int(re.search(r"(\d+)", n).group(1)),
            )
            parts = []
            for name in names:
                xml = zf.read(name).decode("utf-8", errors="ignore")
                texts = [t.strip() for t in _SLIDE_TEXT.findall(xml) if t.strip()]
                if texts:
                    parts.append("\n".join(texts))
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(error=f"PPTX 解析失败: {exc}")
    return ExtractResult(
        text="\n".join(parts), pages=len(names), method="text_layer", engine="ooxml"
    )


# ---------------------------------------------------------------- OCR 引擎
_engine = None
_engine_error: str | None = None


def get_ocr_engine():
    """惰性初始化 PaddleOCR 单例。不可用时返回 None，并缓存失败原因避免重复尝试。"""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error is not None:
        return None
    try:
        from paddleocr import PaddleOCR  # type: ignore

        _engine = PaddleOCR(use_angle_cls=True, lang=settings.OCR_LANG, show_log=False)
        logger.info("PaddleOCR 初始化成功，lang=%s", settings.OCR_LANG)
    except Exception as exc:  # noqa: BLE001
        _engine_error = f"{type(exc).__name__}: {exc}"
        logger.warning("PaddleOCR 不可用，扫描件将标记为 skipped：%s", _engine_error)
        return None
    return _engine


def ocr_engine_status() -> dict:
    """供运维接口查询 OCR 引擎可用性。"""
    engine = get_ocr_engine()
    return {
        "engine": settings.OCR_ENGINE,
        "lang": settings.OCR_LANG,
        "available": engine is not None,
        "error": _engine_error,
    }


def ocr_image_bytes(data: bytes) -> str:
    """图片二进制 → 文本。引擎不可用或识别失败返回空串。"""
    engine = get_ocr_engine()
    if engine is None:
        return ""
    try:
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        array = np.array(image)
        raw = engine.ocr(array)
        return _flatten_ocr(raw)
    except Exception:  # noqa: BLE001
        logger.exception("图片 OCR 失败")
        return ""


def _flatten_ocr(raw) -> str:
    """兼容 PaddleOCR 2.x（[[box, (text, conf)], ...]）与 3.x（dict/列表）返回结构。"""
    lines: list[str] = []

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, str):
            lines.append(node)
            return
        if isinstance(node, dict):
            for key in ("rec_texts", "texts", "text"):
                if key in node:
                    walk(node[key])
                    return
            return
        if isinstance(node, (list, tuple)):
            # 2.x 的单行结果形如 [box, (text, score)]
            if (
                len(node) == 2
                and isinstance(node[0], (list, tuple))
                and isinstance(node[1], (list, tuple))
                and node[1]
                and isinstance(node[1][0], str)
            ):
                lines.append(node[1][0])
                return
            for item in node:
                walk(item)

    walk(raw)
    return "\n".join(t for t in (line.strip() for line in lines) if t)


# ---------------------------------------------------------------- 统一入口
def extract_text(rel_path: str, ext: str, allow_ocr: bool | None = None) -> ExtractResult:
    """按扩展名解析文件。rel_path 为相对 storage 根的路径。"""
    allow_ocr = settings.OCR_ENABLED if allow_ocr is None else allow_ocr
    path = settings.storage_path / rel_path
    if not path.exists():
        return ExtractResult(error="物理文件不存在")
    ext = ext.lower().lstrip(".")

    if ext in TEXT_EXTS:
        result = _read_plain(path)
    elif ext == "pdf":
        result = _read_pdf(path, allow_ocr)
    elif ext == "docx":
        result = _read_docx(path)
    elif ext in {"xlsx", "xlsm"}:
        result = _read_xlsx(path)
    elif ext == "pptx":
        result = _read_pptx(path)
    elif ext in IMAGE_EXTS:
        if not allow_ocr:
            return ExtractResult(method="skipped", error="OCR 已关闭")
        if get_ocr_engine() is None:
            return ExtractResult(method="skipped", error="OCR 引擎不可用（PaddleOCR 未安装）")
        text = ocr_image_bytes(path.read_bytes())
        return ExtractResult(
            text=text, pages=1, method="ocr", engine="paddleocr",
            error=None if text else "图像未识别出文字",
        )
    elif ext in ARCHIVE_EXTS:
        return ExtractResult(method="skipped", error="压缩包不解析内容")
    elif ext in OFFICE_EXTS:
        return ExtractResult(method="skipped", error=f"旧版 {ext.upper()} 需转存为 OOXML 格式后解析")
    else:
        return ExtractResult(method="skipped", error=f"不支持的文件类型: {ext}")

    if result.text:
        result.text = result.text[: settings.OCR_MAX_CHARS]
    return result
