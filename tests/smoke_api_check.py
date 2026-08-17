# -*- coding: utf-8 -*-
"""Runtime smoke test: exercise main API flows against a running server.

Run with NO_PROXY=127.0.0.1,localhost to bypass any system proxy.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []
checks = []


def request(method, path, payload=None, headers=None, expect=200):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        result = json.loads(body)
    except Exception:
        result = body  # non-JSON payload (e.g. CSV export)
    checks.append((method, path, status, result))
    return status, result


def check(name, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  <-- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def get_admin_key():
    key_file = os.path.join(ROOT, "data", "admin_key.txt")
    if os.path.exists(key_file):
        return open(key_file, encoding="utf-8").read().strip()
    return os.environ.get("A01_ADMIN_KEY", "")


def get_enterprise_key():
    key_file = os.path.join(ROOT, "data", "enterprise_key.txt")
    if os.path.exists(key_file):
        return open(key_file, encoding="utf-8").read().strip()
    return os.environ.get("A01_ENTERPRISE_KEY", "")


ADMIN_KEY = get_admin_key()
ENTERPRISE_KEY = get_enterprise_key()


def main():
    print("== 1. status & readiness ==")
    status, info = request("GET", "/api/status")
    check("status ok", status == 200 and info.get("status") == "ok", str(info)[:200])

    status, dims = request("GET", "/api/dimensions")
    check("dimensions", status == 200 and len(dims.get("dimensions", [])) == 6, str(dims)[:200])

    print("\n== 2. start test ==")
    status, start = request("POST", "/api/test/start", {
        "user_name": "冒烟测试学员", "class_name": "自动化班",
        "target_questions": 15,
    })
    check("start test", status == 200 and start.get("test_id"), str(start)[:300])
    test_id = start.get("test_id")
    user_id = start.get("user_id")
    question = start.get("question") or {}

    print("\n== 3. next / palette / select ==")
    status, nxt = request("GET", f"/api/test/{test_id}/next")
    check("next question", status == 200, str(nxt)[:200])
    status, pal = request("GET", f"/api/test/{test_id}/palette")
    check("palette", status == 200 and "palette" in pal, str(pal)[:200])
    palette = pal.get("palette") or []
    if palette:
        first_slot = palette[0].get("number") if isinstance(palette[0], dict) else 1
        status, sel = request("POST", f"/api/test/{test_id}/select/{first_slot}")
        check("select question", status == 200 and sel.get("question"), str(sel)[:200])
        qid = (sel.get("question") or {}).get("id")
    else:
        qid = question.get("id")

    print("\n== 4. objective answer submit ==")
    if qid:
        # Build an answer that is likely correct: use question from select payload
        sel_q = (sel.get("question") or {})
        q_type = sel_q.get("type")
        if q_type == "single_choice" and sel_q.get("options"):
            answer = sel_q.get("answer") or sel_q["options"][0]
            status, sub = request("POST", "/api/answer/submit", {
                "test_id": test_id, "question_id": qid,
                "answer": answer, "elapsed_seconds": 12,
                "options_order": sel_q["options"],
            })
            check("submit objective answer", status == 200, str(sub)[:300])
        else:
            status, sub = request("POST", "/api/answer/submit", {
                "test_id": test_id, "question_id": qid,
                "answer": "我的答案：合理使用工具并检查输出。", "elapsed_seconds": 12,
            })
            check("submit subjective answer", status == 200, str(sub)[:300])
    else:
        check("have a question id to submit", False, str(start)[:200])

    print("\n== 5. dialogue turn & evidence & ai-chat (on a subjective question) ==")
    # 主观题在测评末段出现，初测 15 题内不一定有；找不到时仅跳过（非失败）。
    subj_qid = None
    for entry in (pal.get("palette") or []):
        slot_no = entry.get("number") if isinstance(entry, dict) else None
        if slot_no is None:
            continue
        st2, sel2 = request("POST", f"/api/test/{test_id}/select/{slot_no}")
        if st2 == 200 and (sel2.get("question") or {}).get("type") not in ("single_choice", None):
            subj_qid = (sel2.get("question") or {}).get("id")
            break
    if subj_qid:
        status, dt = request("POST", "/api/dialogue/turn", {
            "test_id": test_id, "question_id": subj_qid, "message": "请给我一点提示",
        })
        check("dialogue turn", status == 200, str(dt)[:200])
        status, ev = request("POST", "/api/evidence", {
            "test_id": test_id, "question_id": subj_qid,
            "filename": "note.txt",
            "content_base64": base64.b64encode("过程记录".encode("utf-8")).decode("ascii"),
        })
        check("evidence upload", status == 200, str(ev)[:200])
        status, chat = request("POST", "/api/ai-chat", {
            "test_id": test_id, "question_id": subj_qid, "message": "这个任务怎么完成？",
        })
        check("ai chat", status == 200, str(chat)[:250])
    else:
        print("[SKIP] no subjective question in initial palette (by design, appears later)")

    print("\n== 6. report before completion should be 409 ==")
    status, rep = request("GET", f"/api/report/{test_id}", expect=409)
    check("report blocked before completion", status == 409, str(rep)[:150])

    print("\n== 7. admin endpoints ==")
    headers = {"X-Admin-Key": ADMIN_KEY}
    status, dash = request("GET", "/api/admin/dashboard", headers=headers)
    check("admin dashboard", status == 200, str(dash)[:200])
    status, accs = request("GET", "/api/admin/accounts", headers=headers)
    check("admin accounts", status == 200, str(accs)[:150])
    status, qs = request("GET", "/api/admin/questions", headers=headers)
    check("admin questions", status == 200 and len(qs.get("items", [])) >= 90, str(qs)[:150])
    status, stats = request("GET", "/api/question-bank/stats", headers=headers)
    check("question bank stats", status == 200, str(stats)[:150])
    status, pending = request("GET", "/api/admin/reviews/pending", headers=headers)
    check("pending reviews", status == 200, str(pending)[:150])
    status, students = request("GET", "/api/admin/students", headers=headers)
    check("admin students", status == 200, str(students)[:150])
    status, feedback = request("GET", "/api/admin/feedback", headers=headers)
    check("admin feedback", status == 200, str(feedback)[:150])
    status, metrics = request("GET", "/api/admin/reviews/metrics", headers=headers)
    check("review metrics", status == 200, str(metrics)[:150])
    status, csvr = request("GET", "/api/admin/export/answers.csv", headers=headers)
    check("export answers csv", status == 200 and isinstance(csvr, str), str(csvr)[:120])
    status, csvr2 = request("GET", "/api/admin/export/badkind.csv", headers=headers, expect=404)
    check("export bad kind -> 404", status == 404, str(csvr2)[:150])

    print("\n== 8. enterprise endpoints ==")
    headers_e = {"X-Enterprise-Key": ENTERPRISE_KEY}
    status, ov = request("GET", "/api/enterprise/overview", headers=headers_e)
    check("enterprise overview", status == 200, str(ov)[:200])
    status, templates = request("GET", "/api/enterprise/job-templates", headers=headers_e)
    check("job templates", status == 200, str(templates)[:200])
    status, positions = request("GET", "/api/enterprise/positions", headers=headers_e)
    check("enterprise positions", status == 200, str(positions)[:200])

    print("\n== 9. user history & positions (student side) ==")
    if user_id:
        status, hist = request("GET", f"/api/users/{user_id}/history")
        check("user history", status == 200 and hist.get("user"), str(hist)[:200])
        status, apps = request("GET", f"/api/users/{user_id}/applications")
        check("user applications", status == 200, str(apps)[:200])
    status, openp = request("GET", "/api/positions")
    check("open positions", status == 200, str(openp)[:150])
    status, ast = request("GET", "/api/ability-standards")
    check("ability standards", status == 200, str(ast)[:100])
    status, roles = request("GET", "/api/roles")
    check("roles", status == 200, str(roles)[:100])

    print("\n== 10. feedback (before completion should be rejected) ==")
    status, fb = request("POST", "/api/feedback", {
        "test_id": test_id, "rating": 4, "ambiguous_questions": "", "usability_feedback": "ok", "report_feedback": "",
    })
    check("feedback rejected before completion", status == 422, str(fb)[:150])

    print("\n== 11. auth flows ==")
    status, login = request("POST", "/api/auth/login", {"username": "nobody", "password": "wrongpw"})
    check("bad login -> 401", status == 401, str(login)[:150])

    print("\n== 12. complete a full 15-question test ==")
    sub2 = None
    total_slots = len(pal.get("palette") or [])
    for slot_no in range(1, total_slots + 1):
        status, sel2 = request("POST", f"/api/test/{test_id}/select/{slot_no}")
        if status != 200:
            check(f"select slot {slot_no}", False, str(sel2)[:250])
            continue
        if sel2.get("readonly"):
            continue  # already answered earlier in this smoke run
        sq = (sel2.get("question") or {})
        qid2 = sq.get("id")
        if not qid2:
            check(f"slot {slot_no} has no question", False, str(sel2)[:250])
            continue
        if sq.get("type") == "single_choice" and sq.get("options"):
            ans = sq.get("answer") or sq["options"][0]
            status, sub2 = request("POST", "/api/answer/submit", {
                "test_id": test_id, "question_id": qid2, "answer": ans,
                "elapsed_seconds": 5, "options_order": sq["options"],
            })
        else:
            status, sub2 = request("POST", "/api/answer/submit", {
                "test_id": test_id, "question_id": qid2, "answer": "这是冒烟测试答案，说明完整流程。",
                "elapsed_seconds": 5,
            })
        if status != 200:
            check(f"submit slot {slot_no}", False, str(sub2)[:250])
            break
        if sub2.get("completed"):
            break
    check("completed test", bool(sub2 and sub2.get("completed")), str(sub2)[:250])

    print("\n== 13. report after completion ==")
    status, rep2 = request("GET", f"/api/report/{test_id}")
    check("report after completion", status == 200 and rep2.get("answer_review"), str(rep2)[:300])

    print("\n== 13b. feedback after completion ==")
    status, fb2 = request("POST", "/api/feedback", {
        "test_id": test_id, "rating": 4, "ambiguous_questions": "", "usability_feedback": "ok", "report_feedback": "",
    })
    check("feedback after completion", status == 200, str(fb2)[:150])

    print("\n== 14. job match consent ==")
    if user_id:
        status, jm = request("POST", f"/api/users/{user_id}/job-match", {"authorized": True})
        check("job match consent", status == 200, str(jm)[:250])
        status, jm0 = request("POST", f"/api/users/{user_id}/job-match", {"authorized": False})
        check("job match revoke", status == 200, str(jm0)[:150])

    print("\n========================================")
    print(f"TOTAL: {len(checks)} checks, FAILURES: {len(failures)}")
    for f in failures:
        print("  FAILED:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
