---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: cb6987ed6602af03cb4cc71d337ad39e_f4ff6169d8b611f19280525400393706
    ReservedCode1: iHR+Y08NU9mQKmc3ZDDGVKw3sqt14XEbEUgAhvtpJxb/N/EqWmDBYv3okgB3UAkVO8vlpnaFK0GsUP6wAqgQZlTrWzu9p0Z3a4q/cmF+RvN1e9GHNd/IXi7zsphKaoFXKX0d6lLcI6uYhLfbIf/5NpyG8VZrw4NRL5k/b9SDWsDe+OTMLS/52ird+Y8=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: cb6987ed6602af03cb4cc71d337ad39e_f4ff6169d8b611f19280525400393706
    ReservedCode2: iHR+Y08NU9mQKmc3ZDDGVKw3sqt14XEbEUgAhvtpJxb/N/EqWmDBYv3okgB3UAkVO8vlpnaFK0GsUP6wAqgQZlTrWzu9p0Z3a4q/cmF+RvN1e9GHNd/IXi7zsphKaoFXKX0d6lLcI6uYhLfbIf/5NpyG8VZrw4NRL5k/b9SDWsDe+OTMLS/52ird+Y8=
---

---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: cb6987ed6602af03cb4cc71d337ad39e_70d34c57d72911f1a216525400248c00
    ReservedCode1: MqC23v93s0eX2iLpkzch8pwxcXl3OzeJd6It5AvJ1wJpyynTtmVa6q4al5zeviAgxJmDJHBkYbdW+aBsSoCfyvcnxNWzpCJV4UDuhVbB8l2ad6nOBIDekZev2zQxnfBbidqSFUNPqnXuVigz53YscIsQOtFSzobHNl/UxGPu9DdRyo4c0CzivQ7uuWo=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: cb6987ed6602af03cb4cc71d337ad39e_70d34c57d72911f1a216525400248c00
    ReservedCode2: MqC23v93s0eX2iLpkzch8pwxcXl3OzeJd6It5AvJ1wJpyynTtmVa6q4al5zeviAgxJmDJHBkYbdW+aBsSoCfyvcnxNWzpCJV4UDuhVbB8l2ad6nOBIDekZev2zQxnfBbidqSFUNPqnXuVigz53YscIsQOtFSzobHNl/UxGPu9DdRyo4c0CzivQ7uuWo=
---

# 电子资料室系统（Electronic Records Room）· AI 协作开发与升级档案

> 用途：把本系统从设计、编码到便携化打包的全部关键信息压缩成一份「可交给其他 AI 工具继续改造」的交接档案。
> 适用读者：Claude Code / Codex / Cursor / Copilot 等编码类 AI，以及后续接手的人类工程师。

| 项 | 值 |
|----|----|
| 系统名称 | 电子资料室系统 / Electronic Records Room |
| 版本 | v1.0.0（便携免安装版） |
| 交付形态 | 免安装绿色包（内嵌 Python 3.11 + PostgreSQL 16.2）+ Docker 部署 + 本地脚本部署 |
| 交付物 | `电子资料室系统_便携版_v1.0.0.zip`，138.6 MB，6659 个文件 |
| 项目根目录（开发副本） | `C:\Users\<本地路径>\<本地路径>\User\oAN1i2cZ4-uDHc7plLVc7_463Ou4\workspace\eb` |
| 默认入口 | http://127.0.0.1:8080 |
| 默认账号 | `admin` / `<见 .env>`（首登强制改密） |
| 使用规模 | 单机局域网 10~30 人，纯内网离线运行 |

## 0. 怎么用这份档案（给 AI 的操作约定）

阅读顺序：第 2 章「硬约束」→ 第 4 章「目录」→ 第 5 章「启动链路」→ 第 6 章「数据模型」→ 第 9 章「API」→ 第 15 章「已知坑」→ 第 16 章「二次开发手册」。

改代码时必须遵守：

1. **先看第 2 章红线**，任何改动不得破坏（四级密级、三角色、软删除、纯内网）。
2. **改动后必须跑第 14 章的验收脚本**，`exit=0` 才算完成。
3. **新增前端接口调用必须同步后端路由**，并在 `backend/app/main.py` 里 `import` + `include_router`，否则 404（历史高频坑）。
4. 不要引入需要联网的依赖、不要换 SQLite、不要新增第 4 类角色、不要改 `/api` 前缀。
5. 前端契约有「类目树双形态」这一历史坑点，改 `Documents.tsx` / `Rooms.tsx` 前必读第 15 章。

## 1. 项目身份与设计基线

### 1.1 业务定位

企业内部档案资料室：把纸质/电子档案收进系统，按资料室 → 类目树归档，做密级管控、全文检索、借阅审批、版本管理、水印导出、审计追溯与备份。

使用者三类：系统管理员（IT）、档案管理员（综合部）、查阅者（普通员工）。

### 1.2 设计基线（不可偏离的参数）

| 维度 | 定稿参数 |
|------|---------|
| 部署网络 | 局域网 / 纯内网，禁止公网暴露 |
| 使用人数 | 10~30 人并发 |
| 密级 | 四级：公开 public / 内部 internal / 秘密 secret / 机密 confidential |
| 角色 | 三级：sysadmin（系统管理员）/ records_manager（档案管理员）/ viewer（查阅者） |
| 主库 | PostgreSQL 16，**禁止 SQLite 作主库** |
| 认证 | JWT（`Authorization: Bearer`），口令 bcrypt 哈希，失败锁定，首登强制改密 |
| 界面 | 全中文，操作路径 ≤ 3 层，面向非技术人员 |
| 传输 | 生产用内网 HTTPS（自签证书含 IP SAN）；便携试用版为 127.0.0.1 HTTP |
| 删除策略 | 一律软删除（`status='archived'` + `is_deleted`），不做物理删除 |
| 文件落盘 | UUID 文件名，按 `年/月` 分目录，原始文件名只存数据库 |
| 时间 | 统一 UTC 存储，前端按本地时区展示 |
| 审计 | 所有写操作落审计日志，DB 触发器 `prevent_audit_modify` 防篡改 |

### 1.3 交付架构（便携版实际链路）

```
浏览器 → 127.0.0.1:8080  preview_server.py（托管 frontend/dist + 反代 /api）
            └→ 127.0.0.1:8000  uvicorn / FastAPI（app.main:app）
                  ├→ 127.0.0.1:4854  PostgreSQL 16.2（pgdata/，由 pg_ctl 拉起）
                  ├→ storage/YYYY/MM/…（UUID 物理文件）
                  └→ OCR Worker（进程内后台线程，轮询 ocr_tasks 表）
```

生产的正式口径是 `Nginx(8443, TLS 终止) → FastAPI(127.0.0.1:8000)`；便携版为了「双击即用、零安装」用 `preview_server.py` 顶替 Nginx，其余不变。`deploy/nginx/`、`deploy/certs/` 保留了正式部署所需配置与自签证书生成脚本。

## 2. 硬约束（改代码前必读）

