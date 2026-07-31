"""Park Day family-sync + push backend.

State sync: one shared JSON blob, optimistic concurrency via rev numbers.
Push: devices subscribe (Web Push), set per-ride wait-threshold watches;
a background poller checks ThemeParks.wiki and fires notifications.

Auth: X-Park-Key header must equal PARKDAY_KEY env var (SHA-256 hex of
the family password — same hash the front-end gate uses).
"""
import asyncio
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("PARKDAY_DB", "/data/parkday.db")
KEY = os.environ.get("PARKDAY_KEY", "")
VAPID_PUBLIC = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUB = os.environ.get("VAPID_SUB", "mailto:admin@j5rescue.com")
MAX_BYTES = 2_000_000
POLL_SECONDS = 180          # check waits every 3 minutes
COOLDOWN_SECONDS = 3600     # one alert per watch per hour

TPW_IDS = {
    "MK": "75ea578a-adc8-4116-a54d-dccb60765ef9",
    "EP": "47f90d2c-e191-4239-a466-5892ef59a88b",
    "HS": "288747d1-8b4f-4a64-867e-ea7c9b27bad8",
    "AK": "1c84a229-8862-4648-9c71-378ddd2c7693",
}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id=1), rev INTEGER NOT NULL, data TEXT)"
    )
    conn.execute("INSERT OR IGNORE INTO state (id, rev, data) VALUES (1, 0, NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS subs (endpoint TEXT PRIMARY KEY, sub TEXT NOT NULL, label TEXT, created INTEGER)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watches (id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT NOT NULL, ride TEXT NOT NULL, threshold INTEGER NOT NULL, last_fired INTEGER DEFAULT 0, UNIQUE(endpoint, ride))"
    )
    try:
        conn.execute("ALTER TABLE subs ADD COLUMN device TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def check_key(x_park_key: str | None):
    if not KEY or x_park_key != KEY:
        raise HTTPException(status_code=401, detail="bad key")


# ---------------- state sync (unchanged) ----------------

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


# ---------------- push: subscribe + watches ----------------

@app.get("/push/config")
def push_config(x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    return {"publicKey": VAPID_PUBLIC, "enabled": bool(VAPID_PUBLIC and VAPID_PRIVATE)}


@app.post("/push/subscribe")
async def push_subscribe(request: Request, x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    body = await request.json()
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint")
    if not endpoint or "keys" not in sub:
        raise HTTPException(status_code=400, detail="bad subscription")
    device = str(body.get("device") or "")[:64]
    with _lock, db() as conn:
        conn.execute(
            "INSERT INTO subs (endpoint, sub, label, created, device) VALUES (?,?,?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET sub=excluded.sub, device=excluded.device, label=excluded.label",
            (endpoint, json.dumps(sub), str(body.get("label") or "")[:60], int(time.time()), device),
        )
        if device:
            olds = [r[0] for r in conn.execute(
                "SELECT endpoint FROM subs WHERE device=? AND endpoint!=?", (device, endpoint)
            ).fetchall()]
            for old in olds:
                conn.execute("DELETE FROM watches WHERE endpoint=?", (old,))
                conn.execute("DELETE FROM subs WHERE endpoint=?", (old,))
        conn.commit()
    return {"ok": True, "cleaned": device != ""}


@app.post("/push/watch")
async def add_watch(request: Request, x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    body = await request.json()
    endpoint, ride = body.get("endpoint"), (body.get("ride") or "").strip()
    try:
        threshold = max(5, min(240, int(body.get("threshold"))))
    except Exception:
        raise HTTPException(status_code=400, detail="bad threshold")
    if not endpoint or not ride:
        raise HTTPException(status_code=400, detail="bad watch")
    with _lock, db() as conn:
        conn.execute(
            "INSERT INTO watches (endpoint, ride, threshold) VALUES (?,?,?) "
            "ON CONFLICT(endpoint, ride) DO UPDATE SET threshold=excluded.threshold, last_fired=0",
            (endpoint, ride, threshold),
        )
        conn.commit()
    return {"ok": True}


@app.post("/push/unwatch")
async def remove_watch(request: Request, x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    body = await request.json()
    with _lock, db() as conn:
        conn.execute(
            "DELETE FROM watches WHERE endpoint=? AND ride=?",
            (body.get("endpoint"), body.get("ride")),
        )
        conn.commit()
    return {"ok": True}


@app.get("/push/watches")
def list_watches(endpoint: str = "", x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    with _lock, db() as conn:
        rows = conn.execute(
            "SELECT ride, threshold FROM watches WHERE endpoint=?", (endpoint,)
        ).fetchall()
    return {"watches": [{"ride": r, "threshold": t} for r, t in rows]}


@app.get("/push/all")
def all_watches(x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    with _lock, db() as conn:
        rows = conn.execute(
            "SELECT w.id, w.ride, w.threshold, w.endpoint, COALESCE(s.label,''), COALESCE(s.device,'') "
            "FROM watches w LEFT JOIN subs s ON s.endpoint = w.endpoint ORDER BY w.ride"
        ).fetchall()
    return {"watches": [
        {"id": i, "ride": r, "threshold": t, "endpoint_tail": ep[-10:], "label": lb, "device": dv}
        for i, r, t, ep, lb, dv in rows
    ]}


@app.post("/push/watch-del")
async def watch_del(request: Request, x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    body = await request.json()
    with _lock, db() as conn:
        conn.execute("DELETE FROM watches WHERE id=?", (int(body.get("id", -1)),))
        conn.commit()
    return {"ok": True}


@app.post("/push/clear")
async def clear_watches(x_park_key: str | None = Header(default=None)):
    check_key(x_park_key)
    with _lock, db() as conn:
        conn.execute("DELETE FROM watches")
        conn.commit()
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}


# ---------------- background wait poller ----------------

def _norm(name: str) -> str:
    return re.sub(r"[™®']", "", (name or "").lower()).strip()


def fetch_current_waits() -> dict:
    """name(normalized) -> minutes, across all four parks."""
    waits = {}
    for pid in TPW_IDS.values():
        try:
            req = urllib.request.Request(
                f"https://api.themeparks.wiki/v1/entity/{pid}/live",
                headers={"User-Agent": "ParkDay/5.0 (family trip planner)"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            for e in data.get("liveData") or []:
                w = ((e.get("queue") or {}).get("STANDBY") or {}).get("waitTime")
                if w is not None and e.get("name"):
                    waits[_norm(e["name"])] = w
        except Exception:
            continue  # one park failing shouldn't kill the sweep
    return waits


def match_wait(ride: str, waits: dict):
    key = _norm(ride).split(" (")[0]
    if key in waits:
        return waits[key]
    for k, v in waits.items():
        if key in k or k in key:
            return v
    return None


def send_push(sub_json: str, payload: dict) -> bool:
    """Returns False if the subscription is dead and should be removed."""
    from pywebpush import webpush, WebPushException
    try:
        webpush(
            subscription_info=json.loads(sub_json),
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE,
            vapid_claims={"sub": VAPID_SUB},
        )
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return code not in (404, 410)
    except Exception:
        return True


def check_watches_once(waits: dict, now: int | None = None) -> int:
    """Fire due notifications. Returns count sent. Pure-ish for testing."""
    now = now or int(time.time())
    fired = 0
    with _lock, db() as conn:
        rows = conn.execute(
            "SELECT w.id, w.endpoint, w.ride, w.threshold, w.last_fired, s.sub "
            "FROM watches w JOIN subs s ON s.endpoint = w.endpoint"
        ).fetchall()
        for wid, endpoint, ride, threshold, last_fired, sub in rows:
            wait = match_wait(ride, waits)
            if wait is None or wait > threshold:
                continue
            if last_fired and now - last_fired < COOLDOWN_SECONDS:
                continue
            ok = send_push(sub, {
                "title": f"🎢 {ride}: {wait} min!",
                "body": f"Wait just dropped to {wait} minutes (your alert: under {threshold}). Go go go!",
                "url": "./",
            })
            if ok:
                conn.execute("UPDATE watches SET last_fired=? WHERE id=?", (now, wid))
                fired += 1
            else:
                conn.execute("DELETE FROM subs WHERE endpoint=?", (endpoint,))
                conn.execute("DELETE FROM watches WHERE endpoint=?", (endpoint,))
        conn.commit()
    return fired


async def poller():
    while True:
        try:
            with _lock, db() as conn:
                has = conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
            if has and VAPID_PRIVATE:
                waits = await asyncio.to_thread(fetch_current_waits)
                if waits:
                    await asyncio.to_thread(check_watches_once, waits)
        except Exception:
            pass
        await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def _start_poller():
    asyncio.create_task(poller())
