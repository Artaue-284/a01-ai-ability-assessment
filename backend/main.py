from __future__ import annotations

import json
import csv
import io
import base64
import hashlib
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algorithm.adaptive_test import AdaptiveTestEngine, DIMENSIONS
from backend.database import (
    application_count_by_position, application_dashboard, apply_position, create_account,
    create_position, create_session, create_test, dashboard_data, delete_session, export_rows,
    get_position, init_db, latest_completed_scores, latest_completed_test_id, list_accounts,
    list_positions, list_question_items, load_test, anonymous_enterprise_overview,
    ai_chat_turns, count_ai_chat_turns, dialogue_turns, evidence_files, feedback_rows,
    list_job_templates, position_applications, reset_account_password, resolve_session,
    save_ai_chat_turn, save_dialogue_turn, save_evidence_file, save_job_template,
    pending_review_answers, question_statistics, question_versions, resolve_review,
    review_records, save_answer, save_human_review, save_question_item, save_state,
    set_account_enabled, set_job_match_consent, set_job_template_enabled,
    set_position_status, set_question_enabled, student_list, user_applications,
    test_answers, upsert_user, user_history, save_test_feedback,
)
from backend.analytics import review_metrics
from backend.enterprise import ROLE_PERMISSIONS, build_dialogue_guidance, score_job_matches
from llm.chat import AIAssistant
from llm.scorer import LLMScorer
from question_bank.loader import assessment_readiness, load_all_questions, validate_question_bank


def all_questions() -> list[dict]:
    return load_all_questions()


SEED_QUESTIONS = all_questions()
SCORER = LLMScorer()
AI_ASSISTANT = AIAssistant()
ABILITY_STANDARDS = json.loads((ROOT / "question_bank" / "ability_standards.json").read_text(encoding="utf-8"))

ADMIN_KEY_FILE = ROOT / "data" / "admin_key.txt"
ENTERPRISE_KEY_FILE = ROOT / "data" / "enterprise_key.txt"


def load_admin_access_key() -> str:
    configured = os.getenv("A01_ADMIN_KEY")
    if configured:
        return configured
    ADMIN_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ADMIN_KEY_FILE.exists():
        saved = ADMIN_KEY_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    generated = secrets.token_urlsafe(24)
    ADMIN_KEY_FILE.write_text(generated, encoding="utf-8")
    return generated


ADMIN_ACCESS_KEY = load_admin_access_key()


def load_enterprise_access_key() -> str:
    configured = os.getenv("A01_ENTERPRISE_KEY")
    if configured:
        return configured
    ENTERPRISE_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ENTERPRISE_KEY_FILE.exists():
        saved = ENTERPRISE_KEY_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    generated = secrets.token_urlsafe(24)
    ENTERPRISE_KEY_FILE.write_text(generated, encoding="utf-8")
    return generated


