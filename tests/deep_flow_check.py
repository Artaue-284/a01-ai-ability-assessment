# -*- coding: utf-8 -*-
"""Deep flow check v2: subjective-question interactions and enterprise loop."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []

# Correct answers from the question bank (answer field is the option text)
BANK_ANSWERS = {}
BANK_TYPES = {}


def load_bank():
    sys.path.insert(0, ROOT)
    from question_bank.loader import load_all_questions
    for q in load_all_questions():
        BANK_ANSWERS[q["id"]] = q.get("answer")
        BANK_TYPES[q["id"]] = q.get("type")


def request(method, path, payload=None, headers=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, body


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
    load_bank()
    admin = load_key("admin_key.txt")
    ent = load_key("enterprise_key.txt")

    print("== A. 25-question test, answer only first 12 objective ==")
    st, start = request("POST", "/api/test/start", {
        "user_name": "深度流程学员2", "class_name": "深度班", "target_questions": 25,
    })
    check("start 25q test", st == 200 and start.get("test_id"), str(start)[:200])
    tid = start["test_id"]
    uid = start["user_id"]

    answered = 0
    for slot in range(1, 13):
        st, sel = request("POST", f"/api/test/{tid}/select/{slot}")
        if st != 200:
            check(f"select slot {slot}", False, str(sel)[:150])
            break
        q = sel.get("question") or {}
        qid = q.get("id")
        if not qid:
            check(f"slot {slot} no question", False, str(sel)[:150])
            break
        correct = BANK_ANSWERS.get(qid)
        if q.get("type") == "single_choice":
            ans = correct if correct else q["options"][0]
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid, "answer": ans,
                "elapsed_seconds": 6, "options_order": q["options"],
            })
        else:
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid, "answer": "深度流程：先明确目标，再执行并用第二种方法核验。",
                "elapsed_seconds": 6,
            })
        if st != 200:
            check(f"submit slot {slot}", False, str(sub)[:200])
            break
        answered += 1
    check("answered exactly 12", answered == 12, f"answered={answered}")

    print("\n== B. find subjective question in tail ==")
    subj = None
    subj_slot = None
    for slot in range(13, 26):
        st, sel = request("POST", f"/api/test/{tid}/select/{slot}")
        if st != 200:
            check(f"select tail slot {slot}", False, str(sel)[:150])
            continue
        q = sel.get("question") or {}
        if q.get("type") not in ("single_choice",):
            subj, subj_slot = q, slot
            break
    check("found subjective question", subj is not None, "slots 13-25 scanned")
    if subj:
        sqid = subj["id"]
        print(f"    subjective q: {sqid} type={subj['type']} slot={subj_slot}")

        print("\n== C. dialogue turn ==")
        st, dt = request("POST", "/api/dialogue/turn", {
            "test_id": tid, "question_id": sqid, "message": "请给我一个处理思路",
        })
        check("dialogue turn ok", st == 200 and dt.get("turn"), str(dt)[:250])
        st, dt2 = request("POST", "/api/dialogue/turn", {
            "test_id": tid, "question_id": sqid, "message": "还有别的建议吗？",
        })
        check("dialogue turn 2 ok", st == 200, str(dt2)[:200])
        st, dlist = request("GET", f"/api/test/{tid}/dialogue/{sqid}")
        check("dialogue history ok", st == 200 and len(dlist.get("items", [])) == 2, str(dlist)[:150])

        print("\n== D. evidence upload ==")
        st, ev = request("POST", "/api/evidence", {
            "test_id": tid, "question_id": sqid, "filename": "note.md",
            "content_base64": base64.b64encode("# 过程记录\n已核验".encode("utf-8")).decode("ascii"),
        })
        check("evidence ok", st == 200 and ev.get("id"), str(ev)[:250])
        st, evs = request("GET", f"/api/test/{tid}/evidence?question_id={sqid}")
        check("evidence list ok", st == 200 and len(evs.get("items", [])) >= 1, str(evs)[:200])

        print("\n== E. ai-chat ==")
        st, chat = request("POST", "/api/ai-chat", {
            "test_id": tid, "question_id": sqid, "message": "这个任务的关键步骤是什么？",
        })
        check("ai chat ok", st == 200 and chat.get("reply"), str(chat)[:300])
        if st == 200:
            print(f"    assistant mode: {chat.get('mode')} model={chat.get('model')} reply head: {str(chat.get('reply'))[:70]}")
        st, turns = request("GET", f"/api/test/{tid}/ai-chat/{sqid}")
        check("ai chat history ok", st == 200, str(turns)[:150])

        print("\n== F. submit the subjective answer ==")
        st, sub = request("POST", "/api/answer/submit", {
            "test_id": tid, "question_id": sqid, "answer": "我的最终答案：目标-执行-核验闭环。", "elapsed_seconds": 30,
        })
        check("submit subjective ok", st == 200 and sub.get("score") is not None, str(sub)[:300])

    print("\n== G. admin review queue shows pending subjective ==")
    st, pending = request("GET", "/api/admin/reviews/pending", headers={"X-Admin-Key": admin})
    check("pending reviews ok", st == 200 and isinstance(pending.get("items"), list), str(pending)[:200])
    if st == 200 and pending["items"]:
        print(f"    pending item count: {len(pending['items'])}, metrics: {pending.get('metrics', {})}")

    print("\n== H. finish the test (answer remaining slots) ==")
    for slot in range(1, 26):
        st, sel = request("POST", f"/api/test/{tid}/select/{slot}")
        if st != 200:
            continue
        if sel.get("readonly"):
            continue
        q = sel.get("question") or {}
        qid = q.get("id")
        if not qid:
            continue
        correct = BANK_ANSWERS.get(qid)
        if q.get("type") == "single_choice":
            ans = correct if correct else q["options"][0]
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid, "answer": ans,
                "elapsed_seconds": 5, "options_order": q["options"],
            })
        else:
            st, sub = request("POST", "/api/answer/submit", {
                "test_id": tid, "question_id": qid, "answer": "完整方案：目标、步骤、核验与风险控制闭环，并保留记录。",
                "elapsed_seconds": 5,
            })
        if st != 200:
            check(f"finish submit slot {slot}", False, str(sub)[:200])
            break
        if sub.get("completed"):
            break
    st, rep = request("GET", f"/api/report/{tid}")
    check("report ok", st == 200, str(rep)[:200])
    if st == 200:
        print(f"    overall={rep.get('overall_score')} level={rep.get('level')}")

    print("\n== I. enterprise template + position + apply with real scores ==")
    st, templates = request("GET", "/api/enterprise/job-templates", headers={"X-Enterprise-Key": ent})
    existing = templates.get("items", []) if st == 200 else []
    template_id = existing[0]["id"] if existing else None
    if not template_id:
        template_id = "deep-flow-template"
        st, tmpl = request("POST", "/api/enterprise/job-templates", {
            "id": template_id, "name": "深度流程岗位模板", "description": "测试模板",
            "weights": {"basic": 1/6, "prompt": 1/6, "tools": 1/6, "evaluation": 1/6, "collaboration": 1/6, "ethics": 1/6},
            "min_scores": {"basic": 40, "prompt": 40, "tools": 40, "evaluation": 40, "collaboration": 40, "ethics": 40},
            "changed_by": "深度测试",
        }, headers={"X-Enterprise-Key": ent})
        check("create template ok", st == 200, str(tmpl)[:200])
    st, pos = request("POST", "/api/enterprise/positions", {
        "title": "深度流程测试岗位2", "description": "由自动测试创建", "template_id": template_id,
    }, headers={"X-Enterprise-Key": ent})
    check("create position ok", st == 200 and pos.get("id"), str(pos)[:200])
    if st == 200:
        pid = pos["id"]
        st, apply = request("POST", f"/api/positions/{pid}/apply", {
            "user_id": uid, "user_name": "深度流程学员2", "class_name": "深度班",
            "contact": "13800000000", "consent": True,
        })
        check("student apply ok", st == 200 and apply.get("match_score") is not None, str(apply)[:250])
        if st == 200:
            print(f"    match_score={apply['match_score']}")
        st, apply2 = request("POST", f"/api/positions/{pid}/apply", {
            "user_id": uid, "user_name": "深度流程学员2", "class_name": "深度班",
            "contact": "13800000000", "consent": True,
        })
        check("duplicate apply -> 409", st == 409, str(apply2)[:150])
        st, dash = request("GET", "/api/teacher/dashboard", headers={"X-Admin-Key": admin})
        check("teacher dashboard ok", st == 200, str(dash)[:200])
        st, closed = request("POST", f"/api/enterprise/positions/{pid}/status", {"status": "closed"}, headers={"X-Enterprise-Key": ent})
        check("close position ok", st == 200, str(closed)[:150])

    print("\n== J. role guard ==")
    st, elogin = request("POST", "/api/auth/login", {"username": "deep_ent", "password": "secret123"})
    if st == 200:
        etoken = elogin["token"]
        st, denied = request("GET", "/api/admin/accounts", headers={"Authorization": f"Bearer {etoken}"})
        check("enterprise token denied admin (401/403)", st in (401, 403), str(denied)[:150])
        st, allowed = request("GET", "/api/enterprise/overview", headers={"Authorization": f"Bearer {etoken}"})
        check("enterprise token allowed enterprise api", st == 200, str(allowed)[:150])
    else:
        check("enterprise login for guard test", False, str(elogin)[:150])

    print("\n========================================")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print("  FAILED:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
