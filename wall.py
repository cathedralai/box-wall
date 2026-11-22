#!/usr/bin/env python3
"""Create N sealed boxes on the broker's front door, have each play Ember Run, save the moves.

Every room carries a short ttl, so the hotel ends it even if this machine dies mid-run.
Every room this run made is deleted in the finally block. The key is read from a file
and never printed or saved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = "https://live.cathedral.computer"
HERE = Path(__file__).resolve().parent


def read_key(path: str) -> str:
    p = os.path.expanduser(path)
    if getattr(os.lstat(p), "st_flags", 0) & 0x40000000:
        raise SystemExit("key file is an iCloud placeholder; skipped")
    return open(p).read().strip()


def game_cmd(steps: int) -> list[str]:
    prog = (HERE / "game.awk").read_text()
    assert "'" not in prog
    script = (
        "S=$(tr -dc 0-9 </proc/sys/kernel/random/uuid 2>/dev/null | cut -c1-8); "
        '[ -n "$S" ] || S=$(( $(date +%s) % 100000000 )); '
        'echo "H $(hostname) $S"; '
        f"awk -v seed=$S -v steps={steps} '{prog}'"
    )
    return ["sh", "-c", script]


def parse_game(stdout: str) -> dict | None:
    host = seed = walls = None
    steps = []
    for line in stdout.splitlines():
        if line.startswith("H "):
            parts = line.split()
            if len(parts) >= 3:
                host, seed = parts[1], parts[2]
        elif line.startswith("W "):
            walls = line[2:].strip()
        else:
            p = line.split()
            if len(p) == 5 and all(x.isdigit() for x in p):
                steps.append([int(x) for x in p])
    if not walls or len(walls) != 256 or not steps:
        return None
    return {"host": host, "seed": seed, "walls": walls, "steps": steps}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--keyfile", required=True)
    ap.add_argument("--ttl", type=int, default=600)
    ap.add_argument("--steps", type=int, default=140)
    ap.add_argument("--image", default="alpine:3.20")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    key = read_key(a.keyfile)
    run = "wall-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json",
               "User-Agent": "cathedral-box-wall/1.0"}
    body = {"image": a.image, "resources": {"vcpu": 1, "memory_gib": 4, "disk_gib": 10},
            "ttl_seconds": a.ttl, "labels": {"run": run, "kind": "box-wall"},
            "network": {"mode": "deny_all"}}
    cmd = game_cmd(a.steps)
    limits = httpx.Limits(max_connections=400, max_keepalive_connections=400)
    rooms: list[dict] = []
    doc = {"run": run, "asked": a.n, "image": a.image, "steps": a.steps, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, limits=limits, timeout=httpx.Timeout(180.0, connect=30.0)) as c:
        try:
            # Warm the connection pool so the clock measures the broker, not TLS handshakes.
            await c.get("/v1/quota")
            t0 = time.perf_counter()

            async def create(i: int) -> dict:
                t = time.perf_counter()
                r: dict = {"i": i}
                try:
                    # A refused create (429 or 503: the hotel or the broker is busy) is tried again
                    # for up to 90 s; the clock keeps running, so the film shows the real time.
                    for attempt in range(40):
                        resp = await c.post("/v1/sandboxes", json=body)
                        r["status"] = resp.status_code
                        r["tries"] = attempt + 1
                        if resp.status_code not in (429, 503) or time.perf_counter() - t > 90:
                            break
                        await asyncio.sleep(min(3.0, float(resp.headers.get("Retry-After") or 1.0)))
                    r["hotel"] = resp.headers.get("X-Broker-Hotel", "")
                    try:
                        d = resp.json()
                    except ValueError:
                        d = {}
                    r["id"] = d.get("id") if isinstance(d, dict) else None
                    if resp.status_code != 202:
                        r["err"] = json.dumps(d)[:160] if d else resp.text[:160]
                except Exception as e:  # one bad answer must never stop the run before its cleanup
                    r["status"], r["err"] = 0, type(e).__name__
                r["create_ms"] = round((time.perf_counter() - t) * 1000, 1)
                r["up_at_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                return r

            rooms = await asyncio.gather(*(create(i) for i in range(a.n)))
            doc["create_wall_s"] = round(time.perf_counter() - t0, 3)
            ok = [r for r in rooms if r.get("status") == 202 and r.get("id")]
            doc["created"] = len(ok)
            print(f"created {len(ok)} of {a.n} in {doc['create_wall_s']} s", flush=True)

            sem = asyncio.Semaphore(128)
            t1 = time.perf_counter()

            async def play(r: dict) -> None:
                async with sem:
                    t = time.perf_counter()
                    try:
                        resp = await c.post(f"/v1/sandboxes/{r['id']}/exec", json={"cmd": cmd, "timeout_seconds": 60})
                        r["exec_status"] = resp.status_code
                        d = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                        out = d.get("stdout") or d.get("output") or ""
                        r["exit"] = d.get("exit_code", d.get("exit"))
                        g = parse_game(out)
                        if g:
                            r.update(g)
                        else:
                            r["exec_err"] = (str(d.get("stderr") or d)[:160])
                            if "exec_keys" not in doc:
                                doc["exec_keys"] = sorted(d.keys()) if isinstance(d, dict) else []
                    except (httpx.HTTPError, ValueError) as e:
                        r["exec_status"], r["exec_err"] = 0, type(e).__name__
                    r["exec_ms"] = round((time.perf_counter() - t) * 1000, 1)
                    r["played_at_ms"] = round((time.perf_counter() - t0) * 1000, 1)

            await asyncio.gather(*(play(r) for r in ok))
            doc["play_wall_s"] = round(time.perf_counter() - t1, 3)
            doc["played"] = sum(1 for r in ok if r.get("steps"))
            doc["total_wall_s"] = round(time.perf_counter() - t0, 3)
            print(f"played {doc['played']} of {len(ok)} in {doc['play_wall_s']} s", flush=True)
        finally:
            ids = [r["id"] for r in rooms if r.get("id")]
            dsem = asyncio.Semaphore(96)
            gone = 0

            async def delete(sid: str) -> None:
                nonlocal gone
                async with dsem:
                    for _ in range(3):
                        try:
                            resp = await c.delete(f"/v1/sandboxes/{sid}")
                            if resp.status_code in (200, 202, 204, 404):
                                gone += 1
                                return
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(1.0)

            await asyncio.gather(*(delete(s) for s in ids))
            # Then delete by the run label too: a create this client gave up on can still have started a room.
            left = None
            for _ in range(4):
                try:
                    resp = await c.get("/v1/sandboxes")
                    d = resp.json()
                    lst = d.get("sandboxes", d) if isinstance(d, dict) else d
                    mine = [x["id"] for x in lst if (x.get("labels") or {}).get("run") == run]
                    left = len(mine)
                    if not mine:
                        break
                    await asyncio.gather(*(delete(s) for s in mine))
                    await asyncio.sleep(2.0)
                except (httpx.HTTPError, ValueError, AttributeError, KeyError):
                    await asyncio.sleep(1.0)
            doc["deleted"], doc["left_after_delete"] = gone, left
            print(f"deleted {gone} of {len(ids)}; rooms of this run still listed: {left}", flush=True)
            doc["rooms"] = rooms
            Path(a.out).write_text(json.dumps(doc))
    by_status: dict = {}
    for r in rooms:
        k = f"{r.get('status')}:{r.get('err', '')}"
        by_status[k] = by_status.get(k, 0) + 1
    print("create answers:", by_status)
    hotels: dict = {}
    for r in rooms:
        if r.get("id"):
            hotels[r.get("hotel")] = hotels.get(r.get("hotel"), 0) + 1
    print("by hotel:", hotels)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