ENTERPRISE_ACCESS_KEY = load_enterprise_access_key()
app = FastAPI(title="AI能力测评智能体", description="学生测评、教师教研与企业匿名岗位标准协作 API", version="1.5.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


class StartRequest(BaseModel):
    user_name: str = Field(min_length=1, max_length=50)
    class_name: str = Field(default="默认班级", max_length=50)
    user_id: str | None = None
    target_questions: int = Field(default=18, ge=15, le=25)


class AnswerRequest(BaseModel):
    test_id: str
    question_id: str
    answer: str = Field(min_length=1, max_length=10000)
    elapsed_seconds: float = Field(default=0, ge=0, le=7200)
    options_order: list[str] = Field(default_factory=list, max_length=20)


class QuestionRequest(BaseModel):
    id: str = Field(pattern=r"^[A-Z0-9_-]{3,30}$")
    dimension: str
    difficulty: int = Field(ge=1, le=5)
    type: str
    question: str = Field(min_length=5, max_length=1000)
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    explanation: str = Field(min_length=2, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    ability_level: str | None = None
    discrimination: float = Field(default=1.0, ge=0, le=3)
    max_score: float = Field(default=10, gt=0, le=100)
    rubric: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    image_url: str | None = None
    changed_by: str = Field(default="管理员", min_length=1, max_length=50)


class ReviewRequest(BaseModel):
    answer_id: int
    reviewer: str = Field(min_length=1, max_length=50)
    score: float = Field(ge=0)
    comment: str = Field(default="", max_length=2000)
    rubric: dict = Field(default_factory=dict)


class ResolutionRequest(BaseModel):
    answer_id: int
    resolver: str = Field(min_length=1, max_length=50)
    score: float = Field(ge=0)
    note: str = Field(default="", max_length=2000)


class QuestionImportRequest(BaseModel):
    items: list[QuestionRequest]


class TestFeedbackRequest(BaseModel):
    test_id: str
    rating: int = Field(ge=1, le=5)
    ambiguous_questions: str = Field(default="", max_length=2000)
    usability_feedback: str = Field(default="", max_length=2000)
    report_feedback: str = Field(default="", max_length=2000)


class JobTemplateRequest(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{3,40}$")
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(default="", max_length=300)
    weights: dict[str, float]
    min_scores: dict[str, float]
    changed_by: str = Field(default="企业协作方", min_length=1, max_length=50)


class JobMatchRequest(BaseModel):
    authorized: bool


class DialogueTurnRequest(BaseModel):
    test_id: str
    question_id: str
    message: str = Field(min_length=2, max_length=2000)


class EvidenceUploadRequest(BaseModel):
    test_id: str
    question_id: str
    filename: str = Field(min_length=1, max_length=150)
    media_type: str = Field(default="application/octet-stream", max_length=100)
    content_base64: str = Field(min_length=1)


class AiChatRequest(BaseModel):
    test_id: str
    question_id: str
    message: str = Field(min_length=2, max_length=2000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=100)


class AccountCreateRequest(BaseModel):
    role: str
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    display_name: str = Field(min_length=2, max_length=50)
    org_name: str = Field(default="", max_length=100)


class AccountEnabledRequest(BaseModel):
    enabled: bool


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=6, max_length=100)


class PositionRequest(BaseModel):
    title: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=500)
    template_id: str


class PositionStatusRequest(BaseModel):
    status: str


class ApplyRequest(BaseModel):
    user_id: str
    user_name: str = Field(min_length=1, max_length=50)
    class_name: str = Field(default="未分组", max_length=50)
    contact: str = Field(default="", max_length=100)
    consent: bool = False


def require_admin(x_admin_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> None:
    """管理员密钥或教师账号登录令牌均可进入教学管理。"""
    if x_admin_key == ADMIN_ACCESS_KEY:
        return None
    session = _bearer_session(authorization)
    if session is not None and session["role"] == "teacher":
        return None
    raise HTTPException(401, "管理员访问密钥或教师登录凭证无效")


def require_enterprise(x_enterprise_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> None:
    """企业协作密钥或企业账号登录令牌均可进入企业工作台。"""
    if x_enterprise_key == ENTERPRISE_ACCESS_KEY:
        return None
    session = _bearer_session(authorization)
    if session is not None and session["role"] == "enterprise":
        return None
    raise HTTPException(401, "企业协作访问密钥或企业登录凭证无效")


def _bearer_session(authorization: str | None) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    return resolve_session(token)


def require_role(role: str):
    """按角色要求登录令牌（教师/企业），返回会话信息。"""
    def dependency(authorization: str | None = Header(default=None)) -> dict:
        session = _bearer_session(authorization)
        if session is None:
            raise HTTPException(401, "请先登录")
        if session["role"] != role:
            raise HTTPException(403, "当前账号无权访问该资源")
        return session
    return dependency


def enterprise_identity(x_enterprise_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict:
    """企业身份：企业账号登录令牌或企业协作密钥均可，返回创建者信息。"""
    session = _bearer_session(authorization)
    if session is not None and session["role"] == "enterprise":
        return session
    if x_enterprise_key == ENTERPRISE_ACCESS_KEY:
        return {"role": "enterprise", "account": {"id": "enterprise-key", "display_name": "企业协作方", "org_name": ""}}
    raise HTTPException(401, "企业登录凭证或协作密钥无效")


def active_questions() -> list[dict]:
    return list_question_items()


def question_index() -> dict[str, dict]:
    return {question["id"]: question for question in list_question_items(include_disabled=True)}


def get_engine(test_id: str) -> tuple[AdaptiveTestEngine, object]:
    row = load_test(test_id)
    if row is None:
        raise HTTPException(404, "测评不存在")
    state = json.loads(row["state_json"])
    # 历史测评可能包含后来停用的题目，因此重建引擎时加载全部版本的当前快照。
    return AdaptiveTestEngine(list_question_items(include_disabled=True), state=state, seed=test_id), row


@app.on_event("startup")
def startup() -> None:
    init_db(SEED_QUESTIONS)


@app.get("/")
def home():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/status")
def status():
    questions = active_questions()
    readiness = assessment_readiness(questions)
    return {
        "status": "ok" if readiness["ready"] else "building",
        "version": app.version,
        "question_bank": validate_question_bank(questions),
        "assessment_readiness": readiness,
        "scoring_mode": SCORER.mode,
        "baibaoxiang": "configured" if SCORER.tbox_configured else "not-configured",
        "ant_line": "configured" if SCORER.ant_line_configured else "not-configured",
        "ai_assistant_mode": AI_ASSISTANT.mode,
    }


@app.get("/api/dimensions")
def dimensions():
    names = ["AI基础认知", "提示词工程", "AI工具使用", "结果评估与优化", "人机协同", "伦理与合规"]
    return {"dimensions": [{"id": key, "name": name} for key, name in zip(DIMENSIONS, names)]}


@app.get("/api/roles")
def roles():
    return {
        "roles": ROLE_PERMISSIONS,
        "privacy": {
            "student": "仅查看本人的测评、成长与主动授权的岗位匹配。",
            "teacher": "可查看本班实名教学数据，用于教研与人工复核。",
            "enterprise": "仅查看达到隐私阈值的匿名群体统计，不接触姓名、班级、答案与个人报告。",
        },
    }


@app.post("/api/auth/login")
def login(request: LoginRequest):
    """平台三角色登录：教师/企业账号（学员沿用测评时生成的本地身份）。"""
    from backend.database import get_account_by_username, verify_password
    account = get_account_by_username(request.username)
    if account is None or not account["enabled"] or not verify_password(request.password, account["password_hash"]):
        raise HTTPException(401, "用户名或密码错误，或账号已被停用")
    session = create_session(account["id"], account["role"])
    return {
        "token": session["token"],
        "role": account["role"],
        "display_name": account["display_name"],
        "org_name": account.get("org_name", ""),
        "permissions": ROLE_PERMISSIONS.get(account["role"], []),
        "expires_in_days": 7,
    }


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    session = _bearer_session(authorization)
    if session is not None:
        delete_session(session["token"])
    return {"success": True}


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None)):
    session = _bearer_session(authorization)
    if session is None:
        raise HTTPException(401, "请先登录")
    account = session["account"]
    return {
        "role": session["role"],
        "display_name": account["display_name"],
        "org_name": account.get("org_name", ""),
        "permissions": ROLE_PERMISSIONS.get(session["role"], []),
    }


def validate_job_template(request: JobTemplateRequest) -> dict:
    expected = set(DIMENSIONS)
    if set(request.weights) != expected or set(request.min_scores) != expected:
        raise HTTPException(422, "岗位模板必须完整覆盖六个能力维度")
    if any(value < 0 or value > 1 for value in request.weights.values()):
        raise HTTPException(422, "岗位权重必须位于 0 到 1")
    if abs(sum(request.weights.values()) - 1.0) > 0.001:
        raise HTTPException(422, "岗位权重之和必须为 1")
    if any(value < 0 or value > 100 for value in request.min_scores.values()):
        raise HTTPException(422, "最低能力要求必须位于 0 到 100")
    return request.model_dump(exclude={"changed_by"})


@app.get("/api/enterprise/overview", dependencies=[Depends(require_enterprise)])
def enterprise_overview():
    return {**anonymous_enterprise_overview(), "templates": list_job_templates()}


@app.get("/api/enterprise/job-templates", dependencies=[Depends(require_enterprise)])
def enterprise_job_templates():
    return {"items": list_job_templates(include_disabled=True)}


@app.post("/api/enterprise/job-templates", dependencies=[Depends(require_enterprise)])
def enterprise_save_job_template(request: JobTemplateRequest):
    return save_job_template(validate_job_template(request), request.changed_by)


@app.post("/api/enterprise/job-templates/{template_id}/enabled", dependencies=[Depends(require_enterprise)])
def enterprise_enable_job_template(template_id: str, enabled: bool):
    if not set_job_template_enabled(template_id, enabled):
        raise HTTPException(404, "岗位模板不存在")
    return {"success": True, "template_id": template_id, "enabled": enabled}


@app.get("/api/enterprise/positions", dependencies=[Depends(require_enterprise)])
def enterprise_positions():
    """企业岗位列表（含各岗位投递数与模板信息）。"""
    templates = {item["id"]: item for item in list_job_templates(include_disabled=True)}
    counts = application_count_by_position()
    items = []
    for position in list_positions():
        template = templates.get(position["template_id"], {})
        items.append({
            **position,
            "template_name": template.get("name", position["template_id"]),
            "applications": counts.get(position["id"], 0),
        })
    return {"items": items, "templates": [{"id": t["id"], "name": t["name"]} for t in templates.values()]}


@app.post("/api/enterprise/positions")
def enterprise_create_position(request: PositionRequest, identity: dict = Depends(enterprise_identity)):
    templates = {item["id"]: item for item in list_job_templates(include_disabled=True)}
    if request.template_id not in templates:
        raise HTTPException(422, "岗位模板不存在")
    account = identity["account"]
    company = account.get("org_name") or account["display_name"]
    item = create_position(company, request.title, request.description, request.template_id, account["id"])
    return {**item, "template_name": templates[request.template_id]["name"], "applications": 0}


@app.post("/api/enterprise/positions/{position_id}/status")
def enterprise_position_status(position_id: str, request: PositionStatusRequest, identity: dict = Depends(enterprise_identity)):
    try:
        if not set_position_status(position_id, request.status, identity["account"]["id"]):
            raise HTTPException(404, "岗位不存在")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"success": True, "position_id": position_id, "status": request.status}


@app.get("/api/enterprise/positions/{position_id}/applications", dependencies=[Depends(require_enterprise)])
def enterprise_position_applications(position_id: str):
    """查看岗位投递列表（学员自愿投递并授权共享能力画像，不展示原始答案与完整报告）。"""
    position = get_position(position_id)
    if position is None:
        raise HTTPException(404, "岗位不存在")
    templates = {item["id"]: item for item in list_job_templates(include_disabled=True)}
    rows = position_applications(position_id)
    items = []
    for row in rows:
        template = templates.get(row["template_id"], {})
        items.append({
            "id": row["id"], "user_name": row["user_name"], "class_name": row["class_name"],
            "contact": row["contact"], "created_at": row["created_at"],
            "match_score": row["match_score"], "template_name": template.get("name", row["template_id"]),
            "notice": "投递信息由学员自愿提供；不得用于自动录用或淘汰。",
        })
    return {"position": position, "items": items}


@app.post("/api/users/{user_id}/job-match")
def student_job_match(user_id: str, request: JobMatchRequest):
    try:
        set_job_match_consent(user_id, request.authorized)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not request.authorized:
        return {"authorized": False, "matches": [], "notice": "未获得学员授权，不进行岗位能力匹配。"}
    scores = latest_completed_scores(user_id)
    if not scores:
        raise HTTPException(409, "请先完成一次测评再进行岗位能力匹配")
    return {
        "authorized": True,
        "matches": score_job_matches(scores, list_job_templates()),
        "notice": "匹配结果仅在学员端展示，企业端无法查看个人结果；不得用于自动录用或淘汰。",
    }


@app.get("/api/positions")
def open_positions(user_id: str | None = None):
    """岗位广场：开放岗位列表（学员端）。附带模板信息与投递情况。"""
    templates = {item["id"]: item for item in list_job_templates(include_disabled=True)}
    counts = application_count_by_position()
    applied = {row["position_id"] for row in user_applications(user_id)} if user_id else set()
    items = []
    for position in list_positions(status="open"):
        template = templates.get(position["template_id"], {})
        items.append({
            "id": position["id"], "company": position["company"], "title": position["title"],
            "description": position["description"], "template_id": position["template_id"],
            "template_name": template.get("name", position["template_id"]),
            "template_description": template.get("description", ""),
            "applications": counts.get(position["id"], 0),
            "applied": position["id"] in applied,
            "created_at": position["created_at"],
        })
    return {"items": items, "notice": "投递即授权企业查看你的能力画像摘要；企业端不接触原始答案与个人报告，不得用于自动录用或淘汰。"}


@app.post("/api/positions/{position_id}/apply")
def apply_open_position(position_id: str, request: ApplyRequest):
    scores = latest_completed_scores(request.user_id)
    if not scores:
        raise HTTPException(409, "请先完成一次测评，获得能力画像后再投递岗位")
    templates = {item["id"]: item for item in list_job_templates(include_disabled=True)}
    position = get_position(position_id)
    if position is None:
        raise HTTPException(404, "岗位不存在")
    template = templates.get(position["template_id"])
    if template is None:
        raise HTTPException(422, "岗位关联的模板已停用，暂不能投递")
    matches = score_job_matches(scores, [template])
    if not matches:
        raise HTTPException(422, "无法为该岗位生成匹配分")
    try:
        row = apply_position(
            position_id, request.user_id, request.user_name, request.class_name,
            request.contact, request.consent, matches[0]["match_score"],
            template["id"], latest_completed_test_id(request.user_id) or "",
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"success": True, "application": row, "match_score": row["match_score"], "notice": "投递成功：已授权企业查看你的能力画像摘要（不含原始答案与报告）。"}


@app.get("/api/users/{user_id}/applications")
def my_applications(user_id: str):
    items = user_applications(user_id)
    return {"items": items, "total": len(items)}


@app.post("/api/dialogue/turn")
def create_dialogue_turn(request: DialogueTurnRequest):
    question = question_index().get(request.question_id)
    if question is None:
        raise HTTPException(404, "题目不存在")
    if question["type"] not in {"open_text", "practical", "code", "image", "dialogue"}:
        raise HTTPException(422, "仅开放题和实操题支持过程引导")
    existing = dialogue_turns(request.test_id, request.question_id)
    if len(existing) >= 6:
        raise HTTPException(409, "本题过程引导已达到 6 轮上限，请整理后提交最终答案")
    guidance = build_dialogue_guidance(len(existing) + 1, request.message)
    try:
        item = save_dialogue_turn(request.test_id, request.question_id, request.message, guidance)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"turn": item, "turns_remaining": 6 - item["turn_index"], "mode": "structured-guidance"}


