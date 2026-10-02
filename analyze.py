"""Fast map evaluation from the game's 160x160 lobby preview + Init player starts."""
import struct
from collections import deque
import numpy as np

PV = 160
WATER = {0x45}
MOUNTAIN = {0x1083: 1.0, 0x8a2: 1.0, 0x901: 0.5, 0xcc2: 0.5, 0x540: 0.4, 0x864: 0.5}
DESERT = {0x3100, 0x1940, 0x2520, 0xd60}
# hex-grid neighbours of S4 tile coordinates
NB = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1))


def player_starts(g):
    arr = g.u32(0x146B0D4)
    out = []
    for i in range(8):
        o = g.u32(arr + 4 * i)
        if not o:
            break
        out.append(struct.unpack("<2i", g.uc.mem_read(o + 8, 8)))
    return out


def classify(pv):
    pv = np.asarray(pv).reshape(PV, PV)
    water = np.isin(pv, list(WATER))
    mtn = np.zeros(pv.shape, float)
    for c, w in MOUNTAIN.items():
        mtn[pv == c] = w
    desert = np.isin(pv, list(DESERT))
    build = ~water & (mtn == 0) & ~desert
    return water, mtn, build


def territories(passable, starts, scale, rmax):
    """Multi-source BFS (hex neighbourhood) -> owner index and distance per cell."""
    h, w = passable.shape
    owner = np.full((h, w), -1, np.int8)
    dist = np.full((h, w), 1 << 20, np.int32)
    q = deque()
    for i, (x, y) in enumerate(starts):
        cx, cy = min(w - 1, int(x / scale)), min(h - 1, int(y / scale))
        owner[cy, cx] = i; dist[cy, cx] = 0; q.append((cx, cy))
    while q:
        x, y = q.popleft()
        d = dist[y, x] + 1
        if d > rmax:
            continue
        for dx, dy in NB:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and passable[ny, nx] and dist[ny, nx] > d:
                dist[ny, nx] = d; owner[ny, nx] = owner[y, x]; q.append((nx, ny))
    return owner, dist


def blobs(mask):
    """Connected components (hex neighbourhood) -> label array, count."""
    lab = np.zeros(mask.shape, np.int32)
    n = 0
    h, w = mask.shape
    for sy, sx in zip(*np.nonzero(mask)):
        if lab[sy, sx]:
            continue
        n += 1; lab[sy, sx] = n; st = [(sx, sy)]
        while st:
            x, y = st.pop()
            for dx, dy in NB:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n; st.append((nx, ny))
    return lab, n


# --- who owns which ground -------------------------------------------------------
# On mirrored maps the mirror axis is the front line: enemies can't build on your half. Inside a team's
# half, ground goes to the closest teammate by land (a mountain between teammates is split fairly).
SPLIT_SHARE = 0.4      # a mountain counts as a field for a 2nd teammate only if they hold >= 40 % of it


def _mirror_fn(mirror, n):
    """(side function f(x, y) -> signed value, point mirror m(x, y)) for a mirror mode, else None."""
    if mirror == 1:   # short diagonal: (x, y) <-> (y, x)
        return (lambda x, y: y - x), (lambda x, y: (y, x))
    if mirror == 2:   # long diagonal: (x, y) <-> (n-1-y, n-1-x)
        return (lambda x, y: (n - 1) - x - y), (lambda x, y: (n - 1 - y, n - 1 - x))
    return None


def team_sides(starts, mirror, n):
    """Team id (0/1) per player from the mirror axis, or None when the map has no single axis."""
    fm = _mirror_fn(mirror, n)
    if fm is None or len(starts) < 2:
        return None
    f, m = fm
    for x, y in starts:  # every castle must have a mirrored partner, on the other side
        mx, my = m(x, y)
        if min(abs(mx - a) + abs(my - b) for a, b in starts) > 8 or f(x, y) == 0:
            return None
    return [int(f(x, y) < 0) for x, y in starts]


def side_share(h, w, scale, mirror, n, sub):
    """Share of each analysis cell that lies on side 1 (f < 0) of the mirror axis, from sub x sub sample tiles
    per cell. Tiles exactly on the axis count half for each side."""
    f, _ = _mirror_fn(mirror, n)
    off = (np.arange(sub) + 0.5) / sub
    ty = np.floor((np.arange(h)[:, None] + off) * scale).reshape(-1)
    tx = np.floor((np.arange(w)[:, None] + off) * scale).reshape(-1)
    F = f(tx[None, :], ty[:, None])
    s1 = (F < 0) + 0.5 * (F == 0)
    return s1.reshape(h, sub, w, sub).mean((1, 3))