| # | 约束 | 落地位置 |
|---|------|---------|
| 1 | 接口前缀统一 `/api`，健康检查 `/api/health` | `app/core/config.py: API_PREFIX` |
| 2 | 权限逐请求在服务端校验，前端隐藏不作为安全边界 | `app/api/deps.py` + `app/core/permissions.py` |
| 3 | 角色固定 3 类，禁止新增第 4 类 | `app/models/enums.py: Role` |
| 4 | 密级可见性 = 角色等级上限，SQL 层过滤 | `permissions.visible_levels()` |
| 5 | 删除一律软删除，唯一例外是演示重置脚本 | `reset_demo_data.py`（见第 13 章） |
| 6 | 文件名 UUID 化、年月分目录，原文件名只存库 | `app/services/storage.py` |
| 7 | 所有写操作写审计；审计写入独立事务，业务回滚不影响审计 | `app/services/audit.py: write_audit` |
| 8 | 迁移只走 Alembic，禁止手改表结构后不回写迁移 | `backend/alembic/versions/` |
| 9 | 禁止引入需要外网的运行时依赖（OCR 模型必须离线） | `requirements*.txt` |
| 10 | 前端每次新增 `http.xxx('/path')`，后端必须有对应路由且已注册 | `backend/app/main.py` |

## 3. 技术栈与版本（实测）

| 层 | 选型 | 便携版实际版本 |
|----|------|--------------|
| 语言 | Python | 3.11（内嵌于 `runtime/python/`） |
| Web 框架 | FastAPI | 0.115.6 |
| ASGI | uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| 迁移 | Alembic | 1.20.1（declared 1.14.0） |
| 校验 | pydantic / pydantic-settings | 2.14.1 / 2.7.0（declared 2.10.4） |
| 驱动 | psycopg | 3.2.3（binary） |
| 数据库 | PostgreSQL | 16.2（内嵌于 `runtime/pg/`） |
| PDF | PyMuPDF | 2.0（declared 1.25.1） |
| Word/Excel | python-docx / openpyxl | 1.2.0 / 3.1.5 |
| 图像 | Pillow | 13.0.0（declared 11.0.0） |
| 认证 | PyJWT / passlib+bcrypt | 2.9.0 / 1.7.4 + 4.0.1 |
| 前端 | React + TypeScript + Vite + Ant Design | 18.3.1 / 5.7.2 / 6.0.7 / 5.22.5 |
| 路由 | react-router-dom | 7.1.1 |
| HTTP | axios | 1.7.9 |
| Web 服务（正式） | Nginx（TLS 终止 + 静态 + 反代） | 由部署方提供 |
| OCR | PaddleOCR CPU（离线模型） | **未安装**，见第 15 章 |

> 注意：`backend/requirements.txt` 是「声明版本」，`runtime/python/Lib/site-packages` 才是「实际运行版本」，两者存在偏差（pydantic / alembic / PyMuPDF / Pillow）。升级依赖时必须以实际运行环境为准，并重新跑第 14 章验收。

## 4. 目录结构与文件职责

```
eb/                                  项目根
├─ .env                              ★ 运行配置（端口、库密码、密钥、OCR 参数）
├─ .env.example                      配置模板
├─ launcher.py                       ★ 便携版启动器（initdb / pg_ctl / 起后端 / 起前端 / pid / 日志）
├─ start.bat / stop.bat / status.bat 双击入口，转调 launcher.py
├─ CLAUDE.md                         给编码 AI 的项目约定（简洁版）
├─ 使用说明.md / 使用说明.txt        面向使用者与运维的操作手册
├─ docker-compose.yml                容器化部署（生产备选）
├─ data/erecords_data.sql            首次初始化的业务数据快照（185 KB，含演示数据与账号）
├─ pgdata/                           数据库集群（★ 不随包分发，首启自动 initdb 生成）
├─ storage/YYYY/MM/…                 物理文件（UUID 命名）
├─ backups/backup_db_*.zip           备份包
├─ logs/                             api.log / web.log / postgres.log / pgctl.log / initdb.log / *.pid
├─ backend/
│  ├─ app/
│  │  ├─ main.py                     ★ 入口：CORS、中间件、全部路由注册
│  │  ├─ core/  config.py settings（.env 映射）｜security.py JWT/bcrypt｜permissions.py 角色权限+密级矩阵
│  │  ├─ db/    session.py SessionLocal / get_db
│  │  ├─ models/  user.py｜room.py｜document.py｜workflow.py｜enums.py｜common.py
│  │  ├─ schemas/ auth.py｜document.py｜borrow.py｜search.py｜audit.py
│  │  ├─ api/   deps.py（当前用户、权限依赖、密级过滤）｜routes/（12 个路由模块，见第 9 章）
│  │  └─ services/ storage.py 落盘｜documents.py 业务｜ocr.py 解析｜ocr_worker.py 后台线程
│  │                borrow.py + borrow_sweeper.py 借阅与到期回收｜search.py 检索
│  │                watermark.py 动态水印｜audit.py 审计｜backup.py 备份
│  ├─ alembic/versions/  0001_initial → 0002_room_location → 0003_search_index → 0004_fts_grams → 0005_borrow_fields
│  ├─ scripts/           ★ 初始化 / 重置 / 验收 / 预览脚本（见第 13 章）
│  ├─ requirements.txt / requirements-ocr.txt / Dockerfile
├─ frontend/
│  ├─ src/
│  │  ├─ App.tsx            ★ 路由与权限守卫（RequireAuth / RequirePermission）
│  │  ├─ auth/AuthContext.tsx 登录态、权限集合 has()
│  │  ├─ layout/AppLayout.tsx 侧边栏 + 顶栏
│  │  ├─ api/client.ts     ★ axios 实例（token 注入、401 跳登录）
│  │  ├─ api/types.ts      接口类型定义
│  │  └─ pages/            Login｜ChangePassword｜Dashboard｜Documents｜Search｜Borrow｜Rooms｜Users｜Audit｜Backups｜SystemCheck
│  ├─ public/config.js     ★ 运行时 API 地址（部署时改这里，不用重新构建）
│  └─ dist/                构建产物（由 preview_server / Nginx 托管）
├─ deploy/
│  ├─ nginx/nginx.conf、nginx.local.conf
│  ├─ certs/gen-cert.ps1 + server.crt/key/pfx（自签，含 IP SAN）
│  ├─ scripts/start.bat、stop.bat、start-preview.ps1
│  └─ README-部署说明.md
└─ runtime/                内嵌 Python 3.11（57 个包）+ PostgreSQL 16.2
```

## 5. 启动 / 停止 / 状态（链路细节）

`launcher.py` 三个子命令：`start`（默认）、`stop`、`status`；`start.bat` 等只是转调。

### 5.1 start 执行顺序

1. `load_env()` 读 `.env`，取 `POSTGRES_PORT`(4854)、`API_PORT`(8000)、`PORTABLE_WEB_PORT`(8080)。
2. 校验 `runtime/python/python.exe` 存在；确保 `storage/`、`backups/`、`logs/` 存在。
3. `start_pg()`：
   - 端口已通 → 直接跳过；
   - `pgdata/PG_VERSION` 不存在 → `initdb -U postgres --pwfile -E UTF8 --locale=C -A trust`（首次约 1 分钟）；
   - `pg_ctl start -o "-p <port> -c listen_addresses=127.0.0.1"`，**用 pg_ctl 而非直接 postgres**，让 Windows 以受限令牌拉起 postmaster，规避「管理员身份运行被拒绝」；
   - 首次时：`createdb erecords` → 若 `data/erecords_data.sql` 存在则 `psql -f` 导入整个库；否则 `alembic upgrade head` + `seed_admin.py`。
4. `start_api()`：`uvicorn app.main:app --host 127.0.0.1 --port 8000`，cwd=`backend`，写 `logs/api.pid`，轮询 `/api/health`。
5. `start_web()`：`python scripts/preview_server.py --host 127.0.0.1 --port 8080`，环境变量 `PREVIEW_API_PORT` 指向后端，写 `logs/web.pid`。
6. 打印地址与默认账号，并 `os.startfile` 打开浏览器。

