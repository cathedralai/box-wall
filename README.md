# The box wall: check it yourself

`box-wall.mp4` shows a wall of squares. Every square is one sealed Cathedral sandbox that started, played a small game by itself, and was deleted. This folder holds what you need to check that this happened, without taking our word for it.

## Check it

You need Python 3.10 or newer.

```sh
git clone https://github.com/cathedralai/box-wall
cd box-wall
curl -fsSLO https://raw.githubusercontent.com/cathedralai/cathedral-sandbox/60426880b322184c7f79deb5f6d9da5defdb9468/room-kit/verify_receipts.py
python3 -m pip install cryptography
python3 verify.py --checker verify_receipts.py
```

The last line should read `RESULT: all checks passed`. The first command fetches Cathedral's public receipt checker at a fixed version; read it before you run it. It contacts AMD's certificate service to check the chip's report.

`python3 verify.py` alone runs the checks that only compare hashes. That shows the files agree with the receipts, not that the receipts are genuine.

## What a pass tells you

- **The receipts are genuine.** Each one is signed by a key that the hotel's AMD SEV-SNP report binds to that boot of that machine, and the report chains to AMD's root certificate. Changing one byte of one receipt makes the checker fail.
- **Every sandbox has three receipts:** it was created, it ran one command, it was deleted. The create receipt names the image (`alpine:3.20` with its digest) and the network rule (no network).
- **Every sandbox ran the same program, and it is the one in this folder.** `command.json` holds the exact command, with `game.awk` inside it. Its hash is the program hash on every run receipt.
- **The squares in the film are what the sandboxes returned.** `results.jsonl` holds each sandbox's answer. Each answer hashes to the result hash on that sandbox's own run receipt, and `run.json`, which the film is drawn from, holds the same moves. Change one move of one sandbox and the check fails.
- **Every sandbox rolled its own seed** from its own kernel's random source, and this recorded run contains distinct seeds. That is not a guarantee for future runs.
- **Both hotels run a build that is on Cathedral's signed list** (the copy in this folder, release 16).

## What a pass does not tell you

- **That these are all the receipts.** This is one account's view of two shared hotels; receipts of other accounts are left out by design. The checker says so itself: "each receipt; not that none are missing".
- **That the signed list is genuine.** `verify.py` only looks the measurements up in the copy of the list in this folder. It does not check the list's own signature.
- **Anything about speed.** The times in the receipts are the hotel's clock. The clock in the film is our client's clock for one recorded run, not a capacity benchmark.
- **That nothing else could go wrong on a hotel.** A receipt says what the sealed hotel signed. It is a signed record, not a mathematical proof.

## One thing we did not do at the time

We did not save each sandbox's raw answer when the film was made. We saved the moves. Each answer in `results.jsonl` was rebuilt from those moves plus the one field we had not kept, the hotel's run time in milliseconds, found by trying values until the hash matched the receipt. A single wrong move would make every value fail, so the match still pins the moves.

## Files

| File | What it is |
| --- | --- |
| `box-wall.mp4` | The film. |
| `verify.py` | The check. Standard library only. |
| `receipts/` | The signed receipts of this run, one file per hotel. |
| `attestation/` | Each hotel's binding and AMD SEV-SNP report. |
| `approved-measurements.signed.json` | Cathedral's signed list of approved hotel builds, as served on 22 Nov 2026. |
| `command.json`, `exec-request.json` | The exact command and the exact request bytes sent to every sandbox. |
| `game.awk` | The game: a runner collects embers in a 16 by 16 arena with random walls. |
| `results.jsonl` | Each sandbox's answer. |
| `run.json`, `render.py` | The film's data and the script that draws it. |
| `wall.py` | The script that made the run. It needs an account key and is here only to be read. |
