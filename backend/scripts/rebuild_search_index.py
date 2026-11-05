"""重建检索列：为存量资料回填 search_text 与 search_grams。

用途：P7 上线后、或 OCR 文本批量补齐后，统一刷一次检索列，保证全文索引覆盖历史数据。
用法（在 backend 目录）：
    python scripts/rebuild_search_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.services.documents import refresh_search_text  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        docs = db.scalars(select(Document).where(Document.is_deleted.is_(False))).all()
        for doc in docs:
            refresh_search_text(db, doc)
        db.commit()
        empty = sum(1 for d in docs if not d.search_text)
        print(f"已重建检索列：{len(docs)} 条，其中无文本 {empty} 条")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
