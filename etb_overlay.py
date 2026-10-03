"""Escape the Backrooms 信息覆盖层（只读内存，不注入、不写入）。

显示怪物、道具、出口、危险区、队友的位置和距离，左上角是信息面板。
游戏需用「窗口化」或「无边框窗口」模式，独占全屏时覆盖层会被盖住。

热键：F8 显示/隐藏全部　F9 切换道具　F10 切换可交互物　End 退出
"""

import ctypes
import ctypes.wintypes as wt
import math
import re
import struct
import sys
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
    Char_Stamina=0x878,
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
        self.world_name = "?"

    def clone(self, mem):
        """给其他线程用的副本：共享已定位的全局地址，但用独立的内存句柄和缓存（Mem 不是线程安全的）。"""
        g2 = Game.__new__(Game)
        g2.pid, g2.globals, g2.gobj = self.pid, self.globals, self.gobj
        g2.m = mem
        g2.ue = UE(mem, self.globals)
        g2.class_cache, g2.targets, g2.world_name = {}, [], "?"
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

    def camera(self, pc):
        pcm = self.m.ptr(pc + OFF["PC_CameraManager"])
        b = self.m.read(pcm + OFF["PCM_POV"], 0x1C)
        if not b:
            return None
        v = struct.unpack("<7f", b)
        if not (1.0 < v[6] < 179.0):
            return None
        return (v[0:3], v[3:6], v[6])

    def refresh(self):
        """重新扫描所有关卡的 Actor，按类别筛选（每 0.5 秒一次）。"""
        w = self.world()
        if not w:
            self.targets = []
            return
        self.world_name = self.ue.objname(w)
        _, pawn = self.local()
        levels_ptr = self.m.ptr(w + OFF["World_Levels"])
        nlev = self.m.i32(w + OFF["World_Levels"] + 8) or 0
        out = []
        for lvl in self.m.ptr_array(levels_ptr, min(nlev, 256)):
            if not lvl:
                continue
            arr = self.m.ptr(lvl + OFF["Level_Actors"])
            n = self.m.i32(lvl + OFF["Level_Actors"] + 8) or 0
            for a in self.m.ptr_array(arr, n):
                if not a or a == pawn:
                    continue
                cls = self.m.ptr(a + OFF["UObject_Class"])
                if not cls:
                    continue
                info = self.class_cache.get(cls)
                if info is None:
                    info = classify(self.ue.class_chain(cls)) or False
                    self.class_cache[cls] = info
                if not info:
                    continue
                root = self.m.ptr(a + OFF["Actor_Root"])
                if root:
                    out.append((a, root, info[0], info[1]))
        self.targets = out


