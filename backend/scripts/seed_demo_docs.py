"""生成 5 份演示资料并上传到综合档案室（走真实上传接口，保留版本 / OCR / 审计链路）。

前置：后端 API 已启动、已执行 seed_admin.py --with-samples。

用法（在 backend 目录下执行）：
    python scripts/seed_demo_docs.py
可重复执行：档号重复时接口返回 409，脚本会跳过并提示。
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document as Docx  # noqa: E402
from docx.shared import Pt  # noqa: E402

from app.core.config import settings  # noqa: E402

API = f"http://{settings.API_HOST}:{settings.API_PORT}/api"
BASE = Path(__file__).resolve().parent
OUT = BASE / "demo_files"
OUT.mkdir(exist_ok=True)


def make_docx(name: str, title: str, lines: list[str]) -> Path:
    doc = Docx()
    h = doc.add_heading(title, level=1)
    for p in h.runs:
        p.font.size = Pt(18)
    for line in lines:
        if line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            doc.add_paragraph(line)
    path = OUT / name
    doc.save(path)
    return path


def make_txt(name: str, lines: list[str]) -> Path:
    path = OUT / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


FILES = []

FILES.append((
    make_docx("公司档案管理办法（试行）.docx", "广州市市维新材料科技有限公司档案管理办法（试行）", [
        "第一章  总则",
        "## 第一条  目的",
        "为规范公司档案的形成、收集、整理、保管与利用，保障档案的真实、完整与安全，依据《中华人民共和国档案法》及上级工会、集团档案管理有关规定，结合公司实际，制定本办法。",
        "## 第二条  适用范围",
        "本办法适用于公司各部门在职能活动中形成的、具有保存价值的文字、图表、声像、电子文件等各种载体的档案。",
        "## 第三条  管理体制",
        "公司档案工作实行统一领导、分级管理。综合部为档案归口管理部门，设综合档案室，配备专（兼）职档案员；各部门指定一名档案联络员。",
        "第二章  归档范围与保管期限",
        "## 第四条  归档范围",
        "- 行政管理类：公司章程、会议纪要、规章制度、年度工作计划与总结、重要请示批复",
        "- 人事管理类：员工档案、劳动合同、考核与培训记录、职称评审材料",
        "- 财务档案类：会计凭证、账簿、财务报告、审计报告、税务资料",
        "- 工程技术与业务类：项目立项、设计图纸、验收资料、合同与结算文件",
        "## 第五条  保管期限",
        "档案保管期限分为永久、30 年、10 年三类。会计档案、人事档案按国家有关规定执行；公司重要决策文件、章程、年度报告列为永久保管。",
        "第三章  整理与著录",
        "## 第六条  分类编号",
        "档案按「资料室—类目—年度—件号」体系整理，档号由系统自动生成，格式为「室编码-年度-流水号」，纸质与电子档案保持一致。",
        "## 第七条  著录要求",
        "每份档案应著录题名、责任者、形成时间、密级、关键词、摘要、保管期限等信息，电子文件应同步完成全文 OCR 以便检索。",
        "第四章  保管与利用",
        "## 第八条  库房管理",
        "档案库房应满足防火、防潮、防虫、防盗、防光、防尘、防高温要求，温度控制在 14—24℃，相对湿度控制在 45%—60%，每季度检查一次并做好记录。",
        "## 第九条  借阅管理",
        "内部人员借阅一般档案，经本部门负责人同意后办理借阅手续；借阅机密级及以上档案，须经分管领导审批。借阅期限一般不超过 7 个工作日，可续借一次。",
        "## 第十条  复制与摘录",
        "档案复制件须加盖档案证明专用章方可对外提供；未经批准，任何人不得擅自复制、摘录、传播涉密档案内容。",
        "第五章  鉴定与销毁",
        "## 第十一条  到期鉴定",
        "保管期限届满的档案，由综合部组织鉴定小组进行鉴定，提出存毁意见，报公司领导批准后执行。",
        "## 第十二条  销毁程序",
        "经批准销毁的档案应编制销毁清册，由两名以上人员监销，并在销毁清册上签字；销毁清册永久保存。",
        "第六章  附则",
        "## 第十三条  施行日期",
        "本办法自发布之日起试行，由综合部负责解释。",
        "",
        "广州市市维新材料科技有限公司",
        "二〇二六年一月",
    ]),
    "行政管理", 7, "公司档案管理的基本制度依据，涵盖归档范围、整理著录、保管利用与鉴定销毁全流程。", "档案管理,规章制度,归档范围,保管期限",
))

FILES.append((
    make_docx("2026年度档案工作会议纪要.docx", "2026 年度档案工作会议纪要", [
        "会议时间：2026 年 1 月 8 日 14:30—16:30",
        "会议地点：公司三楼会议室",
        "主持人：综合部部长",
        "参会人员：各部门档案联络员、综合部档案员、信息化管理员",
        "记录人：综合部干事",
        "## 一、2025 年度档案工作情况通报",
        "全年共接收各部门移交档案 1062 件，完成数字化扫描与著录 100%，电子资料室系统上线试运行，实现全文检索、在线借阅与操作留痕。存在的问题：部分部门移交不及时，个别文件题名与实际内容不符，少数扫描件缺页。",
        "## 二、2026 年度重点工作安排",
        "- 完成 2025 年度及以前积压档案的清理与补录，6 月底前完成率不低于 95%",
        "- 全面启用电子资料室系统，纸质档案与电子档案双套制管理",
        "- 组织两期档案业务培训，覆盖全部档案联络员",
        "- 每季度开展一次库房安全与温湿度专项检查",
        "## 三、议定事项",
        "- 各部门于每月 5 日前完成上月文件移交，综合部按月通报移交情况",
        "- 涉密档案一律不得上传至外网，非涉密电子文件统一在电子资料室系统内流转",
        "- 借阅审批权限按密级分级设置，机密级及以上须分管领导审批",
        "- 综合部负责修订《档案管理办法》，于 2 月底前印发执行",
        "## 四、下一步工作要求",
        "各部门要指定专人负责本部门文件材料的收集与初步整理，做到「应归尽归、应归早归」，确保档案工作与业务工作同步推进。",
        "",
        "广州市市维新材料科技有限公司综合部",
        "二〇二六年一月八日",
    ]),
    "行政管理", 6, "2026 年度档案工作会议纪要，明确年度重点任务、移交时限与借阅审批要求。", "会议纪要,年度工作会议,档案工作",
))

FILES.append((
    make_txt("员工入职材料归档清单.txt", [
        "员工入职材料归档清单",
        "（综合部人事档案专用）",
        "",
        "一、必备材料",
        "1. 入职登记表（本人签名，贴一寸免冠照片）",
        "2. 身份证复印件（正反面同一页，A4）",
        "3. 学历、学位证书复印件及学信网学历认证报告",
        "4. 与原单位解除劳动关系证明或离职证明",
        "5. 劳动合同（一式两份，本人签字并按指模）",
        "6. 保密协议与竞业限制协议（涉密岗位）",
        "7. 银行账户信息确认单（工资代发）",
        "8. 近期体检报告（三个月内有效）",
        "",
        "二、视情况补充材料",
        "1. 职称证书、职业资格证书复印件",
        "2. 中共党员组织关系转接介绍信",
        "3. 工会会员入会申请表",
        "4. 特种作业操作证（相关岗位）",
        "5. 应届毕业生报到证（如适用）",
        "",
        "三、归档要求",
        "1. 材料齐全后 3 个工作日内完成扫描并录入电子资料室系统，归入「人事管理—员工档案」类目；",
        "2. 纸质原件装订成册，一人一档，档案袋标注姓名、工号、部门；",
        "3. 员工档案密级定为「机密」，仅综合部人事岗与分管领导可查阅；",
        "4. 离职员工档案自离职之日起继续保存 30 年，另册存放。",
        "",
        "四、常见问题",
        "问：复印件可以用手机拍照打印吗？答：不可以，须为清晰复印或扫描件，字迹可辨。",
        "问：体检报告过期怎么办？答：重新体检后方可归档，费用按公司规定报销。",
        "",
        "编制：综合部",
        "版本：V1.0    生效日期：2026 年 1 月",
    ]),
    "人事管理", 9, "人事档案归集标准清单，明确必备材料、扫描归档要求与密级设定。", "人事档案,入职材料,归档清单",
))

FILES.append((
    make_txt("2026年度费用报销指引.txt", [
        "2026 年度费用报销指引",
        "",
        "一、报销原则",
        "1. 实事求是、票据真实、一事一报；",
        "2. 报销事项须与公司业务相关，严禁虚开、代开、拆分发票；",
        "3. 费用发生之日起 30 日内提交报销，跨年度费用原则上不予受理。",
        "",
        "二、常见费用标准",
        "1. 市内交通：凭票实报，单次超过 100 元须说明事由；",
        "2. 出差住宿：广州以外地区按职级标准执行，部门负责人及以上不超过 500 元/晚；",
        "3. 业务招待：须事前申请，人均不超过 150 元，附接待对象单位及人数说明；",
        "4. 办公用品：单笔 500 元以上须附比价或询价记录；",
        "5. 快递费：月结单据须与寄件登记表核对一致。",
        "",
        "三、票据要求",
        "1. 发票抬头：广州市市维新材料科技有限公司，须填写纳税人识别号；",
        "2. 发票内容应真实具体，不得笼统开具「办公用品」「材料一批」；",
        "3. 电子发票须提交 PDF 原件，并在系统内查重，避免重复报销。",
        "",
        "四、审批流程",
        "经办人填单 → 部门负责人审核 → 财务复核 → 分管领导审批 → 出纳付款",
        "单笔 5000 元以上须报总经理审批；单笔 50000 元以上按「三重一大」事项集体决策。",
        "",
        "五、付款时限",
        "审批完成后每周三、周五集中付款，一般 5 个工作日内到账。",
        "",
        "六、附则",
        "本指引由财务部负责解释，自 2026 年 1 月 1 日起执行。",
        "",
        "财务部",
        "二〇二五年十二月",
    ]),
    "财务档案", 10, "年度费用报销标准与审批流程说明，含票据要求与付款时限。", "费用报销,财务制度,审批流程",
))

FILES.append((
    make_docx("档案借阅与利用申请流程说明.docx", "档案借阅与利用申请流程说明", [
        "## 一、适用范围",
        "公司内部员工因工作需要查阅、借阅、复制档案，以及外单位因公查阅公司档案，均适用本流程。",
        "## 二、申请方式",
        "登录「电子资料室」系统，在资料详情页点击「申请借阅」，填写借阅事由、期望借阅天数，并选择是否需要下载、打印权限，提交后进入审批流程。",
        "## 三、审批权限",
        "- 公开、内部级档案：部门负责人审批",
        "- 秘密级档案：部门负责人审核后报分管领导审批",
        "- 机密级及以上档案：报总经理审批，原则上限在档案室阅览，不得带离",
        "- 外单位查阅：须持单位介绍信，经分管领导批准，由档案员陪同查阅",
        "## 四、借阅期限",
        "借阅期限一般不超过 7 个工作日，因工作需要可续借一次，续借期限不超过 7 个工作日；逾期未还，系统自动收回权限并提示归还。",
        "## 五、利用要求",
        "- 借阅人应对档案的安全、保密负责，不得转借、涂改、污损、拆散档案",
        "- 复制件仅供本次工作使用，用毕自行销毁或退回档案室",
        "- 引用档案内容形成公开材料的，须经综合部审核",
        "## 六、归还与归档",
        "借阅到期后，借阅人应在系统内点击「归还」，并将纸质原件当面交回档案员核对；档案员检查无误后在系统内确认，完成闭环。",
        "## 七、违规处理",
        "丢失、损毁档案的，借阅人应书面说明情况，按档案价值赔偿并承担相应责任；擅自复制、传播涉密档案的，按公司保密管理规定处理。",
        "",
        "综合部",
        "二〇二六年一月",
    ]),
    "行政管理", 7, "档案借阅与利用的操作流程与审批权限说明，含期限、利用要求与违规处理。", "借阅流程,档案利用,审批权限",
))


def login() -> str:
    body = json.dumps({"username": settings.SEED_ADMIN_USERNAME,
                       "password": os.environ.get("DEMO_ADMIN_PASSWORD",
                                                  settings.SEED_ADMIN_PASSWORD + "#V")}).encode()
    req = urllib.request.Request(
        API + "/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data.get("access_token") or data.get("token")


def upload(token: str, path: Path, title: str, room_id: int, category_id: int,
           summary: str, keywords: str) -> dict:
    boundary = "----demo" + uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    field("room_id", str(room_id))
    field("title", title)
    field("category_id", str(category_id))
    field("secrecy_level", "internal")
    field("summary", summary)
    field("keywords", keywords)
    field("archive_year", "2026")
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
         f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        API + "/documents/upload", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return {"doc_no": "-", "title": title, "files": [], "skipped": True}
        raise


def existing_titles(token: str, room_id: int = 7) -> set:
    """读取资料室已有资料题名，保证脚本幂等（重复执行不会产生重复资料）。"""
    req = urllib.request.Request(
        f"{API}/documents?room_id={room_id}&page_size=200",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    return {i.get("title") for i in (data.get("items") or [])}


def main() -> int:
    token = login()
    print("login ok")
    have = existing_titles(token)
    cat_names = {4: "行政管理", 5: "会议纪要", 6: "年度工作会议", 7: "规章制度",
                 8: "人事管理", 9: "员工档案", 10: "财务档案"}
    results = []
    for path, _cat_label, cat_id, summary, keywords in FILES:
        title = path.stem
        if title in have:
            print(f"已存在，跳过: {title}")
            continue
        info = upload(token, path, title, 7, cat_id, summary, keywords)
        have.add(title)
        results.append({"id": info.get("id"), "doc_no": info.get("doc_no"),
                        "title": info.get("title"), "category": cat_names.get(cat_id),
                        "file": path.name, "files": len(info.get("files") or [])})
        tag = "跳过（档号已存在）" if info.get("skipped") else "已入库"
        print(f"{tag}: {info.get('doc_no')} {title} -> {cat_names.get(cat_id)}")
    (BASE / "demo_upload_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
