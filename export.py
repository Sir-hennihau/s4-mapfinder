"""Discord export: the listed maps as numbered picture sheets plus a vote message to paste."""
import ctypes, io, math, os, time
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont

import analyze
import s4key

PER_SHEET = 6        # maps per picture: 3 x 2 is wide like Discord's preview, so the maps show big enough
COLS = 3
TILE = (720, 480)    # one map (the pictures are 3:2)
GAP, HEAD, CAP = 16, 64, 58
BG, FG, MUTED, GOLD = (30, 31, 34), (242, 243, 245), (148, 155, 164), (240, 178, 50)  # Discord's dark theme
MAX_BYTES = 9_500_000  # Discord's upload limit is 10 MB without Nitro
EMOJI = ["", ":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:", ":eight:", ":nine:", ":keycap_ten:"]
MINERALS = {5: "lower", 10: "normal", 15: "higher"}
MIRRORS = {0: "none", 1: "short diagonal", 2: "long diagonal", 3: "short and long diagonals"}


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def settings_text(key):
    d = s4key.decode(key)
    return (f"{d['players']} players · {d['size']}×{d['size']} · land {d['land']}% · "
            f"minerals {MINERALS.get(d['minerals'], d['minerals'])} · mirror {MIRRORS.get(d['mirror'], d['mirror'])}")


def _tile(im, r, num, radii):
    """One map scaled to TILE, with its vote number in the empty top-left corner and its key below."""
    im = analyze.mountain_contrast(im.convert("RGB").resize(TILE, Image.LANCZOS))
    if radii and r.get("starts"):  # same circles as "Show radii" in the app
        n = s4key.decode(r["key"])["size"]
        im = analyze.draw_radii(im, r["starts"], n, radii["radius"] * n / 1024, radii["near"] * n / 1024)
    out = Image.new("RGB", (TILE[0], TILE[1] + CAP), BG)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    # a gold square, so it can't be mistaken for the round red/blue castle markers
    big = _font(["segoeuib.ttf", "arialbd.ttf"], 46)
    t = str(num)
    w = max(64, d.textlength(t, font=big) + 28)
    d.rounded_rectangle((10, 10, 10 + w, 74), radius=10, fill=GOLD, outline=(255, 255, 255), width=3)
    d.text((10 + w / 2, 42), t, font=big, fill=(20, 20, 20), anchor="mm")
    y = TILE[1] + CAP / 2 + 12  # common baseline of key and score
    d.text((12, y), r["key"], font=_font(["consolab.ttf", "courbd.ttf"], 34), fill=FG, anchor="ls")
    d.text((TILE[0] - 12, y), f"score {r['score']:.0f}", font=_font(["segoeuib.ttf", "arialbd.ttf"], 26),
           fill=GOLD, anchor="rs")
    return out


def sheets(rows, image_of, mode_name, radii_of=lambda r: None):
    """Picture sheets of PER_SHEET maps each, numbered in list order. image_of(row) -> path of its picture,
    radii_of(row) -> {"radius", "near"} in tiles for 1024 to draw the radius circles, or None."""
    out, total = [], len(rows)
    hfont, sfont = _font(["segoeuib.ttf", "arialbd.ttf"], 26), _font(["segoeui.ttf", "arial.ttf"], 22)
    for s in range(0, total, PER_SHEET):
        part = rows[s:s + PER_SHEET]
        cols = min(COLS, len(part)); nrows = math.ceil(len(part) / cols)
        th = TILE[1] + CAP
        head = settings_text(part[0]["key"])
        which = f"{mode_name} · " + (f"maps {s + 1}–{s + len(part)} of {total}" if total > 1 else "1 map")
        tiles_w = GAP + cols * (TILE[0] + GAP)
        W = max(tiles_w, int(GAP * 4 + hfont.getlength(head) + sfont.getlength(which)))  # one map: room for the header
        sheet = Image.new("RGB", (W, HEAD + nrows * (th + GAP)), BG)
        d = ImageDraw.Draw(sheet)
        d.text((GAP, HEAD / 2), head, font=hfont, fill=FG, anchor="lm")
        d.text((W - GAP, HEAD / 2), which, font=sfont, fill=MUTED, anchor="rm")
        x0 = (W - tiles_w) // 2
        for i, r in enumerate(part):
            try:
                im = Image.open(image_of(r))
            except OSError:
                im = Image.new("RGB", TILE, (18, 18, 18))
            sheet.paste(_tile(im, r, s + i + 1, radii_of(r)),
                        (x0 + GAP + i % cols * (TILE[0] + GAP), HEAD + i // cols * (th + GAP)))
        out.append(sheet)
    return out


def message(rows, mode_name):
    """The vote post: one line per map with its number, key and score."""
    lines = [f"**Map vote:** {settings_text(rows[0]['key'])} ({mode_name.lower()} score)",
             "React with the number of the map you want to play!" if len(rows) <= 10 else
             "Reply with the number of the map you want to play!", ""]
    for i, r in enumerate(rows, 1):
        num = EMOJI[i] if len(rows) <= 10 else f"**{i}.**"
        lines.append(f"{num} `{r['key']}` · score {r['score']:.0f}")
    return "\n".join(lines)


def export(rows, image_of, folder, mode_name, radii_of=lambda r: None):
    """Write the sheets (PNG, or JPEG if a PNG is too big for Discord) and message.txt to a new subfolder of
    folder. Returns (that folder, the message, the picture paths)."""
    d = s4key.decode(rows[0]["key"])
    base = os.path.join(folder, time.strftime("%Y-%m-%d_%H%M%S") + f"_{d['players']}p_{d['size']}_land{d['land']}")
    out, n = base, 1
    while os.path.exists(out):  # two exports in the same second
        n += 1; out = f"{base}_{n}"
    os.makedirs(out)
    paths = []
    for i, sh in enumerate(sheets(rows, image_of, mode_name, radii_of), 1):
        p = os.path.join(out, f"maps_{i}.png")
        sh.save(p, optimize=True)
        if os.path.getsize(p) > MAX_BYTES:
            os.remove(p); p = p[:-4] + ".jpg"; sh.save(p, quality=90)
        paths.append(p)
    msg = message(rows, mode_name)
    with open(os.path.join(out, "message.txt"), "w", encoding="utf-8") as f:
        f.write(msg + "\n")
    return out, msg, paths


def copy_picture(path):
    """Put a picture on the Windows clipboard (CF_DIB), to paste into a Discord message."""
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]  # a DIB is a BMP file without its 14-byte file header
    k32, u32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")  # own instances: argtypes stay private
    k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = (wintypes.UINT, ctypes.c_size_t), wintypes.HGLOBAL
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = (wintypes.HGLOBAL,), ctypes.c_void_p
    k32.GlobalUnlock.argtypes = k32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
    u32.OpenClipboard.argtypes = (wintypes.HWND,)
    u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = (wintypes.UINT, wintypes.HANDLE), wintypes.HANDLE
    h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not h:
        raise OSError("out of memory")
    ctypes.memmove(k32.GlobalLock(h), data, len(data)); k32.GlobalUnlock(h)
    for _ in range(20):  # another program may have the clipboard open for a moment
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        k32.GlobalFree(h); raise OSError("the clipboard is in use by another program")
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(8, h):  # CF_DIB; the clipboard owns h from here on
            k32.GlobalFree(h); raise OSError("could not set the clipboard")
    finally:
        u32.CloseClipboard()