SUBJECTIVE_TYPES = {"open_text", "practical", "code", "image", "dialogue"}


@app.post("/api/ai-chat")
def ai_chat(request: AiChatRequest):
    """对接真实 AI 环境：学员在测评中调用 AI 助手完成对话式任务。

    未配置真实模型时透明降级为本地模拟助手（local-simulator），
    保证离线演示可用且不会冒充真实模型。
    """
    row = load_test(request.test_id)
    if row is None:
        raise HTTPException(404, "测评不存在")
    if row["status"] == "completed":
        raise HTTPException(409, "测评已完成，不能继续 AI 助手对话")
    question = question_index().get(request.question_id)
    if question is None:
        raise HTTPException(404, "题目不存在")
    if question["type"] not in SUBJECTIVE_TYPES:
        raise HTTPException(422, "仅主观题支持 AI 助手对话")
    per_question = len(ai_chat_turns(request.test_id, request.question_id)) // 2
    if per_question >= 12:
        raise HTTPException(409, "本题 AI 助手对话已达 12 轮上限，请整理后提交最终答案")
    if count_ai_chat_turns(request.test_id) >= 80:
        raise HTTPException(409, "本次测评 AI 助手对话已达总上限，请整理后提交最终答案")
    history = [
        {"role": turn["role"], "message": turn["message"]}
        for turn in ai_chat_turns(request.test_id, request.question_id)
    ]
    try:
        reply = AI_ASSISTANT.chat(question, history, request.message)
    except Exception as exc:
        raise HTTPException(502, f"AI 助手调用失败：{type(exc).__name__}") from exc
    save_ai_chat_turn(request.test_id, request.question_id, "user", request.message)
    save_ai_chat_turn(request.test_id, request.question_id, "assistant", reply["reply"], reply.get("model", ""))
    used = len(ai_chat_turns(request.test_id, request.question_id)) // 2
    return {**reply, "turns_used": used, "turns_remaining": max(0, 12 - used)}


