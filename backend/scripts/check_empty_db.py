"""判断库内是否还没有任何资料室（用于决定首次部署是否初始化示例数据）。

exit 0 = 空库（应带 --with-samples 初始化示例资料室与类目）
exit 1 = 已有资料室（保持现状，不注入示例数据）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Room  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count(Room.id))) or 0
        return 0 if total == 0 else 1
    except Exception:  # noqa: BLE001
        # 表结构尚未就绪等情况，按“非空”处理，避免误建示例数据
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
