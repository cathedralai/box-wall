#!/usr/bin/env python3
"""Check the box wall film against its receipts. Standard library only.

    python3 verify.py                      # the checks that need nothing else
    python3 verify.py --checker verify_receipts.py   # plus signatures and the chip chain

The second form runs Cathedral's public receipt checker (room-kit/verify_receipts.py in
github.com/cathedralai/cathedral-sandbox; it needs `pip install cryptography` and reaches
AMD's certificate service). Without it this script only compares hashes, which shows the
files agree with the receipts but not that the receipts are genuine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOTELS = ("nc-sealed-2", "nc-sealed-3")
results: list[tuple[str, bool, str]] = []


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(doc) -> bytes:
    # The same form the hotel hashes: sorted keys, no spaces, UTF-8.
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def statement(rec: dict) -> dict:
    st = rec["statement"]
    return st if isinstance(st, dict) else json.loads(st)


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", help="path to Cathedral's verify_receipts.py")
    a = ap.parse_args()

    # Receipts, by room and action.
    by_room: dict[str, dict[str, dict]] = {}
    for h in HOTELS:
        doc = json.loads((HERE / "receipts" / f"{h}.json").read_text())
        for rec in doc["receipts"]:
            st = statement(rec)
            by_room.setdefault(f"{h}.{st['sandbox_id']}", {})[st["action"]] = st
    rooms = sorted(by_room)

    # 1. Every box has a create, a run and a delete receipt.
    full = [r for r in rooms if {"create", "exec", "delete"} <= set(by_room[r])]
    check("every box has a create, a run and a delete receipt", len(full) == len(rooms) and len(rooms) > 0,
          f"{len(full)} of {len(rooms)} boxes")
    creates = [by_room[r]["create"] for r in full]
    check("every box started from the same image with no network",
          len({(c.get("image"), c.get("image_digest")) for c in creates}) == 1
          and all((c.get("network_policy") or {}).get("mode") == "deny_all" for c in creates),
          f"image {creates[0].get('image')} {str(creates[0].get('image_digest'))[:19]}..." if creates else "")

    # 2. The program in this folder is the program every box ran.
    command = json.loads((HERE / "command.json").read_text())
    game = (HERE / "game.awk").read_text()
    cmd_hashes = {by_room[r]["exec"].get("command_sha256") for r in full}
    check("game.awk is inside the command, unchanged", game in command[-1])
    check("the command hashes to the program hash on every run receipt",
          cmd_hashes == {sha(canonical(command))}, f"sha256 {sha(canonical(command))[:16]}...")
    req_hashes = {by_room[r]["exec"].get("customer_request_sha256") for r in full}
    check("the request bytes hash to the request hash on every run receipt",
          req_hashes == {sha((HERE / "exec-request.json").read_bytes())})

    # 3. Each box's answer hashes to the result hash on its own run receipt.
    answers = {}
    for line in (HERE / "results.jsonl").read_text().splitlines():
        row = json.loads(line)
        answers[row["room"]] = row["response"]
    good = [r for r in full if r in answers and sha(answers[r].encode()) == by_room[r]["exec"].get("result_sha256")]
    check("each box's answer hashes to the result hash on its run receipt", len(good) == len(rooms),
          f"{len(good)} of {len(rooms)} boxes")

    # 4. The film's data is exactly those answers.
    run = json.loads((HERE / "run.json").read_text())
    same = 0
    seeds = set()
    for r in run["rooms"]:
        if not r.get("id") or r["id"] not in answers:
            continue
        g = parse_game(json.loads(answers[r["id"]]).get("stdout", ""))
        if g and all(g[k] == r.get(k) for k in ("host", "seed", "walls", "steps")):
            same += 1
            seeds.add(g["seed"])
    check("the moves the film draws are the moves in those answers", same == len(rooms), f"{same} of {len(rooms)} boxes")
    check("every box rolled a different seed", len(seeds) == len(rooms), f"{len(seeds)} distinct seeds")

    # 5. Both hotels' measurements are on Cathedral's public signed list (the copy in this folder).
    listed = (HERE / "approved-measurements.signed.json").read_text()
    for h in HOTELS:
        att = json.loads((HERE / "attestation" / f"{h}.json").read_text())
        m = (att.get("binding") or {}).get("measurement") or ""
        check(f"{h}: its measurement is on the signed list in this folder", bool(m) and m in listed, m[:16] + "...")

    # 6. Signatures, receipt links, the chip's report and AMD's chain: Cathedral's own checker.
    if a.checker:
        for h in HOTELS:
            p = subprocess.run([sys.executable, a.checker, "--attestation", str(HERE / "attestation" / f"{h}.json"),
                                "--receipts", str(HERE / "receipts" / f"{h}.json")], capture_output=True, text=True)
            verdict, detail = "", (p.stderr or p.stdout).strip().splitlines()[-1:] or [""]
            try:
                out = json.loads(p.stdout[p.stdout.index("{"):])
                verdict = out.get("verdict", "")
                ch = out.get("chain", {})
                detail = [f"{ch.get('signatures_ok')} of {ch.get('receipts')} signatures good; {out.get('checked', '')}"]
            except (ValueError, KeyError):
                pass
            check(f"{h}: receipts are signed by the hotel and rooted in the chip (Cathedral's checker)", verdict == "PASS", detail[0][:150])
    else:
        results.append(("signatures and the chip chain", None, "NOT RUN: pass --checker verify_receipts.py (see README)"))  # type: ignore[arg-type]

    width = max(len(n) for n, _, _ in results)
    bad = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        bad += ok is False
        print(f"{mark}  {name.ljust(width)}  {detail}")
    skipped = any(ok is None for _, ok, _ in results)
    print()
    if bad:
        print(f"RESULT: {bad} check(s) FAILED")
    elif skipped:
        print("RESULT: the files agree with the receipts. The receipts themselves were not checked: run again with --checker.")
    else:
        print("RESULT: all checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
