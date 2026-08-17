# -*- coding: utf-8 -*-
"""Review flow + duplicate submission + completion guards."""
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

    print("== 1. duplicate submission ==")
    st, start = request("POST", "/api/test/start", {"user_name": "复核流程学员", "target_questions": 15})
    check("start", st == 200, str(start)[:150])
    tid = start["test_id"]
    st, pal = request("GET", f"/api/test/{tid}/palette")
    q = pal.get("question") or {}
    qid = q["id"]
    st, sub1 = request("POST", "/api/answer/submit", {
        "test_id": tid, "question_id": qid, "answer": q["options"][0], "elapsed_seconds": 5,
        "options_order": q["options"],
    })
    check("first submit ok", st == 200, str(sub1)[:150])
    st, sub2 = request("POST", "/api/answer/submit", {
        "test_id": tid, "question_id": qid, "answer": q["options"][1], "elapsed_seconds": 5,
        "options_order": q["options"],
    })
    check("duplicate submit -> 409", st == 409, str(sub2)[:150])

    print("\n== 2. human review save + resolve + metrics ==")
    st, pending = request("GET", "/api/admin/reviews/pending", headers=headers)
    items = pending.get("items", []) if st == 200 else []
    if items:
        target = items[0]
        aid = target["id"]
        max_score = target["max_score"]
        st, rev = request("POST", "/api/admin/reviews", {
            "answer_id": aid, "reviewer": "自动复核员", "score": max_score * 0.8,
            "comment": "自动测试评分", "rubric": {"note": "auto"},
        }, headers=headers)
        check("save review ok", st == 200, str(rev)[:200])
        st, rev2 = request("POST", "/api/admin/reviews", {
            "answer_id": aid, "reviewer": "自动复核员B", "score": max_score * 0.6,
            "comment": "自动测试评分B", "rubric": {},
        }, headers=headers)
        check("second review ok", st == 200, str(rev2)[:200])
        st, res = request("POST", "/api/admin/reviews/resolve", {
            "answer_id": aid, "resolver": "自动裁决员", "score": max_score * 0.7, "note": "自动裁决",
        }, headers=headers)
        check("resolve ok", st == 200, str(res)[:150])
        st, met = request("GET", "/api/admin/reviews/metrics", headers=headers)
        check("metrics ok", st == 200, str(met)[:200])
        # review with invalid score -> 422
        st, bad = request("POST", "/api/admin/reviews", {
            "answer_id": aid, "reviewer": "坏评分员", "score": max_score * 5, "comment": "x",
        }, headers=headers)
        check("review out of range -> 422", st == 422, str(bad)[:150])
    else:
        print("[SKIP] no pending reviews to exercise")

    print("\n== 3. submit after completion -> 409 ==")
    # complete the test quickly using correct answers from bank
    sys.path.insert(0, ROOT)
    from question_bank.loader import load_all_questions
    answers = {q["id"]: q.get("answer") for q in load_all_questions()}
    for slot in range(1, 16):
        st, sel = request("POST", f"/api/test/{tid}/select/{slot}")
        if st != 200 or sel.get("readonly"):
            continue
        q2 = sel.get("question") or {}
        qid2 = q2.get("id")
        if not qid2:
            continue
        correct = answers.get(qid2)
        if q2.get("type") == "single_choice":
            ans = correct or q2["options"][0]
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid2, "answer": ans,
                "elapsed_seconds": 4, "options_order": q2["options"],
            })
        else:
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid2, "answer": "完整闭环答案：目标、步骤、核验、风险。",
                "elapsed_seconds": 4,
            })
        if st != 200:
            check(f"finish slot {slot}", False, str(sub)[:200])
            break
        if sub.get("completed"):
            break
    st, sub = request("POST", "/api/answer/submit", {
        "test_id": tid, "question_id": qid, "answer": "x", "elapsed_seconds": 1,
    })
    check("submit after completion -> 409", st == 409, str(sub)[:150])
    st, chat = request("POST", "/api/ai-chat", {"test_id": tid, "question_id": qid, "message": "还能对话吗"})
    check("ai-chat after completion -> 409", st == 409, str(chat)[:150])

    print("\n== 4. student history & growth ==")
    st, hist = request("GET", "/api/users/ghost/history")
    check("history unknown user -> 404", st == 404, str(hist)[:100])
    st, students = request("GET", "/api/admin/students", headers=headers)
    check("student list ok", st == 200 and isinstance(students.get("items"), list), str(students)[:150])

    print("\n========================================")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print("  FAILED:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
