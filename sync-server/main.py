"""Park Day family-sync backend.

One shared JSON state blob, optimistic concurrency via rev numbers.
Auth: X-Park-Key header must equal PARKDAY_KEY env var (the SHA-256
hex of the family password — same hash the front-end gate uses).
"""
import json
import os
import sqlite3
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("PARKDAY_DB", "/data/parkday.db")
KEY = os.environ.get("PARKDAY_KEY", "")
MAX_BYTES = 2_000_000  # ~2 MB cap on the plan blob

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id=1), rev INTEGER NOT NULL, data TEXT)"
    )
    conn.execute("INSERT OR IGNORE INTO state (id, rev, data) VALUES (1, 0, NULL)")
    conn.commit()
    return conn


def check_key(x_park_key: str | None):
    if not KEY or x_park_key != KEY:
        raise HTTPException(status_code=401, detail="bad key")


@app.get("/state")
def get_state(x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    with _lock, db() as conn:
        rev, data = conn.execute("SELECT rev, data FROM state WHERE id=1").fetchone()
    return {"rev": rev, "data": json.loads(data) if data else None}


@app.put("/state")
async def put_state(request: Request, x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="plan too large")
    try:
        body = json.loads(raw)
        base_rev = int(body["rev"]) if body.get("rev") is not None else -1
        data = body["data"]
        assert isinstance(data, dict)
    except Exception:
        raise HTTPException(status_code=400, detail="bad body")

    with _lock, db() as conn:
        cur_rev, cur_data = conn.execute("SELECT rev, data FROM state WHERE id=1").fetchone()
        if base_rev != cur_rev:
            return JSONResponse(
                status_code=409,
                content={"rev": cur_rev, "data": json.loads(cur_data) if cur_data else None},
            )
        new_rev = cur_rev + 1
        conn.execute(
            "UPDATE state SET rev=?, data=? WHERE id=1",
            (new_rev, json.dumps(data, separators=(",", ":"))),
        )
        conn.commit()
    return {"rev": new_rev}


@app.get("/health")
def health():
    return {"ok": True}