### 5.2 端口 / 进程 / 日志

| 服务 | 端口 | 配置文件 | 日志 | PID |
|------|------|---------|------|-----|
| PostgreSQL | 4854（仅 127.0.0.1） | `.env: POSTGRES_PORT` | `logs/postgres.log`、`logs/pgctl.log` | pg_ctl 管理 |
| 后端 API | 8000（仅 127.0.0.1） | `.env: API_PORT` | `logs/api.log` | `logs/api.pid` |
| 前端页面 | 8080（仅 127.0.0.1） | `.env: PORTABLE_WEB_PORT` | `logs/web.log` | `logs/web.pid` |

`stop.bat`：按 pid 文件 `taskkill /F` 前后端 → `pg_ctl -m fast stop`。`status.bat`：按端口探测三项「运行中/未运行」。

> 端口冲突处理：改 `.env` 三个端口即可，无需改代码。`launcher` 会先探测端口占用，已占用则视为「已在运行」跳过。

## 6. 数据模型（16 张表 · 字段级）

迁移链共 5 个版本，最终形态与 `data/erecords_data.sql` 一致：

`0001_initial`（核心表）→ `0002_room_location`（资料室位置字段）→ `0003_search_index`（检索列）→ `0004_fts_grams`（中文 bigram 检索 `search_grams`）→ `0005_borrow_fields`（借阅到期/续借字段）。

#### users

> 账号、口令哈希、角色、密级上限、部门归属　共 21 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `username` | character varying(64) | NOT NULL |
| `full_name` | character varying(100) | NOT NULL |
| `password_hash` | character varying(255) | NOT NULL |
| `role` | character varying(32) | NOT NULL, DEFAULT 'viewer' |
| `department_id` | bigint |  |
| `email` | character varying(128) |  |
| `phone` | character varying(32) |  |
| `is_active` | boolean | NOT NULL, DEFAULT true |
| `must_change_password` | boolean | NOT NULL, DEFAULT true |
| `last_login_at` | timestamp with time zone |  |
| `last_login_ip` | character varying(64) |  |
| `failed_login_count` | integer | NOT NULL, DEFAULT 0 |
| `locked_until` | timestamp with time zone |  |
| `token_version` | integer | NOT NULL, DEFAULT 1 |
| `remark` | text |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `is_deleted` | boolean | NOT NULL |
| `deleted_at` | timestamp with time zone |  |
| `deleted_by` | integer |  |

#### departments

> 组织架构（部门字典，parent_id 自关联）　共 12 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `name` | character varying(100) | NOT NULL |
| `code` | character varying(50) |  |
| `parent_id` | bigint |  |
| `sort_order` | integer | NOT NULL, DEFAULT 0 |
| `is_active` | boolean | NOT NULL, DEFAULT true |
| `remark` | text |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `is_deleted` | boolean | NOT NULL |
| `deleted_at` | timestamp with time zone |  |
| `deleted_by` | integer |  |

#### rooms

> 资料室（库房），含位置、容量、密级范围　共 13 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `name` | character varying(100) | NOT NULL |
| `code` | character varying(50) | NOT NULL |
| `description` | text |  |
| `location` | character varying(200) |  |
| `keeper_id` | bigint |  |
| `sort_order` | integer | NOT NULL, DEFAULT 0 |
| `is_active` | boolean | NOT NULL, DEFAULT true |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `is_deleted` | boolean | NOT NULL |
| `deleted_at` | timestamp with time zone |  |
| `deleted_by` | integer |  |

#### categories

> 类目树（parent_id 自关联，支持三级）　共 15 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `room_id` | bigint | NOT NULL |
| `parent_id` | bigint |  |
| `name` | character varying(100) | NOT NULL |
| `code` | character varying(50) |  |
| `path` | character varying(500) | NOT NULL |
| `level` | integer | NOT NULL, DEFAULT 1 |
| `sort_order` | integer | NOT NULL, DEFAULT 0 |
| `is_active` | boolean | NOT NULL, DEFAULT true |
| `remark` | text |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `is_deleted` | boolean | NOT NULL |
| `deleted_at` | timestamp with time zone |  |
| `deleted_by` | integer |  |

#### documents

> 资料主表：档号唯一、密级、状态、检索列 search_text / search_grams　共 29 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `doc_no` | character varying(64) | NOT NULL |
| `title` | character varying(500) | NOT NULL |
| `room_id` | bigint | NOT NULL |
| `category_id` | bigint |  |
| `secrecy_level` | character varying(16) | NOT NULL, DEFAULT 'internal' |
| `status` | character varying(16) | NOT NULL, DEFAULT 'active' |
| `summary` | text |  |
| `keywords` | character varying(500) |  |
| `responsible_dept_id` | bigint |  |
| `created_by` | bigint | NOT NULL |
| `updated_by` | bigint |  |
| `current_version_id` | bigint |  |
| `file_count` | integer | NOT NULL, DEFAULT 0 |
| `total_size` | bigint | NOT NULL, DEFAULT '0' |
| `page_count` | integer | NOT NULL, DEFAULT 0 |
| `view_count` | integer | NOT NULL, DEFAULT 0 |
| `download_count` | integer | NOT NULL, DEFAULT 0 |
| `search_text` | text |  |
| `search_grams` | text |  |
| `archive_year` | integer |  |
| `retention_years` | integer |  |
| `published_at` | timestamp with time zone |  |
| `archived_at` | timestamp with time zone |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `is_deleted` | boolean | NOT NULL |
| `deleted_at` | timestamp with time zone |  |
| `deleted_by` | integer |  |

#### document_versions

> 版本链（同一资料多版本 + 变更说明）　共 9 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `document_id` | bigint | NOT NULL |
| `version_no` | integer | NOT NULL |
| `version_label` | character varying(32) |  |
| `change_note` | text |  |
| `is_current` | boolean | NOT NULL, DEFAULT true |
| `created_by` | bigint | NOT NULL |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### files

> 物理文件登记（UUID 文件名、相对路径、哈希、落盘状态）　共 17 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `document_id` | bigint | NOT NULL |
| `version_id` | bigint |  |
| `original_name` | character varying(500) | NOT NULL |
| `stored_name` | character varying(100) | NOT NULL |
| `rel_path` | character varying(500) | NOT NULL |
| `ext` | character varying(20) | NOT NULL |
| `mime_type` | character varying(128) |  |
| `size_bytes` | bigint | NOT NULL, DEFAULT '0' |
| `sha256` | character varying(64) |  |
| `page_count` | integer | NOT NULL, DEFAULT 0 |
| `status` | character varying(16) | NOT NULL, DEFAULT 'stored' |
| `ocr_status` | character varying(16) | NOT NULL, DEFAULT 'queued' |
| `ocr_text` | text |  |
| `created_by` | bigint | NOT NULL |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### tags

> 标签字典　共 6 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `name` | character varying(50) | NOT NULL |
| `color` | character varying(16) |  |
| `created_by` | bigint |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### document_tags

> 资料-标签关联表　共 2 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `document_id` | bigint | NOT NULL |
| `tag_id` | bigint | NOT NULL |

#### document_permissions

> 资料级显式授权（用户/部门/角色）　共 11 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `document_id` | bigint | NOT NULL |
| `subject_type` | character varying(16) | NOT NULL |
| `subject_id` | bigint | NOT NULL |
| `can_view` | boolean | NOT NULL, DEFAULT true |
| `can_download` | boolean | NOT NULL, DEFAULT false |
| `can_print` | boolean | NOT NULL, DEFAULT false |
| `granted_by` | bigint | NOT NULL |
| `expires_at` | timestamp with time zone |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### borrow_requests