# ---------------------------------------------------------------- 覆盖层窗口

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
KEY = 0x8000
VK_F8, VK_F9, VK_F10, VK_END = 0x77, 0x78, 0x79, 0x23
TRANSPARENT = "#010101"
FONT = "Microsoft YaHei UI"


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
        self.last_refresh = 0.0
        self.prev_keys = {}
        self.trainer = None
        try:
            import etb_trainer
            self.trainer = etb_trainer.Trainer(game)
            self.trainer.start()
        except Exception as e:  # 功能模块起不来时覆盖层照常工作
            print(f"[ETB] 功能模块未启动：{e}")

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
        f = (FONT, size, "bold" if bold else "normal")
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):   # 黑色描边，任何背景都看得清
            self.canvas.create_text(x + dx, y + dy, text=s, fill="#000000", font=f, anchor=anchor)
        self.canvas.create_text(x, y, text=s, fill=color, font=f, anchor=anchor)

    def tick(self):
        try:
            self.frame()
        except Exception as e:  # 关卡切换时指针会短暂失效，跳过这一帧
            self.canvas.delete("all")
            self.text(20, 20, f"读取中… {type(e).__name__}", "#ffffff")
        self.root.after(33, self.tick)

    def frame(self):
        if self.pressed(VK_END):
            if self.trainer:
                self.trainer.running = False        # 线程退出前会还原所有改动并卸下钩子
                self.trainer_thread_wait()
            self.root.destroy()
            sys.exit(0)
        if self.pressed(VK_F8):
            self.show = not self.show
        if self.pressed(VK_F9):
            self.show_items = not self.show_items
        if self.pressed(VK_F10):
            self.show_interact = not self.show_interact

        rect = game_rect(self.g.pid)
        if not rect and not self.game_alive():
            self.root.destroy()          # 游戏已退出：钩子和改动随进程一起消失，不需要还原
            sys.exit(0)
        if not rect:
            self.canvas.delete("all")
            return
        if rect != self.geom:
            x, y, w, h = rect
            self.root.geometry(f"{w}x{h}+{x}+{y}")
            self.geom = rect
        _, _, W, H = rect

        now = time.time()
        if now - self.last_refresh > 0.5:
            self.g.refresh()
            self.last_refresh = now

        self.canvas.delete("all")
        if not self.show or not self.game_focused():
            return

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

        rows = []
        placed = []   # 已画标签的位置，用来让重叠的标签往上错开
        for actor, root, cat, label in self.g.targets:
            if cat == "item" and not self.show_items:
                continue
            if cat == "interact" and not self.show_interact:
                continue
            loc = m.vec(root + OFF["Scene_WorldLoc"])
            if not loc or (loc[0] == 0 and loc[1] == 0 and loc[2] == 0):
                continue
            if cat == "item" and m.read(actor + OFF["DroppedItem_CanPickup"], 1) == b"\x00":
                continue
            dist = math.dist(origin, loc) / 100.0
            rows.append((cat, label, dist, loc))
            color, size, bold = STYLE[cat]
            (sx, sy), visible = w2s(pov, loc, W, H)
            if visible and 0 <= sx <= W and 0 <= sy <= H:
                self.canvas.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill=color, outline="#000000")
                ly = sy - 6
                while any(abs(px - sx) < 70 and abs(py - ly) < 15 for px, py in placed):
                    ly -= 15
                placed.append((sx, ly))
                if ly < sy - 6:
                    self.canvas.create_line(sx, sy - 3, sx, ly, fill=color)
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
                self.canvas.create_polygon(tri, fill=color, outline="#000000")
                self.text(ex, ey + 14, f"{label} {dist:.0f}m", color, 9, bold, anchor="n")

        self.panel(rows, me, pawn)

    def panel(self, rows, me, pawn):
        m = self.g.m
        lines = [(f"关卡：{self.g.world_name}", "#ffffff")]
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

        players = [r for r in rows if r[0] == "player"]
        if players:
            lines.append((f"队友 {len(players)} 人", STYLE["player"][0]))

        t = self.trainer
        if t:
            if t.error:
                lines.append((t.error, "#ff6060"))
            for k, v in t.status.items():
                lines.append((f"● {k}：{v}", "#c08cff"))
            if t.message and time.time() - t.message_t < 4:
                lines.append((t.message, "#ffffff"))
            for h in t.help_lines():
                lines.append((h, "#888888"))
        lines.append(("F8 隐藏  F9 道具  F10 可交互物  End 还原并退出", "#888888"))
        y = 56   # 让开游戏左上角自带的玩家名/语音图标
        for s, c in lines:
            self.text(14, y, s, c, 10)
            y += 19

    def trainer_thread_wait(self, timeout=5.0):
        t0 = time.time()
        while self.trainer.running is False and time.time() - t0 < timeout:
            if getattr(self.trainer, "cleaned", False):
                break
            time.sleep(0.05)

    def run(self):
        self.tick()
        self.root.mainloop()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 坐标和游戏窗口一致
    except Exception:
        pass
    try:
        game = Game()
    except BaseException as e:   # 双击 exe 时没有控制台，用弹窗说明为什么没启动
        msg = e.code if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
        u32.MessageBoxW(None, str(msg), "ETB Trainer", 0x10)
        raise SystemExit(1)
    Overlay(game).run()


if __name__ == "__main__":
    main()
