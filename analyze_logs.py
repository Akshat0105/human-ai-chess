import argparse
import json
import os
from datetime import datetime
from statistics import mean

LOG_FILE = os.path.join("logs", "games.jsonl")

GOOD_BUCKETS = {"Hot", "Warm"}
BAD_BUCKETS = {"Cool", "Cold", "Freezing"}


def load_logs(path: str):
    games = []
    if not os.path.exists(path):
        print(f"No log file found at {path}")
        return games

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                games.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return games


def game_metrics(game):
    """
    Compute simple quality metrics for one game.
    Returns dict with: moves, good_ratio, bad_ratio, good_count, bad_count.
    """
    moves = game.get("moves", [])
    if not moves:
        return None

    good = 0
    bad = 0
    for m in moves:
        b = m.get("bucket")
        if b in GOOD_BUCKETS:
            good += 1
        elif b in BAD_BUCKETS:
            bad += 1

    total = len(moves)
    if total == 0:
        return None

    return {
      "moves": total,
      "good_ratio": good / total,
      "bad_ratio": bad / total,
      "good_count": good,
      "bad_count": bad,
    }


def short_time(ts: str):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def print_client_overview(games, difficulty=None, mode=None):
    """
    When no client-id is passed, show how many games each client has,
    filtered by difficulty / mode.
    """
    per_client = {}

    for g in games:
        if difficulty and g.get("difficulty") != difficulty:
            continue
        if mode and g.get("mode") != mode:
            continue

        cid = g.get("clientId", "UNKNOWN")
        per_client.setdefault(cid, 0)
        per_client[cid] += 1

    if not per_client:
        print("No games matched the filters yet.")
        return

    print("Clients found in log (with given filters):")
    for cid, n in per_client.items():
        print(f"  {cid}: {n} games")
    print()
    print("Run again with for example:")
    print("  python analyze_logs.py --client-id <one-of-these> --difficulty medium")
    print()


def analyze_for_client(games, client_id, difficulty=None, mode="computer"):
    # Filter by client, difficulty, and mode
    filtered = []
    for g in games:
        if g.get("clientId") != client_id:
            continue
        if difficulty and g.get("difficulty") != difficulty:
            continue
        if mode and g.get("mode") != mode:
            continue
        filtered.append(g)

    if not filtered:
        print("No games found for that filter.")
        return

    # Sort chronologically by startedAt
    filtered.sort(key=lambda g: g.get("startedAt", ""))

    print(f"Client:     {client_id}")
    print(f"Mode:       {mode}")
    print(f"Difficulty: {'any' if not difficulty else difficulty}")
    print(f"Games:      {len(filtered)}")
    print()

    per_game = []
    for idx, g in enumerate(filtered, start=1):
        metrics = game_metrics(g)
        if not metrics:
            continue
        per_game.append(metrics)
        started = short_time(g.get("startedAt", ""))
        result = g.get("result") or "-"
        print(
            f"Game {idx:2d} | {started} | result {result:7s} | "
            f"moves {metrics['moves']:3d} | "
            f"good {metrics['good_ratio']*100:5.1f}% | "
            f"bad {metrics['bad_ratio']*100:5.1f}%"
        )

    if not per_game:
        print("No per-move data available.")
        return

    print("\n--- Trend summary (first half vs last half) ---")

    n = len(per_game)
    split = max(1, n // 2)     # first half vs second half of *actual* games

    early = per_game[:split]
    late = per_game[split:]

    def avg(field, games_list):
        return mean(g[field] for g in games_list) if games_list else 0.0

    early_good = avg("good_ratio", early)
    late_good = avg("good_ratio", late)
    early_bad = avg("bad_ratio", early)
    late_bad = avg("bad_ratio", late)

    print(f"Early games (first {len(early)}):")
    print(f"  Avg good moves: {early_good*100:5.1f}%")
    print(f"  Avg bad moves : {early_bad*100:5.1f}%")
    print()
    print(f"Late games (last {len(late)}):")
    print(f"  Avg good moves: {late_good*100:5.1f}%")
    print(f"  Avg bad moves : {late_bad*100:5.1f}%")
    print()

    delta_good = (late_good - early_good) * 100
    delta_bad = (late_bad - early_bad) * 100

    print("Change over time:")
    print(f"  Good move rate  : {'+' if delta_good >= 0 else ''}{delta_good:5.1f} percentage points")
    print(f"  Bad move rate   : {'+' if delta_bad >= 0 else ''}{delta_bad:5.1f} percentage points")
    print()
    print("If good moves went up and bad moves went down,")
    print("that suggests the player improved at this difficulty.\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze Chess AI Support game logs.")
    parser.add_argument("--client-id", help="Filter by clientId")
    parser.add_argument(
        "--difficulty",
        help="Filter by difficulty (easy/medium/hard)",
        default=None,
    )
    parser.add_argument(
        "--mode",
        help="Filter by mode (computer/human-local)",
        default="computer",
    )
    args = parser.parse_args()

    games = load_logs(LOG_FILE)
    if not games:
        return

    # If client-id not passed, overview of players
    if not args.client_id:
        print_client_overview(games, difficulty=args.difficulty, mode=args.mode)
        return

    analyze_for_client(
        games,
        client_id=args.client_id,
        difficulty=args.difficulty,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
