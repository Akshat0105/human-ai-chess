import os
import atexit
import subprocess

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import chess
import chess.engine

# ---------------- CONFIG ----------------

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH") or "/opt/homebrew/bin/stockfish"
STOCKFISH_THREADS = int(os.getenv("STOCKFISH_THREADS", "2"))

app = Flask(__name__, static_url_path="", static_folder="static")
CORS(app)

_engine = None  # global engine instance


# ---------------- ENGINE MANAGEMENT ----------------

def get_engine() -> chess.engine.SimpleEngine:
    """Start Stockfish once and reuse it."""
    global _engine
    if _engine is None:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        engine.configure({"Threads": STOCKFISH_THREADS})
        _engine = engine
    return _engine


@atexit.register
def shutdown_engine():
    """Make sure the engine is shut down when the server stops."""
    global _engine
    if _engine:
        try:
            _engine.quit()
        except Exception:
            pass


def cp_from(info: chess.engine.InfoDict, pov: chess.Color) -> int:
    """Return score in centipawns from pov (mate scaled to big cp)."""
    s = info["score"].pov(pov)
    return s.score(mate_score=100000)


def material_score(board: chess.Board, color: chess.Color) -> int:
    """Very simple material score (only pieces, no pawn structure)."""
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    score = 0
    for ptype, val in values.items():
        score += len(board.pieces(ptype, color)) * val
    return score


def explain_move(board_before: chess.Board,
                 board_after: chess.Board,
                 move: chess.Move,
                 delta_cp: int,
                 bucket: str) -> str:
    """
    Simple heuristic explanation for why a move is good/bad.
    Not a full chess coach, but enough for a student prototype.
    """
    color = board_before.turn
    opp = not color

    mat_before = material_score(board_before, color) - material_score(board_before, opp)
    mat_after = material_score(board_after, color) - material_score(board_after, opp)
    mat_delta = mat_after - mat_before

    # Big material loss
    if mat_delta <= -200:
        return "This move loses material compared to the best continuation."

    # Large eval drop = likely tactic or serious strategic error
    if delta_cp <= -300:
        return "This move allows the opponent strong tactical or positional chances."

    # Very rough king-safety heuristic
    king_sq = board_before.king(color)
    if king_sq is not None:
        piece = board_before.piece_at(move.from_square)
        if piece and piece.piece_type == chess.PAWN:
            if abs(chess.square_file(move.from_square) - chess.square_file(king_sq)) <= 1:
                if delta_cp < 0:
                    return "This move weakens your king's pawn shelter and safety."

    if bucket == "Hot":
        return "This move keeps the position close to the best engine line."
    if bucket in ("Warm", "Cool"):
        return "This move is playable, but there was a more accurate continuation."
    if bucket in ("Cold", "Freezing"):
        return "The engine prefers a different plan here; this move worsens your position."

    return "The engine evaluation drops after this move compared to the best line."


def quantise_delta(delta_cp: int, step: int = 50) -> int:
    """
    Snap a centipawn difference to the nearest 'step' (e.g. 50 cp).
    This makes borderline moves less likely to flip bucket due to noise.
    """
    return int(round(delta_cp / step)) * step


# ---------------- STATIC / ROOT ROUTES ----------------

@app.route("/")
def root():
    """Serve main SPA page."""
    return send_from_directory("static", "index.html")


@app.route("/img/<path:filename>")
def serve_images(filename):
    """Serve piece images and other assets from static/img."""
    return send_from_directory("static/img", filename)


@app.route("/favicon.ico")
def favicon():
    """Serve favicon if present."""
    return send_from_directory("static", "favicon.ico")


# ---------------- API ROUTES ----------------

@app.post("/api/eval-move")
def eval_move():
    """
    Evaluate a candidate move:
      - compares best engine move vs user's move
      - returns bucket (Hot/Warm/Cool/Cold/Freezing)
      - quantised deltaCp (user - best)
      - userCp, bestCp
      - short natural language reason
    """
    data = request.get_json(force=True)
    fen = data["fen"]
    uci = data["uci"]
    depth = int(data.get("depth", 12))

    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)

    if move not in board.legal_moves:
        return jsonify({"error": "Illegal move"}), 400

    eng = get_engine()

    # eval best move from current position (before user move)
    info_best = eng.analyse(board, chess.engine.Limit(depth=depth))
    best_cp = cp_from(info_best, board.turn)

    # eval position after user's move
    board_after = board.copy()
    board_after.push(move)
    info_user = eng.analyse(board_after, chess.engine.Limit(depth=depth))
    user_cp = cp_from(info_user, not board_after.turn)

    delta_raw = user_cp - best_cp
    delta = quantise_delta(delta_raw, step=50)  # snap to nearest 50 cp

    # smoother, slightly wider buckets
    if delta >= -50:
        bucket = "Hot"
    elif delta >= -150:
        bucket = "Warm"
    elif delta >= -300:
        bucket = "Cool"
    elif delta >= -600:
        bucket = "Cold"
    else:
        bucket = "Freezing"

    label_map = {
        "Hot": "Looks optimal",
        "Warm": "Playable but not perfect",
        "Cool": "Inaccuracy",
        "Cold": "Clear mistake",
        "Freezing": "Tactical blunder",
    }
    label = label_map[bucket]

    reason = explain_move(board, board_after, move, delta, bucket)

    return jsonify(
        {
            "bucket": bucket,
            "deltaCp": int(delta),         # quantised
            "message": label,
            "userCp": int(user_cp),
            "bestCp": int(best_cp),
            "reason": reason,
        }
    )


@app.post("/api/make-move")
def make_move():
    """
    Commit a move on the board and return the new FEN and game state.
    """
    data = request.get_json(force=True)
    fen = data["fen"]
    uci = data["uci"]

    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)

    if move not in board.legal_moves:
        return jsonify({"error": "Illegal move"}), 400

    board.push(move)

    return jsonify(
        {
            "fen": board.fen(),
            "turn": "white" if board.turn else "black",
            "isGameOver": board.is_game_over(),
            "result": board.result() if board.is_game_over() else None,
        }
    )


@app.get("/api/best-move")
def best_move():
    """
    Return the engine's suggested best move in SAN for a given FEN.
    Also expose mate distance if the engine sees a forced mate.
    """
    fen = request.args.get("fen")
    if not fen:
        return jsonify({"error": "Missing 'fen' parameter"}), 400

    depth = int(request.args.get("depth", 20))

    board = chess.Board(fen)
    eng = get_engine()
    info = eng.analyse(board, chess.engine.Limit(depth=depth))

    pv = info.get("pv", [])
    san = board.san(pv[0]) if pv else None

    score = info["score"].pov(board.turn)
    mate_in = score.mate()  # plies to mate; positive if side to move mates

    return jsonify(
        {
            "bestSan": san,
            "mateIn": mate_in,
        }
    )


# ---------------- STOCKFISH TEST + MAIN ----------------

def test_stockfish_once():
    print("Testing Stockfish...")
    try:
        result = subprocess.run(
            [STOCKFISH_PATH],
            input="uci\nquit\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print("Stockfish found!")
        else:
            print("Stockfish exited with non-zero status:", result.returncode)
    except Exception as e:
        print("Stockfish NOT found:", e)


if __name__ == "__main__":
    test_stockfish_once()
    app.run(debug=True)
