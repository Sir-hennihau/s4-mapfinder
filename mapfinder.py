"""Settlers 4 (History Edition) random-map finder.

Runs the game's own map generator (emulated from S4_Main.exe) over many seeds,
keeps the maps where *every* player gets enough mountain and building space,
and writes an HTML gallery with in-game-like previews.

    python mapfinder.py                      # 3v3 defaults, scan 3000 seeds, show best 20
    python mapfinder.py --scan 10000 --maps 15
    python mapfinder.py --keys LSGUKDC0 LSG2H840   # just evaluate/render given keys
"""
import argparse, html, json, os, random, sys, time
from multiprocessing import Pool, cpu_count

import numpy as np

import analyze
import s4key

G = None


def _init():
    global G
    from s4gen import S4Generator
    G = S4Generator(heap_mb=64)


def _params(key):
    g = G
    g.reset()
    out = g.alloc(0xB8); g.uc.mem_write(out, b"\0" * 0xB8)
    k = g.alloc(64); g.uc.mem_write(k, (key + "\0").encode("utf-16-le"))
    g.call(0x50ADA0, ecx=out, edx=k)  # the game's own key decoder
    return bytes(g.uc.mem_read(out, 0xB8))


def stage1(key):
    try:
        G.setup(_params(key))
        starts = analyze.player_starts(G)
        pv = np.frombuffer(G.preview(), "<u2").reshape(160, 160)
        per = analyze.evaluate_preview(pv, starts, mirror=s4key.decode(key)["mirror"])
        return key, analyze.score(per), per
    except Exception as e:  # never let one odd seed kill the scan
        return key, -1.0, str(e)


def stage2(job):
    key, img_dir = job
    try:
        G.setup(_params(key))
        starts = analyze.player_starts(G)
        ok, size, la, lb = G.generate()
        A = np.frombuffer(la, np.uint8).reshape(size, size, 4)
        B = np.frombuffer(lb, np.uint8).reshape(size, size, 4)
        per = analyze.evaluate_tiles(A, B, starts, mirror=s4key.decode(key)["mirror"])
        analyze.render(A, B, starts).save(os.path.join(img_dir, key + ".png"))
        return key, analyze.score_tiles(per), per, starts
    except Exception as e:
        return key, -1.0, str(e), []


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, obj):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)


def rank_key(score, per):
    # many good maps hit the 100 cap: break ties by the weakest player's mountain + space
    tie = min(p["mtn"] for p in per) / 9000 + min(p["space"] for p in per) / 40000
    return (-score, -tie)