def zones(passable, starts, scale, rmax, mirror=None, n_tiles=1024, sub=4):
    """Split the land between the players -> list of (weight, owner, dist) per zone.

    weight = share of each cell that belongs to the zone, owner = player per cell (-1 = nobody),
    dist = distance to that player's castle in tiles. With a mirror axis each team's zone is its own half;
    cells the axis runs through are shared out by their tiles, so both halves are exactly mirrored.
    Without an axis there is one zone and every cell goes to the nearest castle."""
    sides = team_sides(starts, mirror, n_tiles)
    if sides is None:
        owner, dist = territories(passable, starts, scale, rmax)
        return [(np.ones(passable.shape), owner, np.where(owner >= 0, dist * scale, np.inf))]
    h, w = passable.shape
    s1 = side_share(h, w, scale, mirror, n_tiles, sub)
    out = []
    for t, wt in ((0, 1 - s1), (1, s1)):
        members = np.array([i for i, s in enumerate(sides) if s == t], np.int8)
        o, d = territories(passable & (wt > 0), [starts[i] for i in members], scale, rmax)
        o[wt <= 0] = -1  # a castle cell is seeded even if the BFS mask excludes it
        owner = np.where(o >= 0, members[np.maximum(o, 0)], -1).astype(np.int8)
        out.append((wt, owner, np.where(o >= 0, d * scale, np.inf)))
    return out


def zone_sum(zs, val, i, near=None):
    """Player i's total of a per-cell value over all zones (optionally only within `near` tiles of the castle).
    val is one array (weighted by each zone's cell share) or a list with one already-split array per zone."""
    tot = 0.0
    for z, (wt, owner, dist) in enumerate(zs):
        sel = owner == i
        if near is not None:
            sel = sel & (dist <= near)
        tot += float((val[z] if isinstance(val, list) else val * wt)[sel].sum())
    return tot


def field_counts(lab, zs, msec, n, min_share):
    """Mountain patches per player, without double counting: a patch counts for the player holding the
    largest share of it (if >= min_share); another player counts it too only when the patch is genuinely
    split (they hold >= SPLIT_SHARE of it and >= min_share)."""
    fields = [0] * n
    for b in range(1, int(lab.max()) + 1):
        sel = lab == b
        part = [v * sel for v in msec] if isinstance(msec, list) else msec * sel
        shares = np.array([zone_sum(zs, part, i) for i in range(n)])
        tot = shares.sum()
        if tot <= 0:
            continue
        best = int(shares.argmax())
        for i in range(n):
            if shares[i] >= min_share and (i == best or shares[i] >= SPLIT_SHARE * tot):
                fields[i] += 1
    return fields


# --- score parameters (editable in the app) ------------------------------------------
# Radii are in tiles and tile targets are for 1024x1024 with 6 players; both are scaled for other settings.
# t_* = value the weakest player needs for full points on that line, w_* = relative weight of the line.
DEFAULT_PARAMS = dict(
    radius=200, near=150, snow=0.5,
    # seen in the lobby preview
    t_mtn=9000, t_mtn_near=5000, t_space=40000, t_space_near=30000, t_fair_mtn=0.6, t_fair_space=0.6,
    w_mtn=30, w_mtn_near=15, w_space=30, w_space_near=0, w_fair_mtn=10, w_fair_space=5,
    # only known from the full map
    t_gold=150, t_coal=800, t_iron=300, t_stone=200, t_sulfur=100,
    t_stonefield=400, t_stonefield_near=250, t_river=100, t_river_near=60,
    w_gold=6, w_coal=5, w_iron=3, w_stone=3, w_sulfur=1,
    w_stonefield=5, w_stonefield_near=5, w_river=3, w_river_near=2)