@app.get("/api/test/{test_id}/ai-chat/{question_id}")
def test_ai_chat(test_id: str, question_id: str):
    if load_test(test_id) is None:
        raise HTTPException(404, "测评不存在")
    return {"items": ai_chat_turns(test_id, question_id)}


@app.get("/api/test/{test_id}/dialogue/{question_id}")
def test_dialogue(test_id: str, question_id: str):
    if load_test(test_id) is None:
        raise HTTPException(404, "测评不存在")
    return {"items": dialogue_turns(test_id, question_id)}


@app.post("/api/evidence")
def upload_evidence(request: EvidenceUploadRequest):
    question = question_index().get(request.question_id)
    if question is None:
        raise HTTPException(404, "题目不存在")
    if question["type"] not in SUBJECTIVE_TYPES:
        raise HTTPException(422, "仅开放题和实操题支持上传过程证据")
    suffix = Path(request.filename).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt", ".md", ".json", ".csv"}
    if suffix not in allowed:
        raise HTTPException(422, "仅支持 PNG/JPG/WEBP/PDF/TXT/MD/JSON/CSV 证据文件")
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(422, "证据文件编码无效") from exc
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(422, "单个证据文件必须大于 0 且不超过 5MB")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(request.filename).name) or f"evidence{suffix}"
    evidence_id = str(uuid.uuid4())
    folder = ROOT / "data" / "evidence" / request.test_id
    folder.mkdir(parents=True, exist_ok=True)
    storage = folder / f"{evidence_id}_{safe_name}"
    storage.write_bytes(content)
    item = {
        "id": evidence_id,
        "test_id": request.test_id,
        "question_id": request.question_id,
        "filename": Path(request.filename).name,
        "media_type": request.media_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "storage_path": str(storage.relative_to(ROOT)),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        return save_evidence_file(item)
    except ValueError as exc:
        storage.unlink(missing_ok=True)
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/test/{test_id}/evidence")
def test_evidence(test_id: str, question_id: str | None = None):
    if load_test(test_id) is None:
        raise HTTPException(404, "测评不存在")
    return {"items": evidence_files(test_id, question_id)}


@app.get("/api/ability-standards")
def ability_standards():
    return ABILITY_STANDARDS


@app.post("/api/test/start")
def start_test(request: StartRequest):
    questions = active_questions()
    readiness = assessment_readiness(questions)
    if not readiness["ready"]:
        raise HTTPException(503, readiness["message"])
    user_id = request.user_id or str(uuid.uuid4())
    test_id = str(uuid.uuid4())
    upsert_user(user_id, request.user_name, request.class_name)
    state = AdaptiveTestEngine.initial_state(request.target_questions)
    create_test(test_id, user_id, request.target_questions, state)
    engine = AdaptiveTestEngine(questions, state=state, seed=test_id)
    question = engine.next_question()
    save_state(test_id, engine.state)
    return {"user_id": user_id, "test_id": test_id, "question": question, "progress": engine.progress(), "palette": engine.question_palette()}


@app.get("/api/test/{test_id}/next")
def next_question(test_id: str):
    engine, row = get_engine(test_id)
    if row["status"] == "completed":
        return {"question": None, "completed": True, "progress": engine.progress(), "palette": engine.question_palette()}
    question = engine.next_question()
    save_state(test_id, engine.state)
    return {"question": question, "completed": question is None, "progress": engine.progress(), "palette": engine.question_palette()}


@app.get("/api/test/{test_id}/palette")
def test_palette(test_id: str):
    engine, row = get_engine(test_id)
    if row["status"] == "completed":
        return {"question": None, "completed": True, "progress": engine.progress(), "palette": engine.question_palette()}
    question = engine.next_question()
    palette = engine.question_palette()
    save_state(test_id, engine.state)
    return {"question": question, "completed": False, "progress": engine.progress(), "palette": palette}


@app.post("/api/test/{test_id}/select/{slot_number}")
def select_test_question(test_id: str, slot_number: int):
    engine, row = get_engine(test_id)
    try:
        question = engine.select_question(slot_number)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    submitted = next((item for item in test_answers(test_id) if item["question_id"] == question["id"]), None)
    source = question_index().get(question["id"], {})
    score_ratio = submitted["score"] / submitted["max_score"] if submitted and submitted["max_score"] else None
    submitted_feedback = json.loads(submitted["feedback_json"]) if submitted else {}
    save_state(test_id, engine.state, completed=row["status"] == "completed")
    return {
        "question": question,
        "progress": engine.progress(),
        "palette": engine.question_palette(),
        "readonly": submitted is not None,
        "options_order": submitted_feedback.get("options_order", []) if submitted else [],
        "submitted_answer": submitted["answer_text"] if submitted else None,
        "submitted_correct": submitted["score"] >= submitted["max_score"] if submitted else None,
        "submitted_status": "correct" if score_ratio is not None and score_ratio >= 0.999 else "partial" if score_ratio is not None and score_ratio >= 0.5 else "incorrect" if score_ratio is not None else None,
        "submitted_score": submitted["score"] if submitted else None,
        "submitted_max_score": submitted["max_score"] if submitted else None,
        "submitted_explanation": source.get("explanation") if submitted else None,
        "submitted_correct_answer": source.get("answer") if submitted and submitted["question_type"] == "single_choice" else None,
        "submitted_rubric": source.get("rubric", []) if submitted and submitted["question_type"] != "single_choice" else [],
    }


@app.post("/api/answer/submit")
def submit_answer(request: AnswerRequest):
    engine, row = get_engine(request.test_id)
    if row["status"] == "completed":
        raise HTTPException(409, "测评已经结束")
    question = question_index().get(request.question_id)
    if question is None:
        raise HTTPException(404, "题目不存在")
    open_score = None
    if question["type"] != "single_choice":
        transcript = "\n".join(
            f"{'学员' if turn['role'] == 'user' else 'AI助手'}：{turn['message']}"
            for turn in ai_chat_turns(request.test_id, request.question_id)
        )
        open_score = SCORER.score(question, request.answer, context=transcript)
    try:
        result = engine.submit_answer(request.question_id, request.answer, request.elapsed_seconds, open_score)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    # 保存学员作答时看到的选项随机顺序，供提交后/回看时按同一顺序渲染，
    # 避免只读视图回退到题库原始顺序导致选项错位。
    if request.options_order:
        feedback = dict(result.get("feedback") or {})
        feedback["options_order"] = request.options_order
        result["feedback"] = feedback
    save_answer(request.test_id, result, request.answer, request.elapsed_seconds)
    result["options_order"] = request.options_order or []
    ratio = result["score"] / result["max_score"] if result["max_score"] else 0
    result["submitted_status"] = "correct" if ratio >= 0.999 else "partial" if ratio >= 0.5 else "incorrect"
    result["explanation"] = question.get("explanation", "该题解析尚未补充。")
    result["correct_answer"] = question.get("answer") if question["type"] == "single_choice" else None
    result["rubric"] = question.get("rubric", []) if question["type"] != "single_choice" else []
    result["palette"] = engine.question_palette()
    save_state(request.test_id, engine.state, completed=result["completed"])
    return result


@app.get("/api/report/{test_id}")
def report(test_id: str):
    engine, row = get_engine(test_id)
    if row["status"] != "completed":
        raise HTTPException(409, "测评尚未完成，完成后才能查看报告与题目解析")
    result = engine.build_report()
    answers = test_answers(test_id)
    index = question_index()
    answer_review = []
    for number, answer in enumerate(answers, start=1):
        question = index.get(answer["question_id"], {})
        is_objective = answer["question_type"] == "single_choice"
        answer_review.append({
            "number": number,
            "question_id": answer["question_id"],
            "dimension": answer["dimension"],
            "question_type": answer["question_type"],
            "question": question.get("question", "历史题目"),
            "user_answer": answer["answer_text"],
            "correct_answer": question.get("answer") if is_objective else None,
            "correct": answer["score"] >= answer["max_score"] if is_objective else None,
            "score": answer["score"],
            "max_score": answer["max_score"],
            "explanation": question.get("explanation", "该题解析尚未补充。"),
            "rubric": question.get("rubric", []) if not is_objective else [],
        })
    result.update({"test_id": test_id, "status": row["status"], "answers": answers, "answer_review": answer_review})
    return result


@app.post("/api/feedback")
def submit_test_feedback(request: TestFeedbackRequest):
    try:
        save_test_feedback(request.test_id, request.rating, request.ambiguous_questions, request.usability_feedback, request.report_feedback)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"success": True}


