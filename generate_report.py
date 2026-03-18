"""
generate_report.py
Reads backend/logs/games.jsonl and generates a rich HTML report (report.html).
"""

import json
import os
from collections import defaultdict

LOG_FILE    = os.path.join("backend", "logs", "games.jsonl")
OUTPUT_FILE = "report.html"

BUCKET_ORDER  = ["Hot", "Warm", "Cool", "Cold", "Freezing"]
BUCKET_COLORS = {
    "Hot":      "#22c55e",
    "Warm":     "#86efac",
    "Cool":     "#fbbf24",
    "Cold":     "#f97316",
    "Freezing": "#ef4444",
}
GOOD = {"Hot", "Warm"}
BAD  = {"Cool", "Cold", "Freezing"}

RATING_LABELS = [
    (1800, "Advanced"),
    (1600, "Strong Club Player"),
    (1400, "Club Player"),
    (1200, "Casual Player"),
    (1000, "Beginner+"),
    (0,    "Beginner"),
]


def rating_label(rating):
    for threshold, label in RATING_LABELS:
        if rating >= threshold:
            return label
    return "Beginner"


def load_games():
    games = []
    if not os.path.exists(LOG_FILE):
        raise FileNotFoundError(f"Log file not found: {LOG_FILE}")
    with open(LOG_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    games.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return games


def user_stats(games):
    users = defaultdict(list)
    for g in games:
        users[g.get("clientId", "unknown")].append(g)

    result = {}
    for cid, gs in sorted(users.items(), key=lambda x: x[0]):
        # Pull real name / rating from first game that has them
        name   = next((g.get("userName",   cid)  for g in gs if g.get("userName")), cid)
        rating = next((g.get("userRating", 0)     for g in gs if g.get("userRating")), 0)

        wins = draws = losses = 0
        for g in gs:
            r = g.get("result", "")
            if r == "1-0":        wins   += 1
            elif r == "0-1":      losses += 1
            elif r == "1/2-1/2":  draws  += 1

        per_game       = []
        bucket_totals  = defaultdict(int)
        total_moves = total_good = total_bad = 0
        delta_cps   = []

        for idx, g in enumerate(gs, start=1):
            moves = g.get("moves", [])
            good = bad = 0
            g_buckets = defaultdict(int)
            g_deltas  = []
            for m in moves:
                b = m.get("bucket")
                d = m.get("deltaCp")
                if b in GOOD: good += 1
                elif b in BAD: bad += 1
                if b:
                    g_buckets[b] += 1
                    bucket_totals[b] += 1
                if d is not None:
                    g_deltas.append(d)
                    delta_cps.append(d)

            total_moves += len(moves)
            total_good  += good
            total_bad   += bad
            avg_delta = round(sum(g_deltas)/len(g_deltas), 1) if g_deltas else 0

            per_game.append({
                "game_num":  idx,
                "result":    g.get("result", "?"),
                "moves":     len(moves),
                "good":      good,
                "bad":       bad,
                "good_pct":  round(good/len(moves)*100, 1) if moves else 0,
                "avg_delta": avg_delta,
                "buckets":   dict(g_buckets),
            })

        avg_cp = round(sum(delta_cps)/len(delta_cps), 1) if delta_cps else 0
        result[cid] = {
            "name":   name,
            "rating": rating,
            "games":  per_game,
            "wins":   wins, "draws": draws, "losses": losses,
            "total_moves": total_moves,
            "good_pct": round(total_good/total_moves*100, 1) if total_moves else 0,
            "bad_pct":  round(total_bad /total_moves*100, 1) if total_moves else 0,
            "avg_cp":   avg_cp,
            "bucket_totals": dict(bucket_totals),
        }
    return result


def jsl(lst):
    return json.dumps(lst)


def build_html(users):
    # Sort by rating descending for display
    user_ids = sorted(users.keys(), key=lambda u: users[u]["rating"], reverse=True)

    display_labels = jsl([f"{users[u]['name']} ({users[u]['rating']})" for u in user_ids])
    short_labels   = jsl([users[u]["name"].split()[0] for u in user_ids])
    lb_good   = jsl([users[u]["good_pct"] for u in user_ids])
    lb_bad    = jsl([users[u]["bad_pct"]  for u in user_ids])
    lb_wins   = jsl([users[u]["wins"]     for u in user_ids])
    lb_draws  = jsl([users[u]["draws"]    for u in user_ids])
    lb_losses = jsl([users[u]["losses"]   for u in user_ids])
    lb_avgcp  = jsl([users[u]["avg_cp"]   for u in user_ids])
    lb_ratings= jsl([users[u]["rating"]   for u in user_ids])

    # Bucket stacked datasets
    all_bucket_data = {b: [] for b in BUCKET_ORDER}
    for uid in user_ids:
        bt    = users[uid]["bucket_totals"]
        total = sum(bt.values()) or 1
        for bk in BUCKET_ORDER:
            all_bucket_data[bk].append(round(bt.get(bk, 0)/total*100, 1))

    bucket_datasets_js = "[" + ",".join(
        f"{{label:{json.dumps(bk)},data:{jsl(all_bucket_data[bk])},"
        f"backgroundColor:{json.dumps(BUCKET_COLORS[bk])}}}"
        for bk in BUCKET_ORDER
    ) + "]"

    # Per-user progress cards
    cards_html   = ""
    cards_scripts = ""
    for i, uid in enumerate(user_ids):
        u  = users[uid]
        gd = u["games"]
        cid = f"prog_{i}"

        game_labels = jsl([f"G{g['game_num']}" for g in gd])
        good_series = jsl([g["good_pct"]  for g in gd])
        delta_series= jsl([g["avg_delta"] for g in gd])

        result_tags = " ".join(
            f'<span class="result-badge r-{g["result"].replace("/","-").replace("-","_")}">{g["result"]}</span>'
            for g in gd
        )

        cards_html += f"""
        <div class="user-card">
          <div class="user-card-header">
            <div>
              <div class="user-name">{u['name']}</div>
              <div class="user-meta">{uid} &nbsp;·&nbsp; Rating: <strong>{u['rating']}</strong> &nbsp;·&nbsp; {rating_label(u['rating'])}</div>
            </div>
            <div class="wdl-row">
              <span class="wdl w">{u['wins']}W</span>
              <span class="wdl d">{u['draws']}D</span>
              <span class="wdl l">{u['losses']}L</span>
              <span class="wdl cp">Avg Δ {u['avg_cp']} cp</span>
            </div>
          </div>
          <div class="results-row">{result_tags}</div>
          <canvas id="{cid}" height="90"></canvas>
        </div>"""

        cards_scripts += f"""
        new Chart(document.getElementById('{cid}'), {{
          type:'line',
          data:{{
            labels:{game_labels},
            datasets:[
              {{label:'Good %',data:{good_series},borderColor:'#22c55e',backgroundColor:'rgba(34,197,94,0.12)',tension:0.4,fill:true,pointRadius:4,pointBackgroundColor:'#22c55e'}},
              {{label:'Avg Δcp',data:{delta_series},borderColor:'#f97316',backgroundColor:'rgba(249,115,22,0.08)',tension:0.4,fill:false,pointRadius:4,pointBackgroundColor:'#f97316',yAxisID:'y2'}}
            ]
          }},
          options:{{
            plugins:{{legend:{{labels:{{color:'#cdd6f4',font:{{size:11}}}}}}}},
            scales:{{
              x:{{ticks:{{color:'#cdd6f4'}},grid:{{color:'rgba(205,214,244,0.08)'}}}},
              y:{{ticks:{{color:'#22c55e',callback:v=>v+'%'}},grid:{{color:'rgba(205,214,244,0.08)'}},title:{{display:true,text:'Good %',color:'#22c55e'}}}},
              y2:{{position:'right',ticks:{{color:'#f97316',callback:v=>v+' cp'}},grid:{{display:false}},title:{{display:true,text:'Avg Δcp',color:'#f97316'}}}}
            }}
          }}
        }});"""

    total_moves = sum(users[u]["total_moves"] for u in user_ids)
    total_wins  = sum(users[u]["wins"]   for u in user_ids)
    total_losses= sum(users[u]["losses"] for u in user_ids)
    total_draws = sum(users[u]["draws"]  for u in user_ids)

    leaderboard_rows = "".join(
        f'<tr>'
        f'<td class="rank-num">{i+1}</td>'
        f'<td><div class="lb-name">{users[u]["name"]}</div><div class="lb-email">{u}</div></td>'
        f'<td style="color:#89b4fa;font-weight:600">{users[u]["rating"]}</td>'
        f'<td style="color:#a6e3a1">{rating_label(users[u]["rating"])}</td>'
        f'<td style="color:#22c55e;font-weight:600">{users[u]["wins"]}</td>'
        f'<td style="color:#fbbf24">{users[u]["draws"]}</td>'
        f'<td style="color:#ef4444">{users[u]["losses"]}</td>'
        f'<td style="color:#22c55e">{users[u]["good_pct"]}%</td>'
        f'<td style="color:#f97316">{users[u]["bad_pct"]}%</td>'
        f'<td style="color:#cba6f7">{users[u]["avg_cp"]} cp</td>'
        f'</tr>'
        for i, u in enumerate(user_ids)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Chess AI – User Performance Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#1e1e2e;--surface:#24243e;--card:#313244;--border:#45475a;
  --text:#cdd6f4;--muted:#6c7086;
  --green:#22c55e;--orange:#f97316;--red:#ef4444;--yellow:#fbbf24;
  --blue:#89b4fa;--pink:#f38ba8;--accent:#cba6f7;
}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}

