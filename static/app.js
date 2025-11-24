const API = {
  evalMove: "/api/eval-move",
  makeMove: "/api/make-move",
  bestMove: "/api/best-move",
};

// -------- GLOBAL STATE --------
let game;
let board;
let pending = null;            // { from, to, uci, eval, san, color, captured }
let gameMode = null;           // 'computer' | 'human-local'
let difficulty = "easy";

let evalChart = null;
let moveCount = 0;

let squareMistakes = {};       // { "e4": count, ... }
const evalCache = new Map();   // key: fen|uci|depth -> evalRes
let moveHistory = [];          // [{ color: 'w'|'b', san, captured }]

// -------- EVAL BANDS (no raw cp in UI) --------

function evalBandInfo(cp) {
  const pawns = cp / 100.0;
  if (pawns > 1.5) {
    return { index: 2, label: "Winning for White" };
  } else if (pawns > 0.5) {
    return { index: 1, label: "Better for White" };
  } else if (pawns > -0.5) {
    return { index: 0, label: "Roughly equal" };
  } else if (pawns > -1.5) {
    return { index: -1, label: "Better for Black" };
  } else {
    return { index: -2, label: "Winning for Black" };
  }
}

function bandLabelFromIndex(index) {
  switch (Math.round(index)) {
    case 2: return "Winning for White";
    case 1: return "Better for White";
    case 0: return "Equal";
    case -1: return "Better for Black";
    case -2: return "Winning for Black";
    default: return "";
  }
}

// -------- CHART FUNCTIONS --------

function initEvalChart() {
  const canvas = document.getElementById("evalChart");
  if (!canvas) return;

  evalChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Position trend",
          data: [],
          borderWidth: 2,
          tension: 0.25,
          pointRadius: 3,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const lbl = bandLabelFromIndex(ctx.parsed.y);
              return lbl ? lbl : "";
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Move number" },
        },
        y: {
          title: { display: true, text: "Who is better?" },
          min: -2,
          max: 2,
          ticks: {
            stepSize: 1,
            callback: (value) => bandLabelFromIndex(value),
          },
        },
      },
    },
  });
}

function addEvalPoint(cp) {
  if (!evalChart) return;
  const band = evalBandInfo(cp);

  moveCount += 1;
  evalChart.data.labels.push(moveCount.toString());
  evalChart.data.datasets[0].data.push(band.index);
  evalChart.update();

  const summary = document.getElementById("evalSummary");
  if (summary) {
    summary.textContent = `Current position: ${band.label}.`;
  }
}

function resetEvalChart() {
  moveCount = 0;
  if (!evalChart) return;
  evalChart.data.labels = [];
  evalChart.data.datasets[0].data = [];
  evalChart.update();

  const summary = document.getElementById("evalSummary");
  if (summary) summary.textContent = "";
}

// -------- BASIC HELPERS --------

function fen() {
  return game.fen();
}

function statusText() {
  if (game.in_checkmate()) return "Checkmate";
  if (game.in_draw()) return "Draw";
  const turn = game.turn() === "w" ? "White" : "Black";
  return `${turn} to move${game.in_check() ? " (check)" : ""}`;
}

function updateStatus() {
  const el = document.getElementById("status");
  if (el) el.textContent = statusText();
}

function chipClassFor(bucket) {
  switch ((bucket || "").toLowerCase()) {
    case "hot": return "hot";
    case "warm": return "warm";
    case "cool": return "cool";
    case "cold": return "cold";
    case "freezing": return "freezing";
    default: return "";
  }
}

function showChip(bucket, message) {
  const chip = document.getElementById("hotcold");
  chip.className = `chip ${chipClassFor(bucket)}`;
  document.getElementById("hcLabel").textContent = bucket;
  document.getElementById("hcDetail").textContent = message ? " — " + message : "";
  chip.classList.remove("hidden");
}

function hideChip() {
  const chip = document.getElementById("hotcold");
  chip.classList.add("hidden");
  chip.className = "chip";
  const expl = document.getElementById("explanation");
  if (expl) expl.textContent = "";
}

// Illegal move message
function showIllegalMessage(text) {
  const el = document.getElementById("illegalMsg");
  if (el) el.textContent = text || "";
}

