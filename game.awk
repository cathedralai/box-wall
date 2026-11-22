# Ember Run: a tiny game that one box plays by itself.
# A runner crosses a 16 by 16 arena with random walls and collects embers.
# The box rolls its own seed, so every box plays a different game.
# Output: one "W" line with the walls, then one line per step: px py ex ey score.
# No single quotes in this file: it travels inside a single-quoted shell string.
function bfs(sx, sy,    head, tail, x, y, i, nx, ny, nk) {
  split("", D); split("", NXT)
  head = 0; tail = 0
  QX[tail] = sx; QY[tail] = sy; tail++
  D[sx "," sy] = 0
  while (head < tail) {
    x = QX[head]; y = QY[head]; head++
    for (i = 0; i < 4; i++) {
      nx = x + DX[i]; ny = y + DY[i]
      if (nx < 0 || ny < 0 || nx >= N || ny >= N) continue
      nk = nx "," ny
      if (W[nk] == 1 || (nk in D)) continue
      D[nk] = D[x "," y] + 1
      NXT[nk] = x "," y
      QX[tail] = nx; QY[tail] = ny; tail++
    }
  }
  REACH = tail
}
function place_runner(    tries) {
  for (tries = 0; tries < 400; tries++) {
    px = int(rand() * N); py = int(rand() * N)
    if (W[px "," py] == 1) continue
    bfs(px, py)
    if (REACH >= 60) return
  }
}
function new_ember(    tries, k) {
  for (tries = 0; tries < 400; tries++) {
    ex = int(rand() * N); ey = int(rand() * N); k = ex "," ey
    if (W[k] == 1 || (ex == px && ey == py)) continue
    bfs(ex, ey)
    if ((px "," py) in D) return
  }
}
BEGIN {
  srand(seed); N = 16
  DX[0] = 1; DY[0] = 0; DX[1] = -1; DY[1] = 0; DX[2] = 0; DY[2] = 1; DX[3] = 0; DY[3] = -1
  out = ""
  for (y = 0; y < N; y++) for (x = 0; x < N; x++) {
    W[x "," y] = (rand() < 0.14) ? 1 : 0
    out = out W[x "," y]
  }
  print "W " out
  place_runner(); new_ember(); score = 0
  for (t = 0; t < steps; t++) {
    if (px == ex && py == ey) { score++; new_ember() }
    else { split(NXT[px "," py], P, ","); px = P[1] + 0; py = P[2] + 0 }
    print px, py, ex, ey, score
  }
}
