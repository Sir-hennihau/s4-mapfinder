# S4 Map Finder

**Finds fair, well-balanced random maps for The Settlers 4 (History Edition).**

In the Settlers 4 lobby, a random map is set by a short key such as `LSGUKDC0`. Most random maps are uneven: one
player gets little mountain, or is boxed in by water. Finding a good one by hand means loading map after map.
S4 Map Finder checks thousands of keys for you and keeps the maps where **every** player has enough mountain
(the most important thing), enough building space, and enough coal and iron. You browse previews of the best maps
and copy a key straight into the lobby.

**How it does it.** The tool runs the game's own random-map generator, taken from your installed `S4_Main.exe` and
run in an emulator (Unicorn). So the map you see for a key is exactly the map the lobby will make for it. Each key
gets a quick check from the small lobby preview first. Only the most promising ones are fully generated, measured
for every player, and scored. A map is only as good as its **weakest** player, so the score is built from what the
weakest player gets.

![](https://img.shields.io/badge/platform-Windows-blue) ![](https://img.shields.io/badge/game-Settlers%204%20History%20Edition-green)

---

## Download

Download **`S4MapFinder.exe`** from the [latest release](../../releases/latest). It is a single file with no install
needed; just run it.

Requirements:

- Windows 10 or 11 (64-bit).
- **The Settlers 4: History Edition installed** (Ubisoft Connect). The tool uses the generator inside your game's
  `S4_Main.exe`; no game files are included in the download.
- Any modern CPU. More cores make searching faster: 20 very good maps take about 5 minutes on 15 cores.

> Windows SmartScreen may warn about the exe because it isn't code-signed. Click **More info → Run anyway**.

## Quick start

1. Start `S4MapFinder.exe`. The top left should say **✓ Settlers 4 History Edition found**. If it doesn't, set the
   game folder (see [below](#game-folder)).
2. On the **Search** tab, set the lobby settings you play with (players, map size, land mass, minerals, mirror axis).
3. Click **Find new maps**. Maps appear in the middle list as they're found.
4. Click a map to see a large preview and the stats for each player.
5. Click **Copy key** (or **Copy** on a card) and paste the key into the random-map key field in the game lobby.
   Use the same lobby settings in the game as in the tool; they are part of the key.

## Game folder

The tool needs the folder that contains **`S4_Main.exe`** of the History Edition, for example

```
C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\thesettlers4
```

- **Automatic:** on start it looks in the Ubisoft Connect install folder (from the registry) and the usual install
  paths on `C:` and `D:`.
- **Manual:** if the line below the folder says ✗, click **…** next to the folder box and pick the folder that holds
  `S4_Main.exe`. In Ubisoft Connect you can find it via the game's page → *Properties* → *Open folder*. The folder is
  remembered.
- **Version check:** the tool only works with the History Edition build it was made for, and checks the exe's
  fingerprint. If Ubisoft updates the game and the generator changes, you'll see *Unsupported S4_Main.exe version*.

## Search tab

### Lobby settings

These must match the settings you will choose in the game lobby. Results are kept separately for every combination.

| Setting | What it does |
| --- | --- |
| **Players** | Number of players on the map (2–8). For 3 vs 3, use 6. P1–P3 and P4–P6 are the two teams. |
| **Map size** | Map width and height in tiles (256–1024). |
| **Land mass** | How much of the map is land rather than water (10–90 %). |
| **Minerals** | Amount of ore in the mountains: Lower, Normal or Higher. |
| **Mirror axis** | How the map is mirrored between the teams. *Short diagonal* is the usual 3v3 setting. With a single mirror axis (short or long diagonal), each team gets its own half of the map. With *None* or *Short and long diagonals*, land is split by nearest castle instead. |

### Search

| Setting | What it does |
| --- | --- |
| **Maps to find** | How many new maps the search should find before it stops. |
| **Minimum score** | Only maps with at least this score (0–100) are shown. 95+ is very good, 90 is good. A higher minimum means a longer search. |
| **CPU cores** | How many processor cores the search uses. The default leaves one core free so the PC stays usable. |

**Find new maps** starts a search; the same button becomes **Stop**, which you can press at any time. Below it you see
how many maps are found, how many keys were checked and fully generated, and the elapsed time.

A search never shows you a map twice: maps you've been shown are remembered, so every run brings new keys. Good maps
found in earlier runs that you haven't seen yet are shown first, instantly.

## Results

- **This search / All found maps** (above the list): *This search* lists the maps from the current run. *All found
  maps* lists every map found so far for the current lobby settings, best first, including ones you've seen.
- **Map cards:** preview, key and score. Click a card to show it on the right; **Copy** copies its key.
- **Big preview:** drawn like the in-game minimap: a slanted map, red circles for team 1 (P1–P3) and blue for team 2
  (P4–P6).
- **Show mines** (top right): off by default, like the lobby preview. Turn it on to see ore on the mountains: dark
  speckles are coal, red is iron, yellow is gold. It switches the big preview and the thumbnails.
- **Stats table**, one row per player plus a *weakest* row (the lowest value of each column):

  | Column | Meaning |
  | --- | --- |
  | Space | Buildable grass tiles in the player's area (flat enough to build on) |
  | Space ≤150 | Buildable tiles within the close radius of the castle |
  | Mountain | Mountain tiles in the player's area |
  | Mtn ≤150 | Mountain tiles within the close radius of the castle |
  | Fields | Separate mountain patches the player has (a patch shared by teammates counts once) |
  | Coal, Iron, Gold, Sulfur | Tiles with that ore in the player's area |

  "The player's area" is explained under [Player areas](#player-areas). The ≤ number follows the close radius on the
  Scoring tab.

Other buttons on the left:

- **Check a map key:** type or paste any key (8 characters, ending in 0) and press **Check**. It is generated
  (about 15 s), scored, and shown, which is handy for a key a friend sent you. The key's own lobby settings are used.
- **Open data folder:** opens where the results of the current settings are stored.
- **Forget seen maps:** makes maps you've already been shown for these settings eligible to be shown again.

## Scoring tab

This tab sets what counts as a good map. The score is 0–100. Each **score line** looks at the **weakest player** for
one thing (for example mountain) and gives full points if that player reaches the line's **target**. The lines are
then combined using their **weights**.

Changing a target or weight re-scores all found maps immediately, so you can sort your maps by what matters to you.
Changes also steer the next search: its quick first check of each key follows your mountain and space settings.
**Reset to defaults** restores the values below, which were calibrated on known-good league maps.

### Player areas

| Setting | Default | What it does |
| --- | --- | --- |
| **Wide radius** | 200 tiles | How far from the castle ground counts for a player at all. Everything further away is ignored. |
| **Close radius** | 150 tiles | Used by the "close" lines and the ≤ columns: only ground within this distance of the castle. Mountain close to home is easier to use and defend. |

Distances are walking distances over land, not straight lines, so water in between makes ground count as further
away.

Changing a radius changes the measurements themselves, so maps have to be generated again: a new search starts its
own list. Maps found with each radius setting are kept separately, and switching back brings the old list back.

### Score lines

| Line | Default target | Default weight | What it measures |
| --- | --- | --- | --- |
| **Mountain** | 9,000 tiles | 30 | Mountain tiles in the weakest player's area. Mountain is where mines go, so this matters most. |
| **Mountain, close** | 5,000 tiles | 15 | Mountain within the close radius of the weakest player's castle. |
| **Space** | 40,000 tiles | 30 | Buildable grass in the weakest player's area. |
| **Space, close** | 30,000 tiles | 0 (off) | Buildable grass within the close radius. |
| **Mountain fairness** | 0.6 | 10 | Weakest player's mountain ÷ strongest player's mountain. 0.6 means full points if the weakest player has at least 60 % of what the strongest has. |
| **Space fairness** | 0.6 | 5 | The same for building space. |
| **Coal** | 300 tiles | 5 | Coal tiles in the weakest player's area. |
| **Iron** | 200 tiles | 5 | Iron tiles in the weakest player's area. |
| **Gold** | 150 tiles | 0 (off) | Gold tiles in the weakest player's area. |
| **Sulfur** | 120 tiles | 0 (off) | Sulfur tiles in the weakest player's area. |

- **Target:** the amount the weakest player needs for full points on that line. Below the target, points drop in
  proportion (half the target gives half the points); above it there is no bonus.
- **Weight:** how much the line counts. Weights are relative: the score is the weighted average of the lines,
  so 30/30 is the same as 1/1. A weight of 0 turns the line off.
- **Scaling:** tile targets are meant for 1024×1024 with 6 players. For other settings they are scaled by the land
  available per player (a 512 map has a quarter of the area; 4 players get 1.5× as much each), so you don't need to
  change them when you switch settings.

Examples:

- *I want lots of mountain near my castle:* raise **Mountain, close** to 8,000 and its weight to 30.
- *Gold matters for my games:* set the **Gold** weight to 5–10.
- *I only care that it's fair:* raise both fairness weights and lower the others.

## How it works

1. **Quick check** (about 1 s per key per core). The tool runs the generator's first step and the 160×160 lobby
   preview, splits the land between the players, and estimates mountain and space for each. This gives a rough
   score.
2. **Full generation** (about 15 s per map, many in parallel) for the top 3 % of keys by quick check. The full
   1024×1024 map is generated, every player's area is measured tile by tile, and the map is scored and drawn.
3. Maps at or above the minimum score are shown. The search keeps checking fresh keys until it has found as many as
   you asked for. With a minimum score of 95, about half of the fully generated maps pass.

### Player areas

On a mirrored map the mirror axis is the front line: enemies can't build on your half. Each team gets its side of the
axis, and within it every tile goes to the **nearest teammate** (walking over land). A mountain between two teammates
is split between them, and **no tile counts for two players**. A mountain patch counts as a *field* for the teammate
who holds most of it, and for a second teammate only if they hold at least 40 % of it. On maps without a single mirror
axis, every tile goes to the nearest castle.

### Calibration

The default score was calibrated on known-good league keys (6 players, 1024, land 90 %, minerals higher, short
diagonal):

| Key | Score |
| --- | --- |
| LSGUKDC0 | 100 |
| LSG5JJE0 | 99.7 |
| LSGFG8O0 | 95 |
| LSG2NBQ0 | 91 |
| LSGKKUJ0 | 90 |
| LSG2H840 | 69 (P2/P5 are short on mountain) |

Typical bad random maps score 20–60.

## Where data is stored

Everything is in `%LOCALAPPDATA%\S4MapFinder`:

- `config.json`: your settings, including the game folder and scoring parameters.
- `maps\<players>p_<size>_land<land>_min<minerals>_mirror<mirror>\`: one folder per lobby setting combination, with
  the found maps (`deep*.json`), checked keys (`scan*.json`), the maps you've been shown (`shown.json`), and the
  preview images (`img\`).

Delete the folder to start completely fresh.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| ✗ *S4_Main.exe not found in this folder* | Pick the game folder with **…** (see [Game folder](#game-folder)). |
| ✗ *Unsupported S4_Main.exe version* | Your game build differs from the one this tool supports. |
| The search finds maps slowly | Lower the minimum score, use more CPU cores, or relax the Scoring targets. |
| Something seems broken | Run `S4MapFinder.exe --selftest` from a command prompt. It runs a short search and writes `%LOCALAPPDATA%\S4MapFinder\selftest.log`. |

---

## For developers

### Run from source

```
pip install -r requirements.txt
python app.py
```

Python 3.11+ on Windows. The game must be installed; set `S4_EXE` to point at a specific `S4_Main.exe`.

### Build the exe

```
pip install pyinstaller
python build.py          # -> dist\S4MapFinder.exe
```

Don't run PyInstaller directly: its launcher is built with Control Flow Guard, which crashes Unicorn's JIT, and
`build.py` clears that flag after building.

### Command line

There is also a command-line version that writes an HTML gallery:

```
python mapfinder.py                       # 6 players, 1024, land 90 %, minerals higher, short-diagonal mirror
python mapfinder.py --scan 10000 --maps 15
python mapfinder.py --keys LSGUKDC0 LSG2H840   # just score and render these keys
python mapfinder.py --mirror 0 --land 80   # other lobby settings
```

Open `results/index.html` to see the results and click a key to copy it. Every run scans new keys and only shows maps
you haven't been shown before (`--reshow` ranks everything again). The command line uses the default score
parameters.

### Files

| File | Purpose |
| --- | --- |
| `app.py` | Desktop UI (Tkinter). |
| `engine.py` | Search engine used by the UI: worker pool, two-stage search, result storage. |
| `analyze.py` | Player areas, metrics, scoring, and rendering. |
| `s4gen.py` | Unicorn emulator for the generator. It stubs the CRT/Win32 functions the generator uses. |
| `s4key.py` | Map key ↔ settings (base32, least-significant character first: players, minerals, size, mirror, land, 20-bit seed). |
| `mapfinder.py` | Command-line version. |
| `s4map.py` | Reads saved `.map` files using the game's own decrypt and decompress routines. |
| `validate.py` | Compares emulated output with real `Map\User\UnitedLeague_*.map` saves. Terrain matches about 88–90 % per byte: mountains, lakes and land outline are identical, and only coast and transition texturing differ. |
| `build.py` | Builds the exe. |

Generator entry points (HE exe, md5 `153c49ab29946c21d50a3ae7a95c5cf8`):

| Address | Function |
| --- | --- |
| `0x50ADA0` | Key decoder |
| `0x50A4D0` | Host |
| `0x68C640` | Init |
| `0x68CAF0` | Preview |
| `0x68D8C0` | Generate |

The RNG is an LCG: `s = s*0x6C078965 + 1`, output `s >> 16`.

*Not affiliated with Ubisoft or Blue Byte. The Settlers is a trademark of Ubisoft Entertainment.*