function clearIllegalMessage() {
  const el = document.getElementById("illegalMsg");
  if (el) el.textContent = "";
}

// Engine depths
function evalDepth() {
  switch (difficulty) {
    case "easy": return 8;
    case "medium": return 12;
    case "hard": return 18;
    default: return 12;
  }
}

function bestMoveDepth() {
  switch (difficulty) {
    case "easy": return 10;
    case "medium": return 16;
    case "hard": return 22;
    default: return 18;
  }
}

// -------- HEATMAP FUNCTIONS --------

function updateHeatmap() {
  const toggle = document.getElementById("heatmapToggle");
  if (!toggle || !toggle.checked) {
    const squares = document.querySelectorAll("[class*='square-']");
    squares.forEach((el) => { el.style.boxShadow = ""; });
    return;
  }

  const entries = Object.entries(squareMistakes);
  if (!entries.length) return;

  const maxCount = Math.max(...entries.map(([, c]) => c));

  entries.forEach(([square, count]) => {
    const el = document.querySelector(`.square-${square}`);
    if (!el) return;
    const intensity = count / maxCount; // 0..1
    el.style.boxShadow = `inset 0 0 0 3px rgba(248, 113, 113, ${0.2 + 0.6 * intensity})`;
  });
}

function resetHeatmap() {
  squareMistakes = {};
  const squares = document.querySelectorAll("[class*='square-']");
  squares.forEach((el) => { el.style.boxShadow = ""; });
}

// -------- MOVE LIST & CAPTURES (OUR OWN HISTORY) --------

function updateMoveList() {
  const container = document.getElementById("moveList");
  if (!container) return;

  if (moveHistory.length === 0) {
    container.innerHTML = "<span class='muted'>No moves yet.</span>";
    return;
  }

  let html = "";
  for (let i = 0; i < moveHistory.length; i += 2) {
    const whiteMove = moveHistory[i];
    const blackMove = moveHistory[i + 1];
    const moveNo = i / 2 + 1;
    html += `
      <div class="move-row">
        <span class="move-no">${moveNo}.</span>
        <span class="move-san">${whiteMove ? whiteMove.san : ""}</span>
        <span class="move-san">${blackMove ? blackMove.san : ""}</span>
      </div>
    `;
  }
  container.innerHTML = html;
}

function pieceSymbol(ptype) {
  // p, n, b, r, q, k -> always show white shapes (just for count)
  switch (ptype) {
    case "p": return "♙";
    case "n": return "♘";
    case "b": return "♗";
    case "r": return "♖";
    case "q": return "♕";
    case "k": return "♔";
    default: return "?";
  }
}

function updateCaptures() {
  const whiteEl = document.getElementById("capturedByWhite");
  const blackEl = document.getElementById("capturedByBlack");
  if (!whiteEl || !blackEl) return;

  const capturedByWhite = [];
  const capturedByBlack = [];

  moveHistory.forEach((m) => {
    if (!m.captured) return;
    const sym = pieceSymbol(m.captured);
    if (m.color === "w") {
      capturedByWhite.push(sym);
    } else {
      capturedByBlack.push(sym);
    }
  });

  whiteEl.textContent = capturedByWhite.join(" ") || "—";
  blackEl.textContent = capturedByBlack.join(" ") || "—";
}

// -------- GAME OVER BANNER --------

function getGameOverMessage() {
  if (!game.game_over()) return "";

  if (game.in_checkmate()) {
    const winner = game.turn() === "w" ? "Black" : "White";
    return `Checkmate — ${winner} wins.`;
  }

  if (game.in_stalemate()) {
    return "Stalemate — no legal moves.";
  }

  if (game.insufficient_material()) {
    return "Draw — insufficient mating material.";
  }

  if (game.in_threefold_repetition()) {
    return "Draw — threefold repetition.";
  }

  if (game.in_draw()) {
    return "Draw — no decisive result.";
  }

  return "Game over.";
}

function refreshGameOverBanner() {
  const box = document.getElementById("gameOverBox");
  const textEl = document.getElementById("gameOverText");
  if (!box || !textEl) return;

  const msg = getGameOverMessage();
  if (msg) {
    textEl.textContent = msg;
    box.classList.remove("hidden");
  } else {
    textEl.textContent = "";
    box.classList.add("hidden");
  }
}

// -------- DRAG & DROP --------

