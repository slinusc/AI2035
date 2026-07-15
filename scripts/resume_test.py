"""Verify that reopening a past thread resumes it (history + context), rather
than opening empty. Requires a live server on BASE_URL and at least one
persisted thread owned by APP_USERNAME.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import socketio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

BASE_URL = "http://127.0.0.1:8010"


async def latest_thread():
    ca = {"ssl": True} if config.DATABASE_SSL else {}
    eng = create_async_engine(config.DATABASE_URL, connect_args=ca)
    async with eng.connect() as conn:
        row = (
            await conn.exec_driver_sql(
                'SELECT id, "userIdentifier" FROM threads '
                'ORDER BY "createdAt" DESC NULLS LAST LIMIT 1'
            )
        ).first()
        steps = 0
        if row:
            steps = (
                await conn.execute(
                    text('SELECT count(*) FROM steps WHERE "threadId" = :tid'),
                    {"tid": row[0]},
                )
            ).scalar()
    await eng.dispose()
    return (row[0], row[1], steps) if row else (None, None, 0)


def main() -> int:
    tid, owner, nsteps = asyncio.run(latest_thread())
    if not tid:
        print("No thread in DB to resume — run smoke_test.py first.")
        return 1
    print(f"[0] resuming thread {tid} (owner={owner}, {nsteps} steps)")

    sess = requests.Session()
    r = sess.post(
        f"{BASE_URL}/login",
        data={"username": config.APP_USERNAME, "password": config.APP_PASSWORD},
    )
    assert r.status_code == 200, f"login {r.status_code}"
    token = sess.cookies.get("access_token")
    print("[1] login OK")

    sio = socketio.Client()
    events: list[str] = []
    tokens: list[str] = []
    resumed_steps = {"n": 0}
    asked = {"n": 0}

    @sio.on("*")
    def catch(event, data=None):
        events.append(event)
        if event == "resume_thread" and isinstance(data, dict):
            resumed_steps["n"] = len(data.get("steps", []) or [])
        if event == "stream_token" and isinstance(data, dict):
            tokens.append(data.get("token", ""))

    @sio.on("ask")
    def on_ask(data):
        asked["n"] += 1
        return {"id": str(uuid.uuid4()), "output": "x",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "type": "user_message", "name": "User"}

    sio.connect(
        BASE_URL, socketio_path="/ws/socket.io", transports=["websocket"],
        headers={"Cookie": f"access_token={token}"},
        auth={"sessionId": str(uuid.uuid4()), "clientType": "webapp",
              "userEnv": "{}", "threadId": str(tid)},
        wait_timeout=10,
    )
    print("[2] socket connected with threadId")
    sio.emit("connection_successful")

    deadline = time.time() + 20
    while time.time() < deadline:
        if "first_interaction" in events or resumed_steps["n"] > 0:
            break
        time.sleep(0.5)
    time.sleep(2)
    print(f"[3] resume_thread steps sent to UI: {resumed_steps['n']}; "
          f"first_interaction: {'first_interaction' in events}; "
          f"intake asks (should be 0): {asked['n']}")

    # Continuation: a follow-up should stream, proving context was restored.
    tokens.clear()
    sio.emit("client_message", {"message": {
        "id": str(uuid.uuid4()), "output": "In one sentence: what was my first assumption?",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "type": "user_message", "name": "User", "parentId": None,
    }, "fileReferences": None})
    deadline = time.time() + 60
    while time.time() < deadline:
        if tokens:
            time.sleep(3)
            break
        time.sleep(0.5)
    follow = sum(len(t) for t in tokens)
    print(f"[4] follow-up streamed {follow} chars")
    sio.disconnect()

    ok = (resumed_steps["n"] > 0 or "resume_thread" in events) and asked["n"] == 0 and follow > 0
    print("    events:", sorted(set(events)))
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
