"""Escape the Backrooms 信息覆盖层（只读内存，不注入、不写入）。

显示怪物、道具、出口、危险区、队友的位置和距离，左上角是信息面板。
游戏需用「窗口化」或「无边框窗口」模式，独占全屏时覆盖层会被盖住。

热键：F8 显示/隐藏全部　F9 切换道具　F10 切换可交互物　End 退出
"""

import collections
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk

PROCESS_NAME = "Backrooms-Win64-Shipping.exe"

# ---------------------------------------------------------------- Win32 读内存

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPMODULE = 0x8
TH32CS_SNAPMODULE32 = 0x10


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
                ("hModule", wt.HMODULE), ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]


def find_pid(name):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    ok = k32.Process32FirstW(snap, ctypes.byref(pe))
    try:
        while ok:
            if pe.szExeFile.lower() == name.lower():
                return pe.th32ProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return None


def find_module(pid, name):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    me = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
    ok = k32.Module32FirstW(snap, ctypes.byref(me))
    try:
        while ok:
            if me.szModule.lower() == name.lower():
                return me.modBaseAddr, me.modBaseSize
            ok = k32.Module32NextW(snap, ctypes.byref(me))
    finally:
        k32.CloseHandle(snap)
    return None, None


class Mem:
    def __init__(self, pid):
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise OSError(f"OpenProcess 失败，错误码 {ctypes.get_last_error()}")
        self._buf = ctypes.create_string_buffer(64)
        self._n = ctypes.c_size_t()

    def read(self, addr, size):
        if not addr or addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            return None
        buf = self._buf if size <= 64 else ctypes.create_string_buffer(size)
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(self._n)):
            return None
        return buf.raw[:size]

    def ptr(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else 0

    def i32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<i", b)[0] if b else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<f", b)[0] if b else None

    def vec(self, addr):
        b = self.read(addr, 12)
        return struct.unpack("<3f", b) if b else None

    def ptr_array(self, addr, count):
        if count <= 0 or count > 200000:
            return []
        b = self.read(addr, count * 8)
        return list(struct.unpack(f"<{count}Q", b)) if b else []


# ---------------------------------------------------------------- 定位 UE 全局对象

AOBS = {
    "GNames": "4C 8D 05 ?? ?? ?? ?? EB 16 48 8D 0D ?? ?? ?? ?? E8",
    "GObjects": "48 8B 05 ?? ?? ?? ?? 48 8B 0C C8 48 8D 04 D1",
    "GWorld": "48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01",
}


def aob_to_regex(pat):
    parts = [b"." if t == "??" else re.escape(bytes([int(t, 16)])) for t in pat.split()]
    return re.compile(b"".join(parts), re.DOTALL)


def exec_sections(mem, base):
    """解析 PE 头，返回可执行节 [(起始地址, 大小)]。"""
    nt = base + mem.i32(base + 0x3C)
    nsec = struct.unpack("<H", mem.read(nt + 6, 2))[0]
    opt_size = struct.unpack("<H", mem.read(nt + 0x14, 2))[0]
    table = nt + 0x18 + opt_size
    out = []
    for i in range(nsec):
        s = mem.read(table + i * 40, 40)
        vsize, vaddr = struct.unpack_from("<II", s, 8)
        chars = struct.unpack_from("<I", s, 0x24)[0]
        if chars & 0x20000000:
            out.append((base + vaddr, vsize))
    return out


def locate_globals(mem, base):
    found = {}
    regs = {k: aob_to_regex(v) for k, v in AOBS.items()}
    for start, size in exec_sections(mem, base):
        chunk = 16 * 1024 * 1024
        for off in range(0, size, chunk):
            n = min(chunk + 64, size - off)
            data = mem.read(start + off, n)
            if not data:
                continue
            for k, rg in regs.items():
                if k in found:
                    continue
                m = rg.search(data)
                if m:
                    ins = start + off + m.start()
                    disp = struct.unpack_from("<i", data, m.start() + 3)[0]
                    found[k] = ins + 7 + disp
        if len(found) == len(regs):
            break
    missing = set(regs) - set(found)
    if missing:
        raise RuntimeError(f"AOB 没找到：{missing}（游戏可能更新了）")
    return found


# ---------------------------------------------------------------- UE4.27 结构偏移

OFF = dict(
    UObject_Class=0x10, UObject_Name=0x18,
    UStruct_Super=0x40,
    World_PersistentLevel=0x30, World_GameInstance=0x180, World_Levels=0x138,
    Level_Actors=0x98,
    GI_LocalPlayers=0x38, Player_PC=0x30,
    Controller_Pawn=0x250, PC_CameraManager=0x2B8,
    PCM_POV=0x1AE0 + 0x10,          # CameraCachePrivate.POV
    Actor_Root=0x130,
    Scene_WorldLoc=0x1D0,           # ComponentToWorld.Translation
    Char_Stamina=0x878, Char_IsDead=0x874,
    World_GameState=0x120, GS_PlayerArray=0x238, GS_PlayersAlive=0x2A0,
    PS_Pawn=0x280, PS_Name=0x300, PS_Sanity=0x338, PS_MaxSanity=0x33C,
    Controller_PlayerState=0x228,
    DroppedItem_CanPickup=0x239,
)


class UE:
    def __init__(self, mem, g):
        self.m = mem
        self.gnames = g["GNames"]
        self.gworld = g["GWorld"]
        self._names = {}
        self._blocks = {}

    def name(self, fname_addr):
        b = self.m.read(fname_addr, 8)
        if not b:
            return "?"
        idx, num = struct.unpack("<II", b)
        s = self._names.get(idx)
        if s is None:
            s = self._resolve(idx)
            self._names[idx] = s
        return f"{s}_{num - 1}" if num else s

    def _resolve(self, idx):
        block, off = idx >> 16, idx & 0xFFFF
        bp = self._blocks.get(block)
        if not bp:
            bp = self.m.ptr(self.gnames + 0x10 + block * 8)
            if bp:
                self._blocks[block] = bp
        if not bp:
            return "?"
        e = bp + off * 2
        hdr = self.m.read(e, 2)
        if not hdr:
            return "?"
        h = struct.unpack("<H", hdr)[0]
        ln, wide = h >> 6, h & 1
        if ln <= 0 or ln > 1024:
            return "?"
        raw = self.m.read(e + 2, ln * (2 if wide else 1)) or b""
        return raw.decode("utf-16-le" if wide else "latin-1", "replace")

    def find_name(self, text):
        """在 FNamePool 里找字符串对应的名字索引；第一次调用时把所有名字块整块读下来建反查表。"""
        if not hasattr(self, "_rev"):
            self._rev, self._rev_lower = {}, {}
            cur_block = self.m.i32(self.gnames + 0x8) or 0
            cursor = self.m.i32(self.gnames + 0xC) or 0
            for b in range(cur_block + 1):
                bp = self.m.ptr(self.gnames + 0x10 + b * 8)
                size = cursor if b == cur_block else 0x20000
                data = self.m.read(bp, size) if bp and size else None
                if not data:
                    continue
                off = 0
                while off + 2 <= len(data):
                    h = struct.unpack_from("<H", data, off)[0]
                    ln, wide = h >> 6, h & 1
                    if ln == 0:
                        break
                    n = ln * (2 if wide else 1)
                    txt = data[off + 2:off + 2 + n].decode("utf-16-le" if wide else "latin-1", "replace")
                    idx = (b << 16) | (off >> 1)
                    self._rev.setdefault(txt, idx)
                    self._rev_lower.setdefault(txt.lower(), idx)
                    off = (off + 2 + n + 1) & ~1
        return self._rev.get(text, self._rev_lower.get(text.lower()))

    def fstring(self, addr):
        data, num = self.m.ptr(addr), self.m.i32(addr + 8) or 0
        if not data or num <= 0 or num > 256:
            return ""
        return (self.m.read(data, num * 2) or b"").decode("utf-16-le", "replace").rstrip("\0")

    def objname(self, obj):
        return self.name(obj + OFF["UObject_Name"])

    def class_chain(self, cls):
        out = []
        while cls and len(out) < 16:
            out.append(self.objname(cls))
            cls = self.m.ptr(cls + OFF["UStruct_Super"])
        return out


