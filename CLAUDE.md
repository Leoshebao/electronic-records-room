# 电子资料室系统（Electronic Records Room）

企业内部档案管理系统。Windows 10 局域网部署，10~30 人使用，全离线运行。

## 一句话架构

客户端浏览器 → Nginx(8443, TLS 终止) → FastAPI(127.0.0.1:8000) → PostgreSQL 16 / OCR Worker / 本地文件存储

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL 16 |
| 前端 | React 18 + TypeScript + Vite + Ant Design 5 |
| Web 服务器 | Nginx（TLS 终止 + 静态托管 + 反代） |
| OCR | PaddleOCR CPU 版（离线模型） |
| 异步任务 | 数据库任务表 + 后台 worker（规模不需要 Redis） |

## 目录约定

```
backend/
  app/
    core/       配置、安全、日志
    db/         会话、基类
    models/     ORM 模型
    schemas/    Pydantic 模型
    api/routes/ 路由
    services/   业务逻辑
  alembic/      迁移
  scripts/      初始化脚本
frontend/
  src/
    api/        axios 客户端
    contexts/   全局状态
    components/ 通用组件
    pages/      页面
  public/config.js   运行时 API 地址配置
deploy/
  nginx/        Nginx 配置
  certs/        证书生成脚本
  scripts/      启动脚本
storage/        运行期文件存储（不入版本库）
```

## 编码规范

- 所有接口前缀 `/api`，健康检查 `/api/health`
- 权限判定一律在服务端逐请求执行，前端隐藏不作为安全手段
- 删除一律软删除（`status='archived'`），不做物理删除
- 文件落盘用 UUID 文件名，按 `年/月` 分目录，原始文件名只存数据库
- 时间统一 UTC 存储，前端按本地时区展示
- 所有写操作记录审计日志

## 分阶段计划

| 阶段 | 目标 | 验收 |
|------|------|------|
| P1 | 项目骨架 + 双部署 + 健康检查 | `/api/health` 返回 200，Docker 与本地均可启动 |
| P2 | 数据库模型与迁移（15 张表） | `alembic upgrade head` 成功，表结构齐全 |
| P3 | 认证与三角色权限 | admin 登录拿 JWT，越权返回 403 |
| P4 | 资料室与类目树 | 三级目录增删改查 |
| P5 | 文件上传与存储 | 上传成功、UUID 落盘、年月分目录 |
| P6 | OCR 异步队列 | 上传后状态 processing → ready |
| P7 | 中文全文检索 | 关键词命中，2 秒内返回 |
| P8 | 借阅审批与到期回收 | 申请→审批→到期自动失效 |
| P9 | 版本、水印、审计、统计、备份 | 各功能可演示 |
| P10 | HTTPS 与局域网多终端联调 | 外部终端导入证书后正常访问 |

## 本地开发命令

```powershell
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

## 生产部署

- Docker：`docker compose up -d`
- 本地：`deploy\scripts\start.bat`
- 初始化数据：`backend\scripts\seed_admin.py`（建 4 个部门 + admin，幂等）；加 `--with-samples` 额外建「综合档案室」与三级示例类目，仅在空库首次部署时由 start.bat 自动带上（`check_empty_db.py` 判定，exit 0 表示空库）。

## 数据重置脚本（backend/scripts，试用与演示场景专用）

| 脚本 | 用途 |
|------|------|
| `reset_demo_data.py` | 清理除「综合档案室」外的全部资料室及其资料、版本、文件、OCR 任务、借阅申请。默认只预演；`--apply` 执行；`--purge-files` 同时回收物理文件。**唯一绕过软删除策略的脚本**，只用于重置演示环境，不参与业务链路。审计日志受 `prevent_audit_modify` 触发器保护，脚本自动保留。 |
| `seed_demo_docs.py` | 生成并上传 5 份演示资料（制度、纪要、清单、指引、流程），按题名判重，可重复执行；走真实上传接口，因此版本、OCR、审计链路完整。 |

调用顺序建议：`reset_demo_data.py --apply --purge-files` → `seed_demo_docs.py`，即可得到一份干净的演示库。

## 验收脚本（backend/scripts）

在 venv 下执行，`exit=0` 视为通过：

| 脚本 | 覆盖范围 |
|------|---------|
| `verify_data_layer.py` | 表/索引/约束/种子数据，直连库校验 |
| `verify_api_contract.py` | 前端调用点与后端路由契约，未匹配数必须为 0 |
| `verify_frontend_api.py` | 以 admin 登录遍历各页面依赖的全部接口（16 项） |
| `verify_p9_frontend_contract.py` | 类目树双形态（分组 dict / 按室数组+嵌套）、404 分支、OCR 统计、重新解析接口 |

注意事项：

- 前端每次新增 `http.xxx('/path')` 调用，必须同步在后端挂路由，并在 `app/main.py` 完成 `import` + `include_router`，否则接口返回 404。
- 前端构建：`npm run build` 输出到 `frontend/dist`，由 Nginx 静态托管；`tsc --noEmit` 必须为 0 错误。
- 资料详情页「重新解析」按钮调用 `POST /api/ocr/documents/{id}/reocr?run_now=true`，需 `doc:edit` 权限。
