"""FastAPI 应用入口。

部署形态：仅监听 127.0.0.1:8000，由 Nginx 承担 TLS 终止与静态托管。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    auth, backup, borrow, documents, files, health, ocr, rooms, search, stats, users,
)
from app.core.config import settings
from app.services import borrow_sweeper, ocr_worker

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("erecords")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.backup_path.mkdir(parents=True, exist_ok=True)
    logger.info("存储目录: %s", settings.storage_path)

    # OCR 后台解析线程：单线程轮询数据库任务表，随应用生命周期启停
    if settings.OCR_ENABLED and settings.OCR_WORKER_ENABLED:
        ocr_worker.start_worker()
    else:
        logger.info(
            "OCR worker 未启用（OCR_ENABLED=%s, OCR_WORKER_ENABLED=%s）",
            settings.OCR_ENABLED, settings.OCR_WORKER_ENABLED,
        )

    # 借阅到期回收线程：扫描已到期借阅并收回临时授权
    if getattr(settings, "BORROW_SWEEP_ENABLED", True):
        borrow_sweeper.start_worker()
    else:
        logger.info("借阅到期回收线程未启用")

    logger.info("%s 启动完成", settings.APP_NAME)
    yield
    borrow_sweeper.stop_worker()
    ocr_worker.stop_worker()
    logger.info("%s 已停止", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url=f"{settings.API_PREFIX}/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url=f"{settings.API_PREFIX}/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# 生产环境走 Nginx 同源，无需 CORS；开发环境仅放行本地 dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        settings.PUBLIC_BASE_URL,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务器内部错误"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一错误响应体为 {code, message}，与前端约定一致。"""
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        429: "TOO_MANY_REQUESTS",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code_map.get(exc.status_code, "ERROR"),
            "message": exc.detail if isinstance(exc.detail, str) else "请求失败",
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": f"参数校验失败: {field} {first.get('msg', '')}".strip(),
            "errors": [
                {"field": ".".join(str(p) for p in e.get("loc", [])), "msg": e.get("msg")}
                for e in exc.errors()[:10]
            ],
        },
    )


# 强制改密拦截：未改初始密码时只放行白名单接口
_PASSWORD_CHANGE_WHITELIST = {
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/auth/logout",
}


@app.middleware("http")
async def enforce_password_change(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _PASSWORD_CHANGE_WHITELIST and path != "/api/health":
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            from app.core.security import decode_token

            payload = decode_token(auth_header[7:])
            if payload and payload.get("must_change"):
                return JSONResponse(
                    status_code=403,
                    content={"code": "PASSWORD_CHANGE_REQUIRED", "message": "请先修改初始密码"},
                )
    return await call_next(request)


app.include_router(health.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(users.router, prefix=settings.API_PREFIX)
app.include_router(users.dept_router, prefix=settings.API_PREFIX)
app.include_router(rooms.router, prefix=settings.API_PREFIX)
app.include_router(rooms.cat_router, prefix=settings.API_PREFIX)
app.include_router(documents.router, prefix=settings.API_PREFIX)
app.include_router(files.router, prefix=settings.API_PREFIX)
app.include_router(ocr.router, prefix=settings.API_PREFIX)
app.include_router(search.router, prefix=settings.API_PREFIX)
app.include_router(borrow.router, prefix=settings.API_PREFIX)
app.include_router(stats.audit_router, prefix=settings.API_PREFIX)
app.include_router(stats.router, prefix=settings.API_PREFIX)
app.include_router(backup.router, prefix=f"{settings.API_PREFIX}/backups")


@app.get("/")
def root() -> dict:
    return {"app": settings.APP_NAME, "version": "0.1.0", "docs": f"{settings.API_PREFIX}/docs"}
