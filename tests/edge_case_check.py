# -*- coding: utf-8 -*-
"""Edge-case checks: invalid inputs and less-common flows."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def request(method, path, payload=None, headers=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(body)
    except Exception:
        return status, body


def check(name, condition, detail=""):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  <-- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def load_key(name):
    path = os.path.join(ROOT, "data", name)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    return ""


def main():
    admin = load_key("admin_key.txt")
    headers = {"X-Admin-Key": admin}

    print("== 1. nonexistent test_id ==")
    st, r = request("GET", "/api/test/nonexistent-id-123/next")
    check("next on missing test -> 404", st == 404, str(r)[:120])
    st, r = request("GET", "/api/report/nonexistent-id-123")
    check("report on missing test -> 404", st == 404, str(r)[:120])

    print("\n== 2. invalid answer submit ==")
    st, start = request("POST", "/api/test/start", {"user_name": "边缘测试", "target_questions": 15})
    check("start test", st == 200, str(start)[:150])
    tid = start["test_id"]
    st, r = request("POST", "/api/answer/submit", {"test_id": tid, "question_id": "NOPE", "answer": "x"})
    check("submit unknown question -> 404", st == 404, str(r)[:120])
    st, r = request("POST", "/api/answer/submit", {"test_id": "bad-test", "question_id": "NOPE", "answer": "x"})
    check("submit to missing test -> 404", st == 404, str(r)[:120])

    print("\n== 3. dialogue / ai-chat on objective question ==")
    st, pal = request("GET", f"/api/test/{tid}/palette")
    q = pal.get("question") or {}
    if q.get("type") == "single_choice":
        st, r = request("POST", "/api/dialogue/turn", {"test_id": tid, "question_id": q["id"], "message": "提示一下"})
        check("dialogue on objective -> 422", st == 422, str(r)[:120])
        st, r = request("POST", "/api/ai-chat", {"test_id": tid, "question_id": q["id"], "message": "提示一下"})
        check("ai-chat on objective -> 422", st == 422, str(r)[:120])

    print("\n== 4. evidence edge cases ==")
    st, r = request("POST", "/api/evidence", {
        "test_id": tid, "question_id": q["id"], "filename": "evil.exe",
        "content_base64": base64.b64encode(b"x").decode(),
    })
    check("bad extension -> 422", st == 422, str(r)[:120])
    st, r = request("POST", "/api/evidence", {
        "test_id": tid, "question_id": q["id"], "filename": "a.png",
        "content_base64": "not-base64!!!",
    })
    check("invalid base64 -> 422", st == 422, str(r)[:120])

    print("\n== 5. admin question save validation ==")
    st, r = request("POST", "/api/admin/questions", {
        "id": "EDGE001", "dimension": "bogus", "difficulty": 2, "type": "single_choice",
        "question": "测试题干是否有效？", "options": ["A", "B"], "answer": "A",
        "explanation": "解析", "changed_by": "edge",
    }, headers=headers)
    check("bad dimension -> 422", st == 422, str(r)[:150])
    st, r = request("POST", "/api/admin/questions", {
        "id": "EDGE001", "dimension": "basic", "difficulty": 2, "type": "single_choice",
        "question": "测试题干是否有效？", "options": ["A"], "answer": "A",
        "explanation": "解析", "changed_by": "edge",
    }, headers=headers)
    check("too few options -> 422", st == 422, str(r)[:150])
    st, r = request("POST", "/api/admin/questions", {
        "id": "EDGE001", "dimension": "basic", "difficulty": 2, "type": "open_text",
        "question": "测试开放题题干是否有效？", "options": [], "answer": None,
        "explanation": "解析", "rubric": [], "changed_by": "edge",
    }, headers=headers)
    check("open question without rubric -> 422", st == 422, str(r)[:150])
    st, r = request("POST", "/api/admin/questions", {
        "id": "EDGE001", "dimension": "basic", "difficulty": 2, "type": "image",
        "question": "测试图像题题干是否有效？", "options": [], "answer": None,
        "explanation": "解析", "rubric": ["a"], "image_url": "", "changed_by": "edge",
    }, headers=headers)
    check("image without url -> 422", st == 422, str(r)[:150])

    print("\n== 6. valid question save + import/export round-trip ==")
    st, r = request("POST", "/api/admin/questions", {
        "id": "EDGE001", "dimension": "basic", "difficulty": 2, "type": "single_choice",
        "question": "边缘测试：单选题题干足够长。", "options": ["选项甲", "选项乙", "选项丙"],
        "answer": "选项乙", "explanation": "解析说明", "tags": ["边缘"], "max_score": 10,
        "changed_by": "edge",
    }, headers=headers)
    check("save valid question", st == 200, str(r)[:200])
    st, exp = request("GET", "/api/admin/questions-export.json", headers=headers)
    check("export ok", st == 200 and len(exp.get("items", [])) >= 90, str(exp)[:120])
    st, vers = request("GET", "/api/admin/questions/EDGE001/versions", headers=headers)
    check("question versions ok", st == 200, str(vers)[:150])
    st, r = request("POST", "/api/admin/questions-import", {
        "items": [{
            "id": "EDGEIMP01", "dimension": "tools", "difficulty": 3, "type": "open_text",
            "question": "导入测试：开放题题干足够长。", "options": [], "answer": None,
            "explanation": "导入解析", "rubric": ["要点一", "要点二"], "max_score": 20,
            "changed_by": "edge",
        }, {
            "id": "EDGEIMP02", "dimension": "bogus", "difficulty": 3, "type": "open_text",
            "question": "导入测试：坏维度题干足够长。", "options": [], "answer": None,
            "explanation": "导入解析", "rubric": ["要点"], "max_score": 20, "changed_by": "edge",
        }],
    }, headers=headers)
    check("import mixed ok/bad", st == 200 and "EDGEIMP01" in r.get("saved", []) and len(r.get("errors", [])) == 1, str(r)[:200])

    print("\n== 7. admin export kinds ==")
    for kind in ("answers", "tests", "users", "reviews", "feedback"):
        st, r = request("GET", f"/api/admin/export/{kind}.csv", headers=headers)
        check(f"export {kind}", st == 200, str(r)[:80])

    print("\n== 8. feedback on missing test ==")
    st, r = request("POST", "/api/feedback", {"test_id": "missing", "rating": 3})
    check("feedback missing test -> 422", st == 422, str(r)[:120])

    print("\n== 9. job match on unknown user ==")
    st, r = request("POST", "/api/users/ghost-user-123/job-match", {"authorized": True})
    check("job-match unknown user -> 404/409", st in (404, 409), str(r)[:150])

    print("\n== 10. question enabled toggle ==")
    st, r = request("POST", "/api/admin/questions/EDGE001/enabled?enabled=false&changed_by=edge", headers=headers)
    check("disable question", st == 200, str(r)[:150])
    st, r = request("POST", "/api/admin/questions/EDGE001/enabled?enabled=true&changed_by=edge", headers=headers)
    check("re-enable question", st == 200, str(r)[:150])

    print("\n== 11. teacher role via admin key on teacher dashboard ==")
    st, r = request("GET", "/api/teacher/dashboard", headers={"X-Admin-Key": admin})
    check("teacher dashboard", st == 200 and "dashboard" in r, str(r)[:150])

    print("\n== 12. resume flow (palette on in-progress test) ==")
    st, r = request("GET", f"/api/test/{tid}/palette")
    check("resume palette", st == 200 and r.get("question"), str(r)[:150])

    print("\n== 13. no auth on admin endpoints ==")
    st, r = request("GET", "/api/admin/dashboard")
    check("admin without key -> 401", st == 401, str(r)[:120])

    print("\n== 14. start test validation ==")
    st, r = request("POST", "/api/test/start", {"user_name": "", "target_questions": 15})
    check("empty name -> 422", st == 422, str(r)[:150])
    st, r = request("POST", "/api/test/start", {"user_name": "x", "target_questions": 5})
    check("target < 15 -> 422", st == 422, str(r)[:150])
    st, r = request("POST", "/api/test/start", {"user_name": "x", "target_questions": 30})
    check("target > 25 -> 422", st == 422, str(r)[:150])

    print("\n== 15. cleanup edge question ==")
    st, r = request("POST", "/api/admin/questions/EDGE001/enabled?enabled=false&changed_by=edge", headers=headers)
    check("disable leftover question", st == 200, str(r)[:120])

    print("\n========================================")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print("  FAILED:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
