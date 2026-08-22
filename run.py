from pathlib import Path
import getpass
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TBOX_SCORING_APP_ID = "202608AP95fB21469777"
TBOX_QUESTION_APP_ID = "202608AP9YhY21462248"


def configure_tbox_both() -> None:
    """交互式配置百宝箱双智能体（评分/对话 + 题库教研）。

    令牌与 APP ID 只写入本进程环境变量，不落盘，与「配置百宝箱并启动.bat」保持一致。
    """
    print("配置百宝箱双智能体：评分/对话（默认 APP ID 可直接回车）与题库教研。")
    print("令牌输入不回显，仅保存在本进程环境变量中，不会写入任何文件。")
    token = getpass.getpass("TBOX_TOKEN（百宝箱令牌）: ").strip()
    scoring_app_id = input(f"TBOX_APP_ID（评分/对话智能体，默认 {TBOX_SCORING_APP_ID}）: ").strip() or TBOX_SCORING_APP_ID
    question_app_id = input(f"TBOX_QUESTION_APP_ID（题库教研智能体，默认 {TBOX_QUESTION_APP_ID}）: ").strip() or TBOX_QUESTION_APP_ID
    if not token:
        print("未输入令牌，百宝箱保持未配置状态；评分与 AI 助手将自动降级。")
        return
    os.environ["TBOX_TOKEN"] = token
    os.environ["TBOX_APP_ID"] = scoring_app_id
    os.environ["TBOX_QUESTION_APP_ID"] = question_app_id
    print("百宝箱配置已加载：评分/对话 + 题库教研。可通过 GET /api/status 查看 scoring_mode。")


def local_urls() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        addresses.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return [f"http://{address}:8000" for address in sorted(addresses, key=lambda value: value == "127.0.0.1")]


def configure_local_allowed_hosts() -> None:
    """Allow local/LAN access plus the changing Cloudflare Quick Tunnel host.

    A Quick Tunnel receives a new ``*.trycloudflare.com`` hostname on every
    launch.  Keeping only yesterday's exact hostname makes the tunnel connect
    successfully while FastAPI rejects every public request with HTTP 400.
    Render starts uvicorn directly and therefore continues to use the exact
    ``A01_ALLOWED_HOSTS`` value configured by the cloud service.
    """
    configured = [item.strip() for item in os.getenv("A01_ALLOWED_HOSTS", "").split(",") if item.strip()]
    defaults = ["localhost", "127.0.0.1", socket.gethostname(), "*.trycloudflare.com"]
    defaults.extend(url.removeprefix("http://").split(":", 1)[0] for url in local_urls())
    os.environ["A01_ALLOWED_HOSTS"] = ",".join(dict.fromkeys([*configured, *defaults]))


def open_browser_when_ready() -> None:
    url = "http://127.0.0.1:8000"
    # 本地就绪探测必须绕过系统代理：部分代理（如加速器）未放行 localhost，
    # 会让探测请求被代理拦截而误判服务未启动，导致浏览器永不自动打开。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            with opener.open(f"{url}/api/status", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


if __name__ == "__main__":
    configure_local_allowed_hosts()
    if "--configure-tbox-both" in sys.argv:
        configure_tbox_both()
    if "--check" in sys.argv:
        from backend.main import app
        print(f"OK: {app.title} {app.version}")
        raise SystemExit(0)
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    print("\nA01 assessment is ready on:")
    for url in local_urls():
        print(f"  {url}")
    print("Teammates on the same Wi-Fi/LAN should use the non-127.0.0.1 address.")
    print("Keep this window open while they are testing.\n")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
