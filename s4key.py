"""Settlers 4 random-map key <-> settings (8 base32 chars, least-significant first)."""
ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
MIRRORS = {0: "none", 1: "short diagonal", 2: "long diagonal", 3: "both"}


def encode(seed, players=6, size=1024, land=90, minerals=15, mirror=1):
    v = ((players - 1) | ((minerals // 5 - 1) << 3) | ((size // 64 - 4) << 5)
         | (mirror << 9) | ((land // 10 - 1) << 11) | (seed << 15))
    return "".join(ALPHA[(v >> (5 * i)) & 31] for i in range(8))


def decode(key):
    v = sum(ALPHA.index(c) << (5 * i) for i, c in enumerate(key.upper()))
    return dict(players=(v & 7) + 1, minerals=(((v >> 3) & 3) + 1) * 5,
                size=(((v >> 5) & 15) + 4) * 64, mirror=(v >> 9) & 3,
                land=(((v >> 11) & 15) + 1) * 10, seed=v >> 15)
