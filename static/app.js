const API = {
  evalMove: "/api/eval-move",
  makeMove: "/api/make-move",
  bestMove: "/api/best-move",
};

let game;
let board;
let pending = null; // { from, to, uci, eval }

let gameMode = null;      // 'computer' | 'human-local'
let difficulty = "easy";  // 'easy' | 'medium' | 'hard'

/* ---------- helpers ---------- */

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
  if (!chip) return;

  chip.className = `chip ${chipClassFor(bucket)}`;

  const labelEl = document.getElementById("hcLabel");
  const detailEl = document.getElementById("hcDetail");

  if (labelEl) labelEl.textContent = bucket || "";
  if (detailEl) detailEl.textContent = message ? " — " + message : "";

  chip.classList.remove("hidden");
}

function hideChip() {
  const chip = document.getElementById("hotcold");
  if (!chip) return;
  chip.classList.add("hidden");
  chip.className = "chip";
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

/* ---------- engine depth by difficulty ---------- */

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

/* ---------- drag / drop ---------- */

const onDragStart = (source, piece) => {
  if (game.game_over()) return false;

  if (
    (game.turn() === "w" && piece.startsWith("b")) ||
    (game.turn() === "b" && piece.startsWith("w"))
  ) {
    return false;
  }
  return true;
};

async function onDrop(source, target) {
  hideChip();

  const piece = game.get(source);
  const needsPromotion =
    piece &&
    piece.type === "p" &&
    (target[1] === (piece.color === "w" ? "8" : "1"));

  const promotion = needsPromotion ? "q" : undefined;

  const move = game.move({ from: source, to: target, promotion });
  if (!move) return "snapback";

  const uci = move.from + move.to + (move.promotion || "");
  game.undo();

  try {
    const subtle = document.getElementById("subtleMode")?.checked;
    const evalRes = await postJSON(API.evalMove, {
      fen: fen(),
      uci,
      depth: evalDepth(),
    });

    pending = { from: source, to: target, uci, eval: evalRes };

    const label = subtle
      ? evalRes.message
      : `${evalRes.message} (Δ ${evalRes.deltaCp} cp)`;
    showChip(evalRes.bucket, label);
  } catch (e) {
    console.error(e);
    alert("Evaluation failed – check backend/Stockfish.");
  }

  return "snapback";
}

function onSnapEnd() {
  if (board) board.position(game.fen());
}

/* ---------- engine reply (vs computer) ---------- */

async function playEngineMoveIfNeeded() {
  if (gameMode !== "computer") return;
  if (game.game_over()) return;

  try {
    const url = `${API.bestMove}?fen=${encodeURIComponent(
      fen()
    )}&depth=${bestMoveDepth()}`;
    const res = await fetch(url);
    const data = await res.json();
    const bestSan = data.bestSan;

    if (!bestSan) {
      console.warn("No engine move returned");
      return;
    }

    const move = game.move(bestSan);
    if (!move) {
      console.warn("Engine suggested illegal move:", bestSan);
      return;
    }

    if (board) board.position(game.fen());
    updateStatus();
  } catch (e) {
    console.error("Error playing engine move:", e);
  }
}

/* ---------- board initialisation ---------- */

function initBoard() {
  const boardEl = document.getElementById("board");
  if (!boardEl) {
    console.error("Missing #board element");
    return;
  }

  board = Chessboard(boardEl, {
    draggable: true,
    position: "start",
    pieceTheme: "/img/chesspieces/maestro/{piece}.svg",
    onDragStart,
    onDrop,
    onSnapEnd,
  });

  updateStatus();
  hideChip();
}

/* ---------- screen switching ---------- */

function showGameScreen() {
  const landing = document.getElementById("landing");
  const gameScreen = document.getElementById("gameScreen");
  const modeInfoEl = document.getElementById("modeInfo");

  if (landing) landing.classList.add("hidden");
  if (gameScreen) gameScreen.classList.remove("hidden");

  if (modeInfoEl) {
    if (gameMode === "computer") {
      modeInfoEl.textContent =
        `Mode: Playing vs computer (${difficulty} level) with AI feedback and engine replies.`;
    } else if (gameMode === "human-local") {
      modeInfoEl.textContent =
        "Mode: Local 2-player game with AI evaluation and suggestions for both sides.";
    } else {
      modeInfoEl.textContent = "";
    }
  }

  if (board && typeof board.resize === "function") {
    board.resize();
  }
}

function showLandingScreen() {
  const landing = document.getElementById("landing");
  const gameScreen = document.getElementById("gameScreen");

  if (gameScreen) gameScreen.classList.add("hidden");
  if (landing) landing.classList.remove("hidden");

  // optional: reset state when going back
  pending = null;
  hideChip();
  game.reset();
  if (board) board.start();
  updateStatus();
}

/* ---------- main setup ---------- */

window.addEventListener("load", () => {
  game = new Chess();
  initBoard();

  // difficulty buttons
  const diffButtons = document.querySelectorAll(".diff-btn");
  diffButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      diffButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      difficulty = btn.dataset.diff || "easy";
    });
  });

  // landing: start vs computer
  const vsComputerBtn = document.getElementById("startVsComputer");
  if (vsComputerBtn) {
    vsComputerBtn.addEventListener("click", () => {
      gameMode = "computer";
      game.reset();
      if (board) board.start();
      updateStatus();
      showGameScreen();
    });
  }

  // landing: start human local
  const humanLocalBtn = document.getElementById("startHumanLocal");
  if (humanLocalBtn) {
    humanLocalBtn.addEventListener("click", () => {
      gameMode = "human-local";
      game.reset();
      if (board) board.start();
      updateStatus();
      showGameScreen();
    });
  }

  // back button (game screen → landing)
  const backBtn = document.getElementById("backBtn");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      showLandingScreen();
    });
  }

  // game controls
  const confirmBtn = document.getElementById("confirmMove");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      if (!pending) return;
      hideChip();

      try {
        const res = await postJSON(API.makeMove, {
          fen: fen(),
          uci: pending.uci,
        });

        game.load(res.fen);
        if (board) board.position(res.fen);
        pending = null;
        updateStatus();

        if (!game.game_over() && gameMode === "computer") {
          await playEngineMoveIfNeeded();
        }
      } catch (e) {
        console.error(e);
        pending = null;
      }
    });
  }

  const cancelBtn = document.getElementById("cancelMove");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      pending = null;
      hideChip();
    });
  }

  const resetBtn = document.getElementById("resetBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      game.reset();
      if (board) board.start();
      updateStatus();
      hideChip();
    });
  }

  const revealBtn = document.getElementById("revealBtn");
  if (revealBtn) {
    revealBtn.addEventListener("click", async () => {
      try {
        const url = `${API.bestMove}?fen=${encodeURIComponent(
          fen()
        )}&depth=${bestMoveDepth()}`;
        const res = await fetch(url);
        const data = await res.json();
        const bestSan = data.bestSan;
        alert(
          bestSan ? `Engine suggests: ${bestSan}` : "No suggestion available."
        );
      } catch (e) {
        console.error(e);
        alert("Error getting best move.");
      }
    });
  }
});
