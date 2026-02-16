import os
import atexit
import subprocess
import json
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import chess
import chess.engine

from models import db, User, Game

# ---------------- CONFIG ----------------

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH") or "/opt/homebrew/bin/stockfish"
STOCKFISH_THREADS = int(os.getenv("STOCKFISH_THREADS", "2"))

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "games.jsonl")

app = Flask(__name__, static_url_path="", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# Database config
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///chess.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

CORS(app, supports_credentials=True)

# Create tables on first run (skip if they already exist)
with app.app_context():
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db.engine)
    existing = inspector.get_table_names()
    if not existing:
        db.create_all()

_engine = None  # global engine instance


# ---------------- LOGIN MANAGER ----------------

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Not authenticated"}), 401


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


# ---------------- AUTH ROUTES ----------------

@app.post("/api/signup")
def signup():
    """Create a new user account with email and password."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({"error": "An account with this email already exists"}), 409

    pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    user = User(email=email, password_hash=pw_hash)
    db.session.add(user)
    db.session.commit()

    login_user(user, remember=True)
    return jsonify({"user": user.to_dict()}), 201


@app.post("/api/login")
def login():
    """Authenticate with email and password."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(user, remember=True)
    return jsonify({"user": user.to_dict()})


@app.post("/api/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    return jsonify({"status": "ok"})


@app.get("/api/me")
def me():
    """Return current user info if logged in."""
    if current_user.is_authenticated:
        return jsonify({"user": current_user.to_dict()})
    return jsonify({"user": None})


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


@app.post("/api/log-game")
def log_game():
    """
    Append one completed game log to a JSONL file.
    If user is logged in, also save to database.

    Expected payload:
    {
      clientId: str,
      startedAt: str,
      endedAt: str,
      mode: 'computer' | 'human-local',
      difficulty: str,
      result: '1-0' | '0-1' | '1/2-1/2' | None,
      moves: [ { moveNumber, color, san, bucket, deltaCp, userCp, bestCp } ]
    }
    """
    data = request.get_json(force=True)
    data["serverReceivedAt"] = datetime.utcnow().isoformat() + "Z"

    # Always write to JSONL log (backward compat)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        return jsonify({"error": f"Failed to write log: {e}"}), 500

    # If user is logged in, also save to database
    if current_user.is_authenticated:
        game_record = Game(
            user_id=current_user.id,
            started_at=data.get("startedAt"),
            ended_at=data.get("endedAt"),
            mode=data.get("mode"),
            difficulty=data.get("difficulty"),
            result=data.get("result"),
            moves=json.dumps(data.get("moves", [])),
        )
        db.session.add(game_record)
        db.session.commit()

    return jsonify({"status": "ok"})


# ---------------- GAME HISTORY ROUTES ----------------

@app.get("/api/my-games")
@login_required
def my_games():
    """Return list of the current user's past games (summary)."""
    games = (
        Game.query
        .filter_by(user_id=current_user.id)
        .order_by(Game.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"games": [g.to_summary() for g in games]})


@app.get("/api/game/<int:game_id>")
@login_required
def get_game(game_id):
    """Return full detail for a single game (must belong to current user)."""
    game_record = Game.query.filter_by(id=game_id, user_id=current_user.id).first()
    if not game_record:
        return jsonify({"error": "Game not found"}), 404
    return jsonify({"game": game_record.to_detail()})


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
