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
from algorithm.level_scale import LEVEL_SCALE
from backend.database import (
    create_test, dashboard_data, export_rows, init_db, list_question_items, load_test,
    anonymous_enterprise_overview, dialogue_turns, evidence_files, latest_completed_scores,
    feedback_rows,
    list_job_templates, save_dialogue_turn, save_evidence_file, save_job_template,
    pending_review_answers, question_statistics, question_versions, resolve_review,
    review_records, save_answer, save_human_review, save_question_item, save_state,
    set_job_match_consent, set_job_template_enabled, set_question_enabled, test_answers, upsert_user, user_history,
    save_test_feedback,
)
from backend.analytics import review_metrics
from backend.enterprise import ROLE_PERMISSIONS, build_dialogue_guidance, score_job_matches
from llm.question_generator import TBoxQuestionGenerator
from llm.scorer import LLMScorer
from llm.dialogue import TBoxDialogueCoach, TBoxDialogueUnavailable
from question_bank.loader import assessment_readiness, load_all_questions, validate_question_bank


def all_questions() -> list[dict]:
    return load_all_questions()


SEED_QUESTIONS = all_questions()
SCORER = LLMScorer()
QUESTION_GENERATOR = TBoxQuestionGenerator()
DIALOGUE_COACH = TBoxDialogueCoach()
ABILITY_STANDARDS = json.loads((ROOT / "question_bank" / "ability_standards.json").read_text(encoding="utf-8"))

ADMIN_KEY_FILE = ROOT / "data" / "admin_key.txt"
ENTERPRISE_KEY_FILE = ROOT / "data" / "enterprise_key.txt"
SYNTHETIC_REPORT_FILE = ROOT / "docs" / "synthetic_validation_100" / "synthetic_validation_report.json"


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
app = FastAPI(title="AI能力测评智能体", description="学生测评、教师教研与企业匿名岗位标准协作 API", version="1.8.0")
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


class QuestionDraftRequest(BaseModel):
    dimension: str
    type: str
    difficulty: int = Field(ge=1, le=5)
    count: int = Field(default=1, ge=1, le=5)


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


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if x_admin_key != ADMIN_ACCESS_KEY:
        raise HTTPException(401, "管理员访问密钥无效")


def require_enterprise(x_enterprise_key: str | None = Header(default=None)) -> None:
    if x_enterprise_key != ENTERPRISE_ACCESS_KEY:
        raise HTTPException(401, "企业协作访问密钥无效")


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
    synthetic_validation = None
    if SYNTHETIC_REPORT_FILE.exists():
        try:
            synthetic = json.loads(SYNTHETIC_REPORT_FILE.read_text(encoding="utf-8"))
            synthetic_validation = {
                "scope": synthetic.get("evidence_scope"),
                "samples": synthetic.get("design", {}).get("total_samples"),
                "balanced": synthetic.get("design", {}).get("maximum_level_share") == 0.2,
                "double_reviewed_answers": synthetic.get("double_review", {}).get("double_reviewed_answers"),
            }
        except (OSError, json.JSONDecodeError):
            synthetic_validation = {"status": "invalid-report"}
    return {
        "status": "ok" if readiness["ready"] else "building",
        "version": app.version,
        "question_bank": validate_question_bank(questions),
        "assessment_readiness": readiness,
        "scoring_mode": SCORER.mode,
        "baibaoxiang": "configured" if SCORER.tbox_configured else "not-configured",
        "question_generation": {
            "mode": "baibaoxiang-agent" if QUESTION_GENERATOR.configured else "not-configured",
            "configured": QUESTION_GENERATOR.configured,
        },
        "continuous_dialogue": {
            "mode": DIALOGUE_COACH.mode,
            "configured": DIALOGUE_COACH.configured,
            "max_turns_per_question": 6,
            "failure_policy": "pause-remote-and-preserve-session",
        },
        "level_calibration": {
            "version": LEVEL_SCALE["version"],
            "thresholds": LEVEL_SCALE["thresholds"],
            "accuracy": LEVEL_SCALE["accuracy"],
            "evidence_scope": LEVEL_SCALE["evidence_scope"],
        },
        "synthetic_validation": synthetic_validation,
    }


@app.get("/api/admin/validation/synthetic", dependencies=[Depends(require_admin)])
def synthetic_validation_report():
    if not SYNTHETIC_REPORT_FILE.exists():
        raise HTTPException(404, "尚未生成仿真样本校验报告")
    try:
        return json.loads(SYNTHETIC_REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "仿真样本校验报告无法读取") from exc


