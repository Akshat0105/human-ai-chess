const API = {
  evalMove: '/api/eval-move',
  makeMove: '/api/make-move',
  bestMove: '/api/best-move'
};

const game = new Chess();
let board;
let pending = null; // { from, to, uci, eval }

function fen() { return game.fen(); }

function statusText() {
  if (game.in_checkmate()) return 'Checkmate';
  if (game.in_draw()) return 'Draw';
  const turn = game.turn() === 'w' ? 'White' : 'Black';
  return `${turn} to move${game.in_check() ? ' (check)' : ''}`;
}
function updateStatus() {
  document.getElementById('status').textContent = statusText();
}

function chipClassFor(bucket) {
  switch ((bucket || '').toLowerCase()) {
    case 'hot': return 'hot';
    case 'warm': return 'warm';
    case 'cool': return 'cool';
    case 'cold': return 'cold';
    case 'freezing': return 'freezing';
    default: return '';
  }
}
function showChip(bucket, message) {
  const chip = document.getElementById('hotcold');
  chip.className = `chip ${chipClassFor(bucket)}`;
  document.getElementById('hcLabel').textContent = bucket;
  document.getElementById('hcDetail').textContent = message ? (' — ' + message) : '';
  chip.classList.remove('hidden');
}
function hideChip() {
  const chip = document.getElementById('hotcold');
  chip.classList.add('hidden');
  chip.className = 'chip';
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

/* ---------- DRAG / DROP ---------- */
const onDragStart = (source, piece) => {
  if (game.game_over()) return false;
  if ((game.turn() === 'w' && piece.startsWith('b')) ||
      (game.turn() === 'b' && piece.startsWith('w'))) return false;
};

async function onDrop(source, target) {
  hideChip();

  // 1. Detect if promotion is needed
  const piece = game.get(source);
  const needsPromotion = piece && piece.type === 'p' &&
    (target[1] === (piece.color === 'w' ? '8' : '1'));

  const promotion = needsPromotion ? 'q' : undefined;   // always queen for now

  // 2. Try the move
  const move = game.move({ from: source, to: target, promotion });
  if (!move) return 'snapback';

  // 3. Build UCI string (includes promotion if any)
  const uci = move.from + move.to + (move.promotion || '');

  // 4. Undo – we only evaluate, we do NOT commit yet
  game.undo();

  try {
    const subtle = document.getElementById('subtleMode').checked;
    const evalRes = await postJSON(API.evalMove, { fen: fen(), uci, depth: 12 });
    pending = { from: source, to: target, uci, eval: evalRes };

    const label = subtle
      ? evalRes.message
      : `${evalRes.message} (Δ ${evalRes.deltaCp} cp)`;
    showChip(evalRes.bucket, label);
  } catch (e) {
    console.error(e);
    alert('Evaluation failed – check Stockfish path.');
  }

  return 'snapback';   // always snap back until the user clicks “Play move”
}

const onSnapEnd = () => board.position(game.fen());

/* ---------- UI BUTTONS ---------- */
document.getElementById('confirmMove').addEventListener('click', async () => {
  if (!pending) return;
  hideChip();
  try {
    const res = await postJSON(API.makeMove, { fen: fen(), uci: pending.uci });
    game.load(res.fen);
    board.position(res.fen);
    updateStatus();
  } catch (e) { console.error(e); }
  pending = null;
});

document.getElementById('cancelMove').addEventListener('click', () => {
  pending = null;
  hideChip();
});

document.getElementById('resetBtn').addEventListener('click', () => {
  game.reset();
  board.start();
  updateStatus();
  hideChip();
});

document.getElementById('revealBtn').addEventListener('click', async () => {
  try {
    const url = `${API.bestMove}?fen=${encodeURIComponent(fen())}&depth=18`;
    const { bestSan } = await (await fetch(url)).json();
    alert(bestSan ? `Engine suggests: ${bestSan}` : 'No suggestion available.');
  } catch (e) {
    alert('Error getting best move.');
  }
});

/* ---------- BOARD INITIALISATION ---------- */
function init() {
  const boardEl = document.getElementById('board');
  if (!boardEl) return console.error('Missing #board element');

  board = Chessboard(boardEl, {
    draggable: true,
    position: 'start',
    pieceTheme: '/static/img/chesspieces/maestro/{piece}.svg',


    onDragStart,
    onDrop,
    onSnapEnd
  });

  updateStatus();
  hideChip();
}
window.addEventListener('load', init);