const onDragStart = (source, piece) => {
  if (game.game_over()) return false;
  if ((game.turn() === "w" && piece.startsWith("b")) ||
      (game.turn() === "b" && piece.startsWith("w"))) return false;
  return true;
};

async function onDrop(source, target) {
  hideChip();
  clearIllegalMessage();

  const piece = game.get(source);
  const needsPromotion =
    piece && piece.type === "p" &&
    (target[1] === (piece.color === "w" ? "8" : "1"));

  const promotion = needsPromotion ? "q" : undefined;

  const colorBefore = game.turn();
  const move = game.move({ from: source, to: target, promotion });

  if (!move) {
    showIllegalMessage("That move is not legal in this position.");
    return "snapback";
  }

  const uci = move.from + move.to + (move.promotion || "");
  const san = move.san;
  const captured = move.captured || null;

  game.undo(); // we only commit on "Play move"

  try {
    const subtle = document.getElementById("subtleMode").checked;
    const depth = evalDepth();
    const key = `${fen()}|${uci}|${depth}`;

    let evalRes;
    if (evalCache.has(key)) {
      evalRes = evalCache.get(key);
    } else {
      evalRes = await postJSON(API.evalMove, {
        fen: fen(),
        uci,
        depth,
      });
      evalCache.set(key, evalRes);
    }

    pending = {
      from: source,
      to: target,
      uci,
      eval: evalRes,
      san,
      color: colorBefore,
      captured,
    };

    const band = evalBandInfo(evalRes.userCp);
    const label = subtle
      ? evalRes.message
      : `${evalRes.message} · ${band.label}`;

    showChip(evalRes.bucket, label);

    const explEl = document.getElementById("explanation");
    if (explEl) explEl.textContent = evalRes.reason || "";

  } catch (e) {
    console.error(e);
    alert("Evaluation failed – check backend.");
  }

  return "snapback";
}

function onSnapEnd() {
  board.position(game.fen());
}

// -------- ENGINE MOVE (vs computer) --------

async function playEngineMoveIfNeeded() {
  if (gameMode !== "computer") return;
  if (game.game_over()) return;

  try {
    const url = `${API.bestMove}?fen=${encodeURIComponent(
      fen()
    )}&depth=${bestMoveDepth()}`;

    const data = await (await fetch(url)).json();
    const bestSan = data.bestSan;

    if (!bestSan) {
      refreshGameOverBanner();
      return;
    }

    // Get capture info using a temp game from current FEN
    const temp = new Chess(fen());
    const mvInfo = temp.move(bestSan); // should be legal
    const moveColor = mvInfo.color;
    const captured = mvInfo.captured || null;

    const move = game.move(bestSan);
    if (!move) return;

    moveHistory.push({
      color: moveColor,
      san: bestSan,
      captured,
    });

    board.position(game.fen());
    updateStatus();
    updateMoveList();
    updateCaptures();
    refreshGameOverBanner();
  } catch (e) {
    console.error("Error engine move:", e);
  }
}

// -------- API HELPER --------

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

// -------- SCREEN SWITCHING --------

function showGameScreen() {
  document.getElementById("landing").classList.add("hidden");
  document.getElementById("gameScreen").classList.remove("hidden");

  const modeInfoEl = document.getElementById("modeInfo");
  if (gameMode === "computer") {
    modeInfoEl.textContent =
      `Mode: vs computer (${difficulty} level) with AI feedback & engine replies.`;
  } else {
    modeInfoEl.textContent =
      "Mode: Local 2-player game with AI evaluation & suggestions.";
  }

  if (board.resize) board.resize();
}

function showLandingScreen() {
  document.getElementById("gameScreen").classList.add("hidden");
  document.getElementById("landing").classList.remove("hidden");

  game.reset();
  board.start();
  updateStatus();
  hideChip();
  resetEvalChart();
  resetHeatmap();
  clearIllegalMessage();
  moveHistory = [];
  updateMoveList();
  updateCaptures();
  refreshGameOverBanner();
}

// -------- INIT --------

