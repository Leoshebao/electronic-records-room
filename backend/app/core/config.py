"""全局配置：全部通过环境变量 / .env 注入，禁止硬编码。"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parents[2]
# 项目根目录（.env 优先读根目录，其次 backend/.env）
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    APP_NAME: str = "电子资料室系统"
    APP_ENV: str = "production"
    DEBUG: bool = False
    SQL_ECHO: bool = False
    API_PREFIX: str = "/api"
    SECRET_KEY: str = "dev-only-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # 数据库
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "erecords"
    POSTGRES_USER: str = "erecords"
    POSTGRES_PASSWORD: str = "erecords_pass"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # 文件存储
    STORAGE_ROOT: str = "./storage"
    MAX_UPLOAD_MB: int = 500
    BATCH_UPLOAD_LIMIT: int = 50
    ALLOWED_EXTENSIONS: str = (
        "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,md,csv,"
        "jpg,jpeg,png,bmp,tif,tiff,zip,rar,7z"
    )

    # 服务端
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    PUBLIC_BASE_URL: str = "https://127.0.0.1:8443"

    # 初始化管理员
    SEED_ADMIN_USERNAME: str = "admin"
    SEED_ADMIN_PASSWORD: str = "Admin@12345"

    # OCR
    OCR_ENGINE: str = "paddleocr"
    OCR_LANG: str = "ch"
    OCR_MAX_RETRY: int = 3
    OCR_ENABLED: bool = True
    OCR_WORKER_ENABLED: bool = True
    OCR_WORKER_INTERVAL_SECONDS: int = 5
    OCR_TASK_TIMEOUT_MINUTES: int = 30
    OCR_MAX_PAGES: int = 100
    OCR_MAX_CHARS: int = 200000
    OCR_IMAGE_DPI: int = 150
    # 单页文本层字符数低于该阈值时，视为扫描件，改走图像 OCR
    OCR_TEXT_LAYER_MIN_CHARS: int = 20

    # ---- 借阅 ----
    BORROW_SWEEP_ENABLED: bool = True
    BORROW_SWEEP_INTERVAL: int = 60
    BORROW_DEFAULT_DAYS: int = 7
    BORROW_MAX_DAYS: int = 90
    BORROW_MAX_RENEW: int = 2

    # 备份
    BACKUP_ROOT: str = "./backups"
    BACKUP_KEEP_DAYS: int = 30

    # 业务常量
    RECYCLE_RETENTION_DAYS: int = 30
    LOGIN_MAX_FAIL: int = 5
    LOGIN_LOCK_MINUTES: int = 10

    @property
    def database_url(self) -> str:
        # 用户名/密码必须做 URL 编码，否则密码中的 @ : / 等字符会把 DSN 解析打乱
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD or "")
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def storage_path(self) -> Path:
        p = Path(self.STORAGE_ROOT)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def backup_path(self) -> Path:
        p = Path(self.BACKUP_ROOT)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def allowed_ext_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ALLOWED_EXTENSIONS.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