> 借阅申请、审批、到期、续借　共 18 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `request_no` | character varying(32) | NOT NULL |
| `document_id` | bigint | NOT NULL |
| `applicant_id` | bigint | NOT NULL |
| `reason` | text | NOT NULL |
| `requested_days` | integer | NOT NULL, DEFAULT 7 |
| `want_download` | boolean | NOT NULL, DEFAULT false |
| `want_print` | boolean | NOT NULL, DEFAULT false |
| `status` | character varying(16) | NOT NULL, DEFAULT 'pending' |
| `approver_id` | bigint |  |
| `approved_at` | timestamp with time zone |  |
| `reject_reason` | text |  |
| `start_at` | timestamp with time zone |  |
| `due_at` | timestamp with time zone |  |
| `returned_at` | timestamp with time zone |  |
| `renew_count` | integer | NOT NULL, DEFAULT 0 |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### ocr_tasks

> OCR / 文本解析任务队列　共 11 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `file_id` | bigint | NOT NULL |
| `status` | character varying(16) | NOT NULL, DEFAULT 'queued' |
| `engine` | character varying(32) | NOT NULL |
| `retry_count` | integer | NOT NULL, DEFAULT 0 |
| `error_msg` | text |  |
| `started_at` | timestamp with time zone |  |
| `finished_at` | timestamp with time zone |  |
| `duration_ms` | integer |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### audit_logs

> 审计日志（DB 触发器防改）　共 11 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `user_id` | bigint |  |
| `username` | character varying(64) |  |
| `action` | character varying(32) | NOT NULL |
| `target_type` | character varying(32) |  |
| `target_id` | bigint |  |
| `detail` | jsonb |  |
| `ip_address` | character varying(64) |  |
| `user_agent` | character varying(500) |  |
| `result` | character varying(16) | NOT NULL, DEFAULT 'success' |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### system_configs

> 运行期配置键值　共 8 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `key` | character varying(64) | NOT NULL |
| `value` | text | NOT NULL |
| `value_type` | character varying(16) | NOT NULL, DEFAULT 'string' |
| `description` | character varying(500) |  |
| `is_editable` | boolean | NOT NULL, DEFAULT true |
| `updated_by` | bigint |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### backup_records

> 备份记录与包路径　共 12 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | bigint | NOT NULL |
| `filename` | character varying(255) | NOT NULL |
| `file_path` | character varying(500) | NOT NULL |
| `backup_type` | character varying(16) | NOT NULL, DEFAULT 'full' |
| `size_bytes` | bigint | NOT NULL, DEFAULT '0' |
| `status` | character varying(16) | NOT NULL, DEFAULT 'running' |
| `error_msg` | text |  |
| `started_at` | timestamp with time zone |  |
| `finished_at` | timestamp with time zone |  |
| `created_by` | bigint |  |
| `created_at` | timestamp with time zone | NOT NULL, DEFAULT now() |
| `updated_at` | timestamp with time zone | NOT NULL, DEFAULT now() |

#### alembic_version

> 迁移版本指针　共 1 个字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `version_num` | character varying(32) | NOT NULL |

## 7. 枚举字典（改状态机前必看）

| 枚举 | 取值 | 说明 |
|------|------|------|
| `Role` | `sysadmin` / `records_manager` / `viewer` | 三类角色，禁止扩展 |
| `SecrecyLevel` | `public`(1) / `internal`(2) / `secret`(3) / `confidential`(4) | rank 越大越机密 |
| `DocStatus` | `draft` / `active` / `archived` / `destroyed` | `archived` 为软删除态 |
| `FileStatus` | `pending` / `stored` / `missing` / `deleted` | 物理文件状态 |
| `OCRStatus` | `queued` / `processing` / `ready` / `failed` / `skipped` | `skipped` 表示无需解析或引擎缺失 |
| `BorrowStatus` | `pending` / `approved` / `rejected` / `returned` / `expired` / `cancelled` | 借阅状态机 |
| `AuditAction` | `login` `login_failed` `logout` `room_create/update/delete` `category_create/update/delete` `doc_create/update/delete/view/download/print` … | 审计动作字典 |
| `Permission` | `doc:view` `doc:upload` `doc:edit` `doc:delete` `doc:download` `doc:print` `borrow:apply` `borrow:approve` `room:manage` `user:manage` `audit:view` `system:config` `backup:manage` `level:confidential` | 权限点 |

状态机要点：

- 资料：`draft → active`（发布）→ `archived`（软删除）；`destroyed` 仅管理员销毁流程使用。
- 解析：`queued → processing → ready | failed | skipped`；`failed` 可 `POST /api/ocr/files/{file_id}/retry` 重试，最多 `OCR_MAX_RETRY`(3) 次。
- 借阅：`pending → approved | rejected`；`approved → returned | expired`；`pending → cancelled`（申请人撤回）。到期由 `borrow_sweeper` 后台线程按 `OCR_WORKER_INTERVAL_SECONDS` 类似节奏扫描回收。

## 8. 权限矩阵与密级可见性

### 8.1 角色 → 权限点（`app/core/permissions.py: ROLE_PERMISSIONS`）

| 权限点 | sysadmin | records_manager | viewer |
|--------|:--------:|:---------------:|:------:|
| `doc:view` | ✔ | ✔ | ✔ |
| `doc:upload` | ✔ | ✔ | — |
| `doc:edit` | ✔ | ✔ | — |
| `doc:delete` | ✔ | ✔ | — |
| `doc:download` | ✔ | ✔ | — |
| `doc:print` | ✔ | ✔ | — |
| `borrow:apply` | ✔ | ✔ | ✔ |
| `borrow:approve` | ✔ | ✔ | — |
| `room:manage` | ✔ | ✔ | — |
| `user:manage` | ✔ | — | — |
| `audit:view` | ✔ | ✔ | — |
| `system:config` | ✔ | — | — |
| `backup:manage` | ✔ | — | — |
| `level:confidential` | ✔ | ✔ | — |

### 8.2 角色 → 最高可访问密级（`ROLE_MAX_LEVEL`）

| 角色 | 公开 | 内部 | 秘密 | 机密 |
|------|:----:|:----:|:----:|:----:|
| sysadmin | ✔ | ✔ | ✔ | ✔ |
| records_manager | ✔ | ✔ | ✔ | — |
| viewer | ✔ | ✔ | — | — |

落地方式：`visible_levels(role)` 返回该角色可见密级列表，检索/列表 SQL 直接加 `secrecy_level IN (...)` 条件；单条访问再做一次 `can_access_level()` 断言，不满足返回 403。

另有三重叠加授权：`document_permissions` 表支持按用户/部门/角色给单份资料开例外；借阅审批后发放临时下载授权（到期由 sweeper 回收）。

## 9. API 清单（69 个端点）

统一前缀 `/api`。鉴权头 `Authorization: Bearer <jwt>`。分页接口统一 `page` / `page_size`，列表返回 `{items, total, page, page_size}`。

#### 健康检查

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/health` | `登录即可` | health |
| GET | `/api/health/db` | `登录即可` | health_db |
| GET | `/api/health/storage` | `登录即可` | health_storage |

#### 认证与会话

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| POST | `/api/auth/change-password` | `登录即可` | change_password |
| POST | `/api/auth/login` | `登录即可` | login |
| POST | `/api/auth/logout` | `登录即可` | logout |
| GET | `/api/auth/me` | `登录即可` | me |
| GET | `/api/auth/permission-matrix` | `登录即可` | permission_matrix |

#### 部门

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/departments` | `doc:view` | list_departments |
| POST | `/api/departments` | `user:manage` | create_department |

