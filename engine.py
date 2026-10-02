"""Search engine shared by the GUI: keeps scanning seeds until enough good maps are found."""
import hashlib, json, os, random, threading, time
from multiprocessing import Pool

import numpy as np

import analyze
import s4key

SUPPORTED_MD5 = "153c49ab29946c21d50a3ae7a95c5cf8"
SCORE_VERSION = 2         # bump when scoring changes: older results get regenerated
DEFAULT_GAME_DIRS = [
    r"D:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\thesettlers4",
    r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\thesettlers4",
    r"C:\Program Files\Ubisoft\Ubisoft Game Launcher\games\thesettlers4",
]
PRE_TOP_FRACTION = 0.03   # fully generate seeds whose pre-screen is in the top 3 % seen so far
BATCH = 480               # seeds per pre-screen batch


def find_game_dir():
    dirs = list(DEFAULT_GAME_DIRS)
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"SOFTWARE\WOW6432Node\Ubisoft\Launcher", r"SOFTWARE\Ubisoft\Launcher"):
                try:
                    with winreg.OpenKey(root, sub) as k:
                        d = winreg.QueryValueEx(k, "InstallDir")[0]
                        dirs.insert(0, os.path.join(d, "games", "thesettlers4"))
                except OSError:
                    pass
    except ImportError:
        pass
    for d in dirs:
        if os.path.isfile(os.path.join(d, "S4_Main.exe")):
            return d
    return ""


def check_game_dir(d):
    """-> (ok, message)"""
    exe = os.path.join(d, "S4_Main.exe")
    if not os.path.isfile(exe):
        return False, "S4_Main.exe not found in this folder"
    h = hashlib.md5()
    with open(exe, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != SUPPORTED_MD5:
        return False, "Unsupported S4_Main.exe version (needs the History Edition build this tool was made for)"
    return True, "Settlers 4 History Edition found"


# ------------------------------------------------------------------ worker side
G = None
INIT_ERROR = None


def _init(exe):
    # never raise here: a failing initializer makes Pool respawn workers forever
    global G, INIT_ERROR
    if os.environ.get("S4MF_TRACE"):  # --selftest: dump worker stacks periodically
        import faulthandler
        f = open(os.path.join(os.environ["S4MF_TRACE"], f"worker_{os.getpid()}.txt"), "w")
        faulthandler.enable(file=f)
        faulthandler.dump_traceback_later(20, repeat=True, file=f)
    try:
        from s4gen import S4Generator
        G = S4Generator(exe=exe, heap_mb=64)
    except Exception as e:
        INIT_ERROR = f"{type(e).__name__}: {e}"


def _params(key):
    g = G
    g.reset()
    out = g.alloc(0xB8); g.uc.mem_write(out, b"\0" * 0xB8)
    k = g.alloc(64); g.uc.mem_write(k, (key + "\0").encode("utf-16-le"))
    g.call(0x50ADA0, ecx=out, edx=k)  # the game's own key decoder
    return bytes(g.uc.mem_read(out, 0xB8))


def stage1(job):
    key, params = job
    if G is None:
        return key, -1.0, INIT_ERROR
    try:
        d = s4key.decode(key)
        P = analyze.params_of(params)
        G.setup(_params(key))
        starts = analyze.player_starts(G)
        pv = np.frombuffer(G.preview(), "<u2").reshape(160, 160)
        sc = d["size"] / 1024
        per = analyze.evaluate_preview(pv, starts, size=d["size"], radius_tiles=P["radius"] * sc,
                                       mirror=d["mirror"], near_tiles=P["near"] * sc)
        return key, analyze.score(per, d["players"], P), None
    except Exception as e:
        return key, -1.0, f"{type(e).__name__}: {e}"


def stage2(job):
    key, img_dir, params = job
    if G is None:
        return key, -1.0, INIT_ERROR, []
    try:
        d = s4key.decode(key)
        P = analyze.params_of(params)
        G.setup(_params(key))
        starts = analyze.player_starts(G)
        ok, size, la, lb = G.generate()
        A = np.frombuffer(la, np.uint8).reshape(size, size, 4)
        B = np.frombuffer(lb, np.uint8).reshape(size, size, 4)
        per = analyze.evaluate_tiles(A, B, starts, radius=int(P["radius"] * size / 1024),
                                     near=int(P["near"] * size / 1024),
                                     mirror=d["mirror"])
        for ores, suffix in ((False, ""), (True, "_ores")):  # in-game style (no mines) + with mines
            analyze.render(A, B, starts, scale=1024 / size, ores=ores).save(os.path.join(img_dir, key + suffix + ".png"))
        return key, analyze.score_tiles(per, size, d["players"], P), per, [list(s) for s in starts]
    except Exception as e:
        return key, -1.0, str(e), []


def rank_key(score, per, size=1024, players=6, params=None):
    P = analyze.params_of(params)
    f = analyze.area_factor(size, players)
    tie = min(p["mtn"] for p in per) / (P["t_mtn"] * f) + min(p["space"] for p in per) / (P["t_space"] * f)
    return (-score, -tie)


def rescore(key, per, params=None):
    """Score stored metrics again with other targets/weights (no generation needed)."""
    d = s4key.decode(key)
    return analyze.score_tiles(per, d["size"], d["players"], params)


def geo(params):
    P = analyze.params_of(params)
    return {k: P[k] for k in analyze.GEO_KEYS}


def _tag(params, keys):
    """'' for default values, else a short hash, so each parameter set gets its own cache file."""
    P = analyze.params_of(params)
    if all(P[k] == analyze.DEFAULT_PARAMS[k] for k in keys):
        return ""
    return "_" + hashlib.md5(json.dumps([P[k] for k in keys]).encode()).hexdigest()[:8]


# ------------------------------------------------------------------ persistent store
def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)