# ---------------------------------------------------------------- 分类与中文名

MONSTER_CN = {
    "Bacteria": "细菌", "Hound": "猎犬", "Smiler": "笑魇", "SkinStealer": "窃皮者",
    "Moth": "飞蛾", "Partygoer": "派对客", "Howler": "嚎叫者", "Clump": "肉团",
    "Wretch": "悲惨者", "Facel": "无面者", "Deathmoth": "死亡飞蛾", "Animation": "动画体",
    "Duller": "黯淡者", "Window": "窗户", "Stalker": "潜行者", "Skin": "窃皮者",
    "BoneThief": "骨窃贼", "Antize": "蚁群",
}
ITEM_CN = {
    "Flashlight": "手电筒", "Rope": "绳子", "AlmondWater": "杏仁水", "Almond": "杏仁水",
    "Chainsaw": "电锯", "Flaregun": "信号枪", "Flare": "信号枪", "Glowstick": "荧光棒",
    "LiquidPain": "液态痛苦", "Liquid_Pain": "液态痛苦", "Radio": "对讲机", "Walkie": "对讲机",
    "Camera": "相机", "DivingHelmet": "潜水头盔", "Lidar": "激光雷达", "MotionScanner": "运动扫描仪",
    "Battery": "电池", "Key": "钥匙", "Juice": "果汁", "Ticket": "门票", "Card": "卡片",
    "Crowbar": "撬棍", "Knife": "刀", "Diary": "日记", "Note": "纸条", "Fuse": "保险丝",
    "Firework": "烟花", "BugSpray": "杀虫喷雾", "PlasticBall": "塑料球", "Toy": "玩具",
    "EnergyBar": "能量棒", "MothJelly": "飞蛾果冻", "Jelly": "飞蛾果冻", "Diving_Helmet": "潜水头盔",
    "Glowstick_Blue": "蓝色荧光棒", "Glowstick_Red": "红色荧光棒", "Glowstick_Yellow": "黄色荧光棒",
    "AlmondBottle": "杏仁水瓶", "Scanner": "扫描仪", "Thermometer": "温度计", "Chainsaw_Fast": "快速电锯",
}

SKIP_PAWNS = ("FancyCharacter", "InteractablePawn", "ClientInteractablePawn", "BoatPawn",
              "SpectatorPawn", "DefaultPawn")


def clean_name(cls_name):
    s = re.sub(r"_C$", "", cls_name)
    s = re.sub(r"^(BP_)?DroppedItem_", "", s)
    s = re.sub(r"^(BP_|BPP_|Item_)", "", s)
    s = re.sub(r"(_BP|_Level\d+|_Roaming)$", "", s)
    return s


def translate(name, table):
    for k, v in sorted(table.items(), key=lambda kv: -len(kv[0])):   # 长的先匹配，Glowstick_Blue 优先于 Glowstick
        if k.lower() in name.lower():
            return f"{v}"
    return name


def classify(chain):
    """根据继承链返回 (类别, 显示名)，不关心的返回 None。"""
    leaf = chain[0]
    if "FancyCharacter" in chain:
        return "player", "队友"
    if "Pawn" in chain and not any(s in chain for s in SKIP_PAWNS):
        return "monster", translate(clean_name(leaf), MONSTER_CN)
    if "DroppedItem" in chain or "ItemActor" in chain:
        return "item", translate(clean_name(leaf), ITEM_CN)
    if any("ExitZone" in s for s in chain):
        return "exit", "出口"
    if any("FallZone" in s for s in chain):
        return "hazard", "坠落区"
    if "InteractableActor" in chain or "ClientInteractableActor" in chain:
        return "interact", clean_name(leaf)
    return None


STYLE = {
    "monster": ("#ff3b3b", 11, True),
    "player": ("#4fc3ff", 10, False),
    "item": ("#ffd84a", 9, False),
    "exit": ("#3dff8a", 11, True),
    "hazard": ("#ff8c1a", 9, False),
    "interact": ("#b0b0b0", 8, False),
}


# ---------------------------------------------------------------- 投影

def w2s(pov, target, w, h):
    (cx, cy, cz), (pitch, yaw, roll), fov = pov
    p, y_, r = (math.radians(a) for a in (pitch, yaw, roll))
    sp, cp, sy, cy_, sr, cr = math.sin(p), math.cos(p), math.sin(y_), math.cos(y_), math.sin(r), math.cos(r)
    ax = (cp * cy_, cp * sy, sp)
    ay = (sr * sp * cy_ - cr * sy, sr * sp * sy + cr * cy_, -sr * cp)
    az = (-(cr * sp * cy_ + sr * sy), cy_ * sr - cr * sp * sy, cr * cp)
    d = (target[0] - cx, target[1] - cy, target[2] - cz)
    tx = d[0] * ay[0] + d[1] * ay[1] + d[2] * ay[2]
    ty = d[0] * az[0] + d[1] * az[1] + d[2] * az[2]
    tz = d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2]
    half_w, half_h = w / 2, h / 2
    f = half_w / math.tan(math.radians(fov) / 2)
    if tz < 1.0:
        # 在身后：只保留左右/上下方向，供屏幕边缘箭头使用
        return (half_w + tx * 1e4, half_h - ty * 1e4), False
    return (half_w + tx * f / tz, half_h - ty * f / tz), True


# ---------------------------------------------------------------- 游戏读取

