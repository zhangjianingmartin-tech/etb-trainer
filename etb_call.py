"""在游戏主线程里调用任意 UFunction。

原理：在 UObject::ProcessEvent 入口挂一个跳转，跳到我们分配的代码洞。代码洞检查
「当前线程是游戏主线程」且「有待执行的调用」，是的话先替我们调用一次 ProcessEvent，
再继续执行原本的调用。外部程序只需把 对象/函数/参数 写进共享内存并等待完成标志。

    python etb_call.py hook       # 安装钩子
    python etb_call.py unhook     # 还原
    python etb_call.py funcs Actor K2_  # 查函数签名
"""

import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time

import etb_overlay as base

k32, u32 = base.k32, base.u32

PROCESS_ALL = 0x0010 | 0x0020 | 0x0008 | 0x0400 | 0x0800   # VM_READ|VM_WRITE|VM_OPERATION|QUERY_INFO|SUSPEND_RESUME
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
TH32CS_SNAPTHREAD = 0x4
THREAD_QUERY_LIMITED_INFORMATION = 0x0800

k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
k32.OpenThread.restype = wt.HANDLE
ntdll = ctypes.WinDLL("ntdll")

# ProcessEvent 开头 19 字节（push rbp/rsi/rdi/r12-r15; sub rsp,0F0），与位置无关，可原样搬到代码洞
PE_PROLOGUE = bytes.fromhex("40 55 56 57 41 54 41 55 41 56 41 57 48 81 EC F0 00 00 00")
PE_VTABLE_INDEX = 0x44
MAGIC = b"ETBHOOK2"

# 代码洞布局：标志/线程/调用数，调用队列（每项 obj,func,params 共 24 字节），代码，参数区
C_FLAG, C_TID, C_COUNT, C_BACK, C_MAGIC, C_ORIG = 0x00, 0x04, 0x08, 0x20, 0x28, 0x30
C_QUEUE = 0x100
C_CODE = 0x400
C_PARAMBUF = 0x1000
SLOT = 0x400                # 每个调用的参数区大小
MAX_BATCH = 32
CAVE_SIZE = C_PARAMBUF + SLOT * MAX_BATCH

# 反射偏移（UE 4.27）
F_CLASS, F_NEXT, F_NAME = 0x08, 0x20, 0x28
P_ELEMSIZE, P_FLAGS, P_OFFSET, P_INNER = 0x3C, 0x40, 0x4C, 0x78
B_FIELDMASK = 0x7B          # FBoolProperty.FieldMask
CPF_PARM, CPF_OUTPARM, CPF_RETURNPARM, CPF_REFERENCEPARM = 0x80, 0x100, 0x400, 0x8000000


class FThreadTimes(ctypes.Structure):
    _fields_ = [("lo", wt.DWORD), ("hi", wt.DWORD)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", wt.DWORD)]


def main_thread_id(pid):
    """最早创建的线程就是 UE 的游戏主线程（GGameThreadId 在 WinMain 里取当前线程）。"""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
    best, best_t = None, None
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            h = k32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, te.th32ThreadID)
            if h:
                c, e, kt, ut = FThreadTimes(), FThreadTimes(), FThreadTimes(), FThreadTimes()
                if k32.GetThreadTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                    t = (c.hi << 32) | c.lo
                    if best_t is None or t < best_t:
                        best, best_t = te.th32ThreadID, t
                k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return best