def run_pool(fn, jobs, workers, label):
    out, t0 = [], time.time()
    with Pool(workers, initializer=_init) as p:
        for i, r in enumerate(p.imap_unordered(fn, jobs, chunksize=1 if fn is stage2 else 4), 1):
            out.append(r)
            if i % max(1, len(jobs) // 50) == 0 or i == len(jobs):
                el = time.time() - t0
                sys.stdout.write(f"\r{label}: {i}/{len(jobs)}  {el:5.0f}s  eta {el / i * (len(jobs) - i):5.0f}s ")
                sys.stdout.flush()
    print()
    return out


CSS = """
:root{--bg:#15171a;--card:#1f2226;--fg:#e8e6e1;--mut:#9aa0a6;--acc:#e0b04a;--bad:#e06a5a;--ok:#7fc06a}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{padding:18px 20px 8px}h1{margin:0;font-size:22px}header p{margin:4px 0;color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:16px;padding:16px 20px}
.card{background:var(--card);border-radius:10px;overflow:hidden}
.card img{width:100%;display:block;background:#111}
.meta{padding:10px 14px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.rank{color:var(--mut)}.key{font:600 20px ui-monospace,Consolas,monospace;letter-spacing:1px;cursor:pointer}
.key:hover{color:var(--acc)}.score{margin-left:auto;font-weight:600;color:var(--acc)}
table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12.5px}
th,td{padding:2px 6px;text-align:right}th{color:var(--mut);font-weight:500}td:first-child,th:first-child{text-align:left}
td.lo{color:var(--bad)}tr.t1 td:first-child{color:#ff7b7b}tr.t2 td:first-child{color:#7fa8ff}
.legend{color:var(--mut);font-size:12px}.chip{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 3px 0 10px;vertical-align:-1px}
"""


def write_html(path, rows, settings, note):
    def table(per):
        cols = [("space", "Space"), ("mtn", "Mountain"), ("mtn_near", "Mtn ≤150"), ("fields", "Mtn fields"),
                ("coal", "Coal"), ("iron", "Iron"), ("gold", "Gold"), ("sulfur", "Sulfur")]
        mins = {k: min(p[k] for p in per) for k, _ in cols}
        maxs = {k: max(p[k] for p in per) for k, _ in cols}
        h = "<tr><th>Player</th>" + "".join(f"<th>{t}</th>" for _, t in cols) + "</tr>"
        half = len(per) // 2
        for i, p in enumerate(per):
            tds = "".join(
                f"<td class='{'lo' if p[k] == mins[k] and maxs[k] > 1.6 * max(mins[k], 1) else ''}'>{p[k]:,}</td>"
                for k, _ in cols)
            h += f"<tr class='t{1 + (i >= half)}'><td>P{i + 1}</td>{tds}</tr>"
        return "<table>" + h + "</table>"

    cards = []
    for rank, (key, sc, per, starts) in enumerate(rows, 1):
        cards.append(f"""<div class="card"><img loading="lazy" src="img/{key}.png" alt="{key}">
<div class="meta"><div class="top"><span class="rank">#{rank}</span>
<span class="key" title="click to copy" onclick="navigator.clipboard.writeText('{key}');this.style.color='#7fc06a'">{key}</span>
<span class="rank">seed {s4key.decode(key)['seed']}</span><span class="score">{sc:.1f}</span></div>{table(per)}</div></div>""")
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>S4 Map Finder</title><style>{CSS}</style></head><body><header><h1>Settlers 4 random maps</h1>
<p>{html.escape(settings)}</p><p>{html.escape(note)}</p>
<p class="legend">Space = buildable grass tiles in the player's own area (closest to them by land, ≤200 tiles).
Mountain = mountain tiles in that area; Mtn ≤150 = within 150 tiles of the castle; Mtn fields = separate mountain patches on that side.
Ore = mineable tiles. Red values = clearly the weakest player.
<span class="chip" style="background:#282828"></span>coal<span class="chip" style="background:#be5a3c"></span>iron
<span class="chip" style="background:#fad228"></span>gold<span class="chip" style="background:#e6e65a"></span>sulfur
— red discs P1–P3, blue discs P4–P6 (mirror sides). Click a key to copy it.</p></header>
<div class="grid">{''.join(cards)}</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=int, default=20, help="how many maps to show (default 20)")
    ap.add_argument("--scan", type=int, default=3000, help="seeds to pre-screen (default 3000)")
    ap.add_argument("--deep", type=int, default=0, help="maps to fully generate (default 2.5x --maps)")
    ap.add_argument("--players", type=int, default=6)
    ap.add_argument("--size", type=int, default=1024, choices=[256 + 64 * i for i in range(13)])
    ap.add_argument("--land", type=int, default=90, help="land mass %% (10..100)")
    ap.add_argument("--minerals", type=int, default=15, help="5 small, 10 medium, 15 large")
    ap.add_argument("--mirror", type=int, default=1, help="0 none, 1 short diagonal, 2 long diagonal, 3 both")
    ap.add_argument("--keys", nargs="*", help="evaluate these keys instead of scanning")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--out", default="results")
    ap.add_argument("--rng", type=int, default=None, help="seed for picking which map seeds to scan")
    ap.add_argument("--reshow", action="store_true", help="also show maps from earlier runs (best overall)")
    a = ap.parse_args()

    img_dir = os.path.join(a.out, "img"); os.makedirs(img_dir, exist_ok=True)
    settings = (f"{a.players} players, {a.size}x{a.size}, land {a.land}%, minerals "
                f"{ {5: 'small', 10: 'medium', 15: 'large'}.get(a.minerals, a.minerals)}, mirror {s4key.MIRRORS[a.mirror]}")
    t0 = time.time()
    tag = f"{a.players}_{a.size}_{a.land}_{a.minerals}_{a.mirror}"
    if a.keys:
        res = run_pool(stage2, [(k.upper(), img_dir) for k in a.keys], a.workers, "full generate")
        for r in res:
            if r[1] < 0:
                print("failed:", r[0], r[2])
        rows = sorted([r for r in res if r[1] >= 0], key=lambda r: rank_key(r[1], r[2]))
        note = "Evaluated the given keys."
    else:
        cache = load_json(os.path.join(a.out, f"scan_{tag}.json"), {})
        deep_cache = load_json(os.path.join(a.out, f"deep_{tag}.json"), {})
        shown_path = os.path.join(a.out, f"shown_{tag}.json")
        shown = set(load_json(shown_path, []))
        if a.reshow:
            shown = set()
        rnd = random.Random(a.rng)
        todo = set()
        while len(todo) < a.scan:
            k = s4key.encode(rnd.randrange(1_000_000), a.players, a.size, a.land, a.minerals, a.mirror)
            if k not in cache:
                todo.add(k)
        print(f"{settings}\npre-screening {len(todo)} new seeds ({len(cache)} cached, "
              f"{len(shown)} already shown) on {a.workers} workers")
        for k, sc, per in run_pool(stage1, sorted(todo), a.workers, "pre-screen"):
            cache[k] = sc
        save_json(os.path.join(a.out, f"scan_{tag}.json"), cache)
        # fully generate the best pre-screened seeds that were never shown or generated before
        n_deep = a.deep or int(a.maps * 2.5)
        fresh = [k for k, _ in sorted(cache.items(), key=lambda kv: -kv[1])
                 if k not in shown and k not in deep_cache][:n_deep]
        for k, sc, per, st in run_pool(stage2, [(k, img_dir) for k in fresh], a.workers, "full generate"):
            if sc < 0:
                print("failed:", k, per)
            else:
                deep_cache[k] = dict(score=sc, players=per, starts=st)
        save_json(os.path.join(a.out, f"deep_{tag}.json"), deep_cache)
        # leftovers from earlier runs that were generated but not shown stay in the pool
        rows = sorted([(k, d["score"], d["players"], d["starts"]) for k, d in deep_cache.items()
                       if k not in shown and os.path.exists(os.path.join(img_dir, k + ".png"))],
                      key=lambda r: rank_key(r[1], r[2]))[:a.maps]
        if not a.reshow:
            save_json(shown_path, sorted(shown | {r[0] for r in rows}))
        note = (f"{len(rows)} maps you have not been shown before. Pool: {len(cache)} pre-screened seeds, "
                f"{len(deep_cache)} fully generated. Older runs: run_*.html in this folder.")
    with open(os.path.join(a.out, "results.json"), "w") as f:
        json.dump([dict(key=k, score=s, players=p, starts=st) for k, s, p, st in rows], f, indent=1)
    page = os.path.join(a.out, "index.html")
    write_html(page, rows, settings, note)
    if not a.keys:
        write_html(os.path.join(a.out, time.strftime("run_%Y%m%d_%H%M%S.html")), rows, settings, note)
    print(f"done in {time.time() - t0:.0f}s -> {os.path.abspath(page)}")
    for k, s, p, _ in rows:
        print(f"  {k}  {s:5.1f}  min mountain {min(x['mtn'] for x in p):6,}  min space {min(x['space'] for x in p):6,}")


if __name__ == "__main__":
    main()
