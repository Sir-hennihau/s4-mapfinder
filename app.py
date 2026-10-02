"""S4 Map Finder — desktop UI."""
import json, multiprocessing, os, queue, sys, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

import analyze
import engine
import s4key

APP = "S4 Map Finder"
HOME = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "S4MapFinder")
CONFIG = os.path.join(HOME, "config.json")
DATA = os.path.join(HOME, "maps")

SIZES = [str(256 + 64 * i) for i in range(13)]
LANDS = [f"{v}%" for v in range(10, 100, 10)]
MINERALS = {"Lower": 5, "Normal": 10, "Higher": 15}
MIRRORS = {"None": 0, "Short diagonal": 1, "Long diagonal": 2, "Short and long diagonals": 3}
MODES = {"preview": "Lobby preview", "full": "Full map"}
STAT_COLS = [("space", "Space"), ("space_near", "Space ≤{near}"), ("mtn", "Mountain"), ("mtn_near", "Mtn ≤{near}"),
             ("fields", "Fields"), ("snow", "Snow"), ("gold", "Gold"), ("coal", "Coal"), ("iron", "Iron"),
             ("stone", "Stone ore"), ("sulfur", "Sulfur"), ("stonefield", "Stones"), ("stonefield_near", "Stones ≤{near}"),
             ("river", "River"), ("river_near", "River ≤{near}")]
PREVIEW_COLS = ["space", "space_near", "mtn", "mtn_near", "fields"]  # all the lobby preview shows
# score lines on the Scoring tab: (line, label, spinbox increment for the target)
SCORE_ROWS = [("mtn", "Mountain", 500), ("mtn_near", "Mountain, close", 500), ("space", "Space", 1000),
              ("space_near", "Space, close", 1000), ("fair_mtn", "Mountain fairness", 0.05),
              ("fair_space", "Space fairness", 0.05),
              ("gold", "Gold", 25), ("coal", "Coal", 50), ("iron", "Iron", 50), ("stone", "Stone ore", 25),
              ("sulfur", "Sulfur", 25), ("stonefield", "Stone fields", 50), ("stonefield_near", "Stone fields, close", 25),
              ("river", "River", 10), ("river_near", "River, close", 10)]
