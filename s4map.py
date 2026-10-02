"""Read Settlers 4 .map files using the game's own decrypt/decompress routines (emulated)."""
import struct
from s4gen import S4Generator

DECRYPT_INIT = 0x68C350
DECRYPT_HEADER = 0x68C260
DECOMPRESS = 0x68C100


def read_segments(path, g=None):
    g = g or S4Generator()
    g.reset()
    data = open(path, "rb").read()
    checksum, version = struct.unpack_from("<II", data, 0)
    g.call(DECRYPT_INIT)
    pos = 8
    segs = []
    hdr = g.alloc(24)
    while pos + 24 <= len(data):
        g.uc.mem_write(hdr, data[pos:pos + 24])
        g.call(DECRYPT_HEADER, ecx=hdr)
        h = bytes(g.uc.mem_read(hdr, 24))
        typ = struct.unpack_from("<H", h, 0)[0]
        packed, unpacked = struct.unpack_from("<II", h, 4)
        pos += 24
        payload = data[pos:pos + packed]
        pos += packed
        buf = g.alloc(max(packed, unpacked) + 16)
        g.uc.mem_write(buf, payload)
        g.call(DECOMPRESS, [unpacked], ecx=buf, edx=packed)
        segs.append((typ, h, bytes(g.uc.mem_read(buf, unpacked))))
    return version, segs


if __name__ == "__main__":
    import sys
    v, segs = read_segments(sys.argv[1])
    print("version", hex(v))
    for t, h, d in segs:
        print("type", t, "hdr", h.hex(), "len", len(d), d[:32].hex())
