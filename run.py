from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def local_urls() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        addresses.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return [f"http://{address}:8000" for address in sorted(addresses, key=lambda value: value == "127.0.0.1")]


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