GEO_KEYS = ("radius", "near")  # change the per-player metrics: maps must be generated again
# score lines; snow = how much a snow tile counts compared with plain rock (snow never has ore under it)
PREVIEW_LINES = ("mtn", "mtn_near", "space", "space_near", "fair_mtn", "fair_space")
MOUNTAIN_LINES = ("mtn", "mtn_near", "fair_mtn")  # keep the same share of the score in both modes
FULL_LINES = PREVIEW_LINES + ("gold", "coal", "iron", "stone", "sulfur",
                              "stonefield", "stonefield_near", "river", "river_near")
LINES = FULL_LINES
MODES = ("preview", "full")
PREVIEW_KEYS = ("radius", "near") + tuple(p + k for k in PREVIEW_LINES for p in ("t_", "w_"))  # the pre-screen uses these


def lines_for(mode):
    return PREVIEW_LINES if mode == "preview" else FULL_LINES


def params_of(p=None):
    out = dict(DEFAULT_PARAMS)
    for k, v in (p or {}).items():
        if k in DEFAULT_PARAMS:
            v = float(v)
            out[k] = int(v) if v.is_integer() else v  # 200.0 and 200 must hash alike
    return out


PREVIEW_CAL = dict(space=1.0, mtn=1.12)  # fitted on 120 random maps (full-map / preview, per player)


def evaluate_preview(pv, starts, size=1024, radius_tiles=200, mirror=None, near_tiles=150):
    """Per-player metrics from the lobby preview, in full-map tiles (each preview pixel is ~6.4x6.4 tiles), so
    preview and full-map metrics can be scored with the same targets."""
    scale = size / PV
    water, mtn, build = classify(pv)
    zs = zones(~water, starts, scale, int(radius_tiles / scale), mirror, size, sub=8)
    lab, _ = blobs(mtn > 0)
    fields = field_counts(lab, zs, mtn, len(starts), 4)
    cell = scale * scale  # tiles per preview pixel; PREVIEW_CAL turns pixel counts into full-map tile counts
    q = lambda v, k, i, d=None: int(round(zone_sum(zs, v, i, d) * cell * PREVIEW_CAL[k]))
    return [dict(space=q(build, "space", i), space_near=q(build, "space", i, near_tiles),
                 mtn=q(mtn, "mtn", i), mtn_near=q(mtn, "mtn", i, near_tiles), fields=fields[i])
            for i in range(len(starts))]


def area_factor(size=1024, players=6):
    """Thresholds were calibrated on 1024x1024 with 6 players; scale by land area per player."""
    return (size / 1024) ** 2 * 6 / max(players, 1)


# ---------------------------------------------------------------- full-map (tile) analysis
GRASS = (16, 17, 20, 24, 25)
MOUNTAIN_T = (32, 33, 35, 128, 129)  # foot (33), rock (32, the only type with ore), snow edge (35), snow
SNOW_T = (35, 128, 129)
ORES = {1: "coal", 2: "iron", 3: "gold", 4: "sulfur", 5: "stone"}  # ore under mountains (B layer byte 3)
RIVER_T = (96, 97, 98, 99)       # river terrain: not shown in the lobby preview
STONE_OBJ = range(124, 136)      # stone objects (B layer byte 0), one per tile, 12 sizes; not in the lobby preview
BLK = 4  # analysis block size in tiles