class Store:
    """Everything known for one combination of lobby settings."""

    def __init__(self, root, players, size, land, minerals, mirror, params=None):
        self.settings = dict(players=players, size=size, land=land, minerals=minerals, mirror=mirror)
        self.params = analyze.params_of(params)
        self.geo = geo(self.params)
        self.dir = self.dir_for(root, players, size, land, minerals, mirror)
        self.img = os.path.join(self.dir, "img")
        os.makedirs(self.img, exist_ok=True)
        # pre-screen scores depend on the pre-screen parameters, per-player metrics on the radii (images don't)
        self.scan_file = os.path.join(self.dir, f"scan_v{SCORE_VERSION}{_tag(self.params, analyze.PREVIEW_KEYS)}.json")
        self.deep_file = os.path.join(self.dir, f"deep{_tag(self.params, analyze.GEO_KEYS)}.json")
        self._scan = None                       # key -> pre-screen score (loaded when a search needs it)
        self.deep = _load(self.deep_file, {})   # key -> {score, players, starts, v, geo}
        self.shown = set(_load(os.path.join(self.dir, "shown.json"), []))
        self.lock = threading.Lock()

    @staticmethod
    def dir_for(root, players, size, land, minerals, mirror):
        return os.path.join(root, f"{players}p_{size}_land{land}_min{minerals}_mirror{mirror}")

    @property
    def scan(self):
        if self._scan is None:
            self._scan = _load(self.scan_file, {})
        return self._scan

    def key(self, seed):
        return s4key.encode(seed, **self.settings)

    def image(self, key, ores=False):
        return os.path.join(self.img, key + ("_ores" if ores else "") + ".png")

    def current(self, key):
        d = self.deep.get(key)
        return (d is not None and d.get("v") == SCORE_VERSION and d.get("geo", self.geo) == self.geo
                and os.path.exists(self.image(key)))

    def entry(self, key, score, per, starts):
        return dict(score=score, players=per, starts=starts, v=SCORE_VERSION, geo=self.geo)

    def save(self):
        with self.lock:
            if self._scan is not None:
                _save(self.scan_file, self._scan)
            _save(self.deep_file, self.deep)
            _save(os.path.join(self.dir, "shown.json"), sorted(self.shown))

    def found(self, min_score=0):
        """All fully generated maps (best first)."""
        s = self.settings
        rows = []
        for k, d in list(self.deep.items()):
            if self.current(k):
                r = dict(d, key=k, score=rescore(k, d["players"], self.params))  # current targets/weights
                if r["score"] >= min_score:
                    rows.append(r)
        rows.sort(key=lambda r: rank_key(r["score"], r["players"], s["size"], s["players"], self.params))
        return rows


def _results(pool, fn, jobs, stop_event, ahead=64):
    """Run fn over jobs on the pool, yielding results as they finish (any order).

    Keeps at most `ahead` jobs queued so a stop takes effect quickly, and polls
    stop_event instead of blocking on a result. (Pool.imap_unordered's iterator
    lost its .next(timeout) in Python 3.14, so we use apply_async.)
    """
    jobs = list(jobs)
    pending = []
    while (jobs or pending) and not stop_event.is_set():
        while jobs and len(pending) < ahead:
            pending.append(pool.apply_async(fn, (jobs.pop(0),)))
        done = [r for r in pending if r.ready()]
        if not done:
            pending[0].wait(0.2)
            continue
        for r in done:
            pending.remove(r)
            yield r.get()


