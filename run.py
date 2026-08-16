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


def read_required_secret(prompt: str) -> str:
    """Keep the interactive launcher open when a paste/Enter is not captured."""
    while True:
        value = getpass.getpass(prompt).strip()
        if value:
            return value
        print("No characters were received. Paste the token first, then press Enter; this window will keep waiting.")


def local_urls() -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        addresses.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return [f"http://{address}:8000" for address in sorted(addresses, key=lambda value: value == "127.0.0.1")]


def open_browser_when_ready() -> None:
    url = "http://127.0.0.1:8000"
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


if __name__ == "__main__":
    if "--configure-tbox-both" in sys.argv:
        scoring_token = read_required_secret("[1/4] Paste scoring-agent token (hidden), then press Enter: ")
        scoring_app_id = input("[2/4] Scoring APP ID: press Enter to use 202608AP95fB21469777: ").strip() or "202608AP95fB21469777"
        question_token = read_required_secret("[3/4] Paste question-bank-agent token (hidden), then press Enter: ")
        question_app_id = input("[4/4] Question APP ID: press Enter to use 202608AP9YhY21462248: ").strip() or "202608AP9YhY21462248"
        os.environ["TBOX_TOKEN"] = scoring_token
        os.environ["TBOX_APP_ID"] = scoring_app_id
        os.environ["TBOX_QUESTION_TOKEN"] = question_token
        os.environ["TBOX_QUESTION_APP_ID"] = question_app_id
        sys.argv.remove("--configure-tbox-both")
    if "--configure-tbox" in sys.argv:
        token = read_required_secret("Paste TBox token (hidden), then press Enter: ")
        os.environ["TBOX_TOKEN"] = token
        os.environ.setdefault("TBOX_APP_ID", "202608AP95fB21469777")
        sys.argv.remove("--configure-tbox")
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
