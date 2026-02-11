from __future__ import annotations

import random
import json
import os
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


# BingoApp のルート（…/BingoApp）
APP_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = APP_ROOT / "web"
DATA_DIR = APP_ROOT / "data"
RUNTIME_DIR = APP_ROOT / "runtime"

LATEST_FILE = DATA_DIR / "latest.json"  # 「今進行中のイベント」を指すリンク的ファイル


def now_id() -> str:
    # 例: 20260209_221530
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_name(s: str) -> str:
    # ファイル名に使いにくい文字をざっくり除去（超シンプル）
    return "".join(ch for ch in s if ch.isalnum() or ch in ("-", "_")).strip() or "event"


def bingo_label(n: int) -> str:
    # 1-15:B, 16-30:I, 31-45:N, 46-60:G, 61-75:O
    if 1 <= n <= 15:
        return f"B-{n}"
    if 16 <= n <= 30:
        return f"I-{n}"
    if 31 <= n <= 45:
        return f"N-{n}"
    if 46 <= n <= 60:
        return f"G-{n}"
    if 61 <= n <= 75:
        return f"O-{n}"
    return str(n)


def load_latest() -> dict | None:
    if not LATEST_FILE.exists():
        return None
    try:
        return json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_latest(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    LATEST_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def new_event(event_name: str, winners_target: int) -> dict:
    event_id = now_id()
    file_name = f"{event_id}_{safe_name(event_name)}.json"
    event_file = DATA_DIR / file_name

    state = {
        "eventId": event_id,
        "eventName": event_name,
        "winnersTarget": winners_target,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "status": "ready",  # ready / running / ended
        "startedAt": None,
        "endedAt": None,
        "currentNumber": None,
        "currentLabel": None,
        "drawnOrder": [],
        "remainingCount": 75,
        "eventFile": str(event_file),  # どこに保存したか（復元用）
        "ui": {
            "animationMs": 1000,
            "confirmUndo": True,
            "confirmEnd": True,
        },
        "rules": {
            "rangeMin": 1,
            "rangeMax": 75,
            "freeCenter": True,
            "winLine": 1,
            "diagAllowed": True,
        },
    }

    # イベントごとのファイルも保存（履歴として残る）
    DATA_DIR.mkdir(exist_ok=True)
    event_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # latest.json も更新
    save_latest(state)
    return state

def persist_state(state: dict) -> None:
    """latest.json と eventFile を両方更新する（保存の一本化）"""
    save_latest(state)

    event_file = state.get("eventFile")
    if isinstance(event_file, str) and event_file:
        try:
            Path(event_file).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def make_remaining_set(state: dict) -> set[int]:
    """drawnOrder から remaining を計算する（source of truth は drawnOrder）"""
    used = set(int(x) for x in state.get("drawnOrder", []) if isinstance(x, int) or (isinstance(x, str) and str(x).isdigit()))
    return set(range(1, 76)) - used


def require_running(state: dict) -> bool:
    return state.get("status") == "running"


class BingoHandler(SimpleHTTPRequestHandler):
    """
    /        -> web/index.html
    /draw    -> web/draw.html
    /api/*   -> JSON API
    その他   -> web/配下の静的ファイル
    """

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/state":
            self.handle_api_state()
            return
        
        if path == "/api/events":
            self.handle_api_events()
            return

        if path == "/":
            self.path = "/index.html"
        elif path == "/draw":
            self.path = "/draw.html"

        return super().do_GET()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/new":
            self.handle_api_new()
            return

        if path == "/api/state":
            self.handle_api_save_state()
            return

        if path == "/api/start":
            self.handle_api_start()
            return

        if path == "/api/draw":
            self.handle_api_draw()
            return

        if path == "/api/undo":
            self.handle_api_undo()
            return

        if path == "/api/end":
            self.handle_api_end()
            return
        
        if path == "/api/reset":
            self.handle_api_reset()
            return

        if path == "/api/use":
            self.handle_api_use()
            return
        
        if path == "/api/delete":
            self.handle_api_delete()
            return

        self.send_error(404, "Not Found")

    # -------- API helpers --------
    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -------- API endpoints --------
    def handle_api_state(self) -> None:
        state = load_latest()
        if state is None:
            self.send_json({"ok": True, "state": None})
        else:
            self.send_json({"ok": True, "state": state})

    def handle_api_new(self) -> None:
        body = self.read_json_body()
        event_name = str(body.get("eventName", "")).strip() or "BingoEvent"
        winners_target = int(body.get("winnersTarget", 0) or 0)
        if winners_target < 0:
            winners_target = 0

        state = new_event(event_name, winners_target)
        self.send_json({"ok": True, "state": state})

    def handle_api_save_state(self) -> None:
        body = self.read_json_body()
        state = body.get("state")
        if not isinstance(state, dict):
            self.send_json({"ok": False, "error": "state is required"}, status=400)
            return

        # latest.json 保存
        save_latest(state)

        # イベントごとのファイルも上書き保存（eventFile があれば）
        event_file = state.get("eventFile")
        if isinstance(event_file, str) and event_file:
            try:
                Path(event_file).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        self.send_json({"ok": True})
    
    def handle_api_start(self) -> None:
        state = load_latest()
        if state is None:
            self.send_json({"ok": False, "error": "no event"}, status=400)
            return

        if state.get("status") == "ended":
            self.send_json({"ok": False, "error": "event ended"}, status=400)
            return

        if state.get("status") != "running":
            state["status"] = "running"
            state["startedAt"] = datetime.now().isoformat(timespec="seconds")
            persist_state(state)

        self.send_json({"ok": True, "state": state})


    def handle_api_draw(self) -> None:
        state = load_latest()
        if state is None:
            self.send_json({"ok": False, "error": "no event"}, status=400)
            return

        if not require_running(state):
            self.send_json({"ok": False, "error": "not running"}, status=400)
            return

        remaining = make_remaining_set(state)
        if not remaining:
            self.send_json({"ok": False, "error": "no remaining numbers"}, status=400)
            return

        n = random.choice(sorted(remaining))
        drawn = list(state.get("drawnOrder", []))
        drawn.append(n)

        state["drawnOrder"] = drawn
        state["currentNumber"] = n
        state["currentLabel"] = bingo_label(n)

        remaining2 = make_remaining_set(state)
        state["remainingCount"] = len(remaining2)

        persist_state(state)
        self.send_json({"ok": True, "state": state})


    def handle_api_undo(self) -> None:
        state = load_latest()
        if state is None:
            self.send_json({"ok": False, "error": "no event"}, status=400)
            return

        if not require_running(state):
            self.send_json({"ok": False, "error": "not running"}, status=400)
            return

        drawn = list(state.get("drawnOrder", []))
        if not drawn:
            self.send_json({"ok": False, "error": "nothing to undo"}, status=400)
            return

        # 直前の1回だけ戻す
        drawn.pop()
        state["drawnOrder"] = drawn

        # current を 1つ前に戻す
        if drawn:
            prev = int(drawn[-1])
            state["currentNumber"] = prev
            state["currentLabel"] = bingo_label(prev)
        else:
            state["currentNumber"] = None
            state["currentLabel"] = None

        remaining2 = make_remaining_set(state)
        state["remainingCount"] = len(remaining2)

        persist_state(state)
        self.send_json({"ok": True, "state": state})


    def handle_api_end(self) -> None:
        state = load_latest()
        if state is None:
            self.send_json({"ok": False, "error": "no event"}, status=400)
            return

        if state.get("status") == "ended":
            self.send_json({"ok": True, "state": state})
            return

        state["status"] = "ended"
        state["endedAt"] = datetime.now().isoformat(timespec="seconds")
        persist_state(state)

        self.send_json({"ok": True, "state": state})

    def handle_api_reset(self) -> None:
        # 「続きから」を消して最初からにする（latest.json を削除）
        try:
            if LATEST_FILE.exists():
                LATEST_FILE.unlink()
        except Exception:
            pass
        self.send_json({"ok": True})

    def handle_api_events(self) -> None:
        """
        data/ 配下のイベントJSONを一覧（latest.jsonは除外）
        新しい順（ファイル名の日時で降順）で返す
        """
        DATA_DIR.mkdir(exist_ok=True)

        items = []
        for p in sorted(DATA_DIR.glob("*.json"), key=lambda x: x.name, reverse=True):
            if p.name == "latest.json":
                continue
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

            items.append({
                "eventId": st.get("eventId"),
                "eventName": st.get("eventName"),
                "status": st.get("status"),
                "createdAt": st.get("createdAt"),
                "startedAt": st.get("startedAt"),
                "endedAt": st.get("endedAt"),
                "remainingCount": st.get("remainingCount"),
                "drawCount": len(st.get("drawnOrder") or []),
                "eventFile": str(p),
                "fileName": p.name,
            })

        self.send_json({"ok": True, "events": items})


    def handle_api_use(self) -> None:
        """
        指定した eventFile の内容を latest.json にコピーして「続き」にする
        """
        body = self.read_json_body()
        event_file = body.get("eventFile")

        if not isinstance(event_file, str) or not event_file:
            self.send_json({"ok": False, "error": "eventFile is required"}, status=400)
            return

        p = Path(event_file)
        # 念のため data/ 配下に限定（安全）
        try:
            p_resolved = p.resolve()
            data_resolved = DATA_DIR.resolve()
            if data_resolved not in p_resolved.parents and p_resolved != data_resolved:
                self.send_json({"ok": False, "error": "invalid path"}, status=400)
                return
        except Exception:
            self.send_json({"ok": False, "error": "invalid path"}, status=400)
            return

        if not p.exists():
            self.send_json({"ok": False, "error": "file not found"}, status=404)
            return

        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.send_json({"ok": False, "error": "failed to read json"}, status=400)
            return

        # latest を更新
        save_latest(st)
        self.send_json({"ok": True, "state": st})
        
    def handle_api_delete(self) -> None:
        """
        指定 eventFile を削除する（latest.jsonは対象外）
        もし削除対象が現在の latest と同一なら latest.json も消す
        """
        body = self.read_json_body()
        event_file = body.get("eventFile")

        if not isinstance(event_file, str) or not event_file:
            self.send_json({"ok": False, "error": "eventFile is required"}, status=400)
            return

        p = Path(event_file)

        # data/配下のみ許可（安全）
        try:
            p_resolved = p.resolve()
            data_resolved = DATA_DIR.resolve()
            if data_resolved not in p_resolved.parents:
                self.send_json({"ok": False, "error": "invalid path"}, status=400)
                return
        except Exception:
            self.send_json({"ok": False, "error": "invalid path"}, status=400)
            return

        if p.name == "latest.json":
            self.send_json({"ok": False, "error": "cannot delete latest.json"}, status=400)
            return

        if not p.exists():
            self.send_json({"ok": False, "error": "file not found"}, status=404)
            return

        # もし今の latest がこの eventFile を指していたら latest も消す
        latest = load_latest()
        if latest and latest.get("eventFile") == str(p):
            try:
                if LATEST_FILE.exists():
                    LATEST_FILE.unlink()
            except Exception:
                pass

        try:
            p.unlink()
        except Exception:
            self.send_json({"ok": False, "error": "failed to delete"}, status=500)
            return

        self.send_json({"ok": True})


    

    def log_message(self, format, *args):
        # ログは server.log に出るので、ここは標準でOK（黙らせたければpass）
        super().log_message(format, *args)


def main() -> None:
    if not WEB_DIR.exists():
        raise RuntimeError(f"web フォルダが見つかりません: {WEB_DIR}")

    # web/ をドキュメントルートにする
    os.chdir(WEB_DIR)

    DATA_DIR.mkdir(exist_ok=True)
    RUNTIME_DIR.mkdir(exist_ok=True)

    # port=0 で OS に空きポートを割り当ててもらう
    server = ThreadingHTTPServer(("127.0.0.1", 0), BingoHandler)
    host, port = server.server_address

    # runtime/url.txt に保存（Start.command が読む）
    url = f"http://{host}:{port}/"
    (RUNTIME_DIR / "url.txt").write_text(url, encoding="utf-8")

    print("✅ BingoApp server started")
    print(f"   docroot: {WEB_DIR}")
    print(f"   open:    {url}")
    print(f"   draw:    {url}draw")
    print("   stop:    Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("🛑 server stopped")


if __name__ == "__main__":
    main()