class Search(threading.Thread):
    """Scans fresh seeds until `want` unseen maps with score >= min_score are found.

    Events put on `events` (a queue.Queue):
      ("progress", dict)   counters for the status line
      ("found", row)       a new map (row = dict key/score/players/starts)
      ("done", reason)
    """

    def __init__(self, exe, store, want, min_score, workers, events):
        super().__init__(daemon=True)
        self.exe, self.store, self.want, self.min_score = exe, store, want, min_score
        self.workers, self.events = workers, events
        self.stop_event = threading.Event()
        self.n_found = 0
        self._ok = 0
        self.stats = dict(scanned=0, generated=0, found=0, want=want, phase="starting", t0=time.time())

    def stop(self):
        self.stop_event.set()

    def _progress(self, **kw):
        self.stats.update(kw)
        self.events.put(("progress", dict(self.stats)))

    def _emit(self, key, d):
        st = self.store
        st.shown.add(key)
        self.n_found += 1
        self.events.put(("found", dict(key=key, **d)))
        self._progress(found=self.n_found)

    def run(self):
        st = self.store
        reason = "done"
        try:
            # 1. good maps generated earlier but never shown
            for r in st.found(self.min_score):
                if self.n_found >= self.want:
                    break
                if r["key"] not in st.shown:
                    self._emit(r["key"], {k: v for k, v in r.items() if k != "key"})
            if self.n_found >= self.want:
                return
            self._progress(phase="starting workers")
            with Pool(self.workers, initializer=_init, initargs=(self.exe,)) as pool:
                rnd = random.Random()
                while self.n_found < self.want and not self.stop_event.is_set():
                    if len(st.scan) >= 990_000:
                        reason = "all seeds for these settings were checked"
                        break
                    # 2. pre-screen a batch of fresh seeds
                    batch = set()
                    while len(batch) < BATCH:
                        k = st.key(rnd.randrange(1_000_000))
                        if k not in st.scan:
                            batch.add(k)
                    self._progress(phase="checking seeds")
                    errors = []
                    for k, sc, err in _results(pool, stage1, [(k, st.params) for k in sorted(batch)],
                                                  self.stop_event):
                        if err:
                            errors.append(err)
                            if self._ok == 0 and len(errors) >= 8:  # nothing ever worked: give up loudly
                                raise RuntimeError(f"the map generator failed: {err}")
                            continue
                        self._ok += 1
                        with st.lock:
                            st.scan[k] = sc
                        self.stats["scanned"] += 1
                        if self.stats["scanned"] % 16 == 0:
                            self._progress()
                        if self.stop_event.is_set():
                            break
                    if self.stop_event.is_set():
                        break
                    # 3. fully generate the promising ones
                    vals = np.array([v for v in st.scan.values() if v >= 0])
                    cut = np.quantile(vals, 1 - PRE_TOP_FRACTION) if len(vals) >= 200 else np.inf
                    if len(vals) < 200:  # tiny history: just take this batch's best
                        cut = np.quantile([st.scan[k] for k in batch], 1 - PRE_TOP_FRACTION)
                    cand = [k for k in st.scan if st.scan[k] >= cut and not st.current(k) and k not in st.shown]
                    cand.sort(key=lambda k: -st.scan[k])
                    if not cand:
                        continue
                    self._progress(phase=f"generating {len(cand)} promising maps")
                    for k, sc, per, starts in _results(pool, stage2, [(k, st.img, st.params) for k in cand],
                                                       self.stop_event, ahead=self.workers):
                        self.stats["generated"] += 1
                        if sc >= 0:
                            d = st.entry(k, sc, per, starts)
                            with st.lock:
                                st.deep[k] = d
                            if sc >= self.min_score and self.n_found < self.want and k not in st.shown:
                                self._emit(k, d)
                        self._progress()
                        if self.stop_event.is_set() or self.n_found >= self.want:
                            break
                    st.save()
                if self.stop_event.is_set():
                    reason = "stopped"
                pool.terminate()
        except Exception as e:  # report instead of dying silently
            reason = f"error: {e}"
        finally:
            st.save()
            self._progress(phase=reason)
            self.events.put(("done", reason))


class KeyCheck(threading.Thread):
    """Fully generate + score one key (e.g. typed in by the user)."""

    def __init__(self, exe, store, key, events):
        super().__init__(daemon=True)
        self.exe, self.store, self.key, self.events = exe, store, key, events

    def run(self):
        try:
            with Pool(1, initializer=_init, initargs=(self.exe,)) as pool:
                k, sc, per, starts = pool.apply(stage2, ((self.key, self.store.img, self.store.params),))
            if sc < 0:
                self.events.put(("checked", dict(key=self.key, error=per)))
                return
            d = self.store.entry(k, sc, per, starts)
            with self.store.lock:
                self.store.deep[k] = d
            self.store.save()
            self.events.put(("checked", dict(key=k, **d)))
        except Exception as e:
            self.events.put(("checked", dict(key=self.key, error=str(e))))
