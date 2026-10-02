"""Build dist/S4MapFinder.exe (python build.py [--dist other_folder], e.g. while the old exe is running).

PyInstaller's bootloader is compiled with Control Flow Guard. Unicorn runs JIT-compiled code, which CFG
rejects (the workers die with an access violation inside Unicorn), so the CFG flag is cleared after the build.
"""
import os, struct, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = sys.argv[sys.argv.index("--dist") + 1] if "--dist" in sys.argv else os.path.join(HERE, "dist")
EXE = os.path.join(DIST, "S4MapFinder.exe")
IMAGE_DLLCHARACTERISTICS_GUARD_CF = 0x4000


def clear_cfg(path):
    with open(path, "r+b") as f:
        f.seek(0x3C); pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe); assert f.read(4) == b"PE\0\0", "not a PE file"
        off = pe + 24 + 70  # IMAGE_OPTIONAL_HEADER.DllCharacteristics (same offset for PE32 and PE32+)
        f.seek(off); dc = struct.unpack("<H", f.read(2))[0]
        f.seek(off); f.write(struct.pack("<H", dc & ~IMAGE_DLLCHARACTERISTICS_GUARD_CF))
    return dc, dc & ~IMAGE_DLLCHARACTERISTICS_GUARD_CF


def main():
    icon = os.path.join(HERE, "icon.ico")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "S4MapFinder", "--icon", icon, "--add-data", f"{icon};.",
        "--collect-all", "unicorn", "--hidden-import", "pefile",
        "--exclude-module", "matplotlib", "--exclude-module", "scipy",
        "--distpath", DIST, "--workpath", os.path.join(HERE, "_scratch", "build"),
        "--specpath", os.path.join(HERE, "_scratch", "build"), os.path.join(HERE, "app.py")])
    for attempt in range(12):  # a virus scanner often holds the fresh exe open for a few seconds
        try:
            before, after = clear_cfg(EXE)
            break
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(5)
    print(f"DllCharacteristics {before:#06x} -> {after:#06x} (CFG off)\n{EXE}")


if __name__ == "__main__":
    main()