window.addEventListener("load", () => {
  game = new Chess();

  board = Chessboard("board", {
    draggable: true,
    position: "start",
    pieceTheme: "/img/chesspieces/maestro/{piece}.svg",
    onDragStart,
    onDrop,
    onSnapEnd,
  });

  updateStatus();
  initEvalChart();
  resetHeatmap();
  moveHistory = [];
  updateMoveList();
  updateCaptures();
  refreshGameOverBanner();

  // difficulty buttons
  document.querySelectorAll(".diff-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".diff-btn")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      difficulty = btn.dataset.diff;
    });
  });

  // heatmap toggle
  const heatToggle = document.getElementById("heatmapToggle");
  if (heatToggle) {
    heatToggle.addEventListener("change", () => {
      updateHeatmap();
    });
  }

  // start vs computer
  document.getElementById("startVsComputer").addEventListener("click", () => {
    gameMode = "computer";
    game.reset();
    board.start();
    resetEvalChart();
    resetHeatmap();
    clearIllegalMessage();
    hideChip();
    updateStatus();
    moveHistory = [];
    updateMoveList();
    updateCaptures();
    refreshGameOverBanner();
    showGameScreen();
  });

  // start human-local
  document.getElementById("startHumanLocal").addEventListener("click", () => {
    gameMode = "human-local";
    game.reset();
    board.start();
    resetEvalChart();
    resetHeatmap();
    clearIllegalMessage();
    hideChip();
    updateStatus();
    moveHistory = [];
    updateMoveList();
    updateCaptures();
    refreshGameOverBanner();
    showGameScreen();
  });

  // back to landing
  document.getElementById("backBtn").addEventListener("click", () => {
    showLandingScreen();
  });

  // Play move
  document.getElementById("confirmMove").addEventListener("click", async () => {
    if (!pending) return;
    hideChip();
    clearIllegalMessage();

    try {
      const res = await postJSON(API.makeMove, {
        fen: fen(),
        uci: pending.uci,
      });

      // add eval point
      if (pending.eval && typeof pending.eval.userCp === "number") {
        addEvalPoint(pending.eval.userCp);
      }

      // heatmap: count mistakes and blunders on target square
      if (pending.eval && pending.eval.bucket) {
        const badBuckets = ["Cool", "Cold", "Freezing"];
        if (badBuckets.includes(pending.eval.bucket) && pending.to) {
          const sq = pending.to;
          squareMistakes[sq] = (squareMistakes[sq] || 0) + 1;
          updateHeatmap();
        }
      }

      // record player's move in our own history
      moveHistory.push({
        color: pending.color,
        san: pending.san,
        captured: pending.captured,
      });

      game.load(res.fen);
      board.position(res.fen);
      pending = null;
      updateStatus();
      updateMoveList();
      updateCaptures();
      refreshGameOverBanner();

      if (!game.game_over() && gameMode === "computer") {
        await playEngineMoveIfNeeded();
      }
    } catch (e) {
      console.error(e);
      pending = null;
    }
  });

  // Cancel move
  document.getElementById("cancelMove").addEventListener("click", () => {
    pending = null;
    hideChip();
    clearIllegalMessage();
  });

  // Reset
  document.getElementById("resetBtn").addEventListener("click", () => {
    game.reset();
    board.start();
    updateStatus();
    hideChip();
    resetEvalChart();
    resetHeatmap();
    clearIllegalMessage();
    moveHistory = [];
    updateMoveList();
    updateCaptures();
    refreshGameOverBanner();
  });

  // Suggest best move (always deep + mate info)
  document.getElementById("revealBtn").addEventListener("click", async () => {
    try {
      const deep = 24; // strong analysis depth for suggestions
      const url = `${API.bestMove}?fen=${encodeURIComponent(
        fen()
      )}&depth=${deep}`;

      const data = await (await fetch(url)).json();
      if (!data.bestSan) {
        refreshGameOverBanner();
        return;
      }

      let msg = `Engine suggests: ${data.bestSan}`;

      if (typeof data.mateIn === "number" && data.mateIn !== 0) {
        const movesToMate = Math.ceil(Math.abs(data.mateIn) / 2);
        if (data.mateIn > 0) {
          msg += ` (mate in ~${movesToMate} moves for the side to move)`;
        } else {
          msg += ` (you are getting mated in ~${movesToMate} moves if you don't defend!)`;
        }
      }

      alert(msg);
    } catch (e) {
      console.error(e);
      alert("Error getting best move.");
    }
  });
});