@app.get("/api/admin/feedback", dependencies=[Depends(require_admin)])
def admin_feedback():
    return {"items": feedback_rows()}


@app.get("/api/admin/dashboard", dependencies=[Depends(require_admin)])
def admin_dashboard():
    return dashboard_data()


@app.get("/api/admin/accounts", dependencies=[Depends(require_admin)])
def admin_accounts():
    """平台三角色账号管理：教师/企业账号列表。"""
    return {"items": list_accounts()}


@app.post("/api/admin/accounts", dependencies=[Depends(require_admin)])
def admin_create_account(request: AccountCreateRequest):
    if request.role not in {"teacher", "enterprise"}:
        raise HTTPException(422, "角色必须是 teacher 或 enterprise")
    try:
        item = create_account(request.role, request.username, request.password, request.display_name, request.org_name)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {k: item[k] for k in ("id", "role", "username", "display_name", "org_name", "enabled", "created_at")}


@app.post("/api/admin/accounts/{account_id}/enabled", dependencies=[Depends(require_admin)])
def admin_account_enabled(account_id: str, request: AccountEnabledRequest):
    if not set_account_enabled(account_id, request.enabled):
        raise HTTPException(404, "账号不存在")
    return {"success": True, "account_id": account_id, "enabled": request.enabled}


