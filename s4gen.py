"""Run the Settlers 4 (History Edition) random map generator inside a CPU emulator.

The generator is statically linked into S4_Main.exe. We map the exe image into Unicorn,
stub the handful of CRT functions it uses (allocation, memset, _controlfp, sqrt, pow) and
call the game's own functions:

    0x50A4D0  CMapGeneratorHost::CMapGeneratorHost(SRandomMapParams*)   (thiscall)
    0x68C640  InitRandomMap(host /*ecx*/, params /*edx*/)
    0x68CAF0  CreatePreview(? /*ecx*/, WORD* buf160x160 /*edx*/, int)
    0x68D8C0  GenerateRandomMap(host /*ecx*/)

The host keeps the generated map in two buffers (4 bytes per tile each), pointers at
host+0x138 and host+0x13C.
"""
import math
import os
import struct

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_INVALID, UcError
from unicorn.x86_const import *

GAME_EXE = os.environ.get(
    "S4_EXE",
    r"D:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\thesettlers4\S4_Main.exe",
)

# ---- addresses in S4_Main.exe (History Edition, md5 153c49ab29946c21d50a3ae7a95c5cf8) ----
HOST_CTOR = 0x50A4D0
INIT_RANDOM_MAP = 0x68C640
CREATE_PREVIEW = 0x68CAF0
GENERATE_RANDOM_MAP = 0x68D8C0
HOST_CTOR_ONCE_FLAG = 0x1535D6C  # host ctor calls a one-time initialiser unless this is set

CRT_NEW = 0xD512C9        # operator new(size)
CRT_NEW_ARR = 0xD51B34    # operator new[](size)
CRT_FREE = 0xD51E45       # operator delete[](p)
CRT_DELETE_SZ = 0xD512B6  # operator delete(p, size)
CRT_MALLOC = 0xD94606
CRT_FREE2 = 0xD94611
CRT_MEMSET = 0xD77420
CRT_MEMCPY = 0xD76EA0
CRT_CONTROLFP = 0xD96900  # _controlfp(new, mask)
CRT_COOKIE = 0xD512A5     # __security_check_cookie (fastcall)
CRT_SQRT = 0xEA3580       # sqrt(xmm0) -> xmm0
CRT_POW = 0xDAD0C0        # pow(xmm0, xmm1) -> xmm0
CRT_ALLOCA = 0xD52200     # _alloca_probe: eax = size

STOP = 0x0FFF0000         # return address that ends an emulated call
TRAP = 0x0FFE0000         # every imported function points here
STACK_BASE, STACK_SIZE = 0x00010000, 0x00200000
TEB = 0x0FF00000
HEAP_BASE, HEAP_SIZE = 0x20000000, 0x30000000

PARAMS_SIZE = 0xB8


def _align(x, a=0x1000):
    return (x + a - 1) & ~(a - 1)


class EmuError(RuntimeError):
    pass