#### 用户

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/users` | `user:manage` | list_users |
| POST | `/api/users` | `user:manage` | create_user |
| DELETE | `/api/users/{user_id}` | `user:manage` | disable_user |
| PATCH | `/api/users/{user_id}` | `user:manage` | update_user |
| POST | `/api/users/{user_id}/reset-password` | `user:manage` | reset_password |

#### 资料室

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/rooms` | `登录即可` | list_rooms |
| POST | `/api/rooms` | `room:manage` | create_room |
| DELETE | `/api/rooms/{room_id}` | `room:manage` | delete_room |
| PATCH | `/api/rooms/{room_id}` | `room:manage` | update_room |
| GET | `/api/rooms/{room_id}/categories` | `登录即可` | room_category_tree |

#### 类目树

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| POST | `/api/categories` | `room:manage` | create_category |
| GET | `/api/categories/tree` | `登录即可` | all_category_tree |
| DELETE | `/api/categories/{category_id}` | `room:manage` | delete_category |
| PATCH | `/api/categories/{category_id}` | `room:manage` | update_category |

#### 资料（含版本）

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/documents` | `doc:view` | list_documents |
| GET | `/api/documents/storage/usage` | `system:config` | storage_usage |
| POST | `/api/documents/upload` | `doc:upload` | upload_document |
| DELETE | `/api/documents/{doc_id}` | `doc:delete` | delete_document |
| GET | `/api/documents/{doc_id}` | `doc:view` | read_document |
| PATCH | `/api/documents/{doc_id}` | `doc:edit` | update_document |
| GET | `/api/documents/{doc_id}/files` | `登录即可` | list_files |
| GET | `/api/documents/{doc_id}/versions` | `doc:view` | list_versions |
| POST | `/api/documents/{doc_id}/versions` | `doc:edit` | add_version |
| POST | `/api/documents/{doc_id}/versions/{version_id}/rollback` | `doc:edit` | rollback_version |

#### 文件下载/预览

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/files/{file_id}/download` | `登录即可` | download_file |
| GET | `/api/files/{file_id}/preview` | `登录即可` | preview_file |
| GET | `/api/files/{file_id}/thumb` | `登录即可` | thumbnail |

#### 解析与 OCR

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| POST | `/api/ocr/documents/{doc_id}/reocr` | `doc:edit` | 整份资料重新解析 |
| POST | `/api/ocr/drain` | `doc:upload` | 立即跑空队列 |
| GET | `/api/ocr/engine` | `doc:upload` | OCR 引擎自检 |
| POST | `/api/ocr/files/{file_id}/retry` | `doc:edit` | 单个文件重试 |
| GET | `/api/ocr/stats` | `doc:upload` | 任务状态统计 |
| GET | `/api/ocr/tasks` | `doc:upload` | 任务列表 |
| POST | `/api/ocr/worker/start` | `system:config` | 启动后台解析线程 |
| POST | `/api/ocr/worker/stop` | `system:config` | 停止后台解析线程 |

#### 检索

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/search` | `doc:view` | search |
| GET | `/api/search/stats` | `audit:view` | stats |
| GET | `/api/search/suggest` | `doc:view` | suggest |

#### 借阅

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/borrow/levels` | `borrow:apply` | 当前用户可借阅的密级范围 |
| GET | `/api/borrow/mine` | `borrow:apply` | 我的借阅（借阅中优先） |
| GET | `/api/borrow/pending` | `borrow:approve` | 待审批列表（管理员） |
| GET | `/api/borrow/requests` | `borrow:apply` | 借阅申请列表 |
| POST | `/api/borrow/requests` | `borrow:apply` | 提交借阅申请 |
| GET | `/api/borrow/requests/{request_id}` | `borrow:apply` | 借阅详情 |
| POST | `/api/borrow/requests/{request_id}/approve` | `borrow:approve` | 审批通过 |
| POST | `/api/borrow/requests/{request_id}/cancel` | `borrow:apply` | 撤回申请 |
| POST | `/api/borrow/requests/{request_id}/reject` | `borrow:approve` | 审批驳回 |
| POST | `/api/borrow/requests/{request_id}/renew` | `borrow:apply` | 续借 |
| POST | `/api/borrow/requests/{request_id}/return` | `borrow:apply` | 归还 |
| POST | `/api/borrow/sweep` | `borrow:approve` | 手动触发到期回收（管理员） |
| GET | `/api/borrow/sweeper` | `borrow:approve` | 到期回收线程状态 |

#### 审计

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/audit/actions` | `audit:view` | 动作字典及各动作条数 |
| GET | `/api/audit/logs` | `audit:view` | 审计日志分页查询 |
| GET | `/api/audit/summary` | `audit:view` | 审计概览 |

#### 统计

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/stats/overview` | `doc:view` | 系统统计概览 |

#### 备份

| 方法 | 路径 | 权限 | 功能 |
|------|------|------|------|
| GET | `/api/backups` | `backup:manage` | 备份记录列表 |
| POST | `/api/backups` | `backup:manage` | 立即备份 |
| DELETE | `/api/backups/cleanup` | `backup:manage` | 清理过期备份 |
| GET | `/api/backups/{backup_id}/download` | `backup:manage` | 下载备份包 |

**契约注意事项**

- 类目树有双形态：`GET /api/categories/tree` 传 `room_id` 返回**数组**（该室类目树），不传返回 `{rooms:[...]}` 分组对象。前端必须兼容两种（历史白屏事故根因）。
- `POST /api/rooms` 承载两种语义：带 `parent_id` 时创建类目、不带时创建资料室（同一路径复用）。
- `POST /api/ocr/documents/{doc_id}/reocr?run_now=true` 需 `doc:edit` 权限，前端「重新解析」按钮用它。
- 下载/预览走 `GET /api/files/{file_id}/download`、`/preview`、`/thumb`，均需校验密级与授权，PDF 导出带动态水印（含用户名 + 时间）。
- 备份下载 `GET /api/backups/{backup_id}/download` 在记录中的绝对路径失效时，会按文件名回退到 `backups/` 目录查找（便携版迁移路径后的必要容错）。

## 10. 核心业务流程

### 10.1 资料入库

```
上传 → 校验扩展名/大小(MAX_UPLOAD_MB=500, 批量≤50) → 写 documents + files(pending)
     → storage.py 落盘 storage/YYYY/MM/{uuid}{ext} → files.status=stored
     → 抽取文本（PDF 文本层优先；DOCX/XLSX 直读；图片/扫描件走 OCR）
     → 回填 documents.search_text + search_grams → 生成 ocr_tasks 记录
     → 写审计 doc_create
```

### 10.2 检索

- 中文按 bigram 切分写入 `search_grams`，`GET /api/search` 走 `ILIKE`/`LIKE` 组合 + 密级过滤 + 类目过滤，目标 2 秒内返回。
- `GET /api/search/suggest` 提供输入联想；`/api/search/stats` 给检索页统计。
- 存量数据回填用 `scripts/rebuild_search_index.py`。

### 10.3 借阅

申请（`borrow:apply`）→ 档案管理员审批（`borrow:approve`）→ 批准后发放临时访问授权、写 `expire_at` → 到期由 `borrow_sweeper` 置 `expired` 并回收授权；支持归还、续借（有次数上限）、撤回。