@app.post("/api/admin/accounts/{account_id}/reset-password", dependencies=[Depends(require_admin)])
def admin_account_reset_password(account_id: str, request: PasswordResetRequest):
    if not reset_account_password(account_id, request.password):
        raise HTTPException(404, "账号不存在")
    return {"success": True, "account_id": account_id}


@app.get("/api/teacher/dashboard")
def teacher_dashboard(x_admin_key: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    """教师工作台：班级投递统计（管理员密钥或教师令牌均可访问）。"""
    require_admin(x_admin_key, authorization)
    return {
        "dashboard": dashboard_data(),
        "applications": application_dashboard(),
    }


@app.get("/api/admin/students", dependencies=[Depends(require_admin)])
def admin_students():
    """教师端成长追踪：返回学员列表（姓名、班级、已完成测评数）。"""
    return {"items": student_list()}


@app.get("/api/question-bank/stats", dependencies=[Depends(require_admin)])
def question_bank_stats():
    questions = active_questions()
    return {**validate_question_bank(questions), "assessment_readiness": assessment_readiness(questions), "item_statistics": question_statistics()}


@app.get("/api/admin/questions", dependencies=[Depends(require_admin)])
def admin_questions(include_disabled: bool = True):
    stats = {row["question_id"]: row for row in question_statistics()}
    items = list_question_items(include_disabled=include_disabled)
    return {"items": [{**item, "statistics": stats.get(item["id"])} for item in items]}


@app.post("/api/admin/questions", dependencies=[Depends(require_admin)])
def admin_save_question(request: QuestionRequest):
    question = request.model_dump(exclude={"changed_by"})
    if question["dimension"] not in DIMENSIONS:
        raise HTTPException(422, "能力维度无效")
    if question["type"] == "single_choice" and (len(question["options"]) < 2 or question["answer"] not in question["options"]):
        raise HTTPException(422, "客观题必须包含有效选项和唯一参考答案")
    if question["type"] != "single_choice" and not question["rubric"]:
        raise HTTPException(422, "开放题或实操题必须提供评分量表")
    if question["type"] == "image" and not question.get("image_url"):
        raise HTTPException(422, "图像任务必须提供图片资源地址 image_url")
    return save_question_item(question, request.changed_by)


@app.post("/api/admin/questions/{question_id}/enabled", dependencies=[Depends(require_admin)])
def admin_enable_question(question_id: str, enabled: bool, changed_by: str = "管理员"):
    if not set_question_enabled(question_id, enabled, changed_by):
        raise HTTPException(404, "题目不存在")
    return {"success": True, "question_id": question_id, "enabled": enabled}


@app.get("/api/admin/questions/{question_id}/versions", dependencies=[Depends(require_admin)])
def admin_question_versions(question_id: str):
    return {"versions": question_versions(question_id)}


@app.get("/api/admin/questions-export.json", dependencies=[Depends(require_admin)])
def admin_export_questions():
    return {"version": "1.0", "items": list_question_items(include_disabled=True)}


@app.post("/api/admin/questions-import", dependencies=[Depends(require_admin)])
def admin_import_questions(request: QuestionImportRequest):
    saved = []
    errors = []
    for index, item in enumerate(request.items):
        try:
            question = item.model_dump(exclude={"changed_by"})
            if question["dimension"] not in DIMENSIONS:
                raise ValueError("能力维度无效")
            if question["type"] == "single_choice" and (len(question["options"]) < 2 or question["answer"] not in question["options"]):
                raise ValueError("客观题选项或答案无效")
            if question["type"] != "single_choice" and not question["rubric"]:
                raise ValueError("非客观题缺少评分量表")
            save_question_item(question, item.changed_by, action="import")
            saved.append(question["id"])
        except Exception as exc:
            errors.append({"row": index + 1, "id": item.id, "message": str(exc)})
    return {"saved": saved, "errors": errors}


@app.get("/api/admin/reviews/pending", dependencies=[Depends(require_admin)])
def admin_pending_reviews():
    index = question_index()
    items = pending_review_answers()
    for item in items:
        question = index.get(item["question_id"], {})
        item["question"] = question.get("question", "历史题目")
        item["rubric"] = question.get("rubric", [])
        item["dialogue_turns"] = dialogue_turns(item["test_id"], item["question_id"])
        item["evidence_files"] = evidence_files(item["test_id"], item["question_id"])
    return {"items": items, "metrics": review_metrics(review_records())}


@app.post("/api/admin/reviews", dependencies=[Depends(require_admin)])
def admin_save_review(request: ReviewRequest):
    try:
        save_human_review(request.answer_id, request.reviewer, request.score, request.comment, request.rubric)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"success": True, "metrics": review_metrics(review_records())}


@app.post("/api/admin/reviews/resolve", dependencies=[Depends(require_admin)])
def admin_resolve_review(request: ResolutionRequest):
    try:
        resolve_review(request.answer_id, request.score, request.resolver, request.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"success": True}


@app.get("/api/admin/reviews/metrics", dependencies=[Depends(require_admin)])
def admin_review_metrics():
    return review_metrics(review_records())


@app.get("/api/users/{user_id}/history")
def history(user_id: str):
    result = user_history(user_id)
    if result["user"] is None:
        raise HTTPException(404, "学员不存在")
    return result


@app.get("/api/admin/export/{kind}.csv", dependencies=[Depends(require_admin)])
def export_csv(kind: str):
    try:
        headers, rows = export_rows(kind)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    stream = io.StringIO()
    stream.write("\ufeff")
    writer = csv.DictWriter(stream, fieldnames=headers or ["message"])
    writer.writeheader()
    if rows:
        writer.writerows(rows)
    else:
        writer.writerow({"message": "暂无数据"})
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})