class S4Generator:
    def __init__(self, exe=GAME_EXE, trace_unknown=False, heap_mb=HEAP_SIZE >> 20):
        self.heap_size = heap_mb << 20
        pe = pefile.PE(exe)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        image = bytearray(pe.get_memory_mapped_image())
        self.image_size = _align(len(image))
        self.trace_unknown = trace_unknown
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(self.base, self.image_size)

        # point every IAT slot at a trap so stray OS calls are caught, not executed
        self.imports = {}
        uc.mem_map(TRAP, 0x10000)
        i = 0
        for d in pe.DIRECTORY_ENTRY_IMPORT:
            for imp in d.imports:
                slot = imp.address - self.base
                tgt = TRAP + 4 * i
                struct.pack_into("<I", image, slot, tgt)
                self.imports[tgt] = (d.dll.decode(), (imp.name or b"#%d" % imp.ordinal).decode())
                i += 1
        uc.mem_write(self.base, bytes(image))
        self._pristine_data = {}
        for s in pe.sections:
            if s.Characteristics & 0x80000000:  # writable section: keep a copy for resets
                va = self.base + s.VirtualAddress
                n = _align(max(s.Misc_VirtualSize, s.SizeOfRawData))
                self._pristine_data[va] = bytes(image[s.VirtualAddress:s.VirtualAddress + n])

        uc.mem_map(STOP, 0x1000)
        uc.mem_write(STOP, b"\xf4")  # hlt (never reached, the hook stops first)
        uc.mem_map(STACK_BASE, STACK_SIZE)
        uc.mem_map(TEB, 0x10000)
        uc.mem_write(TEB, struct.pack("<I", 0xFFFFFFFF))  # empty SEH chain
        uc.mem_write(TEB + 0x18, struct.pack("<I", TEB))
        self._setup_fs()
        uc.mem_map(HEAP_BASE, self.heap_size)

        self.stubs = {
            CRT_NEW: self._new, CRT_NEW_ARR: self._new, CRT_MALLOC: self._new,
            CRT_FREE: self._ret0, CRT_DELETE_SZ: self._ret0, CRT_FREE2: self._ret0,
            CRT_MEMSET: self._memset, CRT_MEMCPY: self._memcpy,
            CRT_CONTROLFP: self._controlfp, CRT_COOKIE: self._keep_eax,
            CRT_SQRT: self._sqrt, CRT_POW: self._pow, CRT_ALLOCA: self._alloca,
        }
        for a in self.stubs:
            uc.hook_add(UC_HOOK_CODE, self._stub_hook, begin=a, end=a)
        uc.hook_add(UC_HOOK_CODE, self._stop_hook, begin=STOP, end=STOP)
        uc.hook_add(UC_HOOK_CODE, self._trap_hook, begin=TRAP, end=TRAP + 0xFFFF)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._bad_mem)
        self.pow_log = []
        self.error = None
        self._init_import_stubs()
        self.reset()

    # ------------------------------------------------------------------ plumbing
    def _setup_fs(self):
        # flat 32-bit GDT with an FS segment based at TEB
        uc = self.uc
        gdt = 0x0FF10000
        uc.mem_map(gdt, 0x1000)

        def desc(base, limit, access, flags):
            return struct.pack(
                "<HHBBBB", limit & 0xFFFF, base & 0xFFFF, (base >> 16) & 0xFF, access,
                ((limit >> 16) & 0xF) | (flags << 4), (base >> 24) & 0xFF)

        entries = [b"\0" * 8,
                   desc(0, 0xFFFFF, 0x9B, 0xC),   # 1 code
                   desc(0, 0xFFFFF, 0x93, 0xC),   # 2 data
                   desc(TEB, 0xFFF, 0x93, 0x4),   # 3 fs
                   desc(0, 0xFFFFF, 0x93, 0xC)]   # 4 stack
        uc.mem_write(gdt, b"".join(entries))
        uc.reg_write(UC_X86_REG_GDTR, (0, gdt, len(entries) * 8 - 1, 0))
        uc.reg_write(UC_X86_REG_FS, 3 << 3)
        uc.reg_write(UC_X86_REG_DS, 2 << 3)
        uc.reg_write(UC_X86_REG_ES, 2 << 3)
        uc.reg_write(UC_X86_REG_SS, 4 << 3)

    def reset(self):
        """Restore writable sections and the heap so each map starts from a clean state."""
        for va, data in self._pristine_data.items():
            self.uc.mem_write(va, data)
        self.uc.mem_write(HOST_CTOR_ONCE_FLAG, b"\x01")
        self.heap = HEAP_BASE + 0x1000
        self.mxcsr = 0x1F80

    def _bad_mem(self, uc, access, addr, size, value, ud):
        eip = uc.reg_read(UC_X86_REG_EIP)
        self.error = "invalid memory access %d at 0x%X (eip 0x%X)" % (access, addr, eip)
        return False

    def _trap_hook(self, uc, addr, size, ud):
        dll, name = self.imports.get(addr, ("?", hex(addr)))
        h = self.import_stubs.get(name)
        if h is None:
            self.error = "unstubbed import called: %s!%s" % (dll, name)
            uc.emu_stop()
            return
        nargs, fn = h
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = self.u32(esp)
        r = fn(*[self.arg(esp, i) for i in range(nargs)])
        uc.reg_write(UC_X86_REG_EAX, (r or 0) & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * nargs)  # stdcall
        uc.reg_write(UC_X86_REG_EIP, ret)

    # minimal file API so the game's own .map reader can run (used for validation)
    def _init_import_stubs(self):
        self.files = {}
        self.import_stubs = {
            "CreateFileA": (7, self._CreateFileA),
            "ReadFile": (5, self._ReadFile),
            "CloseHandle": (1, lambda h: self.files.pop(h, None) is not None),
            "GetFileSize": (2, self._GetFileSize),
            "SetFilePointer": (4, self._SetFilePointer),
            "GetLastError": (0, lambda: 0),
            "SetLastError": (1, lambda e: 0),
            "SysAllocString": (1, self._SysAllocString),
            "SysFreeString": (1, lambda p: 0),
            "SysStringLen": (1, lambda p: self.u32(p - 4) // 2 if p else 0),
            "WideCharToMultiByte": (8, self._WideCharToMultiByte),
            "MultiByteToWideChar": (6, self._MultiByteToWideChar),
        }

    def _wstr(self, a, n=-1):
        out = bytearray()
        while n < 0 or len(out) < 2 * n:
            c = bytes(self.uc.mem_read(a + len(out), 2))
            if n < 0 and c == b"\0\0":
                break
            out += c
        return out.decode("utf-16-le")

    def _WideCharToMultiByte(self, cp, flags, wstr, cch, mb, cbmb, defc, used):
        s = self._wstr(wstr, -1 if cch == 0xFFFFFFFF else cch)
        b = s.encode("latin-1", "replace") + (b"\0" if cch == 0xFFFFFFFF else b"")
        if cbmb:
            self.uc.mem_write(mb, b[:cbmb])
        return len(b)

    def _MultiByteToWideChar(self, cp, flags, mb, cb, wstr, cch):
        s = self._cstr(mb) if cb == 0xFFFFFFFF else bytes(self.uc.mem_read(mb, cb)).decode("latin-1")
        b = (s + ("\0" if cb == 0xFFFFFFFF else "")).encode("utf-16-le")
        if cch:
            self.uc.mem_write(wstr, b[:2 * cch])
        return len(b) // 2

    def _SysAllocString(self, p):
        if not p:
            return 0
        n = 0
        while self.uc.mem_read(p + n, 2) != b"\0\0":
            n += 2
        b = self.alloc(n + 6)
        self.uc.mem_write(b, struct.pack("<I", n) + bytes(self.uc.mem_read(p, n)) + b"\0\0")
        return b + 4

    def _cstr(self, a):
        out = bytearray()
        while True:
            c = self.uc.mem_read(a + len(out), 1)[0]
            if not c:
                return out.decode("latin-1")
            out.append(c)

    def _CreateFileA(self, name, access, share, sec, disp, flags, tmpl):
        path = self._cstr(name)
        try:
            data = open(path, "rb").read()
        except OSError:
            return 0xFFFFFFFF
        h = 0x100 + 4 * len(self.files) + 4
        self.files[h] = [data, 0]
        return h

    def _ReadFile(self, h, buf, n, pread, ovl):
        f = self.files.get(h)
        if f is None:
            return 0
        chunk = f[0][f[1]:f[1] + n]
        f[1] += len(chunk)
        if chunk:
            self.uc.mem_write(buf, chunk)
        if pread:
            self.uc.mem_write(pread, struct.pack("<I", len(chunk)))
        return 1

    def _GetFileSize(self, h, phigh):
        if phigh:
            self.uc.mem_write(phigh, b"\0\0\0\0")
        return len(self.files[h][0])

    def _SetFilePointer(self, h, dist, phigh, method):
        f = self.files[h]
        dist = dist - (1 << 32) if dist & 0x80000000 else dist
        f[1] = {0: 0, 1: f[1], 2: len(f[0])}[method] + dist
        return f[1]

    def _stop_hook(self, uc, addr, size, ud):
        uc.emu_stop()

    def _stub_hook(self, uc, addr, size, ud):
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = self.u32(esp)
        r = self.stubs[addr](esp)
        if r is not None:
            uc.reg_write(UC_X86_REG_EAX, r & 0xFFFFFFFF)
        if addr == CRT_ALLOCA:
            return  # handled entirely in the stub
        uc.reg_write(UC_X86_REG_ESP, esp + 4)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def _keep_eax(self, esp):
        return None  # cookie check must preserve eax (holds the caller's return value)

    def u32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def arg(self, esp, i):
        return self.u32(esp + 4 + 4 * i)

    # ------------------------------------------------------------------ CRT stubs
    def alloc(self, n):
        n = max(int(n), 1)
        p = self.heap
        self.heap = _align(p + n, 16)
        if self.heap >= HEAP_BASE + self.heap_size:
            raise EmuError("emulated heap exhausted")
        return p

    def _new(self, esp):
        n = self.arg(esp, 0)
        p = self.alloc(n)
        # fresh heap memory is not guaranteed zero after a reset; zero it
        self.uc.mem_write(p, b"\0" * n)
        return p

    def _ret0(self, esp):
        return 0

    def _memset(self, esp):
        d, c, n = self.arg(esp, 0), self.arg(esp, 1) & 0xFF, self.arg(esp, 2)
        if n:
            self.uc.mem_write(d, bytes([c]) * n)
        return d

    def _memcpy(self, esp):
        d, s, n = self.arg(esp, 0), self.arg(esp, 1), self.arg(esp, 2)
        if n:
            self.uc.mem_write(d, bytes(self.uc.mem_read(s, n)))
        return d

    def _controlfp(self, esp):
        new, mask = self.arg(esp, 0), self.arg(esp, 1)
        # MSVC _controlfp encodes rounding in bits 8-9 (_RC_NEAR=0, _RC_DOWN=0x100,
        # _RC_UP=0x200, _RC_CHOP=0x300). On x86 it also programs MXCSR.
        old_rc = {0: 0, 1: 0x100, 2: 0x200, 3: 0x300}[(self.mxcsr >> 13) & 3]
        old = 0x9001F | old_rc
        if mask & 0x300:
            rc = (new & 0x300) >> 8
            mx_rc = {0: 0, 1: 1, 2: 2, 3: 3}[rc]  # same order in MXCSR
            self.mxcsr = (self.mxcsr & ~0x6000) | (mx_rc << 13)
            self.uc.reg_write(UC_X86_REG_MXCSR, self.mxcsr)
        return old

    def _sqrt(self, esp):
        x = self._xmm_double(UC_X86_REG_XMM0)
        self._set_xmm_double(UC_X86_REG_XMM0, math.sqrt(x) if x >= 0 else float("nan"))
        return None

    def _pow(self, esp):
        x = self._xmm_double(UC_X86_REG_XMM0)
        y = self._xmm_double(UC_X86_REG_XMM1)
        r = math.pow(x, y)
        self.pow_log.append((x, y, r))
        self._set_xmm_double(UC_X86_REG_XMM0, r)
        return None

    def _alloca(self, esp):
        # _alloca_probe: eax = bytes; moves esp down by eax, keeps return address on top
        n = self.uc.reg_read(UC_X86_REG_EAX)
        ret = self.u32(esp)
        new_esp = esp + 4 - n
        self.uc.reg_write(UC_X86_REG_ESP, new_esp)
        self.uc.reg_write(UC_X86_REG_EIP, ret)

    def _xmm_double(self, reg):
        v = self.uc.reg_read(reg)
        return struct.unpack("<d", struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))[0]

    def _set_xmm_double(self, reg, d):
        v = self.uc.reg_read(reg)
        lo = struct.unpack("<Q", struct.pack("<d", d))[0]
        self.uc.reg_write(reg, (v & ~0xFFFFFFFFFFFFFFFF) | lo)

    # ------------------------------------------------------------------ calls
    def call(self, fn, args=(), ecx=0, edx=0):
        uc = self.uc
        esp = STACK_BASE + STACK_SIZE - 0x100
        for a in reversed(args):
            esp -= 4
            uc.mem_write(esp, struct.pack("<I", a & 0xFFFFFFFF))
        esp -= 4
        uc.mem_write(esp, struct.pack("<I", STOP))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EBP, 0)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.reg_write(UC_X86_REG_EDX, edx)
        uc.reg_write(UC_X86_REG_MXCSR, self.mxcsr)
        self.error = None
        try:
            uc.emu_start(fn, STOP)
        except UcError as e:
            raise EmuError("%s; %s (eip 0x%X)" % (e, self.error, uc.reg_read(UC_X86_REG_EIP)))
        if self.error:
            raise EmuError(self.error)
        if uc.reg_read(UC_X86_REG_EIP) != STOP:
            raise EmuError("stopped at 0x%X" % uc.reg_read(UC_X86_REG_EIP))
        return uc.reg_read(UC_X86_REG_EAX)

    # ------------------------------------------------------------------ high level
    @staticmethod
    def build_params(seed, size=1024, players=6, land=90, minerals=15, mirror=1, extra=None):
        p = bytearray(PARAMS_SIZE)
        struct.pack_into("<i", p, 0x04, seed)
        struct.pack_into("<i", p, 0x08, size)
        struct.pack_into("<i", p, 0x0C, land)
        struct.pack_into("<i", p, 0x10, minerals)
        struct.pack_into("<i", p, 0x14, mirror)
        struct.pack_into("<i", p, 0x20, players)
        if extra:
            for off, fmt, val in extra:
                struct.pack_into(fmt, p, off, val)
        return bytes(p)

    def setup(self, params):
        self.reset()
        pp = self.alloc(PARAMS_SIZE)
        self.uc.mem_write(pp, params)
        host = self.alloc(0x140)
        self.call(HOST_CTOR, [pp], ecx=host)
        self.call(INIT_RANDOM_MAP, ecx=host, edx=pp)
        self.host, self.params_ptr = host, pp
        return host

    def preview(self):
        buf = self.alloc(0xC800)
        self.call(CREATE_PREVIEW, [0], ecx=self.host, edx=buf)
        return bytes(self.uc.mem_read(buf, 0xC800))

    def generate(self):
        ok = self.call(GENERATE_RANDOM_MAP, ecx=self.host) & 0xFF
        size = self.u32(self.host + 0xD0)
        a = self.u32(self.host + 0x138)
        b = self.u32(self.host + 0x13C)
        la = bytes(self.uc.mem_read(a, size * size * 4)) if a else None
        lb = bytes(self.uc.mem_read(b, size * size * 4)) if b else None
        return ok, size, la, lb