class Game:
    def __init__(self):
        pid = find_pid(PROCESS_NAME)
        if not pid:
            raise SystemExit(f"没找到 {PROCESS_NAME}，先启动游戏")
        self.pid = pid
        self.m = Mem(pid)
        base, _ = find_module(pid, PROCESS_NAME)
        g = locate_globals(self.m, base)
        print("[ETB] " + "  ".join(f"{k}=exe+{v - base:X}" for k, v in g.items()))
        self.ue = UE(self.m, g)
        self.gobj = g["GObjects"]
        self.globals = g
        self.class_cache = {}
        self.targets = []       # [(actor, root, 类别, 名称)]
        self.hidden = frozenset()   # 已被捡起（CanPickup=0）的道具，覆盖层不画
        self.world_name = "?"
        self.actor_cache = {}   # Actor 地址 -> 分类结果（False 表示不关心），增量扫描用
        self._scan_world = 0
        self._recheck = 0

    def clone(self, mem):
        """给其他线程用的副本：共享已定位的全局地址，但用独立的内存句柄和缓存（Mem 不是线程安全的）。"""
        g2 = Game.__new__(Game)
        g2.pid, g2.globals, g2.gobj = self.pid, self.globals, self.gobj
        g2.m = mem
        g2.ue = UE(mem, self.globals)
        g2.class_cache, g2.targets, g2.world_name = {}, [], "?"
        g2.hidden, g2.actor_cache, g2._scan_world, g2._recheck = frozenset(), {}, 0, 0
        return g2

    def world(self):
        return self.m.ptr(self.ue.gworld)

    def local(self):
        w = self.world()
        gi = self.m.ptr(w + OFF["World_GameInstance"])
        lp = self.m.ptr(self.m.ptr(gi + OFF["GI_LocalPlayers"]))
        pc = self.m.ptr(lp + OFF["Player_PC"])
        pawn = self.m.ptr(pc + OFF["Controller_Pawn"])
        return pc, pawn

    def world_time_offset(self):
        """用相机缓存的时间戳（就是当帧的 World->TimeSeconds）在 UWorld 里找 TimeSeconds 的偏移。"""
        if getattr(self, "_time_off", None):
            return self._time_off
        pc, _ = self.local()
        pcm = self.m.ptr(pc + OFF["PC_CameraManager"])
        ts = self.m.f32(pcm + OFF["PCM_POV"] - 0x10) if pcm else None
        raw = self.m.read(self.world(), 0x900) if ts else None
        if raw:
            for o in range(0x400, 0x900 - 0x14, 4):
                t, dt = struct.unpack_from("<f", raw, o)[0], struct.unpack_from("<f", raw, o + 0x10)[0]
                if abs(t - ts) < 0.5 and 0 < dt < 0.5:
                    self._time_off = o
                    return o
        return WORLD_TIME_FALLBACK

    def frame_stamp(self):
        """当前游戏帧的 World->TimeSeconds，每个游戏帧都会变，用来和游戏帧同步。"""
        w = self.world()
        return self.m.f32(w + self.world_time_offset()) if w else None

    def frame_delta(self):
        """游戏上一帧的耗时（秒），读 UWorld::DeltaTimeSeconds。"""
        dt = self.m.f32(self.world() + self.world_time_offset() + 0x10)
        return dt if dt and 0 < dt < 1 else None

    def camera(self, pc):
        pcm = self.m.ptr(pc + OFF["PC_CameraManager"])
        b = self.m.read(pcm + OFF["PCM_POV"], 0x1C)
        if not b:
            return None
        v = struct.unpack("<7f", b)
        if not (1.0 < v[6] < 179.0):
            return None
        return (v[0:3], v[3:6], v[6])

    RECHECK_PER_SCAN = 1000     # 每次扫描顺带重新核对这么多个已缓存 Actor 的类（防止地址被回收后复用）

    def refresh(self):
        """扫描所有关卡的 Actor，按类别筛选。

        增量：已经分类过的 Actor 地址直接用缓存，只读新出现的 Actor 的类，所以大关卡（几万个 Actor）
        每次也只要几毫秒；缓存每次轮流核对一部分，几秒内全部核对一遍。
        """
        w = self.world()
        if not w:
            self.targets, self.hidden = [], frozenset()
            return
        if w != self._scan_world:
            self.actor_cache, self._scan_world, self._recheck = {}, w, 0
            self.world_name = self.ue.objname(w)
        _, pawn = self.local()
        levels_ptr = self.m.ptr(w + OFF["World_Levels"])
        nlev = self.m.i32(w + OFF["World_Levels"] + 8) or 0
        actors = []
        for lvl in self.m.ptr_array(levels_ptr, min(nlev, 256)):
            if not lvl:
                continue
            arr = self.m.ptr(lvl + OFF["Level_Actors"])
            n = self.m.i32(lvl + OFF["Level_Actors"] + 8) or 0
            actors.extend(self.m.ptr_array(arr, min(n, 1 << 20)))

        old, cache = self.actor_cache, {}
        lo = self._recheck if self._recheck < len(actors) else 0
        hi = lo + self.RECHECK_PER_SCAN
        self._recheck = hi
        out, hidden = [], set()
        for i, a in enumerate(actors):
            if not a or a == pawn:
                continue
            info = old.get(a)
            if info is None or lo <= i < hi:
                cls = self.m.ptr(a + OFF["UObject_Class"])
                if not cls:
                    continue
                info = self.class_cache.get(cls)
                if info is None:
                    info = classify(self.ue.class_chain(cls)) or False
                    self.class_cache[cls] = info
            cache[a] = info
            if not info:
                continue
            root = self.m.ptr(a + OFF["Actor_Root"])
            if root:
                out.append((a, root, info[0], info[1]))
                if info[0] == "item" and self.m.read(a + OFF["DroppedItem_CanPickup"], 1) == b"\x00":
                    hidden.add(a)
        self.actor_cache = cache
        self.targets, self.hidden = out, frozenset(hidden)


# ---------------------------------------------------------------- 覆盖层窗口

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
KEY = 0x8000
VK_F8, VK_F9, VK_F10, VK_END = 0x77, 0x78, 0x79, 0x23
VK_ALT, VK_LBRACKET, VK_RBRACKET = 0x12, 0xDB, 0xDD

# 对齐补偿：游戏画面要经过渲染线程、GPU 和它自己的帧队列才显示出来，比内存里的相机晚几帧。
# 覆盖层每个游戏帧采样一次，再故意晚 N 帧显示，让标记和画面对上。Alt+[ / Alt+] 调整。
SYNC_DELAY_DEFAULT = 2
SYNC_DELAY_MAX = 8
INJECT_DELAY_DEFAULT = 1      # 注入版：Present 时读到的相机通常已经是下一帧的，取上一帧那份正好对齐
SETTINGS_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "etb-trainer", "overlay.json")


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass
TRANSPARENT = "#010101"