### 10.4 版本与水印

`POST /api/documents/{doc_id}/versions` 上传新版本 → 版本链递增 → 可 `rollback` 回滚到指定版本。导出/打印走 `watermark.py` 生成带「用户名 + 时间戳」的动态水印 PDF。

### 10.5 备份

`POST /api/backups` 触发 `pg_dump` + `storage/` 打包为 `backups/backup_db_YYYYMMDD_HHMMSS.zip`，写 `backup_records`；`DELETE /api/backups/cleanup` 按 `BACKUP_KEEP_DAYS`(30) 清理过期包。

## 11. 前端结构

| 文件 | 职责 |
|------|------|
| `App.tsx` | 路由表 + `RequireAuth`（未登录跳 `/login` 并记来源）+ `RequirePermission`（无权限回首页，避免空白页）；页面全部 `lazy` 懒加载 |
| `auth/AuthContext.tsx` | 登录态、用户信息、`has(perm)` 判定、登出；token 存 `localStorage` |
| `layout/AppLayout.tsx` | 侧边栏菜单（按权限动态显隐）+ 顶栏（用户、改密、退出） |
| `api/client.ts` | axios 实例：注入 Bearer、统一错误提示、401 自动跳登录 |
| `api/types.ts` | 接口出入参类型 |
| `public/config.js` | **运行时**后端地址：`window.__APP_CONFIG__ = { apiBase: '/api' }`，部署改这里无需重新构建 |

页面与权限对应：

| 路由 | 页面 | 权限 |
|------|------|------|
| `/login` | Login | 公开 |
| `/change-password` | ChangePassword | 登录即可 |
| `/` | Dashboard | 登录即可 |
| `/documents` | Documents（上传、列表、详情、版本、下载、重新解析） | `doc:view` |
| `/search` | Search | `doc:view` |
| `/borrow` | Borrow（申请、我的借阅、待审批） | `borrow:apply` |
| `/rooms` | Rooms（资料室 + 类目树管理） | `room:manage` |
| `/users` | Users（用户与部门） | `user:manage` |
| `/audit` | Audit（日志、概览） | `audit:view` |
| `/backups` | Backups | `backup:manage` |
| `/health` | SystemCheck（自检：库、存储、OCR 引擎） | 登录即可 |

构建：`cd frontend && npm run build`（先 `tsc --noEmit`，0 错误才出包），产物 `frontend/dist` 由 `preview_server.py` 或 Nginx 托管。

## 12. 配置项清单（`.env`）

| 变量 | 当前值 | 说明 | 是否建议改 |
|------|-------|------|-----------|
| `APP_ENV` / `DEBUG` | development / true | 运行环境与调试开关 | 生产改 `production`/`false` |
| `SECRET_KEY` | `<见 .env>`（演示值） | JWT 签名密钥 | **生产必须换**（换后旧 token 全部失效） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 480 | token 有效期（8 小时） | 可调 |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | 127.0.0.1 / 4854 / erecords / postgres / `<见 .env>` | 库连接；**改密码需与已有 pgdata 一致** | 生产改密码 |
| `STORAGE_ROOT` / `BACKUP_ROOT` | ./storage / ./backups | 相对项目根 | 一般不改 |
| `MAX_UPLOAD_MB` / `BATCH_UPLOAD_LIMIT` | 500 / 50 | 单文件上限、批量条数 | 按需 |
| `API_HOST` / `API_PORT` | 127.0.0.1 / 8000 | 后端监听（仅本机，前面有反代） | 端口冲突时改 |
| `PUBLIC_BASE_URL` | http://127.0.0.1:8080 | 对外基址（下载链接、水印等） | 部署改真实地址 |
| `SEED_ADMIN_USERNAME/PASSWORD` | admin / `Admin@12345` | 仅 `seed_admin.py` 建号时用 | 生产改 |
| `OCR_ENGINE` / `OCR_LANG` | paddleocr / ch | 引擎与语言 | 换引擎改此 |
| `OCR_ENABLED` / `OCR_WORKER_ENABLED` | true / true | 总开关、后台线程开关 | 无 OCR 环境可关 |
| `OCR_WORKER_INTERVAL_SECONDS` | 5 | worker 轮询间隔 | 可调 |
| `OCR_MAX_RETRY` | 3 | 失败重试上限 | 可调 |
| `OCR_TASK_TIMEOUT_MINUTES` | 30 | 单任务超时 | 可调 |
| `OCR_MAX_PAGES` / `OCR_MAX_CHARS` / `OCR_IMAGE_DPI` | 50 / 200000 / 200 | 解析限流参数 | 可调 |
| `OCR_TEXT_LAYER_MIN_CHARS` | 20 | 文本层字符数达此值即不跑 OCR | 关键：调大可强制 OCR |
| `BACKUP_KEEP_DAYS` / `RECYCLE_RETENTION_DAYS` | 30 / 30 | 备份与回收站保留 | 按需 |
| `PORTABLE_WEB_PORT` | 8080 | 便携版页面端口 | 端口冲突时改 |

## 13. 脚本清单（`backend/scripts`）

| 脚本 | 用途 |
|------|------|
| `seed_admin.py` | 幂等初始化：4 个部门 + admin 账号；`--with-samples` 额外建「综合档案室」与三级示例类目（仅空库首部署用） |
| `check_empty_db.py` | 判定库内是否无任何资料室（exit 0 = 空库），供 start.bat 决定是否带示例数据 |
| `seed_demo_docs.py` | 生成并上传 5 份演示资料（管理办法/会议纪要/入职清单/报销指引/借阅流程），走真实上传链路（版本+OCR+审计完整），按题名判重可重跑 |
| `reset_demo_data.py` | 清理除「综合档案室」外全部资料室及其资料/版本/文件/OCR 任务/借阅。默认预演，`--apply` 执行，`--purge-files` 回收物理文件。**唯一绕过软删除的脚本**，审计日志受触发器保护会保留 |
| `rebuild_search_index.py` | 为存量资料回填 `search_text` 与 `search_grams` |
| `ocr_cli.py` | 不启 Web 也能补跑解析（命令行） |
| `preview_server.py` | 托管 `frontend/dist` + 反代 `/api` 到后端，替代 Nginx 供试用 |
| `verify_p0_smoke.py` | 骨架/模型/认证三角色/资料室类目树冒烟（P1~P4 合并版） |
| `verify_p5.py` | 入库/检索/版本/下载/预览/权限/审计 |
| `verify_p6.py` | OCR 队列/文本提取/状态流转/检索联动/审计 |
| `verify_p7.py` | 检索专项验收 |
| `verify_p8.py` | 借阅申请→审批→临时授权→归还/续借/到期回收 |
| `verify_p9.py` | 版本管理/PDF 动态水印/审计防篡改/备份 |
| `verify_p9_frontend_contract.py` | 类目树双形态、重新解析接口权限 |
| `verify_p10.py` | HTTPS 部署联调（Nginx TLS + 自签证书 + 反代头 + 运行时配置） |
| `verify_data_layer.py` | 直连库校验表/索引/约束/种子数据 |
| `verify_api_contract.py` | 静态比对「前端调用点 × 后端路由定义」，未匹配数必须为 0 |
| `verify_frontend_api.py` | 以 admin 登录遍历各页面依赖的全部接口（16 项） |
| `run_all_verify.py` | 串行跑 `verify_p*.py` 并汇总结果 |

推荐的演示库重建顺序：

```powershell
.\runtime\python\python.exe scripts\reset_demo_data.py --apply --purge-files
.\runtime\python\python.exe scripts\seed_demo_docs.py
```

