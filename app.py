import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import chess
import chess.engine
import subprocess

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH") or "/opt/homebrew/bin/stockfish"

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)

 
@app.route('/img/<path:filename>')
def serve_images(filename):
    return send_from_directory('static/img', filename)

_engine = None
def get_engine():
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        _engine.configure({"Threads": 2})
    return _engine

@app.route('/')
def root():
    return send_from_directory('static', 'index.html')



def cp_from(info, pov):
  s = info['score'].pov(pov)
  return s.score(mate_score=100000)

@app.post('/api/eval-move')
def eval_move():
  data = request.get_json(force=True)
  fen = data['fen']; uci = data['uci']
  depth = int(data.get('depth', 12))
  board = chess.Board(fen)
  move = chess.Move.from_uci(uci)
  if move not in board.legal_moves:
    return jsonify({'error':'Illegal move'}), 400

  eng = get_engine()
  info_best = eng.analyse(board, chess.engine.Limit(depth=depth))
  best_cp = cp_from(info_best, board.turn)

  board2 = board.copy()
  board2.push(move)
  info_user = eng.analyse(board2, chess.engine.Limit(depth=depth))
  user_cp = cp_from(info_user, not board2.turn)

  delta = user_cp - best_cp
  if delta >= -20: bucket = 'Hot'
  elif delta >= -100: bucket = 'Warm'
  elif delta >= -250: bucket = 'Cool'
  elif delta >= -500: bucket = 'Cold'
  else: bucket = 'Freezing'

  label = {
    "Hot": "Looks optimal",
    "Warm": "Playable but not perfect",
    "Cool": "Inaccuracy",
    "Cold": "Clear mistake",
    "Freezing": "Tactical blunder"
  }[bucket]

  return jsonify({'bucket': bucket, 'deltaCp': int(delta), 'message': label})

@app.post('/api/make-move')
def make_move():
  data = request.get_json(force=True)
  board = chess.Board(data['fen'])
  move = chess.Move.from_uci(data['uci'])
  if move not in board.legal_moves:
    return jsonify({'error':'Illegal move'}), 400
  board.push(move)
  return jsonify({'fen': board.fen(), 'turn': 'white' if board.turn else 'black',
                  'isGameOver': board.is_game_over(),
                  'result': board.result() if board.is_game_over() else None})

@app.get('/api/best-move')
def best_move():
  fen = request.args.get('fen'); depth = int(request.args.get('depth', 18))
  board = chess.Board(fen)
  eng = get_engine()
  info = eng.analyse(board, chess.engine.Limit(depth=depth))
  pv = info.get('pv', [])
  san = board.san(pv[0]) if pv else None
  return jsonify({'bestSan': san})

if __name__ == '__main__':
  app.run(debug=True)
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')  # Add a file or use a placeholder

print("Testing Stockfish...")
try:
    result = subprocess.run([STOCKFISH_PATH], input="uci\nquit\n", capture_output=True, text=True, timeout=5)
    print("Stockfish found!")
except Exception as e:
    print("Stockfish NOT found:", e)