def evaluate_tiles(A, B, starts, radius=200, near=150, mirror=None):
    """A,B: (n,n,4) uint8 layers. Returns per-player metrics in tiles (each tile counted for one player)."""
    n = A.shape[0]
    t = A[:, :, 1]; h = A[:, :, 0].astype(np.int16)
    slope = np.zeros_like(h)
    for dx, dy in ((1, 0), (0, 1), (1, 1)):
        slope = np.maximum(slope, np.abs(h - np.roll(np.roll(h, dy, 0), dx, 1)))
    water = t < 16
    mtn = np.isin(t, MOUNTAIN_T)
    snow = np.isin(t, SNOW_T)
    build = np.isin(t, GRASS) & (slope <= 6)
    river = np.isin(t, RIVER_T)
    stones = np.isin(B[:, :, 0], STONE_OBJ)
    ore = B[:, :, 3] >> 4
    ore_ok = ((B[:, :, 3] & 15) > 0) & ~water
    m = n // BLK
    blk = lambda a: a.reshape(m, BLK, m, BLK).sum((1, 3))
    water_b = blk(water) > BLK * BLK // 2
    zs = zones(~water_b, starts, BLK, radius // BLK, mirror, n)
    # each team only gets the tiles on its side of the mirror axis (axis tiles count half): split every
    # tile layer by side first, then sum it into blocks per team
    if len(zs) == 2:
        s1 = side_share(n, n, 1, mirror, n, 1)
        side_w = [1 - s1, s1]
    else:
        side_w = [1.0]
    split = lambda a: [blk(a * sw) for sw in side_w]
    mtn_z, build_z, snow_z, river_z, stone_z = split(mtn), split(build), split(snow), split(river), split(stones)
    ore_z = {k: split((ore == k) & ore_ok) for k in ORES}
    lab, _ = blobs(blk(mtn) >= BLK * BLK // 2)
    mineable = [a - b for a, b in zip(mtn_z, snow_z)]
    fields = field_counts(lab, zs, mineable, len(starts), 200)  # a field = >= ~200 mineable tiles
    res = []
    q = lambda v, i, d=None: int(round(zone_sum(zs, v, i, d)))
    for i in range(len(starts)):
        r = dict(space=q(build_z, i), space_near=q(build_z, i, near), mtn=q(mtn_z, i), mtn_near=q(mtn_z, i, near),
                 fields=fields[i], snow=q(snow_z, i), snow_near=q(snow_z, i, near),
                 stonefield=q(stone_z, i), stonefield_near=q(stone_z, i, near),
                 river=q(river_z, i), river_near=q(river_z, i, near))
        for k, name in ORES.items():
            r[name] = q(ore_z[k], i)
        res.append(r)
    return res


def effective(p, params=None):
    """Per-player metrics with snow mountain weighted by the 'snow' parameter (stored metrics are raw counts;
    preview metrics have no snow, the lobby preview doesn't show it)."""
    k = 1 - params_of(params)["snow"]
    q = dict(p)
    q["mtn"] = p["mtn"] - k * p.get("snow", 0)
    q["mtn_near"] = p["mtn_near"] - k * p.get("snow_near", 0)
    return q


def score_lines(per, size=1024, players=6, params=None, mode="full"):
    """-> {line: fraction 0..1 of its target reached by the weakest player}"""
    P = params_of(params)
    per = [effective(p, P) for p in per]
    f = area_factor(size, players)
    g = lambda k: np.array([p.get(k, 0) for p in per], float)
    c = lambda v: float(np.clip(v, 0, 1))
    out = {}
    for line in lines_for(mode):
        t = max(P["t_" + line], 1e-9)
        if line.startswith("fair_"):
            v = g(line[5:])
            out[line] = c(v.min() / max(v.max(), 1) / t)
        else:
            out[line] = c(g(line).min() / (t * f))
    return out


def line_weights(params=None, mode="full"):
    """Share of the score per line (sums to 1). Full map mode gives the mountain lines exactly the share they have
    in lobby preview mode; space and the full-map-only lines (ore, stone, river) split the rest by their weights,
    so adding those lines takes from space, never from mountain."""
    P = params_of(params)
    w = {k: float(P["w_" + k]) for k in lines_for(mode)}
    tot = sum(w.values())
    if tot <= 0:
        return {k: 0.0 for k in w}
    if mode == "full":
        m_pre = sum(w[k] for k in MOUNTAIN_LINES)
        pre = sum(w[k] for k in PREVIEW_LINES)
        rest = tot - m_pre
        if pre > 0 and rest > 0:
            share = m_pre / pre  # mountain's share in lobby preview mode
            return {k: (share * v / m_pre if k in MOUNTAIN_LINES else (1 - share) * v / rest) for k, v in w.items()}
    return {k: v / tot for k, v in w.items()}


def score_tiles(per, size=1024, players=6, params=None, mode="full"):
    """0-100: weighted average of the score lines. mode "preview" uses only what the lobby preview shows."""
    lines = score_lines(per, size, players, params, mode)
    w = line_weights(params, mode)
    return round(100 * sum(w[k] * v for k, v in lines.items()), 1)


RIVER_RGB = (80, 165, 235)
STONE_RGB = (185, 185, 178)


def _grow(mask, r):
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out |= np.roll(np.roll(mask, dy, 0), dx, 1)
    return out


def render(A, B, starts, scale=0.5, shear=True, details=True):
    """In-game-like picture of the full map. details=False shows only what the lobby preview shows (water, land,
    mountain); details=True adds rivers (light blue), stone fields (grey) and ore. Returns a PIL image."""
    n = A.shape[0]
    t = A[:, :, 1]; h = A[:, :, 0].astype(float)
    pal = np.zeros((256, 3), np.uint8); pal[:] = (90, 150, 60)
    for i in range(16):
        pal[i] = (20 + min(i, 7) * 4, 50 + min(i, 7) * 8, 120 + min(i, 7) * 12)
    pal[16] = (70, 140, 50); pal[17] = (100, 130, 75); pal[20] = (150, 150, 70)
    pal[24] = (50, 110, 40); pal[25] = (60, 125, 45)
    pal[32] = (120, 115, 110); pal[33] = (140, 130, 105); pal[35] = (200, 200, 205)
    pal[48] = (210, 200, 140); pal[64] = (220, 190, 110); pal[65] = (180, 170, 90)
    pal[128] = (240, 240, 250); pal[129] = (190, 190, 200)
    pal[96:100] = pal[16]  # river looks like grass in the lobby preview
    img = pal[t].astype(float)
    gx = np.gradient(h, axis=1); gy = np.gradient(h, axis=0)
    img *= np.clip(1 + 0.04 * (gx + gy), 0.6, 1.4)[:, :, None]
    if details:
        # rivers are thin and stones single tiles: draw both a little bigger so they show up at picture size
        river = _grow(np.isin(t, RIVER_T), max(1, int(round(1 / scale))))
        img[river] = RIVER_RGB
        stones = _grow(np.isin(B[:, :, 0], STONE_OBJ), max(1, int(round(1.5 / scale))))
        img[stones] = STONE_RGB
        ore = B[:, :, 3] >> 4; amt = B[:, :, 3] & 15
        on = (amt > 0) & np.isin(t, MOUNTAIN_T)
        col = {1: (40, 40, 40), 2: (190, 90, 60), 3: (250, 210, 40), 4: (230, 230, 90), 5: (235, 235, 235)}
        for k, c in col.items():
            sel = on & (ore == k)
            img[sel] = img[sel] * 0.45 + np.array(c) * 0.55
    return _finish(np.clip(img, 0, 255).astype(np.uint8), starts, scale, shear)


def render_preview(pv, starts, size=1024, scale=0.5, shear=True):
    """The game's 160x160 lobby preview, drawn with the full map's colours from exactly what the pre-screen
    reads out of it: water, land, mountain (and desert). Rivers and stones aren't in the preview."""
    from PIL import Image
    water, mtn, build = classify(pv)
    desert = ~water & (mtn == 0) & ~build
    img = np.zeros((PV, PV, 3), float); img[:] = (70, 140, 50)
    img[water] = (35, 85, 165)
    img[desert] = (220, 190, 110)
    img = img * (1 - mtn[:, :, None]) + np.array((120, 115, 110)) * mtn[:, :, None]
    big = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((size, size), Image.BILINEAR)
    return _finish(np.asarray(big), starts, scale, shear)


def _finish(img, starts, scale, shear):
    """Shear an (n, n, 3) picture into the in-game parallelogram and draw the castles."""
    from PIL import Image, ImageDraw, ImageFont
    n = img.shape[0]
    H = int(n * scale)
    W = int(n * scale * (1.5 if shear else 1))
    oy, ox = np.mgrid[0:H, 0:W]
    y = (oy / scale).astype(int)
    x = (ox / scale - ((n - y) / 2 if shear else 0)).astype(int)
    ok = (x >= 0) & (x < n)
    out = np.full((H, W, 3), 18, np.uint8)
    out[ok] = img[y[ok], x[ok]]
    im = Image.fromarray(out)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arialbd.ttf", max(12, int(28 * scale)))
    except OSError:
        font = ImageFont.load_default()
    team_col = [(220, 40, 40), (40, 90, 230)]
    half = len(starts) // 2
    for i, (sx, sy) in enumerate(starts):
        px = (sx + ((n - sy) / 2 if shear else 0)) * scale; py = sy * scale
        r = max(9, int(22 * scale))
        d.ellipse((px - r, py - r, px + r, py + r), fill=team_col[i >= half], outline=(255, 255, 255), width=2)
        d.text((px, py), str(i + 1), fill=(255, 255, 255), font=font, anchor="mm")
    return im