LEGEND = {
    "preview": (
        "Lobby preview mode: maps are scored only from what the game's lobby preview shows (water, land, mountain), "
        "the way players have always judged a key. A player's area is their side of the mirror axis, shared with "
        "teammates by distance (each tile counts for one player), up to the wide radius. Space = buildable land, "
        "Mountain = mountain tiles, “≤ n” = only within n tiles of the castle, Fields = separate mountain patches "
        "(a shared patch counts once). Values are full-map tiles estimated from the preview. "
        "Red P1–P3 / blue P4–P6 are the two mirror sides."),
    "full": (
        "Full map mode: maps are generated completely and also scored on what the lobby preview hides. "
        "A player's area is their side of the mirror axis, shared with teammates by distance (each tile counts for "
        "one player), up to the wide radius. Space = buildable grass, Mountain = mountain tiles (snow weighted by the "
        "Scoring tab's snow factor, as it has no ore), Snow = snow tiles, “≤ n” = only within n tiles of the castle, "
        "Fields = separate mountain patches. Gold … Sulfur = tiles with that ore, Stones = stone tiles to quarry, "
        "River = river tiles. The picture looks like the lobby preview; “Show full details” adds rivers (light "
        "blue), stone fields (grey) and ore speckles on the mountains: dark = coal, red = iron, yellow = gold, "
        "pale yellow = sulfur, white = stone. Red P1–P3 / blue P4–P6 are the two mirror sides."),
}
THUMB = (210, 140)


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.events = queue.Queue()
        self.search = None
        self.store = None
        self.rows = []           # rows currently listed
        self.thumbs = {}         # (key, mode, details) -> PhotoImage (keep references!)
        self.cards = {}
        self.card_imgs = {}      # key -> thumbnail label of its card
        self._par_job = None
        self.selected = None
        self._big_src = None
        self.k = k = max(1.0, root.winfo_fpixels("1i") / 96)  # DPI scale
        self.thumb = (int(THUMB[0] * k), int(THUMB[1] * k))
        root.title(APP)
        if self.cfg.get("geometry"):
            root.geometry(self.cfg["geometry"])
        else:
            root.state("zoomed")
        root.minsize(int(1100 * k), int(680 * k))
        self._style()
        self._build()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._check_game(silent=True)
        self._load_list()

    # ------------------------------------------------------------------ layout
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure("Key.TLabel", font=("Consolas", 22, "bold"))
        st.configure("CardKey.TLabel", font=("Consolas", 13, "bold"))
        st.configure("Score.TLabel", font=("Segoe UI", 11, "bold"), foreground="#b07800")
        st.configure("Muted.TLabel", foreground="#666")
        st.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=6)
        st.configure("Treeview", rowheight=int(22 * self.k))

    def _build(self):
        r = self.root
        r.columnconfigure(1, weight=0); r.columnconfigure(2, weight=1); r.rowconfigure(0, weight=1)
        c = self.cfg

        # ---- left: settings
        side = ttk.Frame(r, padding=12); side.grid(row=0, column=0, sticky="ns")
        ttk.Label(side, text="Game folder").grid(row=0, column=0, columnspan=2, sticky="w")
        self.v_game = tk.StringVar(value=c.get("game_dir") or engine.find_game_dir())
        e = ttk.Entry(side, textvariable=self.v_game, width=34); e.grid(row=1, column=0, sticky="ew")
        ttk.Button(side, text="…", width=3, command=self._browse).grid(row=1, column=1, padx=(4, 0))
        self.l_game = ttk.Label(side, text="", wraplength=int(260 * self.k), style="Muted.TLabel")
        self.l_game.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 10))

        side.rowconfigure(3, weight=1)
        nb = ttk.Notebook(side); nb.grid(row=3, column=0, columnspan=2, sticky="nsew")
        tab = ttk.Frame(nb, padding=(6, 8, 6, 6)); nb.add(tab, text="Search")
        tab_sc = ttk.Frame(nb, padding=(6, 8, 6, 6)); nb.add(tab_sc, text="Scoring")
        tab.columnconfigure(0, weight=1)
        mo = ttk.LabelFrame(tab, text="Mode", padding=(10, 6, 10, 8))
        mo.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.v_mode = tk.StringVar(value=c.get("mode", "preview") if c.get("mode") in MODES else "preview")
        self.mode_btns = []
        for i, (m, t) in enumerate(MODES.items()):
            b = ttk.Radiobutton(mo, text=t, value=m, variable=self.v_mode, command=self._mode_changed)
            b.grid(row=0, column=i, sticky="w", padx=(0, 14)); self.mode_btns.append(b)
        self.l_mode = ttk.Label(mo, text="", style="Muted.TLabel", wraplength=int(250 * self.k), justify="left")
        self.l_mode.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        lob = ttk.LabelFrame(tab, text="Lobby settings", padding=10)
        lob.grid(row=1, column=0, sticky="ew")
        self.v_players = tk.StringVar(value=str(c.get("players", 6)))
        self.v_size = tk.StringVar(value=str(c.get("size", 1024)))
        self.v_land = tk.StringVar(value=f"{c.get('land', 90)}%")
        self.v_min = tk.StringVar(value=c.get("minerals_name", "Higher"))
        self.v_mirror = tk.StringVar(value=c.get("mirror_name", "Short diagonal"))
        rows = [("Players", ttk.Spinbox(lob, from_=2, to=8, textvariable=self.v_players, width=6)),
                ("Map size", ttk.Combobox(lob, values=SIZES, textvariable=self.v_size, state="readonly", width=12)),
                ("Land mass", ttk.Combobox(lob, values=LANDS, textvariable=self.v_land, state="readonly", width=12)),
                ("Minerals", ttk.Combobox(lob, values=list(MINERALS), textvariable=self.v_min, state="readonly", width=12)),
                ("Mirror axis", ttk.Combobox(lob, values=list(MIRRORS), textvariable=self.v_mirror, state="readonly", width=22))]
        for i, (t, w) in enumerate(rows):
            ttk.Label(lob, text=t).grid(row=i, column=0, sticky="w", pady=3)
            w.grid(row=i, column=1, sticky="w", padx=(8, 0), pady=3)
            if isinstance(w, ttk.Combobox):
                w.bind("<<ComboboxSelected>>", lambda e: self._load_list())
        self.v_players.trace_add("write", lambda *a: self.root.after(300, self._load_list))

        se = ttk.LabelFrame(tab, text="Search", padding=10)
        se.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.v_want = tk.StringVar(value=str(c.get("want", 20)))
        self.v_minscore = tk.StringVar(value=str(c.get("min_score", 95)))
        self.v_workers = tk.StringVar(value=str(c.get("workers", max(1, multiprocessing.cpu_count() - 1))))
        for i, (t, w, hint) in enumerate([
                ("Maps to find", ttk.Spinbox(se, from_=1, to=200, textvariable=self.v_want, width=6), ""),
                ("Minimum score", ttk.Spinbox(se, from_=50, to=100, increment=1, textvariable=self.v_minscore, width=6),
                 "0–100; 95+ = very good, 90 = good"),
                ("CPU cores", ttk.Spinbox(se, from_=1, to=multiprocessing.cpu_count(), textvariable=self.v_workers, width=6), "")]):
            ttk.Label(se, text=t).grid(row=2 * i, column=0, sticky="w", pady=(3, 0))
            w.grid(row=2 * i, column=1, sticky="w", padx=(8, 0), pady=(3, 0))
            if hint:
                ttk.Label(se, text=hint, style="Muted.TLabel").grid(row=2 * i + 1, column=0, columnspan=2, sticky="w")
        self._build_scoring(tab_sc)
        self.b_find = ttk.Button(side, text="Find new maps", style="Big.TButton", command=self._toggle_search)
        self.b_find.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.pbar = ttk.Progressbar(side, mode="determinate"); self.pbar.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.l_status = ttk.Label(side, text="", wraplength=int(270 * self.k), justify="left")
        self.l_status.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ck = ttk.LabelFrame(tab, text="Check a map key", padding=10)
        ck.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.v_key = tk.StringVar()
        ke = ttk.Entry(ck, textvariable=self.v_key, width=14, font=("Consolas", 11))
        ke.grid(row=0, column=0, sticky="w"); ke.bind("<Return>", lambda e: self._check_key())
        self.b_check = ttk.Button(ck, text="Check", command=self._check_key); self.b_check.grid(row=0, column=1, padx=(6, 0))
        self.l_check = ttk.Label(ck, text="Paste a key to preview and score it.", style="Muted.TLabel", wraplength=int(250 * self.k))
        self.l_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        bot = ttk.Frame(tab); bot.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(bot, text="Open data folder", command=lambda: os.startfile(self._store().dir)).pack(side="left")
        ttk.Button(bot, text="Forget seen maps", command=self._forget).pack(side="left", padx=(6, 0))

        # ---- middle: list of maps
        mid = ttk.Frame(r, padding=(0, 12, 0, 12)); mid.grid(row=0, column=1, sticky="ns")
        top = ttk.Frame(mid); top.pack(fill="x")
        self.v_view = tk.StringVar(value="new")
        ttk.Radiobutton(top, text="This search", value="new", variable=self.v_view, command=self._load_list).pack(side="left")
        ttk.Radiobutton(top, text="All found maps", value="all", variable=self.v_view, command=self._load_list).pack(side="left", padx=8)
        self.l_count = ttk.Label(top, text="", style="Muted.TLabel"); self.l_count.pack(side="right")
        wrap = ttk.Frame(mid); wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.lc = tk.Canvas(wrap, width=self.thumb[0] * 2 + int(40 * self.k), highlightthickness=0, bg="#f3f3f3")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.lc.yview)
        self.lc.configure(yscrollcommand=sb.set)
        self.lc.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.lf = tk.Frame(self.lc, bg="#f3f3f3")
        self.lc.create_window((0, 0), window=self.lf, anchor="nw")
        self.lf.bind("<Configure>", lambda e: self.lc.configure(scrollregion=self.lc.bbox("all")))
        self.lc.bind_all("<MouseWheel>", self._wheel)

        # ---- right: detail
        det = ttk.Frame(r, padding=12); det.grid(row=0, column=2, sticky="nsew")
        det.columnconfigure(0, weight=1); det.rowconfigure(2, weight=1)
        hdr = ttk.Frame(det); hdr.grid(row=0, column=0, sticky="ew")
        self.l_key = ttk.Label(hdr, text="", style="Key.TLabel"); self.l_key.pack(side="left")
        self.b_copy = ttk.Button(hdr, text="Copy key", style="Big.TButton", command=self._copy_selected, state="disabled")
        self.b_copy.pack(side="left", padx=12)
        self.l_score = ttk.Label(hdr, text="", style="Score.TLabel"); self.l_score.pack(side="left", padx=6)
        # like the lobby preview: rivers, stone fields and mines hidden unless asked for
        self.v_details = tk.BooleanVar(value=False)
        self.c_details = ttk.Checkbutton(hdr, text="Show full details", variable=self.v_details,
                                         command=self._toggle_details)
        self.c_details.pack(side="right")
        self.l_info = ttk.Label(det, text="", style="Muted.TLabel"); self.l_info.grid(row=1, column=0, sticky="w")
        self.big = tk.Label(det, bg="#121212", text="Press “Find new maps” to start.", fg="#aaa", font=("Segoe UI", 12))
        self.big.grid(row=2, column=0, sticky="nsew", pady=8)
        self.big.bind("<Configure>", lambda e: self._show_big())
        self.tree = ttk.Treeview(det, columns=[k for k, _ in STAT_COLS], height=8)
        self.tree.heading("#0", text="Player"); self.tree.column("#0", width=int(70 * self.k), anchor="w")
        for k, t in STAT_COLS:
            self.tree.column(k, width=int(68 * self.k), minwidth=int(52 * self.k), anchor="e", stretch=True)
        self._headings(analyze.DEFAULT_PARAMS["near"])
        self.tree.tag_configure("t1", foreground="#c62828"); self.tree.tag_configure("t2", foreground="#1e4fc4")
        self.tree.grid(row=3, column=0, sticky="ew")
        xs = ttk.Scrollbar(det, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=xs.set); xs.grid(row=4, column=0, sticky="ew")
        self.legend = legend = ttk.Label(det, style="Muted.TLabel", justify="left")
        legend.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        legend.bind("<Configure>", lambda e: legend.configure(wraplength=e.width - 8))
        self._mode_ui()

    # ------------------------------------------------------------------ settings helpers
    def _settings(self):
        try:
            players = max(2, min(8, int(self.v_players.get())))
        except ValueError:
            players = 6
        return dict(players=players, size=int(self.v_size.get()), land=int(self.v_land.get().rstrip("%")),
                    minerals=MINERALS[self.v_min.get()], mirror=MIRRORS[self.v_mirror.get()])

    def _store(self, settings=None):
        s = settings or self._settings()
        P = self._valid_params()
        mode = self.v_mode.get()
        if self.store is None or self.store.settings != s or self.store.params != P or self.store.mode != mode:
            if self.search and self.search.is_alive() and self.store is self.search.store:
                return engine.Store(DATA, **s, params=P, mode=mode)  # don't swap the store a running search writes to
            self.store = engine.Store(DATA, **s, params=P, mode=mode)
        return self.store

    # ------------------------------------------------------------------ modes
    def _mode_changed(self):
        self._mode_ui()
        self.selected = None
        self._load_list()
        if self.rows:
            self._select(self.rows[0])
        else:  # nothing found in this mode yet: don't leave the other mode's map on screen
            self.l_key.configure(text=""); self.l_score.configure(text=""); self.l_info.configure(text="")
            self.b_copy.configure(state="disabled")
            self.tree.delete(*self.tree.get_children())
            self._big_src = None
            self.big.configure(image="", text="Press “Find new maps” to start.")

    def _mode_ui(self):
        """Show what the current mode uses: preview mode has no mines, stones, rivers or snow."""
        mode = self.v_mode.get()
        full = mode == "full"
        self.l_mode.configure(text=(
            "Fully generates the best maps (~15 s each) and also scores ore, stone, rivers and snow."
            if full else "Scores only what the game's lobby preview shows: water, land and mountain. Fast."))
        self.c_details.configure(state="normal" if full else "disabled")
        self.tree.configure(displaycolumns=[k for k, _ in STAT_COLS] if full else PREVIEW_COLS)
        self.legend.configure(text=LEGEND[mode])
        used = set(analyze.lines_for(mode))
        for line, (lbl, ws) in self.score_widgets.items():
            on = line in used
            lbl.configure(style="TLabel" if on else "Muted.TLabel")
            for w in ws:
                w.configure(state="normal" if on else "disabled")
        self.snow_spin.configure(state="normal" if full else "disabled")
        self.l_full.configure(text="Full map only" if full else "Full map only (not used in lobby preview mode)")

    # ------------------------------------------------------------------ scoring tab
    def _build_scoring(self, tab):
        P = analyze.params_of(self.cfg.get("score_params"))
        self.v_par = {k: tk.StringVar(value=str(v)) for k, v in P.items()}
        wrap = int(250 * self.k)
        ar = ttk.LabelFrame(tab, text="Player areas", padding=10); ar.grid(row=0, column=0, sticky="ew")
        for i, (k, t) in enumerate([("radius", "Wide radius"), ("near", "Close radius")]):
            ttk.Label(ar, text=t).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Spinbox(ar, from_=20, to=600, increment=10, textvariable=self.v_par[k], width=7).grid(
                row=i, column=1, sticky="w", padx=(8, 4), pady=2)
            ttk.Label(ar, text="tiles from the castle", style="Muted.TLabel").grid(row=i, column=2, sticky="w")
        ttk.Label(ar, text="Snow").grid(row=2, column=0, sticky="w", pady=2)
        self.snow_spin = ttk.Spinbox(ar, from_=0, to=1, increment=0.1, textvariable=self.v_par["snow"], width=7)
        self.snow_spin.grid(row=2, column=1, sticky="w", padx=(8, 4), pady=2)
        ttk.Label(ar, text="× rock (no ore)", style="Muted.TLabel").grid(row=2, column=2, sticky="w")

        sc = ttk.LabelFrame(tab, text="Score lines", padding=10); sc.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for j, t in enumerate(("Lobby preview", "Target", "Weight")):
            ttk.Label(sc, text=t, style="Muted.TLabel").grid(row=0, column=j, sticky="w", padx=(0 if j == 0 else 8, 0))
        self.score_widgets = {}
        i = 1
        for line, label, inc in SCORE_ROWS:
            if line not in analyze.PREVIEW_LINES and not hasattr(self, "l_full"):
                self.l_full = ttk.Label(sc, text="", style="Muted.TLabel")
                self.l_full.grid(row=i, column=0, columnspan=3, sticky="w", pady=(6, 0)); i += 1
            lbl = ttk.Label(sc, text=label); lbl.grid(row=i, column=0, sticky="w", pady=1)
            t = ttk.Spinbox(sc, from_=0, to=1 if line.startswith("fair_") else 200000, increment=inc,
                            textvariable=self.v_par["t_" + line], width=7)
            t.grid(row=i, column=1, sticky="w", padx=(8, 0), pady=1)
            w = ttk.Spinbox(sc, from_=0, to=100, increment=1, textvariable=self.v_par["w_" + line], width=4)
            w.grid(row=i, column=2, sticky="w", padx=(8, 0), pady=1)
            self.score_widgets[line] = (lbl, (t, w)); i += 1
        ttk.Label(sc, style="Muted.TLabel", wraplength=wrap, justify="left", text=(
            "Target = what the weakest player needs for full points (tiles, for 1024 and 6 players; scaled otherwise). "
            "Fairness = weakest ÷ strongest. Weights are relative, 0 = off.")).grid(
            row=i, column=0, columnspan=3, sticky="w", pady=(4, 0))

        bot = ttk.Frame(tab); bot.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bot, text="Reset to defaults", command=self._reset_params).pack(side="left")
        self.l_par = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=wrap, justify="left")
        self.l_par.grid(row=3, column=0, sticky="w", pady=(4, 0))
        for v in self.v_par.values():
            v.trace_add("write", lambda *a: self._params_edited())
        self._params_note(P)

    def _score_params(self):
        """Parameters from the Scoring tab; ValueError with a readable message if one is off."""
        out = {}
        for k, v in self.v_par.items():
            try:
                out[k] = float(v.get().replace(",", "."))
            except ValueError:
                raise ValueError(f"“{v.get()}” is not a number") from None
            if out[k] < 0:
                raise ValueError("Values can't be negative")
        if not 20 <= out["radius"] <= 600:
            raise ValueError("Wide radius must be between 20 and 600 tiles")
        if out["snow"] > 1:
            raise ValueError("Snow must be between 0 and 1 (1 = as good as rock)")
        if not 10 <= out["near"] <= out["radius"]:
            raise ValueError("Close radius must be between 10 tiles and the wide radius")
        if not any(out["w_" + k] > 0 for k in analyze.lines_for(self.v_mode.get())):
            raise ValueError("At least one weight of this mode's lines must be above 0")
        if any(out["t_" + k] <= 0 for k in analyze.LINES):
            raise ValueError("Targets must be above 0")
        return analyze.params_of(out)

    def _valid_params(self):
        try:
            return self._score_params()
        except (ValueError, AttributeError):
            return analyze.params_of(self.cfg.get("score_params"))

    def _params_note(self, P):
        changed = engine.geo(P) != engine.geo(None)
        self.l_par.configure(foreground="#666", text=(
            "Other radii than 200 / 150: maps are generated again (kept separately per radius)." if changed else
            "Found maps are re-scored right away."))

    def _reset_params(self):
        for k, v in analyze.DEFAULT_PARAMS.items():
            self.v_par[k].set(str(v))

    def _params_edited(self):
        if self._par_job:
            self.root.after_cancel(self._par_job)
        self._par_job = self.root.after(400, self._apply_params)

    def _apply_params(self):
        self._par_job = None
        try:
            P = self._score_params()
        except ValueError as e:
            self.l_par.configure(text=str(e), foreground="#c62828"); return
        self._params_note(P)
        if self.search and self.search.is_alive():
            self.l_par.configure(text=self.l_par.cget("text") + " The running search keeps the settings it started with.")
            if self.v_view.get() == "new":
                return
        if self.v_view.get() == "all":
            self._load_list()
        else:  # this search's maps: re-score those measured with the same radii
            for r in self.rows:
                if r.get("geo", engine.geo(None)) == engine.geo(P):
                    r["score"] = engine.rescore(r["key"], r["players"], P, r.get("mode", "full"))
            self._sort_rows(); self._render_list()
        if self.selected:
            r = next((r for r in self.rows if r["key"] == self.selected["key"]), None)
            if r is not None:
                self._select(r)

    def _browse(self):
        d = filedialog.askdirectory(title="Settlers 4 game folder (contains S4_Main.exe)",
                                    initialdir=self.v_game.get() or "C:\\")
        if d:
            self.v_game.set(os.path.normpath(d)); self._check_game()

    def _check_game(self, silent=False):
        ok, msg = engine.check_game_dir(self.v_game.get())
        self.l_game.configure(text=("✓ " if ok else "✗ ") + msg, foreground="#2e7d32" if ok else "#c62828")
        if not ok and not silent:
            messagebox.showerror(APP, msg)
        return ok

    def _save_config(self):
        s = self._settings()
        cfg = dict(game_dir=self.v_game.get(), players=s["players"], size=s["size"], land=s["land"],
                   minerals_name=self.v_min.get(), mirror_name=self.v_mirror.get(),
                   want=self.v_want.get(), min_score=self.v_minscore.get(), workers=self.v_workers.get(),
                   mode=self.v_mode.get(),
                   score_params=self._valid_params(),
                   geometry=self.root.geometry() if self.root.state() != "zoomed" else "")
        os.makedirs(HOME, exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump(cfg, f, indent=1)

    # ------------------------------------------------------------------ search
    def _toggle_search(self):
        if self.search and self.search.is_alive():
            self.search.stop(); self.b_find.configure(text="Stopping…", state="disabled")
            return
        if not self._check_game():
            return
        try:
            want = int(self.v_want.get()); min_score = float(self.v_minscore.get()); workers = int(self.v_workers.get())
        except ValueError:
            messagebox.showerror(APP, "Maps to find, minimum score and CPU cores must be numbers."); return
        try:
            self._score_params()
        except ValueError as e:
            messagebox.showerror(APP, f"Scoring tab: {e}"); return
        self._save_config()
        self.store = None
        st = self._store()
        self.v_view.set("new"); self.rows = []; self._render_list()
        self.search = engine.Search(os.path.join(self.v_game.get(), "S4_Main.exe"), st, want, min_score,
                                    workers, self.events)
        self.search.start()
        for b in self.mode_btns:
            b.configure(state="disabled")
        self.pbar.configure(maximum=want, value=0)
        self.b_find.configure(text="Stop")

    def _status(self, p):
        el = time.time() - p["t0"]
        gen = f"   fully generated: {p['generated']}" if self.search and self.search.store.mode == "full" else ""
        self.l_status.configure(text=(
            f"Found {p['found']} of {p['want']} maps\n"
            f"Seeds checked: {p['scanned']:,}{gen}\n"
            f"{p['phase'].capitalize()} · {int(el // 60)}:{int(el % 60):02d}"))
        self.pbar.configure(value=p["found"])

    def _poll(self):
        try:
            while True:
                ev, data = self.events.get_nowait()
                if ev == "progress":
                    self._status(data)
                elif ev == "found":
                    if self.v_view.get() == "new" and self.search and self.store is self.search.store:
                        self.rows.append(data); self._add_card(data, len(self.rows) - 1)
                        self.l_count.configure(text=f"{len(self.rows)} maps")
                        if self.selected is None:
                            self._select(data)
                elif ev == "done":
                    self.b_find.configure(text="Find new maps", state="normal")
                    for b in self.mode_btns:
                        b.configure(state="normal")
                    if str(data).startswith("error"):
                        messagebox.showerror(APP, f"The search stopped with an {data}")
                    if self.v_view.get() == "new" and self.rows:
                        self._sort_rows(); self._render_list()
                elif ev == "checked":
                    self.b_check.configure(state="normal")
                    if "error" in data:
                        self.l_check.configure(text=f"Could not generate {data['key']}: {data['error']}")
                    else:
                        self.l_check.configure(text=f"{data['key']}: score {data['score']:.1f}")
                        self._select(data)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _check_key(self):
        key = self.v_key.get().strip().upper()
        if len(key) != 8 or any(ch not in s4key.ALPHA for ch in key) or key[-1] != "0":
            self.l_check.configure(text="That doesn't look like a map key (8 characters, ends with 0)."); return
        if not self._check_game():
            return
        d = s4key.decode(key)
        st = engine.Store(DATA, **{k: d[k] for k in ("players", "size", "land", "minerals", "mirror")},
                          params=self._valid_params(), mode=self.v_mode.get())
        self._check_store = st
        mir = {v: k for k, v in MIRRORS.items()}[d["mirror"]]
        how = "Generating" if st.mode == "full" else "Reading the lobby preview of"
        self.l_check.configure(text=f"{how} {key} ({d['players']} players, {d['size']}, land {d['land']}%, "
                                    f"mirror {mir.lower()}) … ~{15 if st.mode == 'full' else 5} s")
        self.b_check.configure(state="disabled")
        engine.KeyCheck(os.path.join(self.v_game.get(), "S4_Main.exe"), st, key, self.events).start()

    def _forget(self):
        st = self._store()
        if messagebox.askyesno(APP, f"Forget the {len(st.shown)} maps you've already been shown for these settings?\n"
                                    "They can then be shown again in future searches."):
            st.shown.clear(); st.save(); self._load_list()

    # ------------------------------------------------------------------ list
    def _sort_rows(self):
        s = self._settings()
        P = self._valid_params()
        self.rows.sort(key=lambda r: engine.rank_key(r["score"], r["players"], s["size"], s["players"], P))

    def _load_list(self):
        if self.search and self.search.is_alive() and self.v_view.get() == "new":
            return
        st = self._store()
        if self.v_view.get() == "all":
            self.rows = st.found()
        else:
            self.rows = []
        self._render_list()

    def _render_list(self):
        for w in self.lf.winfo_children():
            w.destroy()
        self.cards = {}; self.card_imgs = {}
        for i, r in enumerate(self.rows):
            self._add_card(r, i)
        n = len(self.rows)
        self.l_count.configure(text=f"{n} maps" if n else "")
        if not n and self.v_view.get() == "new":
            tk.Label(self.lf, text="New maps appear here while searching.\n\n"
                                   "“All found maps” lists every map\nfound so far for these settings.",
                     bg="#f3f3f3", fg="#777", justify="left", font=("Segoe UI", 10)).grid(padx=16, pady=16)
        self.lc.yview_moveto(0)

    def _thumb(self, r):
        key, mode = r["key"], r.get("mode", "full")
        det = self.v_details.get() and mode == "full"
        if (key, mode, det) not in self.thumbs:
            p = self._image_path(key, mode, det)
            try:
                im = Image.open(p); im.thumbnail(self.thumb, Image.LANCZOS)
                self.thumbs[key, mode, det] = ImageTk.PhotoImage(im)
            except OSError:
                return None
        return self.thumbs[key, mode, det]

    def _image_path(self, key, mode="full", details=False):
        d = s4key.decode(key)
        img = os.path.join(engine.Store.dir_for(DATA, **{k: d[k] for k in ("players", "size", "land", "minerals", "mirror")}), "img")
        p = engine.image_path(img, key, mode, details)
        return p if os.path.exists(p) else engine.image_path(img, key, mode)

    def _toggle_details(self):
        for key, (lbl, r) in self.card_imgs.items():
            try:
                lbl.configure(image=self._thumb(r))
            except tk.TclError:
                pass
        if self.selected:
            self._load_big(self.selected)

    def _add_card(self, r, i):
        key = r["key"]
        f = tk.Frame(self.lf, bg="white", highlightthickness=2, highlightbackground="white", cursor="hand2")
        f.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="n")
        img = tk.Label(f, image=self._thumb(r), bg="white", bd=0); img.pack()
        self.card_imgs[key] = (img, r)
        row = tk.Frame(f, bg="white"); row.pack(fill="x", padx=6, pady=4)
        tk.Label(row, text=key, font=("Consolas", 12, "bold"), bg="white").pack(side="left")
        tk.Label(row, text=f"{r['score']:.0f}", font=("Segoe UI", 10, "bold"), fg="#b07800", bg="white").pack(side="left", padx=6)
        b = ttk.Button(row, text="Copy", width=6, command=lambda k=key: self._copy(k)); b.pack(side="right")
        for w in (f, img, row) + tuple(c for c in row.winfo_children() if isinstance(c, tk.Label)):
            w.bind("<Button-1>", lambda e, rr=r: self._select(rr))
        self.cards[key] = f
        if self.selected and self.selected["key"] == key:
            f.configure(highlightbackground="#e0a000")

    def _wheel(self, e):
        x, y = self.root.winfo_pointerxy()
        w = self.root.winfo_containing(x, y)
        while w is not None:
            if w is self.lc:
                self.lc.yview_scroll(int(-e.delta / 120) * 3, "units"); return
            w = getattr(w, "master", None)

    # ------------------------------------------------------------------ detail
    def _select(self, r):
        if self.selected and self.selected["key"] in self.cards:
            try:
                self.cards[self.selected["key"]].configure(highlightbackground="white")
            except tk.TclError:
                pass
        self.selected = r
        if r["key"] in self.cards:
            self.cards[r["key"]].configure(highlightbackground="#e0a000")
        d = s4key.decode(r["key"])
        mir = {v: k for k, v in MIRRORS.items()}[d["mirror"]]
        minr = {v: k for k, v in MINERALS.items()}.get(d["minerals"], d["minerals"])
        self.l_key.configure(text=r["key"]); self.b_copy.configure(state="normal", text="Copy key")
        self.l_score.configure(text=f"score {r['score']:.1f}")
        self.l_info.configure(text=f"{d['players']} players · {d['size']}×{d['size']} · land {d['land']}% · "
                                   f"minerals {minr.lower()} · mirror {mir.lower()} · seed {d['seed']}")
        self._load_big(r)
        self._headings(r.get("geo", engine.geo(None))["near"])
        full = r.get("mode", "full") == "full"
        self.tree.configure(displaycolumns=[k for k, _ in STAT_COLS] if full else PREVIEW_COLS)
        self.tree.delete(*self.tree.get_children())
        # mountain columns as scored: snow weighted by the Scoring tab's snow factor
        per = [analyze.effective(p, self._valid_params()) for p in r["players"]]; half = len(per) // 2
        for i, p in enumerate(per):
            self.tree.insert("", "end", text=f"P{i + 1}", values=[f"{round(p.get(k, 0)):,}" for k, _ in STAT_COLS],
                             tags=("t1" if i < half else "t2",))
        mins = {k: min(p.get(k, 0) for p in per) for k, _ in STAT_COLS}
        self.tree.insert("", "end", text="weakest", values=[f"{round(mins[k]):,}" for k, _ in STAT_COLS])

    def _headings(self, near):
        for k, t in STAT_COLS:
            self.tree.heading(k, text=t.format(near=near))

    def _load_big(self, r):
        mode = r.get("mode", "full")
        try:
            self._big_src = Image.open(self._image_path(r["key"], mode, self.v_details.get() and mode == "full")).convert("RGB")
        except OSError:
            self._big_src = None
        self._show_big()

    def _show_big(self):
        if self._big_src is None:
            return
        w, h = max(50, self.big.winfo_width() - 4), max(50, self.big.winfo_height() - 4)
        sw, sh = self._big_src.size
        f = min(w / sw, h / sh)
        im = self._big_src.resize((max(1, int(sw * f)), max(1, int(sh * f))), Image.LANCZOS)
        self._big_tk = ImageTk.PhotoImage(im)
        self.big.configure(image=self._big_tk, text="")

    def _copy(self, key):
        self.root.clipboard_clear(); self.root.clipboard_append(key); self.root.update()
        if self.selected and self.selected["key"] == key:
            self.b_copy.configure(text="Copied ✓")
        self.l_status_flash(f"Copied {key} — paste it in the lobby's map key field.")

    def _copy_selected(self):
        if self.selected:
            self._copy(self.selected["key"])

    def l_status_flash(self, text):
        self.l_check.configure(text=text)

    def _close(self):
        try:
            self._save_config()
        except OSError:
            pass
        if self.search and self.search.is_alive():
            self.search.stop()
            self.search.join(timeout=5)
        self.root.destroy()


