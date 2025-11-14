import os
import atexit
import subprocess

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import chess
import chess.engine


# Basic config
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH") or "/opt/homebrew/bin/stockfish"
THREADS = int(os.getenv("STOCKFISH_THREADS", 2))

app = Flask(__name__, static_url_path="", static_folder="static")
CORS(app)

_engine = None


# ---- Engine Handling ----

def get_engine():
    """Start Stockfish once and reuse it."""
    global _engine
    if _engine is None:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        engine.configure({"Threads": THREADS})
        _engine = engine
    return _engine


@atexit.register
def shutdown_engine():
    """Make sure the engine is shut down when the server stops."""
    global _engine
    if _engine:
        try:
            _engine.quit()
        except:
            pass


def score_cp(info, pov):
    """Convert python-chess Score object to a centipawn number."""
    s = info["score"].pov(pov)
    return s.score(mate_score=100000)


# ---- Static + Root ----

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/img/<path:f>")
def serve_img(f):
    return send_from_directory("static/img", f)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon.ico")


# ---- API ----

@app.post("/api/eval-move")
def api_eval_move():
    data = request.get_json(force=True)
    fen = data["fen"]
    uci = data["uci"]
    depth = int(data.get("depth", 12))

    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)

    if move not in board.legal_moves:
        return jsonify({"error": "Illegal move"}), 400

    engine = get_engine()

    # Eval before move
    info_best = engine.analyse(board, chess.engine.Limit(depth=depth))
    best_cp = score_cp(info_best, board.turn)

    # Eval after user move
    b2 = board.copy()
    b2.push(move)
    info_user = engine.analyse(b2, chess.engine.Limit(depth=depth))
    user_cp = score_cp(info_user, not b2.turn)

    delta = user_cp - best_cp

    if delta >= -20:
        bucket = "Hot"
    elif delta >= -100:
        bucket = "Warm"
    elif delta >= -250:
        bucket = "Cool"
    elif delta >= -500:
        bucket = "Cold"
    else:
        bucket = "Freezing"

    labels = {
        "Hot": "Looks optimal",
        "Warm": "Playable but not perfect",
        "Cool": "Inaccuracy",
        "Cold": "Clear mistake",
        "Freezing": "Tactical blunder"
    }

    return jsonify({
        "bucket": bucket,
        "deltaCp": int(delta),
        "message": labels[bucket]
    })


@app.post("/api/make-move")
def api_make_move():
    data = request.get_json(force=True)
    fen = data["fen"]
    uci = data["uci"]

    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)

    if move not in board.legal_moves:
        return jsonify({"error": "Illegal move"}), 400

    board.push(move)

    return jsonify({
        "fen": board.fen(),
        "turn": "white" if board.turn else "black",
        "isGameOver": board.is_game_over(),
        "result": board.result() if board.is_game_over() else None
    })


@app.get("/api/best-move")
def api_best_move():
    fen = request.args.get("fen")
    if not fen:
        return jsonify({"error": "Missing FEN"}), 400

    depth = int(request.args.get("depth", 18))

    board = chess.Board(fen)
    engine = get_engine()

    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    pv = info.get("pv", [])
    san = board.san(pv[0]) if pv else None

    return jsonify({"bestSan": san})


# ---- Startup ----

def test_stockfish():
    print("Testing Stockfish...")
    try:
        subprocess.run(
            [STOCKFISH_PATH],
            input="uci\nquit\n",
            capture_output=True,
            text=True,
            timeout=5
        )
        print("Stockfish found!")
    except Exception as e:
        print("Stockfish NOT found:", e)


if __name__ == "__main__":
    test_stockfish()
    app.run(debug=True)