.hero{{
  background:linear-gradient(135deg,#1e1e2e 0%,#2d1b69 50%,#1e1e2e 100%);
  padding:56px 40px 44px;text-align:center;border-bottom:1px solid var(--border);
}}
.hero h1{{
  font-size:2.4rem;font-weight:700;
  background:linear-gradient(90deg,var(--blue),var(--accent));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:10px;
}}
.hero p{{color:var(--muted);font-size:1rem}}

.stats-row{{
  display:flex;flex-wrap:wrap;gap:18px;justify-content:center;padding:28px 40px;
}}
.stat-pill{{
  background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:16px 28px;text-align:center;min-width:120px;
}}
.stat-pill .val{{font-size:1.9rem;font-weight:700;color:var(--accent)}}
.stat-pill .lbl{{font-size:.78rem;color:var(--muted);margin-top:4px}}

.section{{padding:28px 40px;max-width:1400px;margin:0 auto}}
.section-title{{
  font-size:1.2rem;font-weight:600;color:var(--text);
  margin-bottom:22px;display:flex;align-items:center;gap:10px;
}}
.section-title::before{{
  content:'';display:block;width:4px;height:20px;
  background:var(--accent);border-radius:4px;
}}
.chart-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:16px;padding:26px;margin-bottom:26px;
}}
.chart-card h3{{
  font-size:.85rem;font-weight:600;color:var(--muted);
  margin-bottom:16px;letter-spacing:.05em;text-transform:uppercase;
}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}