# 覆盖层刷新率跟随游戏帧率
OVERLAY_MIN_FPS = 30
OVERLAY_MAX_FPS = 144
OVERLAY_CPU_BUDGET = 0.6      # 画图最多占一个核心的 60%，画得慢就自动降刷新率
OVERLAY_IDLE_MS = 100         # 游戏不在前台 / 隐藏时的轮询间隔
PANEL_INTERVAL = 0.1          # 左侧文字面板每秒刷新 10 次就够了
WORLD_TIME_FALLBACK = 0x5A0   # UWorld::TimeSeconds（运行时会再核对一次）；DeltaTimeSeconds 在其后 0x10
FONT = "Microsoft YaHei UI"
BACKEND_CN = {"inject": "注入游戏画面", "gpu": "独立窗口 GPU", "tk": "tkinter"}


# ---------------------------------------------------------------- GPU 渲染后端

RENDER_MAGIC, RENDER_VERSION = 0x4F425445, 1          # "ETBO"，和 renderer/etb_render.cpp 保持一致
RENDER_BUF = 1 << 20
RENDER_HDR = 64
ANCHORS = {"nw": 0, "n": 1, "ne": 2, "w": 3, "center": 4, "e": 5, "sw": 6, "s": 7, "se": 8}

k32.CreateFileMappingW.restype = wt.HANDLE
k32.CreateFileMappingW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
k32.CreateEventW.restype = wt.HANDLE
k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
k32.SetEvent.argtypes = [wt.HANDLE]
k32.GetTickCount.restype = wt.DWORD


