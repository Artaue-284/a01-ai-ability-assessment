from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "assessment.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db(seed_questions: list[dict[str, Any]] | None = None) -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                class_name TEXT NOT NULL DEFAULT '默认班级',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tests (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                status TEXT NOT NULL,
                target_questions INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT NOT NULL REFERENCES tests(id),
                question_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                question_type TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                answer_text TEXT NOT NULL,
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                elapsed_seconds REAL NOT NULL,
                feedback_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(test_id, question_id)
            );
            CREATE INDEX IF NOT EXISTS idx_answers_test ON answers(test_id);
            CREATE INDEX IF NOT EXISTS idx_tests_user ON tests(user_id);
            CREATE TABLE IF NOT EXISTS question_items (
                id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'seed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS question_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                action TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS human_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL,
                score REAL NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                rubric_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(answer_id, reviewer)
            );
            CREATE TABLE IF NOT EXISTS review_resolutions (
                answer_id INTEGER PRIMARY KEY REFERENCES answers(id) ON DELETE CASCADE,
                resolved_score REAL NOT NULL,
                resolver TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_feedback (
                test_id TEXT PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE,
                rating INTEGER NOT NULL,
                ambiguous_questions TEXT NOT NULL DEFAULT '',
                usability_feedback TEXT NOT NULL DEFAULT '',
                report_feedback TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                weights_json TEXT NOT NULL,
                min_scores_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_match_consents (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                granted INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dialogue_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(test_id, question_id, turn_index)
            );
            CREATE TABLE IF NOT EXISTS evidence_files (
                id TEXT PRIMARY KEY,
                test_id TEXT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_question_enabled ON question_items(enabled);
            CREATE INDEX IF NOT EXISTS idx_reviews_answer ON human_reviews(answer_id);
            CREATE INDEX IF NOT EXISTS idx_dialogue_test_question ON dialogue_turns(test_id,question_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_test_question ON evidence_files(test_id,question_id);
            """
        )
        from backend.enterprise import DEFAULT_JOB_TEMPLATES

        now = utc_now()
        for template in DEFAULT_JOB_TEMPLATES:
            db.execute(
                """INSERT OR IGNORE INTO job_templates
                   (id,name,description,weights_json,min_scores_json,enabled,created_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,1,'system',?,?)""",
                (template["id"], template["name"], template["description"],
                 json.dumps(template["weights"], ensure_ascii=False),
                 json.dumps(template["min_scores"], ensure_ascii=False), now, now),
            )
        if seed_questions:
            for question in seed_questions:
                payload = json.dumps(question, ensure_ascii=False)
                existing = db.execute("SELECT source FROM question_items WHERE id=?", (question["id"],)).fetchone()
                if existing is None:
                    db.execute(
                        "INSERT INTO question_items VALUES (?, ?, 1, 1, 'seed', ?, ?)",
                        (question["id"], payload, now, now),
                    )
                    db.execute(
                        "INSERT INTO question_versions(question_id,version,data_json,action,changed_by,created_at) VALUES (?,1,?,'seed','system',?)",
                        (question["id"], payload, now),
                    )
                elif existing["source"] == "seed":
                    db.execute("UPDATE question_items SET data_json=?, updated_at=? WHERE id=?", (payload, now, question["id"]))


def upsert_user(user_id: str, name: str, class_name: str) -> None:
    with connection() as db:
        db.execute(
            """INSERT INTO users(id, name, class_name, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, class_name=excluded.class_name""",
            (user_id, name, class_name, utc_now()),
        )


def create_test(test_id: str, user_id: str, target_questions: int, state: dict[str, Any]) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO tests VALUES (?, ?, 'active', ?, ?, ?, NULL)",
            (test_id, user_id, target_questions, json.dumps(state, ensure_ascii=False), utc_now()),
        )


def load_test(test_id: str) -> sqlite3.Row | None:
    with connection() as db:
        return db.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()


def save_state(test_id: str, state: dict[str, Any], completed: bool = False) -> None:
    with connection() as db:
        db.execute(
            "UPDATE tests SET state_json=?, status=?, completed_at=? WHERE id=?",
            (
                json.dumps(state, ensure_ascii=False),
                "completed" if completed else "active",
                utc_now() if completed else None,
                test_id,
            ),
        )


def save_answer(test_id: str, result: dict[str, Any], answer_text: str, elapsed_seconds: float) -> None:
    with connection() as db:
        db.execute(
            """INSERT INTO answers(test_id, question_id, dimension, question_type,
               difficulty, answer_text, score, max_score, elapsed_seconds, feedback_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                test_id,
                result["question_id"],
                result["dimension"],
                result["question_type"],
                result["difficulty"],
                answer_text,
                result["score"],
                result["max_score"],
                elapsed_seconds,
                json.dumps(result.get("feedback", {}), ensure_ascii=False),
                utc_now(),
            ),
        )


def test_answers(test_id: str) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute("SELECT * FROM answers WHERE test_id=? ORDER BY id", (test_id,)).fetchall()
        return [dict(row) for row in rows]


def save_test_feedback(test_id: str, rating: int, ambiguous_questions: str, usability_feedback: str, report_feedback: str) -> None:
    now = utc_now()
    with connection() as db:
        test = db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            raise ValueError("测评不存在")
        if test["status"] != "completed":
            raise ValueError("请完成测评后再提交反馈")
        db.execute(
            """INSERT INTO test_feedback(test_id,rating,ambiguous_questions,usability_feedback,report_feedback,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(test_id) DO UPDATE SET rating=excluded.rating,
               ambiguous_questions=excluded.ambiguous_questions,usability_feedback=excluded.usability_feedback,
               report_feedback=excluded.report_feedback,updated_at=excluded.updated_at""",
            (test_id, rating, ambiguous_questions, usability_feedback, report_feedback, now, now),
        )


def feedback_rows() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT f.test_id,u.name user_name,u.class_name,f.rating,f.ambiguous_questions,
               f.usability_feedback,f.report_feedback,f.created_at,f.updated_at
               FROM test_feedback f JOIN tests t ON t.id=f.test_id
               JOIN users u ON u.id=t.user_id ORDER BY f.updated_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def list_job_templates(include_disabled: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM job_templates" + ("" if include_disabled else " WHERE enabled=1") + " ORDER BY name"
    with connection() as db:
        rows = db.execute(query).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["weights"] = json.loads(item.pop("weights_json"))
        item["min_scores"] = json.loads(item.pop("min_scores_json"))
        result.append(item)
    return result


def save_job_template(template: dict[str, Any], changed_by: str) -> dict[str, Any]:
    now = utc_now()
    with connection() as db:
        db.execute(
            """INSERT INTO job_templates
               (id,name,description,weights_json,min_scores_json,enabled,created_by,created_at,updated_at)
               VALUES (?,?,?,?,?,1,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
               weights_json=excluded.weights_json,min_scores_json=excluded.min_scores_json,
               created_by=excluded.created_by,updated_at=excluded.updated_at""",
            (template["id"], template["name"], template.get("description", ""),
             json.dumps(template["weights"], ensure_ascii=False),
             json.dumps(template["min_scores"], ensure_ascii=False), changed_by, now, now),
        )
    return next(item for item in list_job_templates(include_disabled=True) if item["id"] == template["id"])


def set_job_template_enabled(template_id: str, enabled: bool) -> bool:
    with connection() as db:
        cursor = db.execute("UPDATE job_templates SET enabled=?,updated_at=? WHERE id=?", (int(enabled), utc_now(), template_id))
    return cursor.rowcount > 0


def anonymous_enterprise_overview(minimum_group_size: int = 3) -> dict[str, Any]:
    """Aggregate completed assessments without exposing identities or row-level data."""
    with connection() as db:
        rows = db.execute("SELECT state_json,completed_at FROM tests WHERE status='completed'").fetchall()
    count = len(rows)
    if count < minimum_group_size:
        return {
            "eligible": False,
            "sample_size": count,
            "minimum_group_size": minimum_group_size,
            "dimension_averages": {},
            "distribution": {},
            "notice": f"为防止身份推断，至少需要 {minimum_group_size} 份已完成测评后才展示群体统计。",
        }
    values: dict[str, list[float]] = {}
    overall_scores = []
    for row in rows:
        scores = json.loads(row["state_json"]).get("scores", {})
        if not scores:
            continue
        overall_scores.append(sum(float(value) for value in scores.values()) / len(scores))
        for key, value in scores.items():
            values.setdefault(key, []).append(float(value))
    distribution = {
        "foundation": sum(score < 60 for score in overall_scores),
        "developing": sum(60 <= score < 75 for score in overall_scores),
        "proficient": sum(75 <= score < 90 for score in overall_scores),
        "advanced": sum(score >= 90 for score in overall_scores),
    }
    return {
        "eligible": True,
        "sample_size": count,
        "minimum_group_size": minimum_group_size,
        "dimension_averages": {key: round(sum(items) / len(items), 1) for key, items in values.items()},
        "distribution": distribution,
        "notice": "仅展示匿名汇总；企业端不提供姓名、班级、原始答案或个人测评记录。",
    }


def set_job_match_consent(user_id: str, granted: bool) -> None:
    with connection() as db:
        if db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise ValueError("学员不存在")
        db.execute(
            """INSERT INTO job_match_consents(user_id,granted,updated_at) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET granted=excluded.granted,updated_at=excluded.updated_at""",
            (user_id, int(granted), utc_now()),
        )


def latest_completed_scores(user_id: str) -> dict[str, float] | None:
    with connection() as db:
        row = db.execute(
            "SELECT state_json FROM tests WHERE user_id=? AND status='completed' ORDER BY completed_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {key: float(value) for key, value in json.loads(row["state_json"]).get("scores", {}).items()}


def save_dialogue_turn(test_id: str, question_id: str, user_message: str, assistant_message: str) -> dict[str, Any]:
    now = utc_now()
    with connection() as db:
        test = db.execute("SELECT status FROM tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            raise ValueError("测评不存在")
        if test["status"] == "completed":
            raise ValueError("测评已完成，不能继续添加对话")
        count = db.execute("SELECT COUNT(*) total FROM dialogue_turns WHERE test_id=? AND question_id=?", (test_id, question_id)).fetchone()["total"]
        turn_index = count + 1
        db.execute(
            "INSERT INTO dialogue_turns(test_id,question_id,turn_index,user_message,assistant_message,created_at) VALUES (?,?,?,?,?,?)",
            (test_id, question_id, turn_index, user_message, assistant_message, now),
        )
    return {"turn_index": turn_index, "user_message": user_message, "assistant_message": assistant_message, "created_at": now}


def dialogue_turns(test_id: str, question_id: str) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            "SELECT turn_index,user_message,assistant_message,created_at FROM dialogue_turns WHERE test_id=? AND question_id=? ORDER BY turn_index",
            (test_id, question_id),
        ).fetchall()
    return [dict(row) for row in rows]


def save_evidence_file(item: dict[str, Any]) -> dict[str, Any]:
    with connection() as db:
        test = db.execute("SELECT 1 FROM tests WHERE id=?", (item["test_id"],)).fetchone()
        if test is None:
            raise ValueError("测评不存在")
        db.execute(
            """INSERT INTO evidence_files
               (id,test_id,question_id,filename,media_type,size_bytes,sha256,storage_path,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item["id"], item["test_id"], item["question_id"], item["filename"], item["media_type"],
             item["size_bytes"], item["sha256"], item["storage_path"], item["created_at"]),
        )
    return {key: value for key, value in item.items() if key != "storage_path"}


def evidence_files(test_id: str, question_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT id,test_id,question_id,filename,media_type,size_bytes,sha256,created_at FROM evidence_files WHERE test_id=?"
    params: tuple[Any, ...] = (test_id,)
    if question_id is not None:
        query += " AND question_id=?"
        params = (test_id, question_id)
    query += " ORDER BY created_at"
    with connection() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def dashboard_data() -> dict[str, Any]:
    with connection() as db:
        totals = db.execute(
            """SELECT COUNT(DISTINCT u.id) users, COUNT(DISTINCT t.id) tests,
               COUNT(DISTINCT CASE WHEN t.status='completed' THEN t.id END) completed
               FROM users u LEFT JOIN tests t ON t.user_id=u.id"""
        ).fetchone()
        completed = db.execute(
            "SELECT t.*, u.name, u.class_name FROM tests t JOIN users u ON u.id=t.user_id WHERE t.status='completed'"
        ).fetchall()
        feedback_total = db.execute("SELECT COUNT(*) total, AVG(rating) average_rating FROM test_feedback").fetchone()
    dimension_values: dict[str, list[float]] = {}
    recent = []
    for row in completed:
        state = json.loads(row["state_json"])
        for key, value in state.get("scores", {}).items():
            dimension_values.setdefault(key, []).append(float(value))
        recent.append({
            "test_id": row["id"], "user_name": row["name"], "class_name": row["class_name"],
            "overall": round(sum(state.get("scores", {}).values()) / 6, 1),
            "completed_at": row["completed_at"],
        })
    return {
        "summary": {**dict(totals), "feedback": feedback_total["total"], "average_rating": round(feedback_total["average_rating"], 1) if feedback_total["average_rating"] is not None else None},
        "dimension_averages": {k: round(sum(v) / len(v), 1) for k, v in dimension_values.items()},
        "recent_tests": sorted(recent, key=lambda x: x["completed_at"] or "", reverse=True)[:20],
    }


def list_question_items(include_disabled: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM question_items" + ("" if include_disabled else " WHERE enabled=1") + " ORDER BY id"
    with connection() as db:
        rows = db.execute(query).fetchall()
    result = []
    for row in rows:
        item = json.loads(row["data_json"])
        item.update({"enabled": bool(row["enabled"]), "version": row["version"], "source": row["source"], "updated_at": row["updated_at"]})
        result.append(item)
    return result


def save_question_item(question: dict[str, Any], changed_by: str, action: str = "update") -> dict[str, Any]:
    now = utc_now()
    payload = json.dumps(question, ensure_ascii=False)
    with connection() as db:
        row = db.execute("SELECT version,created_at FROM question_items WHERE id=?", (question["id"],)).fetchone()
        version = 1 if row is None else row["version"] + 1
        created = now if row is None else row["created_at"]
        db.execute(
            """INSERT INTO question_items(id,data_json,enabled,version,source,created_at,updated_at)
               VALUES (?,?,1,?,'managed',?,?)
               ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json,version=excluded.version,
               source='managed',updated_at=excluded.updated_at""",
            (question["id"], payload, version, created, now),
        )
        db.execute(
            "INSERT INTO question_versions(question_id,version,data_json,action,changed_by,created_at) VALUES (?,?,?,?,?,?)",
            (question["id"], version, payload, action, changed_by, now),
        )
    return {**question, "enabled": True, "version": version, "source": "managed", "updated_at": now}


def set_question_enabled(question_id: str, enabled: bool, changed_by: str) -> bool:
    now = utc_now()
    with connection() as db:
        row = db.execute("SELECT data_json,version FROM question_items WHERE id=?", (question_id,)).fetchone()
        if row is None:
            return False
        version = row["version"] + 1
        db.execute("UPDATE question_items SET enabled=?,version=?,updated_at=? WHERE id=?", (int(enabled), version, now, question_id))
        db.execute(
            "INSERT INTO question_versions(question_id,version,data_json,action,changed_by,created_at) VALUES (?,?,?,?,?,?)",
            (question_id, version, row["data_json"], "enable" if enabled else "disable", changed_by, now),
        )
    return True


def question_versions(question_id: str) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute("SELECT * FROM question_versions WHERE question_id=? ORDER BY version DESC", (question_id,)).fetchall()
    return [{**dict(row), "question": json.loads(row["data_json"])} for row in rows]


def question_statistics() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT question_id,dimension,question_type,difficulty,COUNT(*) exposures,
               AVG(score/max_score) mean_score_ratio,AVG(elapsed_seconds) mean_seconds
               FROM answers GROUP BY question_id,dimension,question_type,difficulty"""
        ).fetchall()
        raw = db.execute(
            """SELECT a.question_id,a.score/a.max_score response_ratio,t.state_json
               FROM answers a JOIN tests t ON t.id=a.test_id WHERE t.status='completed'"""
        ).fetchall()
    by_question: dict[str, list[tuple[float, float]]] = {}
    for row in raw:
        scores = json.loads(row["state_json"]).get("scores", {})
        overall = sum(scores.values()) / max(1, len(scores))
        by_question.setdefault(row["question_id"], []).append((overall, float(row["response_ratio"])))
    result = []
    for row in rows:
        item = dict(row)
        pairs = sorted(by_question.get(row["question_id"], []))
        discrimination = None
        if len(pairs) >= 10:
            group_size = max(1, round(len(pairs) * 0.27))
            low = sum(value for _, value in pairs[:group_size]) / group_size
            high = sum(value for _, value in pairs[-group_size:]) / group_size
            discrimination = round(high - low, 3)
        ratio = round(float(row["mean_score_ratio"] or 0), 3)
        flags = []
        if row["exposures"] < 10:
            flags.append("样本不足")
        if row["exposures"] >= 10 and ratio > 0.9:
            flags.append("可能过易")
        if row["exposures"] >= 10 and ratio < 0.2:
            flags.append("可能过难")
        if discrimination is not None and discrimination < 0.15:
            flags.append("区分度偏低")
        result.append({**item, "mean_score_ratio": ratio, "mean_seconds": round(float(row["mean_seconds"] or 0), 1), "observed_discrimination": discrimination, "quality_flags": flags})
    return result


def pending_review_answers() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT a.*,u.name user_name,u.class_name,
               (SELECT COUNT(*) FROM human_reviews r WHERE r.answer_id=a.id) review_count
               FROM answers a JOIN tests t ON t.id=a.test_id JOIN users u ON u.id=t.user_id
               WHERE a.question_type!='single_choice' ORDER BY a.created_at DESC"""
        ).fetchall()
        reviews = db.execute("SELECT * FROM human_reviews ORDER BY answer_id,created_at").fetchall()
        resolutions = db.execute("SELECT * FROM review_resolutions").fetchall()
    reviews_by_answer: dict[int, list[dict[str, Any]]] = {}
    for review in reviews:
        data = dict(review)
        data["rubric"] = json.loads(data.pop("rubric_json"))
        reviews_by_answer.setdefault(data["answer_id"], []).append(data)
    resolution_by_answer = {row["answer_id"]: dict(row) for row in resolutions}
    result = []
    for row in rows:
        item = dict(row)
        item["feedback"] = json.loads(item.pop("feedback_json"))
        item["reviews"] = reviews_by_answer.get(item["id"], [])
        item["resolution"] = resolution_by_answer.get(item["id"])
        result.append(item)
    return result


def save_human_review(answer_id: int, reviewer: str, score: float, comment: str, rubric: dict[str, Any]) -> None:
    now = utc_now()
    with connection() as db:
        answer = db.execute("SELECT max_score FROM answers WHERE id=?", (answer_id,)).fetchone()
        if answer is None:
            raise ValueError("答案记录不存在")
        if not 0 <= score <= answer["max_score"]:
            raise ValueError("人工评分超出允许范围")
        db.execute(
            """INSERT INTO human_reviews(answer_id,reviewer,score,comment,rubric_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(answer_id,reviewer) DO UPDATE SET
               score=excluded.score,comment=excluded.comment,rubric_json=excluded.rubric_json,updated_at=excluded.updated_at""",
            (answer_id, reviewer, score, comment, json.dumps(rubric, ensure_ascii=False), now, now),
        )


def resolve_review(answer_id: int, score: float, resolver: str, note: str) -> None:
    now = utc_now()
    with connection() as db:
        answer = db.execute("SELECT max_score FROM answers WHERE id=?", (answer_id,)).fetchone()
        if answer is None or not 0 <= score <= answer["max_score"]:
            raise ValueError("复核分数无效")
        db.execute(
            """INSERT INTO review_resolutions(answer_id,resolved_score,resolver,note,created_at) VALUES (?,?,?,?,?)
               ON CONFLICT(answer_id) DO UPDATE SET resolved_score=excluded.resolved_score,resolver=excluded.resolver,note=excluded.note,created_at=excluded.created_at""",
            (answer_id, score, resolver, note, now),
        )


def review_records() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT r.*,a.question_id,a.score model_score,a.max_score,u.name user_name
               FROM human_reviews r JOIN answers a ON a.id=r.answer_id
               JOIN tests t ON t.id=a.test_id JOIN users u ON u.id=t.user_id
               ORDER BY r.answer_id,r.reviewer"""
        ).fetchall()
    return [dict(row) for row in rows]


def user_history(user_id: str) -> dict[str, Any]:
    with connection() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        rows = db.execute("SELECT * FROM tests WHERE user_id=? AND status='completed' ORDER BY completed_at", (user_id,)).fetchall()
    if user is None:
        return {"user": None, "tests": []}
    tests = []
    for row in rows:
        state = json.loads(row["state_json"])
        scores = state.get("scores", {})
        tests.append({"test_id": row["id"], "completed_at": row["completed_at"], "overall": round(sum(scores.values()) / max(1, len(scores)), 1), "dimension_scores": scores})
    return {"user": dict(user), "tests": tests}


def export_rows(kind: str) -> tuple[list[str], list[dict[str, Any]]]:
    with connection() as db:
        if kind == "answers":
            rows = db.execute("""SELECT a.id,a.test_id,u.name user_name,u.class_name,a.question_id,a.dimension,a.question_type,a.difficulty,a.answer_text,a.score,a.max_score,a.elapsed_seconds,a.created_at FROM answers a JOIN tests t ON t.id=a.test_id JOIN users u ON u.id=t.user_id ORDER BY a.id""").fetchall()
        elif kind == "reviews":
            rows = db.execute("""SELECT r.id,r.answer_id,r.reviewer,r.score,r.comment,r.created_at,a.question_id,a.score model_score,a.max_score FROM human_reviews r JOIN answers a ON a.id=r.answer_id ORDER BY r.id""").fetchall()
        elif kind == "feedback":
            rows = db.execute("""SELECT f.test_id,u.name user_name,u.class_name,f.rating,f.ambiguous_questions,f.usability_feedback,f.report_feedback,f.created_at,f.updated_at FROM test_feedback f JOIN tests t ON t.id=f.test_id JOIN users u ON u.id=t.user_id ORDER BY f.updated_at DESC""").fetchall()
        else:
            raise ValueError("不支持的导出类型")
    data = [dict(row) for row in rows]
    return (list(data[0].keys()) if data else [], data)