def selftest():
    """S4MapFinder.exe --selftest: short real search in a scratch folder, log to selftest.log."""
    import tempfile, traceback
    log = open(os.path.join(HOME, "selftest.log"), "w", encoding="utf-8")
    import faulthandler
    os.environ["S4MF_TRACE"] = HOME
    main_trace = open(os.path.join(HOME, "selftest_main.txt"), "w")
    faulthandler.dump_traceback_later(30, repeat=True, file=main_trace)
    try:
        d = engine.find_game_dir()
        log.write(f"game dir: {d}\n{engine.check_game_dir(d)}\n"); log.flush()
        root = tempfile.mkdtemp(prefix="s4mf_")
        engine.BATCH = 64
        for mode in engine.analyze.MODES:
            st = engine.Store(root, 6, 1024, 90, 15, 1, mode=mode)
            q = queue.Queue(); t0 = time.time()
            s = engine.Search(os.path.join(d, "S4_Main.exe"), st, 2, 0, 4, q)
            s.start()
            while True:
                ev, data = q.get(timeout=900)
                if ev == "found":
                    log.write(f"{mode} {time.time() - t0:.0f}s found {data['key']} {data['score']}\n"); log.flush()
                if ev == "done":
                    log.write(f"{mode} done: {data} after {time.time() - t0:.0f}s, scanned {s.stats['scanned']}\n")
                    break
    except Exception:
        log.write(traceback.format_exc())
    log.close()


def main():
    multiprocessing.freeze_support()
    os.makedirs(HOME, exist_ok=True)
    if "--selftest" in sys.argv:
        selftest(); return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    ico = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "icon.ico")
    if os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