@app.get("/api/dimensions")
def dimensions():
    names = ["AI基础认知", "提示词工程", "AI工具使用", "结果评估与优化", "人机协同", "伦理与合规"]
    return {"dimensions": [{"id": key, "name": name} for key, name in zip(DIMENSIONS, names)]}


@app.get("/api/level-scale")
def level_scale():
    return LEVEL_SCALE


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


@app.post("/api/dialogue/turn")
def create_dialogue_turn(request: DialogueTurnRequest):
    question = question_index().get(request.question_id)
    if question is None:
        raise HTTPException(404, "题目不存在")
    if question["type"] not in {"open_text", "practical", "code", "image"}:
        raise HTTPException(422, "仅开放题和实操题支持过程引导")
    existing = dialogue_turns(request.test_id, request.question_id)
    if len(existing) >= 6:
        raise HTTPException(409, "本题过程引导已达到 6 轮上限，请整理后提交最终答案")
    if DIALOGUE_COACH.configured:
        try:
            guidance = DIALOGUE_COACH.guide(
                test_id=request.test_id,
                question=question,
                history=existing,
                message=request.message,
            )
            mode = DIALOGUE_COACH.mode
        except TBoxDialogueUnavailable as exc:
            raise HTTPException(
                503,
                {
                    "code": exc.code,
                    "message": "真实模型连续对话已暂停，本轮未保存、不会自动重试；既有会话仍保留，可在额度或服务恢复后重试。",
                },
            ) from exc
    else:
        guidance = build_dialogue_guidance(len(existing) + 1, request.message)
        mode = DIALOGUE_COACH.mode
    try:
        item = save_dialogue_turn(request.test_id, request.question_id, request.message, guidance)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"turn": item, "turns_remaining": 6 - item["turn_index"], "mode": mode}


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
    if question["type"] not in {"open_text", "practical", "code", "image"}:
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
    save_state(test_id, engine.state, completed=row["status"] == "completed")
    return {
        "question": question,
        "progress": engine.progress(),
        "palette": engine.question_palette(),
        "readonly": submitted is not None,
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
    open_score = SCORER.score(question, request.answer) if question["type"] != "single_choice" else None
    try:
        result = engine.submit_answer(request.question_id, request.answer, request.elapsed_seconds, open_score)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    save_answer(request.test_id, result, request.answer, request.elapsed_seconds)
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


@app.get("/api/question-bank/stats", dependencies=[Depends(require_admin)])
def question_bank_stats():
    questions = active_questions()
    return {**validate_question_bank(questions), "assessment_readiness": assessment_readiness(questions), "item_statistics": question_statistics()}


@app.get("/api/admin/questions", dependencies=[Depends(require_admin)])
def admin_questions(include_disabled: bool = True):
    stats = {row["question_id"]: row for row in question_statistics()}
    items = list_question_items(include_disabled=include_disabled)
    return {"items": [{**item, "statistics": stats.get(item["id"])} for item in items]}


@app.post("/api/admin/questions/generate-draft", dependencies=[Depends(require_admin)])
def admin_generate_question_draft(request: QuestionDraftRequest):
    """方案A：只返回草稿；教师确认并点击保存后才进入正式题库。"""
    if request.dimension not in DIMENSIONS:
        raise HTTPException(422, "能力维度无效")
    if request.type not in {"single_choice", "open_text", "practical"}:
        raise HTTPException(422, "题型无效")
    if not QUESTION_GENERATOR.configured:
        raise HTTPException(503, "题库智能体尚未配置，请使用双智能体启动方式")
    try:
        items = QUESTION_GENERATOR.generate(request.dimension, request.type, request.difficulty, request.count)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"题库智能体生成失败：{exc}") from exc
    return {
        "items": items,
        "draft_only": True,
        "message": "草稿尚未写入题库，请由教师审核题干、答案、解析和评分量表后再保存。",
    }


@app.post("/api/admin/questions", dependencies=[Depends(require_admin)])
def admin_save_question(request: QuestionRequest):
    question = request.model_dump(exclude={"changed_by"})
    if question["dimension"] not in DIMENSIONS:
        raise HTTPException(422, "能力维度无效")
    if question["type"] == "single_choice" and (len(question["options"]) < 2 or question["answer"] not in question["options"]):
        raise HTTPException(422, "客观题必须包含有效选项和唯一参考答案")
    if question["type"] != "single_choice" and not question["rubric"]:
        raise HTTPException(422, "开放题或实操题必须提供评分量表")
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
        if item["dialogue_turns"] or item["evidence_files"]:
            item["question"] += (
                f"（过程引导 {len(item['dialogue_turns'])} 轮，"
                f"证据文件 {len(item['evidence_files'])} 个）"
            )
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