## 14. 验收体系（改完必须跑）

在项目根或 `backend/` 下用**内嵌运行时**执行（不是系统 Python）：

```powershell
cd backend
..\runtime\python\python.exe scripts\run_all_verify.py
..\runtime\python\python.exe scripts\verify_api_contract.py
..\runtime\python\python.exe scripts\verify_frontend_api.py
```

判定标准：

| 脚本 | 通过标准 |
|------|---------|
| `run_all_verify.py` | 全部 `verify_p*.py` 返回 0，汇总行显示 `X/X 通过` |
| `verify_api_contract.py` | 未匹配路由数 = 0 |
| `verify_frontend_api.py` | 16 项接口全部 200/预期状态码 |
| `verify_p9.py` | 水印 PDF 可生成、审计触发器禁止 UPDATE/DELETE、备份包可下载 |

前端另加一道：

```powershell
cd frontend
npm run build      # tsc --noEmit 必须 0 错误
```

> 验收脚本依赖数据库已启动（`start.bat` 或 `launcher.py start`）。历史经验：每阶段都跑双验收（数据层 + 接口层），能提前暴露「模型与路由不一致」「路由未注册」类缺陷。

## 15. 已知限制与历史坑（升级重点）

| # | 问题 | 现状 | 处理建议 |
|---|------|------|---------|
| 1 | **OCR 引擎未安装**：`runtime` 内无 `paddleocr`/`paddlepaddle`，`/api/ocr/engine` 返回 `available=false` | 扫描件/图片解析走 `skipped`，PDF 有文本层仍正常抽取；入库不阻塞 | 需要扫描件识别时按 `requirements-ocr.txt` 补装（注意 numpy 2.x 与 paddle 兼容），模型须离线放入；否则保持 `OCR_ENABLED=false` 避免误导 |
| 2 | 新增接口未在 `main.py` 注册 | 曾返回 404 | 每次加路由都要 `import` + `include_router`，并跑 `verify_api_contract.py` |
| 3 | **类目树双形态**：传 `room_id` 返数组，不传返 `{rooms:[...]}` | `/documents` 页曾因按数组解析而白屏，已修 | 改 `Documents.tsx` / `Rooms.tsx` 必须兼容两形态；建议给页面套 `ErrorBoundary`（当前缺失） |
| 4 | `audit_logs.created_at` 曾用字符串常量默认值 | 已改 `func.now()` + `ALTER TABLE SET DEFAULT now()`；旧库里 614 条历史记录时间不可还原 | 新库无此问题；如需修历史只能按其他字段推断 |
| 5 | `requirements.txt` 声明版本 ≠ 运行时实际版本 | pydantic 2.14.1 / alembic 1.20.1 / PyMuPDF 2.0 / Pillow 13.0.0 | 升级依赖以 `runtime` 实测为准，装完必须重跑验收 |
| 6 | `pgdata/` 不随包分发 | 首次 `start.bat` 自动 `initdb`（约 1 分钟） | 不要手动改 `pgdata` 内文件；改库密码需重建集群或改 pg_hba |
| 7 | 首次初始化走 `data/erecords_data.sql` | 导入的是含演示数据 + admin 哈希的整库快照 | 要「干净空库」发布：删掉该 SQL，改走 `alembic upgrade head` + `seed_admin.py`（此时 admin 密码 = `SEED_ADMIN_PASSWORD`） |
| 8 | 默认口令与密钥为演示值 | admin/`<见 .env>`（SQL 快照）或 `Admin@12345`（seed 路径），`SECRET_KEY` 固定 | 正式投用前必须改密 + 换 `SECRET_KEY` |
| 9 | 便携版无 TLS，仅 127.0.0.1 | `preview_server.py` 明文 HTTP | 局域网多终端需按 `deploy/nginx/` + `deploy/certs/gen-cert.ps1` 起 Nginx(8443)，各终端导入 `server.crt` |
| 10 | 备份记录存绝对路径 | 迁移目录后会失效 | 已加「按文件名回退到 `backups/`」容错，勿删该逻辑 |
| 11 | 解压路径过深/含空格中文可能触发 Windows 长路径问题 | 使用说明已提示 | 建议解压到 `D:\erecords` 这类短路径，**不要以管理员身份运行** |
| 12 | 演示重置脚本是唯一物理删除入口 | `reset_demo_data.py --purge-files` | 生产环境禁止使用；日常删除一律软删除 |
| 13 | 前端无全局错误边界，组件异常即白屏 | 仅路由级权限守卫 | 可在 `AppLayout` 外包 `ErrorBoundary` + 兜底页面 |
| 14 | `data/` 中的 SQL 是快照，结构变更后不同步 | 结构以 Alembic 为准 | 改表后如仍要保留 SQL 快照，需重新 `pg_dump` |

## 16. 二次开发手册（常见改造路径）

### 16.1 加一个字段（例：资料增加「保存期限」）

1. `app/models/document.py` 加 `retention_years: Mapped[int]`。
2. `alembic revision -m "add retention_years"`，手写 `op.add_column`。
3. `app/schemas/document.py` 出入参加字段。
4. `app/services/documents.py` 增改查逻辑同步。
5. 前端 `api/types.ts` + `Documents.tsx` 表单/列表加列。
6. `alembic upgrade head` → `npm run build` → 跑第 14 章验收。

### 16.2 加一个接口

1. 在对应 `app/api/routes/*.py` 下加函数，装饰器写 `@router.get/post(...)`，依赖 `Depends(require_permission(Permission.XXX))`。
2. **在 `app/main.py` 里确认该 router 已 `import` 且 `include_router(..., prefix=settings.API_PREFIX)`**（新模块才需要）。
3. `verify_api_contract.py` 确认契约零偏差。
4. 写操作记得 `write_audit(...)`。

### 16.3 加一个页面

1. `frontend/src/pages/Xxx.tsx`；`App.tsx` 加 `lazy` + `<Route>`，用 `RequirePermission` 包住。
2. `layout/AppLayout.tsx` 侧边栏加菜单项，按权限显隐。
3. 接口调用统一走 `api/client.ts`；后端必须有对应路由（否则第 2 条坑）。
4. `npm run build`（`tsc --noEmit` 必须 0 错）。

### 16.4 改权限 / 密级

- 权限点：`app/models/enums.py: Permission` → `app/core/permissions.py: ROLE_PERMISSIONS` → 前端菜单/按钮显隐。
- 密级：`SecrecyLevel.rank` 与 `ROLE_MAX_LEVEL` 同时改，否则列表过滤与单条校验会不一致。
- 不要新增第 4 类角色；需要更细粒度请用 `document_permissions` 做资料级例外授权。

### 16.5 换 OCR 引擎

1. `app/services/ocr.py: get_ocr_engine()` 返回对象需支持 `.ocr(np_array)`，返回值由 `_normalize` 兼容 2.x/3.x 结构。
2. 装包后设 `OCR_ENGINE`，重启后端，用 `GET /api/ocr/engine` 确认 `available=true`。
3. 用 `POST /api/ocr/files/{file_id}/retry` 对历史 skipped 文件补跑。

### 16.6 升级依赖 / 换 Python 版本

1. 只改 `runtime/python`（便携版）时：`runtime\python\python.exe -m pip install -U ...`。
2. 装完立刻跑 `run_all_verify.py` + `verify_frontend_api.py`。
3. PyMuPDF、pydantic、SQLAlchemy 大版本升级要重点回归：文件预览、模型序列化、检索 SQL。

