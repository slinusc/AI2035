"""End-to-end smoke test: drive a real Chainlit session over socket.io.

Logs in, triggers the intake (on_chat_start), answers both prompts, collects the
streamed first response, sends one free-conversation follow-up, then reports the
rows persisted to Postgres. Run against a live server on BASE_URL.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import socketio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

BASE_URL = "http://127.0.0.1:8010"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(output: str, type_: str = "user_message") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "parentId": None,
        "createdAt": _now(),
        "start": _now(),
        "end": _now(),
        "output": output,
        "name": "User",
        "type": type_,
        "streaming": False,
        "isError": False,
        "metadata": {},
    }


def main() -> int:
    # 1. Log in (password auth) and capture the access_token cookie.
    sess = requests.Session()
    r = sess.post(
        f"{BASE_URL}/login",
        data={"username": config.APP_USERNAME, "password": config.APP_PASSWORD},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    token = sess.cookies.get("access_token")
    assert token, "no access_token cookie set by /login"
    print("[1] login OK, token acquired")

    sio = socketio.Client(logger=False, engineio_logger=False)

    answers = [
        "Ich bin KI-Forscherin und denke aus einer europaeischen, "
        "regulierungsbewussten Perspektive.",
        "1. KI-Bildung ist 2030 flaechendeckend\n"
        "2. Energie wird billiger und sauberer\n"
        "3. Demokratische Kontrolle ueber KI bleibt bestehen",
    ]
    tokens: list[str] = []
    events: list[str] = []

    @sio.on("*")
    def catch_all(event, data=None):
        events.append(event)
        if event == "stream_token" and isinstance(data, dict):
            tokens.append(data.get("token", ""))

    def send(text: str) -> None:
        sio.emit("client_message",
                 {"message": _step(text), "fileReferences": None})

    def wait_stream(seconds: float = 90) -> int:
        tokens.clear()
        deadline = time.time() + seconds
        while time.time() < deadline:
            if tokens:
                time.sleep(3)  # let the stream finish
                break
            time.sleep(0.5)
        return sum(len(t) for t in tokens)

    sio.connect(
        BASE_URL,
        socketio_path="/ws/socket.io",
        transports=["websocket"],
        headers={"Cookie": f"access_token={token}"},
        auth={
            "sessionId": str(uuid.uuid4()),
            "clientType": "webapp",
            "userEnv": "{}",
        },
        wait_timeout=10,
    )
    print("[2] socket connected")

    # Frontend emits this to trigger on_chat_start (welcome + background prompt).
    sio.emit("connection_successful")
    time.sleep(2)
    print("[3] connection_successful sent -> intake started")

    # Intake is now normal messages: background, then assumptions.
    send(answers[0])          # background -> app replies with assumptions prompt
    time.sleep(2)
    send(answers[1])          # assumptions -> triggers the first response
    first_len = wait_stream()
    print(f"[4] intake completed; first response streamed {first_len} chars")

    # Free-conversation follow-up (multi-turn).
    send("Summarise your scenario in one sentence.")
    follow_len = wait_stream()
    print(f"[5] follow-up streamed {follow_len} chars")

    time.sleep(2)
    sio.disconnect()

    # 6. Verify persistence in Postgres.
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def check_db():
        ca = {"ssl": True} if config.DATABASE_SSL else {}
        eng = create_async_engine(config.DATABASE_URL, connect_args=ca)
        async with eng.connect() as conn:
            counts = {}
            for tbl in ("users", "threads", "steps"):
                res = await conn.exec_driver_sql(f'SELECT count(*) FROM {tbl}')
                counts[tbl] = res.scalar()
        await eng.dispose()
        return counts

    counts = asyncio.run(check_db())
    print(f"[6] DB rows -> users={counts['users']} "
          f"threads={counts['threads']} steps={counts['steps']}")
    print("    distinct events seen:", sorted(set(events)))

    ok = (
        ask_count["n"] >= 2
        and first_len > 0
        and follow_len > 0
        and counts["threads"] >= 1
        and counts["steps"] >= 1
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