class MemRW(base.Mem):
    def __init__(self, pid):
        self.h = k32.OpenProcess(PROCESS_ALL, False, pid)
        if not self.h:
            raise OSError(f"OpenProcess 失败，错误码 {ctypes.get_last_error()}（试试以管理员身份运行）")
        self._buf = ctypes.create_string_buffer(64)
        self._n = ctypes.c_size_t()

    def write(self, addr, data):
        n = ctypes.c_size_t()
        ok = k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n))
        if not ok or n.value != len(data):
            raise OSError(f"写内存失败 {addr:X}，错误码 {ctypes.get_last_error()}")

    def write_code(self, addr, data):
        old = wt.DWORD()
        k32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), PAGE_EXECUTE_READWRITE, ctypes.byref(old))
        self.write(addr, data)
        k32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(self.h, ctypes.c_void_p(addr), len(data))

    def alloc(self, size):
        a = k32.VirtualAllocEx(self.h, None, size, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
        if not a:
            raise OSError(f"VirtualAllocEx 失败，错误码 {ctypes.get_last_error()}")
        return a

    def suspend(self):
        ntdll.NtSuspendProcess(wt.HANDLE(self.h))

    def resume(self):
        ntdll.NtResumeProcess(wt.HANDLE(self.h))


def build_cave_code(cave, back):
    """生成代码洞机器码。所有 RIP 相对寻址都按 cave 实际地址计算。"""
    code = bytearray()

    def here():
        return cave + C_CODE + len(code)

    def rip(op, target, tail=b""):
        # op + disp32 + tail；disp 相对于整条指令结束处
        end = here() + len(op) + 4 + len(tail)
        code.extend(op + struct.pack("<i", target - end) + tail)

    code += b"\x51\x52\x41\x50\x41\x51"                      # push rcx/rdx/r8/r9
    code += b"\x65\x8B\x04\x25\x48\x00\x00\x00"              # mov eax, gs:[48h]   当前线程 ID
    rip(b"\x3B\x05", cave + C_TID)                           # cmp eax, [tid]
    code += b"\x75\x00"; jne1 = len(code) - 1                # jne skip
    code += b"\xB8\x01\x00\x00\x00"                          # mov eax, 1
    code += b"\xBA\x02\x00\x00\x00"                          # mov edx, 2
    rip(b"\xF0\x0F\xB1\x15", cave + C_FLAG)                  # lock cmpxchg [flag], edx   1→2
    code += b"\x75\x00"; jne2 = len(code) - 1                # jne skip
    code += b"\x53\x56"                                      # push rbx; push rsi
    code += b"\x48\x83\xEC\x28"                              # sub rsp, 28h（共 6 次 push，再减 28h 正好 16 字节对齐）
    rip(b"\x48\x8D\x1D", cave + C_QUEUE)                     # lea rbx, [queue]
    rip(b"\x8B\x35", cave + C_COUNT)                         # mov esi, [count]
    loop = len(code)
    code += b"\x85\xF6"                                      # test esi, esi
    code += b"\x74\x00"; jz = len(code) - 1                  # jz done
    code += b"\x48\x8B\x0B"                                  # mov rcx, [rbx]
    code += b"\x48\x8B\x53\x08"                              # mov rdx, [rbx+8]
    code += b"\x4C\x8B\x43\x10"                              # mov r8, [rbx+10h]
    code += b"\xE8\x00\x00\x00\x00"; call_at = len(code) - 4  # call orig
    code += b"\x48\x83\xC3\x18"                              # add rbx, 18h
    code += b"\xFF\xCE"                                      # dec esi
    code += b"\xEB\x00"; jmp_back = len(code) - 1            # jmp loop
    done = len(code)
    code += b"\x48\x83\xC4\x28"                              # add rsp, 28h
    code += b"\x5E\x5B"                                      # pop rsi; pop rbx
    rip(b"\xC7\x05", cave + C_FLAG, b"\x03\x00\x00\x00")     # mov dword [flag], 3   完成
    skip = len(code)
    code += b"\x41\x59\x41\x58\x5A\x59"                      # pop r9/r8/rdx/rcx
    orig = len(code)
    code += PE_PROLOGUE
    code += b"\xFF\x25\x00\x00\x00\x00" + struct.pack("<Q", back)   # jmp [rip+0] → ProcessEvent+19

    code[jne1] = skip - (jne1 + 1)
    code[jne2] = skip - (jne2 + 1)
    code[jz] = done - (jz + 1)
    code[jmp_back] = (loop - (jmp_back + 1)) & 0xFF
    code[call_at:call_at + 4] = struct.pack("<i", orig - (call_at + 4))
    return bytes(code)


class Caller:
    def __init__(self, game=None):
        self.g = game or base.Game()
        self.m = MemRW(self.g.pid)
        self.ue = self.g.ue
        self.pe = self._process_event()
        self.cave = None
        self._funcs = None
        self._classes = None
        self._props = {}

    # ---------------------------------------------------------- 钩子

    def _process_event(self):
        gi = self.m.ptr(self.g.world() + base.OFF["World_GameInstance"])
        return self.m.ptr(self.m.ptr(gi) + PE_VTABLE_INDEX * 8)

    def hooked_cave(self, any_version=False):
        """已挂钩时返回代码洞地址。旧版代码洞的代码偏移不同，按魔数前缀识别。"""
        head = self.m.read(self.pe, 14)
        if head and head[:6] == b"\xFF\x25\x00\x00\x00\x00":
            target = struct.unpack("<Q", head[6:14])[0]
            for code_off in (C_CODE, 0x80):
                cave = target - code_off
                magic = self.m.read(cave + C_MAGIC, 8) or b""
                if magic == MAGIC or (any_version and magic.startswith(b"ETBHOOK")):
                    return cave
        return None

    def hook(self):
        cave = self.hooked_cave()
        if cave:
            self.cave = cave
            self.m.write(cave + C_TID, struct.pack("<I", main_thread_id(self.g.pid)))
            return cave
        if self.hooked_cave(any_version=True):
            self.unhook()   # 旧版钩子，先还原再装新的
        head = self.m.read(self.pe, len(PE_PROLOGUE))
        if head != PE_PROLOGUE:
            raise RuntimeError(f"ProcessEvent 开头字节和预期不同：{head.hex(' ')}（游戏可能更新了或被别的工具挂过钩）")
        tid = main_thread_id(self.g.pid)
        cave = self.m.alloc(CAVE_SIZE)
        hdr = struct.pack("<IIQQQQ", 0, tid, 0, 0, 0, self.pe + len(PE_PROLOGUE)) + MAGIC + PE_PROLOGUE
        self.m.write(cave, hdr)
        self.m.write(cave + C_CODE, build_cave_code(cave, self.pe + len(PE_PROLOGUE)))
        patch = b"\xFF\x25\x00\x00\x00\x00" + struct.pack("<Q", cave + C_CODE)
        patch += b"\x90" * (len(PE_PROLOGUE) - len(patch))
        self.m.suspend()
        try:
            self.m.write_code(self.pe, patch)
        finally:
            self.m.resume()
        self.cave = cave
        return cave

    def unhook(self):
        cave = self.hooked_cave(any_version=True)
        if not cave:
            return False
        self.m.suspend()
        try:
            self.m.write_code(self.pe, PE_PROLOGUE)
        finally:
            self.m.resume()
        self.cave = None
        return True

    # ---------------------------------------------------------- 反射

    def _index(self):
        """一次性建立 类名→UClass、(类名,函数名)→UFunction 的索引。"""
        if self._funcs is not None:
            return
        m, ue = self.m, self.ue
        objs = m.ptr(self.ue_gobj())
        num = m.i32(self.ue_gobj() + 0x14)
        funcs, classes = {}, {}
        for chunk_i in range((num + 65535) // 65536):
            chunk = m.ptr(objs + chunk_i * 8)
            n = min(65536, num - chunk_i * 65536)
            raw = m.read(chunk, n * 0x18) or b""
            for i in range(n):
                o = struct.unpack_from("<Q", raw, i * 0x18)[0]
                if not o:
                    continue
                hdr = m.read(o + 0x10, 0x18)
                if not hdr:
                    continue
                cls, name_idx, name_num, outer = struct.unpack("<QIIQ", hdr)
                cname = ue.objname(cls) if cls else ""
                if cname == "Function":
                    funcs[(ue.objname(outer), ue.name(o + 0x18))] = o
                elif cname in ("Class", "BlueprintGeneratedClass", "AnimBlueprintGeneratedClass", "WidgetBlueprintGeneratedClass"):
                    classes.setdefault(ue.name(o + 0x18), o)
        self._funcs, self._classes = funcs, classes

    def ue_gobj(self):
        return self.g.gobj

    def find_class(self, name):
        self._index()
        return self._classes.get(name)

    def find_func(self, obj, fname):
        """沿对象的类继承链查找函数。"""
        self._index()
        cls = self.m.ptr(obj + 0x10)
        while cls:
            f = self._funcs.get((self.ue.objname(cls), fname))
            if f:
                return f
            cls = self.m.ptr(cls + 0x40)
        raise KeyError(f"{self.ue.objname(self.m.ptr(obj + 0x10))} 上没有函数 {fname}")

    def params(self, func):
        """返回 [(名字, 类型, 偏移, 大小, 标志, 附加)]，按声明顺序。"""
        if func in self._props:
            return self._props[func]
        out = []
        p = self.m.ptr(func + 0x50)
        while p:
            flags = struct.unpack("<Q", self.m.read(p + P_FLAGS, 8))[0]
            if flags & CPF_PARM:
                t = self.ue.name(self.m.ptr(p + F_CLASS))
                extra = None
                if t == "BoolProperty":
                    extra = self.m.read(p + B_FIELDMASK, 1)[0]
                out.append((self.ue.name(p + F_NAME), t, self.m.i32(p + P_OFFSET),
                            self.m.i32(p + P_ELEMSIZE), flags, extra))
            p = self.m.ptr(p + F_NEXT)
        self._props[func] = out
        return out

    # ---------------------------------------------------------- 调用

    def call(self, obj, fname, *args, timeout=2.0):
        """obj.fname(*args)，返回 {参数名: 值}（含 ReturnValue 和 out 参数）。"""
        return self.batch([(obj, fname) + tuple(args)], timeout)[0]

    def batch(self, calls, timeout=2.0):
        """在游戏主线程的同一时刻依次执行多个调用：[(obj, 函数名, 参数...)]。"""
        if not self.cave:
            self.hook()
        if len(calls) > MAX_BATCH:
            raise ValueError(f"一次最多 {MAX_BATCH} 个调用")
        queue, plans = bytearray(), []
        params_blob = bytearray(SLOT * len(calls))
        for i, (obj, fname, *args) in enumerate(calls):
            func = self.find_func(obj, fname)
            props = self.params(func)
            inputs = [p for p in props if not (p[4] & CPF_RETURNPARM) and
                      (not (p[4] & CPF_OUTPARM) or (p[4] & CPF_REFERENCEPARM))]
            kwargs = args.pop() if args and isinstance(args[-1], dict) else {}   # 末尾的 dict 按参数名传
            if len(args) > len(inputs):
                raise TypeError(f"{fname} 最多 {len(inputs)} 个参数：{[p[0] for p in inputs]}")
            slot_addr = self.cave + C_PARAMBUF + i * SLOT
            buf = bytearray(SLOT)
            for (name, t, off, sz, flags, extra), v in zip(inputs, args):
                self._pack(buf, t, off, sz, v, slot_addr)
            for name, t, off, sz, flags, extra in props:
                if name in kwargs:
                    self._pack(buf, t, off, sz, kwargs[name], slot_addr)
            params_blob[i * SLOT:(i + 1) * SLOT] = buf
            queue += struct.pack("<QQQ", obj, func, slot_addr)
            plans.append(props)
        while self.m.read(self.cave + C_FLAG, 4) != b"\x00\x00\x00\x00":
            time.sleep(0.0005)
        self.m.write(self.cave + C_PARAMBUF, bytes(params_blob))
        self.m.write(self.cave + C_QUEUE, bytes(queue))
        self.m.write(self.cave + C_COUNT, struct.pack("<I", len(calls)))
        self.m.write(self.cave + C_FLAG, struct.pack("<I", 1))
        t0 = time.time()
        while True:
            st = self.m.read(self.cave + C_FLAG, 4)
            if st == b"\x03\x00\x00\x00":
                break
            if time.time() - t0 > timeout:
                if st == b"\x01\x00\x00\x00":
                    self.m.write(self.cave + C_FLAG, struct.pack("<I", 0))
                raise TimeoutError("调用超时：游戏主线程没有执行到 ProcessEvent（加载中？）")
            time.sleep(0.0005)
        out = self.m.read(self.cave + C_PARAMBUF, len(params_blob))
        self.m.write(self.cave + C_FLAG, struct.pack("<I", 0))
        results = []
        for i, props in enumerate(plans):
            raw = out[i * SLOT:(i + 1) * SLOT]
            res = {}
            for name, t, off, sz, flags, extra in props:
                if flags & (CPF_OUTPARM | CPF_RETURNPARM):
                    res[name] = self._unpack(raw, t, off, sz, extra)
            results.append(res)
        return results

    def _pack(self, buf, t, off, sz, v, slot_addr):
        if t in ("ObjectProperty", "ClassProperty", "InterfaceProperty"):
            struct.pack_into("<Q", buf, off, v or 0)
        elif t == "FloatProperty":
            struct.pack_into("<f", buf, off, float(v))
        elif t == "IntProperty":
            struct.pack_into("<i", buf, off, int(v))
        elif t in ("BoolProperty", "ByteProperty", "EnumProperty"):
            buf[off] = int(v) & 0xFF
        elif t == "NameProperty":
            if isinstance(v, str):
                idx = self.ue.find_name(v)
                if idx is None:
                    raise ValueError(f"名字表里没有 {v!r}")
                v = (idx, 0)
            idx, num = v if isinstance(v, tuple) else (v, 0)
            struct.pack_into("<II", buf, off, idx, num)
        elif t == "StrProperty":
            # FString 的字符数据放在参数缓冲区尾部
            data = (str(v) + "\0").encode("utf-16-le")
            soff = len(buf) - 0x180
            buf[soff:soff + len(data)] = data
            struct.pack_into("<Qii", buf, off, slot_addr + soff, len(data) // 2, len(data) // 2)
        elif t == "StructProperty":
            if isinstance(v, (bytes, bytearray)):
                buf[off:off + len(v)] = v
            else:   # Vector / Rotator 等全 float 结构
                vals = list(v)
                struct.pack_into(f"<{len(vals)}f", buf, off, *vals)
        else:
            raise TypeError(f"暂不支持的参数类型 {t}")

    def _unpack(self, raw, t, off, sz, extra):
        if t in ("ObjectProperty", "ClassProperty"):
            return struct.unpack_from("<Q", raw, off)[0]
        if t == "FloatProperty":
            return struct.unpack_from("<f", raw, off)[0]
        if t == "IntProperty":
            return struct.unpack_from("<i", raw, off)[0]
        if t == "BoolProperty":
            return bool(raw[off] & (extra or 0xFF))
        if t in ("ByteProperty", "EnumProperty"):
            return raw[off]
        if t == "StructProperty" and sz in (12, 24):
            return struct.unpack_from(f"<{sz // 4}f", raw, off)
        return bytes(raw[off:off + sz])


def _main():
    g = base.Game()
    c = Caller(g)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hook"
    if cmd == "hook":
        print(f"ProcessEvent={c.pe:X} cave={c.hook():X} 主线程={main_thread_id(g.pid)}")
    elif cmd == "unhook":
        print("已还原" if c.unhook() else "没有挂钩")
    elif cmd == "funcs":
        c._index()
        for (cls, fn), f in sorted(c._funcs.items()):
            if cls == sys.argv[2] and (len(sys.argv) < 4 or sys.argv[3].lower() in fn.lower()):
                ps = ", ".join(f"{n}:{t.replace('Property', '')}" for n, t, *_ in c.params(f))
                print(f"{cls}::{fn}({ps})")


if __name__ == "__main__":
    _main()