### 16.7 改端口 / 换机部署

- 只改 `.env`：`POSTGRES_PORT` / `API_PORT` / `PORTABLE_WEB_PORT` / `PUBLIC_BASE_URL`，前端无需重建。
- 换机：拷整个目录（除 `pgdata`、`logs/*.pid`）→ 首启自动 initdb → 若需保留数据，用 `backups/backup_db_*.zip` 恢复或直接搬 `pgdata`（同版本、同路径策略下可用）。

### 16.8 正式化上线清单

1. 换 `SECRET_KEY`、改 admin 密码、关闭 `DEBUG`。
2. Nginx + 自签证书（`deploy/certs/gen-cert.ps1`，证书含服务器 IP SAN），确认 `PUBLIC_BASE_URL` 为 `https://<IP>:8443`。
3. 关掉 `preview_server`，改由 Nginx 管 `dist`。
4. 配 Windows 计划任务：每日 `backups` + 日志清理。
5. 建 3 类账号各一，按第 8 章矩阵逐项验证越权返回 403。

## 17. 交接与打包清单

**必须带走**

```
backend/（全部）  frontend/src、frontend/public、frontend/dist、frontend/package.json、vite/ts 配置
deploy/  data/erecords_data.sql  .env  .env.example  launcher.py  start/stop/status.bat
docker-compose.yml  CLAUDE.md  使用说明.md/txt  runtime/python  runtime/pg
```

**不要带**

```
pgdata/（体积大且与本机绑定）  logs/  storage/（含真实档案）  backups/（含业务数据）  __pycache__/  node_modules/
```

## 18. 术语与环境速查

| 概念 | 含义 |
|------|------|
| 资料室 room | 一级库房，含位置、责任人、密级范围 |
| 类目 category | 资料室下的树形分类，支持三级（`parent_id` 自关联） |
| 档号 doc_no | 资料唯一编号，形如 `ZH-2026-0001` |
| 密级 secrecy_level | 公开/内部/秘密/机密，决定可见范围 |
| 借阅 borrow | 查阅者对无下载权限资料的临时申请，审批后限时可用 |
| 软删除 archive | `status='archived'` + `is_deleted=true`，数据仍在，可恢复 |

**运行环境**：Windows 10/11 x64；内嵌 Python 3.11（`runtime/python`）、PostgreSQL 16.2（`runtime/pg`）；无需系统级安装任何组件；解压即用，`start.bat` 一键起，`stop.bat` 一键停，`status.bat` 看三服务状态。

**默认访问**：http://127.0.0.1:8080 ，账号 `admin` / `<见 .env>`。

## 19. 设计提示词与分阶段开发提示词（可复用基线）

> 说明：本节不是历史会话原文的抄录，而是依据已定稿的设计参数与最终代码结构**重建**的可复用提示词骨架，用于让其他 AI 按同一基线继续迭代，避免推倒重来。

### 19.1 设计文档生成提示词（15 章骨架）

```
角色：你是企业内网档案系统的解决方案架构师。
任务：为「电子资料室系统」输出一份 15 章设计文档，全部中文，面向非技术人员阅读。

硬性参数（不得改动）：
1. 部署：Windows 10/11 单机局域网，10~30 人，纯内网，禁止公网访问；
2. 密级：四级——公开/内部/秘密/机密；
3. 角色：三类——系统管理员 sysadmin / 档案管理员 records_manager / 查阅者 viewer，禁止第 4 类；
4. 数据库：PostgreSQL，禁止 SQLite 作为主库；
5. 传输：内网 HTTPS，自签证书须含服务器 IP SAN；
6. 界面：全中文，任意功能操作路径 ≤ 3 层；
7. OCR：离线引擎，异步队列，不阻塞入库；
8. 部署方式：Docker 与纯本地双方案。

章节要求：
1 项目背景与目标 2 用户角色与权限矩阵 3 密级与可见性模型 4 功能清单（按角色）
5 数据模型与表设计 6 文件存储策略 7 检索方案（中文） 8 OCR 异步方案
9 借阅审批流程 10 版本与水印 11 审计与防篡改 12 备份与恢复
13 部署架构（Docker/本地） 14 安全与合规 15 验收标准与分阶段计划
```

### 19.2 分阶段编码提示词模板（P1~P10）

每阶段都用同一模板，只是替换目标与验收。模板：

```
阶段：P<N> <阶段名>
输入：设计文档第 <相关章节>；已完成 P<N-1>，数据库已 upgrade 到 head。
产出要求：
1. 只改本阶段相关文件，给出完整文件内容（不省略）；
2. service + route + schema + migration 四件套齐全；
3. 新路由必须在 app/main.py 完成 import 与 include_router；
4. 写操作必须调用 write_audit；
5. 同步产出 scripts/verify_p<N>.py：用 fastapi TestClient 断言，覆盖正常流程 + 未登录 401 + 越权 403 + 审计落库。
完成标准：verify_p<N>.py 全部断言通过（exit=0），并把结果行贴出来。
```

各阶段目标与对应验收脚本（与现有代码一一对应）：

| 阶段 | 目标 | 验收脚本 |
|------|------|---------|
| P1 | 项目骨架、配置、双部署、健康检查 | `verify_p0_smoke.py`（合并版覆盖 P1~P4） |
| P2 | 数据模型与迁移（16 表） | `verify_data_layer.py` |
| P3 | JWT 认证、三角色权限、首登改密 | `verify_p0_smoke.py` |
| P4 | 资料室与三级类目树 | `verify_p0_smoke.py` |
| P5 | 上传、UUID 落盘、年月分目录、版本、下载/预览 | `verify_p5.py` |
| P6 | OCR 异步队列、文本提取、状态流转 | `verify_p6.py` |
| P7 | 中文全文检索（bigram + 密级过滤） | `verify_p7.py` |
| P8 | 借阅申请→审批→临时授权→归还/续借/到期回收 | `verify_p8.py` |
| P9 | 版本回滚、动态水印、审计防篡改、备份 | `verify_p9.py` + `verify_p9_frontend_contract.py` |
| P10 | HTTPS 部署联调、多终端证书导入 | `verify_p10.py`（需 Nginx 环境） |

### 19.3 阶段推进纪律（踩坑总结）

1. 每阶段结束先 `alembic upgrade head`，再跑验收，避免跨阶段数据库形态不一致。
2. 数据层与接口层分开验：数据层直连库查表/索引/约束；接口层用 TestClient 查路由挂载与状态码。
3. 每阶段都必须断言「未登录 401 / 越权 403」，否则权限漏洞会累积到最后才暴露。
4. 前端页面写完立刻跑 `verify_api_contract.py`，静态比对调用路径与后端路由，未匹配必须为 0。
5. 任何「页面白屏」优先查接口返回结构是否与前端解析假设一致（类目树双形态就是这么来的）。

### 19.4 一句话交接提示词（可直接粘给其他 AI）

```
项目：电子资料室系统（FastAPI + PostgreSQL 16 + React/TS/AntD），Windows 局域网离线部署，便携免安装。
根目录：<解压后的项目根>
必读：本档案「2 硬约束 / 4 目录 / 6 数据模型 / 9 API / 15 已知坑」，其次 CLAUDE.md。
改造原则：不引入联网依赖、不换 SQLite、不新增角色、不破坏软删除与审计、所有新路由必须在 app/main.py 注册。
验证：改完跑 backend/scripts/run_all_verify.py + verify_api_contract.py + verify_frontend_api.py + npm run build，全部通过才算完成。
本次任务：<在此写你的需求>
```
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
