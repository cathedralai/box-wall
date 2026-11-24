#!/usr/bin/env python3
"""Render the box wall film from a run file: one tile per sandbox, drawn from its recorded moves.

No sandbox count appears anywhere in the film (Fred, 21 Nov 2026: "we wont name a number").
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
BG = np.array([8, 8, 8], dtype=np.float32)
TILE = np.array([26, 26, 28], dtype=np.float32)
WALL = np.array([84, 84, 90], dtype=np.float32)
ACCENT = np.array([255, 138, 101], dtype=np.float32)
EMBER = np.array([255, 213, 79], dtype=np.float32)
WHITE = np.array([245, 245, 245], dtype=np.float32)
INK = (245, 245, 245)
DIM = (150, 150, 150)
CELLS, PX, GAP = 16, 2, 2
PITCH = CELLS * PX + GAP


def font(size: int, bold: bool = False):
    for path, idx in (("/System/Library/Fonts/Menlo.ttc", 1 if bold else 0), ("/System/Library/Fonts/Monaco.ttf", 0),
                      ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0)):
        try:
            return ImageFont.truetype(path, size, index=idx)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    run_file, out = sys.argv[1], sys.argv[2]
    doc = json.load(open(run_file))
    rooms = [r for r in doc["rooms"] if r.get("steps")]
    rooms.sort(key=lambda r: r["up_at_ms"])
    n = len(rooms)
    steps = min(len(r["steps"]) for r in rooms)
    cols = 40 if n <= 1000 else 48
    rows = (n + cols - 1) // cols
    grid_w, grid_h = cols * PITCH - GAP, rows * PITCH - GAP
    panel_w = 400
    gx = (W - panel_w - grid_w) // 2
    gy = 170 + max(0, (H - 170 - 70 - grid_h) // 2)

    walls = np.zeros((n, CELLS, CELLS), dtype=bool)
    moves = np.zeros((n, steps, 5), dtype=np.int32)
    for k, r in enumerate(rooms):
        walls[k] = (np.frombuffer(r["walls"].encode(), dtype=np.uint8) == ord("1")).reshape(CELLS, CELLS)
        moves[k] = np.array(r["steps"][:steps], dtype=np.int32)
    up_ms = np.array([r["up_at_ms"] for r in rooms], dtype=np.float64)
    create_s = float(up_ms.max()) / 1000.0

    # Destination pixel index for each upscaled grid pixel (leaves the gaps untouched).
    def dst(count: int) -> np.ndarray:
        j = np.arange(count * CELLS * PX)
        return (j // (CELLS * PX)) * PITCH + (j % (CELLS * PX))
    ydst, xdst = dst(rows) + gy, dst(cols) + gx
    idx = np.arange(n)
    slot_r, slot_c = idx // cols, idx % cols

    f_title, f_big, f_mid, f_small, f_tiny = font(54, True), font(84, True), font(30), font(24), font(20)

    # Timeline, in frames.
    T_INTRO, T_UP, T_HOLD = int(1.6 * FPS), int(5.0 * FPS), int(0.6 * FPS)
    STEP_FRAMES = 3                      # 10 moves a second
    T_PLAY = steps * STEP_FRAMES
    T_END = int(3.4 * FPS)
    total = T_INTRO + T_UP + T_HOLD + T_PLAY + T_END

    heat = np.zeros((n, CELLS, CELLS), dtype=np.float32)
    zoom_ids = [int(n * f) for f in (0.07, 0.38, 0.71, 0.93)]

    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                           "-preset", "medium", "-movflags", "+faststart", out], stdin=subprocess.PIPE)

    def tiles_rgb(step: int | None, lit: np.ndarray, flash: np.ndarray) -> np.ndarray:
        """Colour of every cell of every tile: (n, 16, 16, 3)."""
        img = np.where(walls[..., None], WALL, TILE).astype(np.float32)
        if step is not None:
            px, py, ex, ey = moves[:, step, 0], moves[:, step, 1], moves[:, step, 2], moves[:, step, 3]
            img = img + heat[..., None] * (ACCENT - img) * 1.0
            img[idx, ey, ex] = EMBER
            img[idx, py, px] = WHITE
        img = img * lit[:, None, None, None]
        img = img + flash[:, None, None, None] * (WHITE - img)
        return img

    def compose(img: np.ndarray, canvas: np.ndarray) -> None:
        full = np.zeros((rows * cols, CELLS, CELLS, 3), dtype=np.float32) + BG
        full[:n] = img
        big = full.reshape(rows, cols, CELLS, CELLS, 3).transpose(0, 2, 1, 3, 4).reshape(rows * CELLS, cols * CELLS, 3)
        big = np.repeat(np.repeat(big, PX, axis=0), PX, axis=1)
        canvas[ydst[:, None], xdst[None, :]] = big

    def zoom_panel(draw: ImageDraw.ImageDraw, frame: Image.Image, img: np.ndarray, k: int, step: int) -> None:
        z = 20
        tile = np.repeat(np.repeat(img[k], z, axis=0), z, axis=1).clip(0, 255).astype(np.uint8)
        x0, y0 = gx + grid_w + 48, gy + 40
        frame.paste(Image.fromarray(tile), (x0, y0))
        draw.rectangle([x0 - 2, y0 - 2, x0 + CELLS * z + 1, y0 + CELLS * z + 1], outline=(255, 138, 101), width=2)
        r = rooms[k]
        draw.text((x0, y0 - 38), "one sandbox, up close", font=f_small, fill=DIM)
        yy = y0 + CELLS * z + 22
        for label, value in (("sandbox", str(r.get("host") or "")[:12]), ("its own seed", str(r.get("seed"))), ("embers", str(int(moves[k, step, 4])))):
            draw.text((x0, yy), label, font=f_tiny, fill=DIM)
            draw.text((x0 + 170, yy), value, font=f_tiny, fill=INK)
            yy += 32
        # Mark the same tile on the wall.
        tx, ty = gx + int(slot_c[k]) * PITCH, gy + int(slot_r[k]) * PITCH
        draw.rectangle([tx - 3, ty - 3, tx + CELLS * PX + 2, ty + CELLS * PX + 2], outline=(255, 138, 101), width=2)

    for f in range(total):
        canvas = np.zeros((H, W, 3), dtype=np.float32) + BG
        step = None
        lit = np.zeros(n, dtype=np.float32)
        flash = np.zeros(n, dtype=np.float32)
        clock_s = None
        phase = "intro"
        if f < T_INTRO:
            pass
        elif f < T_INTRO + T_UP + T_HOLD:
            phase = "up"
            u = min(1.0, (f - T_INTRO) / T_UP)
            now_ms = u * up_ms.max()
            clock_s = now_ms / 1000.0
            # Frames since this sandbox came up; not capped, so the last flashes fade during the hold.
            age = ((f - T_INTRO) / T_UP * up_ms.max() - up_ms) / max(1.0, up_ms.max() / T_UP)
            lit = (age >= 0).astype(np.float32)
            flash = np.where((age >= 0) & (age < 5), 1.0 - age / 5.0, 0.0).astype(np.float32)
        else:
            lit[:] = 1.0
            pf = f - (T_INTRO + T_UP + T_HOLD)
            if pf < T_PLAY:
                phase = "play"
                step = pf // STEP_FRAMES
                if pf % STEP_FRAMES == 0:
                    heat *= 0.88
                    heat[idx, moves[:, step, 1], moves[:, step, 0]] = 1.0
            else:
                phase = "end"
                step = steps - 1
        img = tiles_rgb(step, lit, flash)
        compose(img, canvas)
        if phase == "end":
            e = min(1.0, (f - (total - T_END)) / (0.5 * FPS))
            canvas = canvas * (1.0 - 0.78 * e)
        frame = Image.fromarray(canvas.clip(0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(frame)
        draw.text((gx, 44), "CATHEDRAL", font=f_small, fill=(255, 138, 101))
        if phase == "intro":
            a = min(1.0, f / (0.5 * FPS))
            c = int(245 * a)
            draw.text((gx, 84), "A wall of sandboxes.", font=f_title, fill=(c, c, c))
        elif phase == "up":
            draw.text((gx, 84), "Sandboxes coming up.", font=f_title, fill=INK)
            draw.text((gx + grid_w + 48, gy), f"{clock_s:5.1f} s", font=f_big, fill=INK)
            draw.text((gx + grid_w + 48, gy + 104), "client clock, one run", font=f_tiny, fill=DIM)
            draw.text((gx + grid_w + 48, gy + 150), "Each square is one\nsandbox, lit the\nmoment it answered.", font=f_small, fill=DIM, spacing=8)
        elif phase == "play":
            draw.text((gx, 84), "Each sandbox plays its game.", font=f_title, fill=INK)
            seg = min(len(zoom_ids) - 1, step * len(zoom_ids) // steps)
            zoom_panel(draw, frame, img, zoom_ids[seg], step)
            embers = int(moves[:, step, 4].sum())
            draw.text((gx + grid_w + 48, gy + 40 + CELLS * 20 + 140), "embers caught,\nall sandboxes", font=f_tiny, fill=DIM, spacing=6)
            draw.text((gx + grid_w + 48, gy + 40 + CELLS * 20 + 200), f"{embers:,}", font=f_big, fill=(255, 213, 79))
        else:
            cy = H // 2 - 150
            draw.text((gx + 40, cy), "One square per recorded sandbox.", font=f_title, fill=INK)
            draw.text((gx + 40, cy + 90), "Saved moves and receipts accompany this run.", font=f_mid, fill=INK)
            draw.text((gx + 40, cy + 150), "One recorded run, not a capacity benchmark.", font=f_mid, fill=(255, 138, 101))
            draw.text((gx + 40, cy + 240), "cathedral.computer", font=f_mid, fill=(255, 213, 79))
        draw.text((gx, H - 46), "Replay of one recorded run. Data and receipts: github.com/cathedralai/box-wall", font=f_tiny, fill=DIM)
        ff.stdin.write(frame.tobytes())
    ff.stdin.close()
    rc = ff.wait()
    print(json.dumps({"frames": total, "seconds": round(total / FPS, 1), "tiles": n, "cols": cols, "rows": rows, "steps": steps,
                      "create_s": round(create_s, 2), "ffmpeg_exit": rc}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