def renderer_path():
    """etb_render.exe：exe 版本从 PyInstaller 解压目录找，源码版本在 renderer/ 下。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "renderer")
    return os.path.join(base, "etb_render.exe")


def argb(color):
    if not color:
        return 0
    return 0xFF000000 | int(color.lstrip("#"), 16)


class D2DCanvas:
    """接口和 tkinter.Canvas 用到的那几个方法一致：create_text/oval/line/polygon + delete(tag)。

    绘制命令按标签分组缓存，flush() 时拼起来写进共享内存的空闲缓冲区，再递增 seq 通知渲染器。
    """

    def __init__(self):
        exe = renderer_path()
        if not os.path.exists(exe):
            raise FileNotFoundError(exe)
        self.name = f"Local\\ETB_Overlay_{os.getpid()}"
        size = RENDER_HDR + 2 * RENDER_BUF
        self.hmap = k32.CreateFileMappingW(wt.HANDLE(-1), None, 0x04, 0, size, self.name)   # PAGE_READWRITE
        self.base = k32.MapViewOfFile(self.hmap, 0x000F001F, 0, 0, size)                    # FILE_MAP_ALL_ACCESS
        if not self.base:
            raise OSError("共享内存创建失败")
        ctypes.memmove(self.base, struct.pack("<II", RENDER_MAGIC, RENDER_VERSION), 8)
        self.event = k32.CreateEventW(None, False, False, self.name + "_evt")   # 自动复位；新帧写好后唤醒渲染器
        self.proc = subprocess.Popen([exe, self.name, str(os.getpid())])
        time.sleep(0.3)
        if self.proc.poll() is not None:
            raise RuntimeError(f"渲染器启动失败，退出码 {self.proc.returncode}")
        try:
            dpi = u32.GetDpiForSystem()
        except Exception:
            dpi = 96
        self.pt2px = dpi / 72.0             # tkinter 的字号是磅，换算成像素
        self.layers = {}
        self.seq = 0
        self.idx = 0
        self.last_empty = False
        self.delay = 0                      # 晚几帧显示（对齐补偿）
        self.history = collections.deque()

    def _add(self, tags, data):
        self.layers.setdefault(tags or "", []).append(data)

    def delete(self, tag):
        if tag == "all":
            self.layers.clear()
        else:
            self.layers.pop(tag, None)

    def create_text(self, x, y, text="", fill="#000000", font=None, anchor="center", tags=None):
        size, bold = 10, False
        if font:
            size = font[1]
            bold = len(font) > 2 and "bold" in font[2]
        s = str(text).encode("utf-16-le")
        self._add(tags, struct.pack("<BffIfBBH", 1, x, y, argb(fill), size * self.pt2px, bold,
                                    ANCHORS.get(anchor, 4), len(s) // 2) + s)

    def create_oval(self, x0, y0, x1, y1, fill="", outline="#000000", width=1, tags=None, **_):
        self._add(tags, struct.pack("<BffffIIf", 2, (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2,
                                    abs(y1 - y0) / 2, argb(fill), argb(outline), width))

    def create_line(self, x0, y0, x1, y1, fill="#000000", width=1, tags=None, **_):
        self._add(tags, struct.pack("<BffffIf", 3, x0, y0, x1, y1, argb(fill), width))

    def create_polygon(self, *coords, fill="#000000", outline="", width=1, tags=None, **_):
        pts = list(coords[0]) if len(coords) == 1 else list(coords)
        n = len(pts) // 2
        self._add(tags, struct.pack("<BHIIf", 4, n, argb(fill), argb(outline), width) +
                  struct.pack(f"<{n * 2}f", *pts[:n * 2]))

    def flush(self, rect):
        data = b"".join(b"".join(v) for v in self.layers.values())
        if data:
            self.history.append(data)
            while len(self.history) > self.delay + 1:
                self.history.popleft()
            data = self.history[0]
        else:
            self.history.clear()             # 隐藏后不要再把旧帧放出来
        if not data and self.last_empty:
            return
        self.last_empty = not data
        data = data[:RENDER_BUF]
        idx = self.idx ^ 1
        ctypes.memmove(self.base + RENDER_HDR + idx * RENDER_BUF, data, len(data))
        x, y, w, h = rect or (0, 0, 0, 0)
        # Header：magic, version, seq, active, x, y, w, h, visible, quit, used[2]
        ctypes.memmove(self.base + 12, struct.pack("<I4iII", idx, x, y, w, h, 1, 0), 28)
        ctypes.memmove(self.base + 40 + idx * 4, struct.pack("<I", len(data)), 4)
        self.idx = idx
        self.seq += 1
        ctypes.memmove(self.base + 8, struct.pack("<i", self.seq), 4)   # 最后写 seq，渲染器据此取新帧
        k32.SetEvent(self.event)

    def close(self):
        try:
            ctypes.memmove(self.base + 36, struct.pack("<I", 1), 4)      # quit = 1
            self.proc.wait(2)
        except Exception:
            self.proc.kill()


def list_modules(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    me = MODULEENTRY32W(dwSize=ctypes.sizeof(MODULEENTRY32W))
    ok = k32.Module32FirstW(snap, ctypes.byref(me))
    out = []
    try:
        while ok:
            out.append(me.szModule)
            ok = k32.Module32NextW(snap, ctypes.byref(me))
    finally:
        k32.CloseHandle(snap)
    return out


def hook_dll_path():
    base = getattr(sys, "_MEIPASS", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "renderer")
    return os.path.join(base, "etb_hook.dll")


k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
k32.CreateRemoteThread.restype = wt.HANDLE
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                                   wt.DWORD, ctypes.c_void_p]
k32.GetModuleHandleW.restype = wt.HMODULE
k32.GetProcAddress.restype = ctypes.c_void_p
k32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]


def inject_dll(pid, path):
    """CreateRemoteThread(LoadLibraryW)。kernel32 在所有进程里基址相同，本进程的函数地址可以直接用。"""
    h = k32.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x00100000, False, pid)
    if not h:
        raise OSError(f"OpenProcess 失败，错误码 {ctypes.get_last_error()}")
    try:
        data = (path + "\0").encode("utf-16-le")
        mem = k32.VirtualAllocEx(h, None, len(data), 0x3000, 0x04)
        if not mem:
            raise OSError("VirtualAllocEx 失败")
        n = ctypes.c_size_t()
        k32.WriteProcessMemory(h, mem, data, len(data), ctypes.byref(n))
        fn = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        th = k32.CreateRemoteThread(h, None, 0, fn, mem, 0, None)
        if not th:
            raise OSError(f"CreateRemoteThread 失败，错误码 {ctypes.get_last_error()}")
        k32.WaitForSingleObject(th, 5000)
        code = wt.DWORD()
        k32.GetExitCodeThread(th, ctypes.byref(code))
        k32.CloseHandle(th)
        k32.VirtualFreeEx(h, mem, 0, 0x8000)
        if not code.value:
            raise OSError("LoadLibraryW 返回 0（DLL 加载失败）")
    finally:
        k32.CloseHandle(h)


class InjectCanvas(D2DCanvas):
    """把 etb_hook.dll 注入游戏，在游戏的 Present 里画（和画面同一帧）。

    共享内存名 Local\\ETB_Inject_<游戏PID>。世界坐标标记用 marker() 发给 DLL，由 DLL 在 Present 时
    读相机和 Actor 位置再投影；面板等 2D 内容和独立窗口版一样用 create_* 画。
    """

    def __init__(self, game_pid):
        src = hook_dll_path()
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        self.game_pid = game_pid
        self.name = f"Local\\ETB_Inject_{game_pid}"
        size = RENDER_HDR + 2 * RENDER_BUF
        self.hmap = k32.CreateFileMappingW(wt.HANDLE(-1), None, 0x04, 0, size, self.name)
        self.base = k32.MapViewOfFile(self.hmap, 0x000F001F, 0, 0, size)
        if not self.base:
            raise OSError("共享内存创建失败")
        self.proc = None
        self.pt2px = self._pt2px()
        self.layers = {}
        self.seq = 0
        self.idx = 0
        self.delay = INJECT_DELAY_DEFAULT

        # DLL 复制到临时目录再注入：游戏会一直占着这个文件，exe 版本的解压目录退出时要删掉
        with open(src, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()[:10]
        dll_name = f"etb_hook_{digest}.dll"
        loaded = [m for m in list_modules(game_pid) if m.lower().startswith("etb_hook")]
        # 上次留下的旧版 DLL：让它自己卸载（共享内存是同一块，写 quit 它就能看到）
        stale = [m for m in loaded if m.lower() != dll_name.lower()]
        if stale:
            self._header(quit=1)
            for _ in range(30):
                time.sleep(0.1)
                if not any(m.lower().startswith("etb_hook") and m.lower() != dll_name.lower()
                           for m in list_modules(game_pid)):
                    break
        self._header(quit=0)
        ctypes.memmove(self.base + 56, struct.pack("<i", 0), 4)       # loaded = 0，等 DLL 报告
        if dll_name.lower() not in (m.lower() for m in loaded) or stale:
            tmp = os.path.join(os.environ.get("TEMP", "."), "etb-trainer")
            os.makedirs(tmp, exist_ok=True)
            dst = os.path.join(tmp, dll_name)
            if not os.path.exists(dst):
                shutil.copyfile(src, dst)
            inject_dll(game_pid, dst)
        # 等 DLL 在 Present 里初始化完（1=正常，2=不支持）
        for _ in range(50):
            self.flush(None)
            state = struct.unpack("<i", ctypes.string_at(self.base + 56, 4))[0]
            if state == 1:
                return
            if state == 2:
                self.close()
                raise RuntimeError("游戏不是 D3D11 或后台缓冲格式不支持，详见 %TEMP%\\etb_hook.log")
            time.sleep(0.1)
        self.close()
        raise RuntimeError("DLL 没有响应（游戏没在渲染？）")

    @staticmethod
    def _pt2px():
        try:
            return u32.GetDpiForSystem() / 72.0
        except Exception:
            return 96 / 72.0

    def _header(self, quit=0):
        ctypes.memmove(self.base, struct.pack("<II", RENDER_MAGIC, RENDER_VERSION), 8)
        ctypes.memmove(self.base + 36, struct.pack("<I", quit), 4)

    def camera(self, pov_addr, origin_addr, rcx, rcy, radius, rng, tags=None):
        self._add(tags, struct.pack("<BQQffff", 6, pov_addr or 0, origin_addr or 0, rcx, rcy, radius, rng))

    def marker(self, loc_addr, loc, color, px, arrow_px, bold, flags, label, tags=None):
        s = str(label).encode("utf-16-le")
        x, y, z = loc
        self._add(tags, struct.pack("<BQfffIffBBH", 5, loc_addr or 0, x, y, z, argb(color), px, arrow_px,
                                    bool(bold), flags, len(s) // 2) + s)

    def flush(self, rect):
        data = b"".join(b"".join(v) for v in self.layers.values())[:RENDER_BUF]
        idx = self.idx ^ 1
        ctypes.memmove(self.base + RENDER_HDR + idx * RENDER_BUF, data, len(data))
        x, y, w, h = rect or (0, 0, 0, 0)
        ctypes.memmove(self.base + 12, struct.pack("<I4iII", idx, x, y, w, h, 1, 0), 28)
        ctypes.memmove(self.base + 40 + idx * 4, struct.pack("<I", len(data)), 4)
        ctypes.memmove(self.base + 48, struct.pack("<II", self.delay, k32.GetTickCount() & 0xFFFFFFFF), 8)
        self.idx = idx
        self.seq += 1
        ctypes.memmove(self.base + 8, struct.pack("<i", self.seq), 4)

    def close(self):
        """让 DLL 恢复虚表并卸载自己。"""
        try:
            self._header(quit=1)
            for _ in range(30):
                if struct.unpack("<i", ctypes.string_at(self.base + 56, 4))[0] != 1:
                    break
                time.sleep(0.05)
        except Exception:
            pass


def game_rect(pid):
    """找游戏主窗口，返回客户区屏幕坐标 (x, y, w, h)。"""
    result = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            rc = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(rc))
            if rc.right > 200:
                pt = wt.POINT(0, 0)
                u32.ClientToScreen(hwnd, ctypes.byref(pt))
                result.append((pt.x, pt.y, rc.right, rc.bottom))
                return False
        return True

    u32.EnumWindows(cb, 0)
    return result[0] if result else None


class Overlay:
    def __init__(self, game):
        self.g = game
        self.show = True
        self.show_items = True
        self.show_interact = False
        self.prev_keys = {}
        threading.Thread(target=self.scan_loop, daemon=True).start()
        self.trainer = None
        try:
            import etb_trainer
            self.trainer = etb_trainer.Trainer(game)
            self.trainer.start()
        except Exception as e:  # 功能模块起不来时覆盖层照常工作
            print(f"[ETB] 功能模块未启动：{e}")

        self.root = None
        self.backend = "tk"
        self.backend_note = ""
        if "--tk" not in sys.argv and "--window" not in sys.argv:
            try:
                self.canvas = InjectCanvas(game.pid)
                self.backend = "inject"
            except Exception as e:
                self.backend_note = f"注入不可用：{e}"
                print(f"[ETB] {self.backend_note}")
        if self.backend == "tk" and "--tk" not in sys.argv:
            try:
                self.canvas = D2DCanvas()
                self.backend = "gpu"
            except Exception as e:
                print(f"[ETB] GPU 渲染器不可用，改用 tkinter：{e}")
        if self.backend == "tk":
            self.root = tk.Tk()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-transparentcolor", TRANSPARENT)
            self.root.config(bg=TRANSPARENT)
            self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            self.root.update_idletasks()
            hwnd = u32.GetParent(self.root.winfo_id())
            ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.geom = None
        self.ui = 1.0
        self.layer = "fast"
        self.active = False           # 本帧有没有真正画东西（决定下一帧的间隔）
        self.game_fps = 0.0
        self.overlay_fps = 0.0
        self.draw_cost = 0.0
        self._frames, self._fps_t = 0, time.time()
        self._panel_t = 0.0
        self._rect, self._rect_t = None, 0.0
        self._stamp = None
        self.settings = load_settings()
        self.delay_key = {"gpu": "sync_delay", "inject": "inject_delay"}.get(self.backend)
        if self.delay_key:
            default = INJECT_DELAY_DEFAULT if self.backend == "inject" else SYNC_DELAY_DEFAULT
            self.canvas.delay = int(self.settings.get(self.delay_key, default))

    def scan_loop(self):
        """后台扫描 Actor（独立的内存句柄），结果整体替换到 self.g 上，画图线程永远不用等扫描。"""
        g = self.g.clone(Mem(self.g.pid))
        while True:
            try:
                g.refresh()
                self.g.targets, self.g.hidden, self.g.world_name = g.targets, g.hidden, g.world_name
            except Exception:
                pass                 # 关卡切换时指针会短暂失效，下次再扫
            time.sleep(0.5)

    def pressed(self, vk):
        down = bool(u32.GetAsyncKeyState(vk) & KEY)
        was = self.prev_keys.get(vk, False)
        self.prev_keys[vk] = down
        return down and not was

    def game_alive(self):
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(self.g.m.h, ctypes.byref(code)):
            return False
        return code.value == 259     # STILL_ACTIVE

    def game_focused(self):
        """游戏不在前台（切到别的窗口）时不画，免得盖住其他程序。"""
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), ctypes.byref(p))
        return p.value == self.g.pid

    def text(self, x, y, s, color, size=10, bold=False, anchor="nw"):
        f = (FONT, round(size * self.ui), "bold" if bold else "normal")
        # 只画一层黑色阴影：四向描边要 5 个元素，实测覆盖层只能跑 38 帧；单阴影 2 个元素能到 87 帧
        self.canvas.create_text(x + 1, y + 1, text=s, fill="#000000", font=f, anchor=anchor, tags=self.layer)
        self.canvas.create_text(x, y, text=s, fill=color, font=f, anchor=anchor, tags=self.layer)

    def oval(self, *a, **k):
        self.canvas.create_oval(*a, tags=self.layer, **k)

    def line(self, *a, **k):
        self.canvas.create_line(*a, tags=self.layer, **k)

    def polygon(self, *a, **k):
        self.canvas.create_polygon(*a, tags=self.layer, **k)

    def tick(self):
        t0 = time.perf_counter()
        try:
            self.frame()
        except Exception as e:  # 关卡切换时指针会短暂失效，跳过这一帧
            self.canvas.delete("all")
            self.layer = "panel"
            self.text(20, 20, f"读取中… {type(e).__name__}", "#ffffff")
            self.active = False
        if self.backend in ("gpu", "inject"):
            self.canvas.flush(self.geom)
        cost = time.perf_counter() - t0
        if self.active:
            self.draw_cost = cost if not self.draw_cost else self.draw_cost * 0.9 + cost * 0.1
            self._frames += 1
        now = time.time()
        if now - self._fps_t >= 1.0:
            self.overlay_fps, self._frames, self._fps_t = self._frames / (now - self._fps_t), 0, now
        if self.root:
            self.root.after(self.next_delay(), self.tick)

    def next_delay(self):
        """下一帧等多久（毫秒）：跟随游戏帧率，限制在 30~144，并且不让画图吃掉太多 CPU。"""
        if not self.active:
            return OVERLAY_IDLE_MS
        fps = min(max(self.game_fps or 60.0, OVERLAY_MIN_FPS), OVERLAY_MAX_FPS)
        if self.draw_cost > 0:
            fps = max(min(fps, OVERLAY_CPU_BUDGET / self.draw_cost), OVERLAY_MIN_FPS)
        return max(1, int(1000.0 / fps - self.draw_cost * 1000))

    def frame(self):
        if self.pressed(VK_END):
            if self.trainer:
                self.trainer.running = False        # 线程退出前会还原所有改动并卸下钩子
                self.trainer_thread_wait()
            self.shutdown()
        if self.pressed(VK_F8):
            self.show = not self.show
        if self.pressed(VK_F9):
            self.show_items = not self.show_items
        if self.pressed(VK_F10):
            self.show_interact = not self.show_interact
        lb, rb = self.pressed(VK_LBRACKET), self.pressed(VK_RBRACKET)
        if self.delay_key and (lb or rb) and u32.GetAsyncKeyState(VK_ALT) & KEY:
            d = min(max(self.canvas.delay + (1 if rb else -1), 0), SYNC_DELAY_MAX)
            self.canvas.delay = self.settings[self.delay_key] = d
            save_settings(self.settings)
            self._panel_t = 0.0              # 面板马上刷新显示新数值

        now = time.time()
        if now - self._rect_t > 0.5:          # 枚举窗口比较慢，每 0.5 秒查一次窗口位置
            self._rect, self._rect_t = game_rect(self.g.pid), now
        rect = self._rect
        if not rect and not self.game_alive():
            self.shutdown()              # 游戏已退出：钩子和改动随进程一起消失，不需要还原
        self.active = False
        if not rect:
            self.canvas.delete("all")
            return
        if rect != self.geom:
            x, y, w, h = rect
            if self.root:
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            self.geom = rect
        _, _, W, H = rect
        self.ui = min(max(H / 1080.0, 1.0), 2.0)   # 界面缩放：以 1080p 为基准，2K 约 1.33、4K 为 2

        if not self.show or not self.game_focused():
            self.canvas.delete("all")
            return
        self.active = True
        dt = self.g.frame_delta()
        if dt:
            fps = 1.0 / dt
            self.game_fps = fps if not self.game_fps else self.game_fps * 0.9 + fps * 0.1
        self.canvas.delete("fast")
        self.layer = "fast"

        m = self.g.m
        pc, pawn = self.g.local()
        pov = self.g.camera(pc)
        me = None
        if pawn:
            r = m.ptr(pawn + OFF["Actor_Root"])
            me = m.vec(r + OFF["Scene_WorldLoc"]) if r else None
        if not pov:
            return
        origin = me or pov[0]
        inject = self.backend == "inject"
        if inject:
            pcm = m.ptr(pc + OFF["PC_CameraManager"])
            root = m.ptr(pawn + OFF["Actor_Root"]) if pawn else 0
            rcx, rcy, R = self.radar_geom(W)
            self.canvas.camera(pcm + OFF["PCM_POV"], root + OFF["Scene_WorldLoc"] if root else 0,
                               rcx, rcy, R, self.RADAR_RANGE, tags=self.layer)
            self.radar_frame(W)          # 雷达底图先画，DLL 画的点在上面

        rows = []
        placed = []   # 已画标签的位置，用来让重叠的标签往上错开
        hidden = self.g.hidden
        for actor, root, cat, label in self.g.targets:
            if cat == "item" and not self.show_items:
                continue
            if cat == "interact" and not self.show_interact:
                continue
            loc = m.vec(root + OFF["Scene_WorldLoc"])
            if not loc or (loc[0] == 0 and loc[1] == 0 and loc[2] == 0):
                continue
            if actor in hidden:
                continue
            dist = math.dist(origin, loc) / 100.0
            rows.append((cat, label, dist, loc))
            color, size, bold = STYLE[cat]
            if inject:
                big = cat in ("monster", "player", "exit")
                flags = (1 if big else 0) | 2 | (4 if cat == "monster" else 0) | (8 if big else 0)
                self.canvas.marker(root + OFF["Scene_WorldLoc"], loc, color,
                                   round(size * self.ui) * self.canvas.pt2px,
                                   round(9 * self.ui) * self.canvas.pt2px, bold, flags, label, tags=self.layer)
                continue
            (sx, sy), visible = w2s(pov, loc, W, H)
            if visible and 0 <= sx <= W and 0 <= sy <= H:
                self.oval(sx - 3, sy - 3, sx + 3, sy + 3, fill=color, outline="#000000")
                ly = sy - 6
                while any(abs(px - sx) < 70 and abs(py - ly) < 15 for px, py in placed):
                    ly -= 15
                placed.append((sx, ly))
                if ly < sy - 6:
                    self.line(sx, sy - 3, sx, ly, fill=color)
                self.text(sx, ly, f"{label} {dist:.0f}m", color, size, bold, anchor="s")
            elif cat in ("monster", "exit", "player"):
                # 屏幕外：在边缘画方向提示
                cx, cy = W / 2, H / 2
                ang = math.atan2(sy - cy, sx - cx)
                ex = cx + math.cos(ang) * (W / 2 - 40)
                ey = cy + math.sin(ang) * (H / 2 - 40)
                ca, sa = math.cos(ang), math.sin(ang)
                tri = [ex + ca * 12, ey + sa * 12,
                       ex - ca * 8 - sa * 8, ey - sa * 8 + ca * 8,
                       ex - ca * 8 + sa * 8, ey - sa * 8 - ca * 8]
                self.polygon(tri, fill=color, outline="#000000")
                self.text(ex, ey + 14, f"{label} {dist:.0f}m", color, 9, bold, anchor="n")

        if not inject:
            self.radar(rows, origin, pov[1][1], W)
        if now - self._panel_t >= PANEL_INTERVAL:
            self._panel_t = now
            self.canvas.delete("panel")
            self.layer = "panel"
            self.panel(rows, me, pawn, origin)
            self.layer = "fast"

    def panel(self, rows, me, pawn, origin=None):
        m = self.g.m
        lines = [(f"关卡：{self.g.world_name}", "#ffffff"),
                 (f"帧率：游戏 {self.game_fps:.0f} / 覆盖层 {self.overlay_fps:.0f}"
                  f"（{BACKEND_CN[self.backend]}）"
                  + (f"  对齐补偿 {self.canvas.delay} 帧" if self.delay_key else ""), "#cccccc")]
        if self.backend_note:
            lines.append((self.backend_note, "#ff9060"))
        if me:
            lines.append((f"坐标：{me[0]:.0f}, {me[1]:.0f}, {me[2]:.0f}", "#cccccc"))
        if pawn:
            st = m.f32(pawn + OFF["Char_Stamina"])
            if st is not None and -1 < st < 10000:
                lines.append((f"体力：{st:.0f}", "#cccccc"))

        monsters = sorted((r for r in rows if r[0] == "monster"), key=lambda r: r[2])
        if monsters:
            near = monsters[0][2]
            warn = "#ff3b3b" if near < 15 else ("#ffb03b" if near < 35 else "#ff8080")
            lines.append((f"⚠ 怪物 {len(monsters)} 只，最近 {near:.0f}m", warn))
            for _, label, d, _ in monsters[:6]:
                lines.append((f"   {label}  {d:.0f}m", "#ff8080"))
        else:
            lines.append(("怪物：无", "#80ff80"))

        exits = sorted((r for r in rows if r[0] == "exit"), key=lambda r: r[2])
        for _, label, d, _ in exits[:3]:
            lines.append((f"{label}  {d:.0f}m", STYLE["exit"][0]))

        items = sorted((r for r in rows if r[0] == "item"), key=lambda r: r[2])
        if items:
            lines.append((f"道具 {len(items)} 个：", STYLE["item"][0]))
            for _, label, d, _ in items[:8]:
                lines.append((f"   {label}  {d:.0f}m", STYLE["item"][0]))

        mates = self.teammates(pawn, origin)
        if mates:
            alive_n = sum(1 for x in mates if x[1] == "存活")
            lines.append((f"队友 {alive_n}/{len(mates)} 存活：", STYLE["player"][0]))
            for name, state, dist, san in mates:
                d = f"{dist:.0f}m" if dist is not None else "-"
                sv = f"  理智 {san:.0f}" if san is not None and 0 <= san <= 1000 else ""
                color = STYLE["player"][0] if state == "存活" else "#888888"
                lines.append((f"   {name[:16]}  {state}  {d}{sv}", color))

        t = self.trainer
        if t:
            if t.error:
                lines.append((t.error, "#ff6060"))
            for k, v in t.status.items():
                lines.append((f"● {k}：{v}", "#c08cff"))
            if t.message and time.time() - t.message_t < 4:
                lines.append((t.message, "#ffffff"))
            if u32.GetAsyncKeyState(0x12) & 0x8000:      # 按住 Alt
                for h in t.help_lines():
                    lines.append((h, "#bbbbbb"))
            else:
                lines.append(("按住 Alt 查看全部热键", "#888888"))
        lines.append(("F8 隐藏  F9 道具  F10 可交互物  End 还原并退出", "#888888"))
        if self.delay_key:
            lines.append(("Alt+[ / Alt+] 调对齐补偿：标记比画面先动就加，落后就减", "#888888"))
        y = 56 * self.ui   # 让开游戏左上角自带的玩家名/语音图标
        for s, c in lines:
            self.text(14 * self.ui, y, s, c, 10)
            y += 19 * self.ui

    def shutdown(self):
        if self.root:
            self.root.destroy()
        else:
            self.canvas.close()
        sys.exit(0)

    def trainer_thread_wait(self, timeout=5.0):
        t0 = time.time()
        while self.trainer.running is False and time.time() - t0 < timeout:
            if getattr(self.trainer, "cleaned", False):
                break
            time.sleep(0.05)

    def teammates(self, my_pawn, origin):
        """[(名字, 状态, 距离m 或 None, 理智)]：读 GameState.PlayerArray 和 PlayersAlive。"""
        m, ue = self.g.m, self.g.ue
        gs = m.ptr(self.g.world() + OFF["World_GameState"])
        if not gs:
            return []
        alive = set(m.ptr_array(m.ptr(gs + OFF["GS_PlayersAlive"]), m.i32(gs + OFF["GS_PlayersAlive"] + 8) or 0))
        out = []
        for ps in m.ptr_array(m.ptr(gs + OFF["GS_PlayerArray"]), min(m.i32(gs + OFF["GS_PlayerArray"] + 8) or 0, 16)):
            pawn = m.ptr(ps + OFF["PS_Pawn"])
            if not ps or pawn == my_pawn:
                continue
            name = ue.fstring(ps + OFF["PS_Name"]) or "?"
            cls = ue.objname(m.ptr(pawn + 0x10)) if pawn else ""
            dead = (not pawn or "Spectator" in cls or (alive and pawn not in alive)   # 大厅里存活列表是空的
                    or (cls == "BPCharacter_Demo_C" and m.read(pawn + OFF["Char_IsDead"], 1) == b"\x01"))
            dist = None
            if pawn and not dead:
                r = m.ptr(pawn + OFF["Actor_Root"])
                loc = m.vec(r + OFF["Scene_WorldLoc"]) if r else None
                dist = math.dist(origin, loc) / 100 if loc and origin else None
            san = m.f32(ps + OFF["PS_Sanity"])
            out.append((name, "阵亡" if dead else "存活", dist, san))
        return out

    # ---- 雷达：右上角俯视图，镜头朝向永远朝上
    RADAR_R = 95
    RADAR_RANGE = 40.0   # 米

    def radar_geom(self, W):
        R = self.RADAR_R * self.ui
        return W - R - 16, R + 16, R

    def radar_frame(self, W):
        cx, cy, R = self.radar_geom(W)
        self.oval(cx - R, cy - R, cx + R, cy + R, outline="#9a9a9a", width=2)
        self.oval(cx - R / 2, cy - R / 2, cx + R / 2, cy + R / 2, outline="#555555")
        self.line(cx, cy - R, cx, cy + R, fill="#444444")
        self.line(cx - R, cy, cx + R, cy, fill="#444444")
        self.text(cx + R - 4, cy + R - 2, f"{self.RADAR_RANGE:.0f}m", "#aaaaaa", 8, anchor="se")
        self.polygon(cx, cy - 7, cx - 5, cy + 5, cx + 5, cy + 5, fill="#ffffff", outline="#000000")

    def radar(self, rows, origin, yaw, W):
        cx, cy, R = self.radar_geom(W)
        rng = self.RADAR_RANGE
        self.radar_frame(W)
        a = math.radians(yaw)
        ca, sa = math.cos(a), math.sin(a)
        order = {"item": 0, "interact": 0, "hazard": 1, "exit": 2, "player": 3, "monster": 4}
        for cat, label, dist, loc in sorted(rows, key=lambda r: order.get(r[0], 0)):
            dx, dy = loc[0] - origin[0], loc[1] - origin[1]
            fwd = (dx * ca + dy * sa) / 100.0       # 前方为正
            right = (-dx * sa + dy * ca) / 100.0    # 右方为正
            d = math.hypot(fwd, right)
            if d > rng:
                if cat != "monster":
                    continue
                fwd, right = fwd / d * rng, right / d * rng   # 远处的怪物钉在雷达边缘
            px, py = cx + right / rng * R, cy - fwd / rng * R
            color = STYLE[cat][0]
            rad = 5 if cat in ("monster", "player", "exit") else 3
            self.oval(px - rad, py - rad, px + rad, py + rad, fill=color, outline="#000000")

    def run(self):
        if self.root:
            self.tick()
            self.root.mainloop()
            return
        while True:                          # GPU 后端没有 tk 事件循环：每个游戏帧采样一次
            self.tick()
            if not self.active:
                time.sleep(OVERLAY_IDLE_MS / 1000.0)
                continue
            if self.backend == "inject":
                time.sleep(1 / 60)
            else:
                self.wait_game_frame()

    def wait_game_frame(self, timeout=0.05):
        """等游戏出下一帧（TimeSeconds 变化）；暂停或读不到时最多等 timeout 秒。"""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            try:
                st = self.g.frame_stamp()
            except Exception:
                st = None
            if st is not None and st != self._stamp:
                self._stamp = st
                return
            time.sleep(0.0005)


def main():
    sys.setswitchinterval(0.0005)    # 后台线程（扫描、热键功能）别占着 GIL 太久，画图线程能及时拿到
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 坐标和游戏窗口一致
    except Exception:
        pass
    # Windows 默认定时器精度约 15.6ms，tkinter 的 after(3) 实际要等十几毫秒；调到 1ms 才跟得上高帧率
    ctypes.windll.winmm.timeBeginPeriod(1)
    try:
        game = Game()
    except BaseException as e:   # 双击 exe 时没有控制台，用弹窗说明为什么没启动
        msg = e.code if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
        u32.MessageBoxW(None, str(msg), "ETB Trainer", 0x10)
        raise SystemExit(1)
    Overlay(game).run()


if __name__ == "__main__":
    main()