.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}}
th{{
  text-align:left;padding:11px 13px;border-bottom:1px solid var(--border);
  color:var(--muted);font-weight:500;text-transform:uppercase;
  font-size:.75rem;letter-spacing:.06em;
}}
td{{padding:11px 13px;border-bottom:1px solid rgba(69,71,90,.4)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:rgba(137,180,250,.04)}}
.rank-num{{color:var(--accent);font-weight:700}}
.lb-name{{font-weight:600}}
.lb-email{{font-size:.75rem;color:var(--muted);margin-top:2px}}

.user-grid{{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:22px;
}}
.user-card{{
  background:var(--card);border:1px solid var(--border);
  border-radius:16px;padding:20px;
}}
.user-card-header{{
  display:flex;justify-content:space-between;align-items:flex-start;
  margin-bottom:10px;
}}
.user-name{{font-size:1rem;font-weight:600}}
.user-meta{{font-size:.75rem;color:var(--muted);margin-top:3px}}
.wdl-row{{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}}
.wdl{{font-size:.78rem;font-weight:600;padding:3px 9px;border-radius:20px}}
.wdl.w{{background:rgba(34,197,94,.15);color:var(--green)}}
.wdl.d{{background:rgba(251,191,36,.15);color:var(--yellow)}}
.wdl.l{{background:rgba(239,68,68,.15);color:var(--red)}}
.wdl.cp{{background:rgba(203,166,247,.1);color:var(--accent)}}
.results-row{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}}
.result-badge{{
  font-size:.72rem;font-weight:600;padding:2px 9px;
  border-radius:20px;border:1px solid;
}}
.r-1_0{{color:#22c55e;border-color:#22c55e55;background:rgba(34,197,94,.1)}}
.r-0_1{{color:#ef4444;border-color:#ef444455;background:rgba(239,68,68,.1)}}
.r-1_2_1_2{{color:#fbbf24;border-color:#fbbf2455;background:rgba(251,191,36,.1)}}

footer{{
  text-align:center;padding:28px;color:var(--muted);
  font-size:.82rem;border-top:1px solid var(--border);margin-top:28px;
}}

@media(max-width:720px){{
  .two-col{{grid-template-columns:1fr}}
  .hero h1{{font-size:1.7rem}}
  .section,.stats-row{{padding:18px 14px}}
}}
</style>
</head>
<body>

<div class="hero">
  <h1>♟ Chess AI – User Performance Report</h1>
  <p>15 users &nbsp;·&nbsp; 15 games each &nbsp;·&nbsp; Powered by Stockfish analysis</p>
</div>

<div class="stats-row">
  <div class="stat-pill"><div class="val">15</div><div class="lbl">Users</div></div>
  <div class="stat-pill"><div class="val">{len(user_ids)*15}</div><div class="lbl">Games Played</div></div>
  <div class="stat-pill"><div class="val">{total_moves:,}</div><div class="lbl">Total Moves</div></div>
  <div class="stat-pill"><div class="val">{total_wins}</div><div class="lbl">White Wins</div></div>
  <div class="stat-pill"><div class="val">{total_losses}</div><div class="lbl">Black Wins</div></div>
  <div class="stat-pill"><div class="val">{total_draws}</div><div class="lbl">Draws</div></div>
</div>

<div class="section">
  <div class="section-title">Overall Performance</div>
  <div class="two-col">
    <div class="chart-card">
      <h3>Good vs. Bad Move % (sorted by rating)</h3>
      <canvas id="goodBadBar" height="230"></canvas>
    </div>
    <div class="chart-card">
      <h3>Win / Draw / Loss per User</h3>
      <canvas id="wdlBar" height="230"></canvas>
    </div>
  </div>
  <div class="two-col">
    <div class="chart-card">
      <h3>Move Quality Distribution (stacked %)</h3>
      <canvas id="bucketStacked" height="230"></canvas>
    </div>
    <div class="chart-card">
      <h3>Average Centipawn Loss vs Rating</h3>
      <canvas id="cpScatter" height="230"></canvas>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">Leaderboard</div>
  <div class="chart-card">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th><th>User</th><th>Rating</th><th>Level</th>
            <th>W</th><th>D</th><th>L</th>
            <th>Good %</th><th>Bad %</th><th>Avg Δcp</th>
          </tr>
        </thead>
        <tbody>{leaderboard_rows}</tbody>
      </table>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">Per-User Game Progression</div>
  <div class="user-grid">{cards_html}</div>
</div>

<footer>Generated 2026-03-18 &nbsp;·&nbsp; Human-AI Chess &nbsp;·&nbsp; Stockfish Analysis</footer>

<script>
const gc = c => 'rgba(205,214,244,0.08)';

// Good vs Bad Bar
new Chart(document.getElementById('goodBadBar'),{{
  type:'bar',
  data:{{
    labels:{short_labels},
    datasets:[
      {{label:'Good %',data:{lb_good},backgroundColor:'rgba(34,197,94,0.7)',borderRadius:5}},
      {{label:'Bad %', data:{lb_bad}, backgroundColor:'rgba(239,68,68,0.6)', borderRadius:5}}
    ]
  }},
  options:{{
    plugins:{{legend:{{labels:{{color:'#cdd6f4',font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#cdd6f4',maxRotation:35,font:{{size:10}}}},grid:{{color:gc()}}}},
      y:{{ticks:{{color:'#cdd6f4',callback:v=>v+'%'}},grid:{{color:gc()}}}}
    }}
  }}
}});

// WDL Bar
new Chart(document.getElementById('wdlBar'),{{
  type:'bar',
  data:{{
    labels:{short_labels},
    datasets:[
      {{label:'Wins',  data:{lb_wins},  backgroundColor:'rgba(34,197,94,0.75)', borderRadius:5}},
      {{label:'Draws', data:{lb_draws}, backgroundColor:'rgba(251,191,36,0.75)',borderRadius:5}},
      {{label:'Losses',data:{lb_losses},backgroundColor:'rgba(239,68,68,0.65)', borderRadius:5}}
    ]
  }},
  options:{{
    plugins:{{legend:{{labels:{{color:'#cdd6f4',font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#cdd6f4',maxRotation:35,font:{{size:10}}}},grid:{{color:gc()}}}},
      y:{{ticks:{{color:'#cdd6f4'}},grid:{{color:gc()}}}}
    }}
  }}
}});

// Stacked bucket bar
new Chart(document.getElementById('bucketStacked'),{{
  type:'bar',
  data:{{labels:{short_labels},datasets:{bucket_datasets_js}}},
  options:{{
    plugins:{{legend:{{labels:{{color:'#cdd6f4',font:{{size:11}}}}}}}},
    scales:{{
      x:{{stacked:true,ticks:{{color:'#cdd6f4',maxRotation:35,font:{{size:10}}}},grid:{{color:gc()}}}},
      y:{{stacked:true,ticks:{{color:'#cdd6f4',callback:v=>v+'%'}},grid:{{color:gc()}}}}
    }}
  }}
}});

// Scatter: rating vs avg cp loss
new Chart(document.getElementById('cpScatter'),{{
  type:'scatter',
  data:{{
    datasets:[{{
      label:'Avg Δcp vs Rating',
      data: {jsl([{"x": users[u]["rating"], "y": users[u]["avg_cp"]} for u in user_ids])},
      backgroundColor:'rgba(137,180,250,0.85)',
      pointRadius:7,pointHoverRadius:9
    }}]
  }},
  options:{{
    plugins:{{legend:{{labels:{{color:'#cdd6f4',font:{{size:11}}}}}}}},
    scales:{{
      x:{{
        title:{{display:true,text:'Rating',color:'#cdd6f4'}},
        ticks:{{color:'#cdd6f4'}},grid:{{color:gc()}}
      }},
      y:{{
        title:{{display:true,text:'Avg Δcp',color:'#cdd6f4'}},
        ticks:{{color:'#cdd6f4',callback:v=>v+' cp'}},grid:{{color:gc()}}
      }}
    }}
  }}
}});

// Per-user progress charts
{cards_scripts}
</script>
</body>
</html>"""
    return html


def main():
    print(f"Loading games from {LOG_FILE}…")
    games = load_games()
    print(f"  {len(games)} games loaded.")
    users = user_stats(games)
    print(f"  {len(users)} unique users found.")
    html = build_html(users)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\n✅  Report saved → {OUTPUT_FILE}")
    print(f"   Open: file://{os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    main()
