"""Escape the Backrooms 娱乐功能（热键），运行在覆盖层进程的后台线程里。

所有游戏函数都经 etb_call 在游戏主线程执行。启动后自动判断身份（单人 / 房主 / 房客），
房客身份下改走服务器 RPC 或换成只影响本地的替代做法，做不到的功能直接提示。

热键（仅在游戏窗口处于前台时响应）：
    F5  房主：附身最近的怪物 / 回到自己身体（WASD 移动、鼠标转向、空格跳、Shift 加速）
        房客：切到最近怪物的视角（只能看）
    F6  冻结 / 解冻所有怪物（仅房主）
    F7  飞行穿墙，空格上升、Ctrl 下降（仅房主）
    F2  加速 + 无限体力（走 SetWalkSpeedServer / SetSprintSpeedServer，房客也生效）
    F3  第三人称视角（本地）
    F4  换肤：下一个（Shift+F4 上一个）；服装走 AssignCostumeRPC，别人也看得到
    Insert  传送到最近的出口（仅房主）
    PageUp/PageDown 选择道具，Home 把选中的道具生成到手上（服务器 RPC，房客也能用）
    Delete  复活自己：房主 / 单人在死亡位置重生；房客只能向房主发重生请求，大概率被忽略
    F1  夜视（本地后处理：提高曝光，去掉暗角/颗粒/色散）
    Alt+1 自由镜头（WASD 移动、空格/Ctrl 升降、Shift 加速；身体留在原地）
    Alt+2 理智锁满（SRV_AddSanity，房客也生效）
    Alt+3 游戏自带的加速 + 体力增益（SpeedBoost / StaminaBoost）
    Alt+4 超级跳（SRV_Launch）
    Alt+5 穿墙（SetCanCollide 服务器 RPC，房客实验）
    Alt+6 远程拾取最近的掉落道具（PickUp_SERVER）
    Alt+7 远程交互：准星方向上最近的可交互物（Interact）
    Alt+8 把 PgUp/PgDn 选中的道具写进背包空格（SetInventoryItem）
    Alt+9 屏蔽突脸动画（只改本地：PlayJumpScare 直接返回；MC_KillAnimation 只在目标是自己时返回）
    F4 换肤也会读取 custom_skins.txt 里的自定义模型（需要先把模组 pak 放进 Paks/~mods，见 MODDING.md）
    F11 无敌（仅房主 / 单人）：所有致死途径都会调用玩家的 KillServer / KillClient，
        在这两个蓝图函数的字节码开头插入“被杀的是我就直接返回”，队友不受影响
"""

import math
import os
import struct
import sys
import threading
import time
import traceback

import etb_call as ec
import etb_overlay as ov

u32 = ov.u32

VK = dict(F1=0x70, F2=0x71, F3=0x72, F4=0x73, F5=0x74, F6=0x75, F7=0x76, F11=0x7A, INSERT=0x2D, DELETE=0x2E,
          ALT=0x12, **{f"D{i}": 0x30 + i for i in range(1, 10)},
          HOME=0x24, PGUP=0x21, PGDN=0x22,
          W=0x57, A=0x41, S=0x53, D=0x44, SPACE=0x20, SHIFT=0x10, CTRL=0x11)

# 玩家 / 组件字段偏移（反射导出，见 NOTES.md）
O = dict(
    Pawn_Controller=0x258, Char_Mesh=0x280, Char_CMC=0x288,
    Fancy_Camera=0x4E0, Fancy_SpringArm=0x4E8, Fancy_Arms=0x4F0, Fancy_Legs=0x578,
    Player_Stamina=0x878, Player_WalkSpeed=0x988, Player_SprintSpeed=0x98C,
    Actor_TimeDilation=0x98,
    CMC_MaxWalkSpeed=0x18C, CMC_MaxFlySpeed=0x198,
    Scene_RelLoc=0x11C,
    Skinned_Mesh=0x480, Skel_AnimClass=0x6A8,
    Actor_Role=0xF0, World_NetDriver=0x38,
    Fancy_CostumeComp=0x528, Costume_Assigned=0xB0,
    Player_IsDead=0x874, Fancy_CanCollide=0x4C3,
    Cam_PPWeight=0x240, Cam_PP=0x270,
    Controller_PlayerState=0x228, PS_Sanity=0x338, PS_MaxSanity=0x33C, PS_Items=0x398,
    DroppedItem_ID=0x230, DroppedItem_CanPickup=0x239,
    World_GameMode=0x118, World_GameState=0x120, GS_PlayersAlive=0x2A0,
)

ROLE_AUTHORITY, ROLE_AUTONOMOUS = 3, 2
ROLE_NAMES = {"solo": "单人", "host": "房主", "client": "房客", None: "未知"}
# 房客实测无效的功能：房客身份下不显示、按了也不响应
# （附身被引擎丢弃；冻结、飞行、传送、穿墙被房主同步覆盖；复活请求被忽略；击杀判定在房主端）
CLIENT_HIDDEN = {"possess", "freeze", "fly", "teleport", "noclip", "revive", "god"}

# 蓝图字节码（EExprToken，UE 4.27）
EX_JUMP_IF_NOT, EX_CALL_MATH, EX_SELF, EX_OBJECT_CONST = 0x07, 0x68, 0x17, 0x20
EX_END_FUNCTION_PARMS, EX_RETURN, EX_NOTHING = 0x16, 0x04, 0x0B
UFUNC_SCRIPT = 0x60            # UStruct::Script (TArray<uint8>)
GOD_FUNCS = ("KillServer", "KillClient")
GOD_HEAD_LEN = 27
GOD_PAWN_AT = 16               # 字节码里“我的角色”指针的位置
# 突脸相关：玩家身上的突脸过场（客户端 RPC）+ 各怪物的惊吓 / 击杀动画 / 击杀尖叫（多播）
JUMPSCARE_FUNCS = ("PlayJumpScare", "MC_Jumpscare", "MC_KillAnimation", "MC_KillSound", "PlayScare")
JUMPSCARE_RESCAN = 3.0         # 秒；换关后新加载的怪物类要补上


def app_dir():
    """exe 版本放在 exe 旁边，源码版本放在脚本旁边。"""
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))

MOVE_WALKING, MOVE_FLYING = 1, 5
MONSTER_SPEED = 650.0
THIRD_PERSON_OFFSET = (-280.0, 0.0, 90.0)   # 相对胶囊体：身后 2.8m、上方 0.9m
MOUSE_SENS = 1.0
FREECAM_SPEED = 800.0
SUPER_JUMP = 2500.0          # SRV_Launch 参数；实测竖直速度约为参数的 0.45 倍
NIGHT_VISION = {             # PostProcessSettings 字段 → 值（bOverride_ 开关一并打开）
    "AutoExposureBias": 3.0,
    "VignetteIntensity": 0.0,
    "GrainIntensity": 0.0,
    "SceneFringeIntensity": 0.0,
}


def key(vk):
    return bool(u32.GetAsyncKeyState(vk) & 0x8000)


class Trainer:
    def __init__(self, game):
        mem = ec.MemRW(game.pid)
        self.g = game.clone(mem)          # 本线程专用的读写副本
        self.c = ec.Caller(self.g)
        self.m = self.c.m
        self.status = {}                  # 给覆盖层面板显示：{功能名: 状态文字}
        self.message = ""                 # 最近一次操作的提示
        self.message_t = 0.0
        self.error = None
        self._prev = {}
        self.possess = None               # dict(monster, ai, body, name)
        self.frozen = set()
        self.flying = False
        self.boost = None                 # 原始 (walk, sprint)
        self.third = None                 # 原始弹簧臂长度
        self.skins = None                 # 换肤候选列表
        self.skin_i = 0
        self.original_skin = None
        self.items = None                 # [(显示名, UClass)]
        self.item_i = 0
        self.role = None                  # "solo" / "host" / "client"
        self.spectate = None              # 房客的怪物视角：正在看的怪物
        self.last_alive = None            # 最近一次活着时的 (位置, 朝向)，复活时用
        self.god = None                   # 无敌：[(UFunction, 原Data, 原Num, 原Max, 新缓冲区)]
        self.god_pawn = 0
        self.checks = []                  # 房客实验的延时检测：[(到期时间, 函数)]
        self.test_results = {}            # {功能: 检测结论}
        self.night = None                 # 夜视：(相机, 原始字节备份)
        self.freecam = None               # 自由镜头：dict(cam, rel, pos, yaw, pitch)
        self.sanity_lock = False
        self.noclip = False
        self._last_sanity = 0.0
        self._pp_fields = None
        self.inv_ids = None               # 背包用的道具 ID（来自各掉落物类默认对象的 ID 字段）
        self.jumpscare = None             # 屏蔽突脸：{UFunction: (原字节码地址, 原前两字节, 名字索引)}
        self._js_scan = 0.0
        self._js_numobj = 0
        self._ksl = None                  # KismetSystemLibrary 默认对象（调静态函数用）
        self._loaded = {}                 # 自定义模型路径 → 已加载对象
        self.running = True
        self._last_refresh = 0.0
        self._last_monster_loc = None
        self._mouse = (0.0, 0.0)
        self._last_t = time.time()

    # ---------------------------------------------------------- 基础

    def say(self, s):
        self.message, self.message_t = s, time.time()

    def pressed(self, vk):
        down = key(vk)
        was = self._prev.get(vk, False)
        self._prev[vk] = down
        return down and not was

    def focused(self):
        p = ov.wt.DWORD()
        u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), ctypes_byref(p))
        return p.value == self.g.pid

    def local(self):
        return self.g.local()            # (pc, pawn)

    def body(self):
        """自己的身体：附身怪物期间记录的原身体，否则就是当前 Pawn。"""
        return self.possess["body"] if self.possess else self.local()[1]

    def name_of(self, obj):
        return self.g.ue.objname(obj) if obj else "None"

    def class_name(self, obj):
        return self.g.ue.objname(self.m.ptr(obj + 0x10)) if obj else ""

    def monsters(self):
        return [a for a, r, cat, l in self.g.targets if cat == "monster"]

    def nearest(self, actors, origin):
        best, bd = None, 1e18
        for a in actors:
            r = self.m.ptr(a + ov.OFF["Actor_Root"])
            loc = self.m.vec(r + ov.OFF["Scene_WorldLoc"]) if r else None
            if loc:
                d = math.dist(origin, loc)
                if d < bd:
                    best, bd = a, d
        return best, bd

    def detect_role(self):
        pc, pawn = self.local()
        actor = pawn or pc
        if not actor:
            return None
        r = (self.m.read(actor + O["Actor_Role"], 1) or b"\0")[0]
        if r == ROLE_AUTHORITY:
            return "host" if self.m.ptr(self.g.world() + O["World_NetDriver"]) else "solo"
        if r == ROLE_AUTONOMOUS:
            return "client"
        return None

    @property
    def is_client(self):
        return self.role == "client"

    def refuse(self, feature):
        """房客身份下实测无效的功能：静默忽略（热键说明里也不显示）。"""
        return self.is_client and feature in CLIENT_HIDDEN

    def later(self, delay, fn):
        self.checks.append((time.time() + delay, fn))

    def run_checks(self):
        now = time.time()
        due = [c for c in self.checks if c[0] <= now]
        self.checks = [c for c in self.checks if c[0] > now]
        for _, fn in due:
            try:
                fn()
            except Exception as e:
                self.say(f"检测出错：{e}")

    def result(self, feature, text):
        self.test_results[feature] = text
        self.say(f"实验结果·{feature}：{text}")

    def on_role_change(self, old, new):
        """换了战局（加入别人的房间、回到单人）时，旧对象都失效了，只清状态不调用。"""
        if self.god:
            self.restore_god()
        if old is not None:
            self.possess, self.spectate, self.frozen, self.flying = None, None, set(), False
            self.boost, self.third, self.skins, self.skin_i, self.items = None, None, None, 0, None
        self.test_results, self.checks = {}, []
        if self.jumpscare is not None:
            self.restore_jumpscare()
        self.night, self.freecam, self.noclip, self.inv_ids = None, None, False, None
        self.say(f"身份：{ROLE_NAMES[new]}")

    def help_lines(self):
        if self.is_client:
            return [
                "F1 夜视  F2 加速  F3 第三人称  F4 换肤  F5 怪物视角",
                "PgUp/PgDn 选道具  Home 生成到手上  Alt+8 写进背包",
                "Alt+1 自由镜头  Alt+2 理智锁满  Alt+3 加速/体力增益  Alt+4 超级跳",
                "Alt+6 远程拾取  Alt+7 远程交互（对准目标）  Alt+9 屏蔽突脸",
            ]
        return [
            "F1 夜视  F2 加速  F3 第三人称  F4 换肤  F5 附身怪物",
            "F6 冻结怪物  F7 飞行穿墙  F11 无敌  Del 复活  Insert 传送出口",
            "PgUp/PgDn 选道具  Home 生成到手上  Alt+8 写进背包",
            "Alt+1 自由镜头  Alt+2 理智锁满  Alt+3 加速/体力增益  Alt+4 超级跳",
            "Alt+5 穿墙  Alt+6 远程拾取  Alt+7 远程交互（对准目标）  Alt+9 屏蔽突脸",
        ]

    def my_loc(self):
        b = self.body()
        r = self.m.ptr(b + ov.OFF["Actor_Root"]) if b else 0
        return self.m.vec(r + ov.OFF["Scene_WorldLoc"]) if r else None

    # ---------------------------------------------------------- 主循环

    def run(self):
        try:
            self.c.hook()
            self.c._index()
        except Exception as e:
            self.error = f"挂钩失败：{e}"
            return
        while self.running:
            try:
                self.tick()
            except Exception as e:
                self.say(f"出错：{type(e).__name__}: {e}")
                traceback.print_exc()
                time.sleep(0.5)
        self.cleanup()
        self.cleaned = True

    def tick(self):
        now = time.time()
        if now - self._last_refresh > 1.0:
            self.g.refresh()
            self._last_refresh = now
            role = self.detect_role()
            if role and role != self.role:
                old, self.role = self.role, role
                self.on_role_change(old, role)
            if self.frozen:
                self.apply_freeze()
            if self.god:
                self.update_god_pawn()
            if self.jumpscare is not None and now - self._js_scan > JUMPSCARE_RESCAN:
                num = self.m.i32(self.g.gobj + 0x14)
                if num != self._js_numobj:      # 对象总数变了才重建索引（换关、刷怪时）
                    self.patch_jumpscare()
            if self.night:
                self.apply_night()
            if self.sanity_lock:
                self.keep_sanity()
            if self.possess and not self.m.ptr(self.possess["monster"] + 0x10):
                self.possess = None
                self.say("怪物已消失，附身结束")

        self.run_checks()
        if not self.focused():
            time.sleep(0.05)
            self._last_t = time.time()
            return

        if self.pressed(VK["F5"]):
            self.toggle_possess()
        if self.pressed(VK["F6"]):
            self.toggle_freeze()
        if self.pressed(VK["F7"]):
            self.toggle_fly()
        if self.pressed(VK["F2"]):
            self.toggle_boost()
        if self.pressed(VK["F3"]):
            self.toggle_third()
        if self.pressed(VK["F4"]):
            self.next_skin(-1 if key(VK["SHIFT"]) else 1)
        if self.pressed(VK["INSERT"]):
            self.teleport_exit()
        if self.pressed(VK["PGUP"]):
            self.select_item(-1)
        if self.pressed(VK["PGDN"]):
            self.select_item(1)
        if self.pressed(VK["HOME"]):
            self.give_item()
        if self.pressed(VK["DELETE"]):
            self.revive()
        if self.pressed(VK["F11"]):
            self.toggle_god()
        if self.pressed(VK["F1"]):
            self.toggle_night()
        alt = key(VK["ALT"])
        actions = {1: self.toggle_freecam, 2: self.toggle_sanity, 3: self.game_boosts, 4: self.super_jump,
                   5: self.toggle_noclip, 6: self.remote_pickup, 7: self.remote_interact, 8: self.add_to_inventory,
                   9: self.toggle_jumpscare}
        for i, fn in actions.items():
            if self.pressed(VK[f"D{i}"]) and alt:
                fn()

        self.track_alive()
        if self.freecam:
            self.drive_freecam()
        elif self.possess:
            self.drive_monster()
        else:
            if self.flying:
                self.drive_fly()
            if self.boost:
                self.m.write(self.body() + O["Player_Stamina"], struct.pack("<f", 100.0))
            time.sleep(0.01)
        self.update_status()

    def update_status(self):
        st = {}
        st["身份"] = ROLE_NAMES[self.role]
        if self.god:
            st["无敌"] = "开"
        if self.night:
            st["夜视"] = "开"
        if self.jumpscare is not None:
            st["屏蔽突脸"] = f"开（{len(self.jumpscare)} 个函数）"
        if self.freecam:
            st["自由镜头"] = "开（Alt+1 回到身体）"
        if self.sanity_lock:
            st["理智锁满"] = f"开（当前 {self._last_sanity:.0f}）"
        if self.noclip:
            st["穿墙"] = "开"
        if self.possess:
            st["附身"] = self.possess["name"]
        if self.spectate:
            st["怪物视角"] = self.spectate[1]
        if self.frozen:
            st["冻结怪物"] = f"{len(self.frozen)} 只"
        if self.flying:
            st["飞行穿墙"] = "开"
        if self.boost:
            st["加速+无限体力"] = "开"
        if self.third is not None:
            st["第三人称"] = "开"
        if self.skins and self.skin_i:
            st["皮肤"] = self.skins[self.skin_i]["name"]
        if self.items:
            st["道具"] = f"{self.items[self.item_i][0]}（Home 生成）"
        for k, v in self.test_results.items():
            st[f"实验·{k}"] = v
        self.status = st

    # ---------------------------------------------------------- 附身

    def toggle_spectate(self):
        """房客版 F5：只切镜头，不改控制权。"""
        pc, pawn = self.local()
        if self.spectate:
            self.c.call(pc, "SetViewTargetWithBlend", pawn, {"BlendTime": 0.3})
            self.spectate = None
            self.say("已切回自己的视角")
            return
        origin = self.my_loc()
        mon, d = self.nearest(self.monsters(), origin) if origin else (None, 0)
        if not mon:
            self.say("附近没有怪物（太远的怪物房主可能没同步过来）")
            return
        label = next((l for a, r, cat, l in self.g.targets if a == mon), self.class_name(mon))
        self.c.call(pc, "SetViewTargetWithBlend", mon, {"BlendTime": 0.3})
        self.spectate = (mon, label)
        self.say(f"正在看：{label}（{d / 100:.0f}m），再按 F5 切回")

    def toggle_possess(self):
        if self.refuse("possess"):
            return self.toggle_spectate()
        pc, pawn = self.local()
        if self.possess:
            p = self.possess
            calls = [(pc, "Possess", p["body"])]
            if p["ai"] and self.class_name(p["ai"]):
                calls.append((p["ai"], "Possess", p["monster"]))
            self.c.batch(calls)
            self.possess = None
            self.say("已回到自己身体")
            return
        if self.flying:
            self.toggle_fly()
        origin = self.my_loc()
        mon, d = self.nearest(self.monsters(), origin) if origin else (None, 0)
        if not mon:
            self.say("附近没有怪物")
            return
        ai = self.m.ptr(mon + O["Pawn_Controller"])
        self.c.call(pc, "Possess", mon)
        if self.m.ptr(pc + ov.OFF["Controller_Pawn"]) != mon:
            self.say("附身失败")
            return
        label = next((l for a, r, cat, l in self.g.targets if a == mon), self.class_name(mon))
        rot = self.c.call(pc, "GetControlRotation")["ReturnValue"]
        self.possess = dict(monster=mon, ai=ai, body=pawn, name=label, yaw=rot[1])
        self._last_monster_loc = self.c.call(mon, "K2_GetActorLocation")["ReturnValue"]
        self._mouse = (0.0, 0.0)
        self._last_t = time.time()
        self.say(f"已附身：{label}（{d / 100:.0f}m）")

    def drive_monster(self):
        """怪物蓝图没有绑定输入，这里每帧把键鼠操作翻译成函数调用。"""
        pc, _ = self.local()
        mon = self.possess["monster"]
        now = time.time()
        dt = min(now - self._last_t, 0.05)
        self._last_t = now
        yaw = math.radians(self.possess["yaw"])
        fwd = (math.cos(yaw), math.sin(yaw))
        right = (-math.sin(yaw), math.cos(yaw))
        f = key(VK["W"]) - key(VK["S"])
        r = key(VK["D"]) - key(VK["A"])
        mx, my = fwd[0] * f + right[0] * r, fwd[1] * f + right[1] * r
        n = math.hypot(mx, my)
        dx, dy = self._mouse
        calls = [(pc, "AddYawInput", dx * MOUSE_SENS), (pc, "AddPitchInput", -dy * MOUSE_SENS)]
        if n > 0 and self._last_monster_loc:
            speed = MONSTER_SPEED * (2.0 if key(VK["SHIFT"]) else 1.0)
            x, y, z = self._last_monster_loc
            target = (x + mx / n * speed * dt, y + my / n * speed * dt, z)
            calls.append((mon, "K2_SetActorLocation", target, {"bSweep": True, "bTeleport": False}))
        calls.append((mon, "K2_SetActorRotation", (0.0, self.possess["yaw"], 0.0), False))
        if self.pressed(VK["SPACE"]):
            calls.append((mon, "Jump"))
        calls += [(pc, "GetInputMouseDelta"), (mon, "K2_GetActorLocation"), (pc, "GetControlRotation")]
        res = self.c.batch(calls)
        md, loc, rot = res[-3], res[-2]["ReturnValue"], res[-1]["ReturnValue"]
        self._mouse = (md["DeltaX"], md["DeltaY"])
        self._last_monster_loc = loc
        self.possess["yaw"] = rot[1]

    # ---------------------------------------------------------- 冻结怪物

    def toggle_freeze(self):
        if not self.frozen and self.refuse("freeze"):
            return
        if self.frozen:
            for a in self.frozen:
                if self.m.ptr(a + 0x10):
                    self.m.write(a + O["Actor_TimeDilation"], struct.pack("<f", 1.0))
            self.frozen = set()
            self.say("怪物已解冻")
        else:
            self.frozen = {None}
            self.apply_freeze()
            self.say(f"已冻结 {len(self.frozen)} 只怪物")

    def actor_loc(self, a):
        r = self.m.ptr(a + ov.OFF["Actor_Root"])
        return self.m.vec(r + ov.OFF["Scene_WorldLoc"]) if r else None

    def apply_freeze(self):
        current = set(self.monsters())
        if self.possess:
            current.discard(self.possess["monster"])
        for a in current:
            self.m.write(a + O["Actor_TimeDilation"], struct.pack("<f", 0.0))
        self.frozen = {a for a in (self.frozen | current) if a and self.m.ptr(a + 0x10)}

    # ---------------------------------------------------------- 飞行穿墙

    def toggle_fly(self):
        if not self.flying and self.refuse("fly"):
            return
        pawn = self.body()
        cmc = self.m.ptr(pawn + O["Char_CMC"])
        if self.flying:
            self.c.batch([(pawn, "SetActorEnableCollision", True), (cmc, "SetMovementMode", MOVE_WALKING, 0)])
            self.m.write(cmc + O["CMC_MaxFlySpeed"], struct.pack("<f", self._fly_speed))
            self.flying = False
            self.say("飞行穿墙：关")
        else:
            self._fly_speed = self.m.f32(cmc + O["CMC_MaxFlySpeed"]) or 600.0
            self.m.write(cmc + O["CMC_MaxFlySpeed"], struct.pack("<f", 1200.0))
            self.c.batch([(pawn, "SetActorEnableCollision", False), (cmc, "SetMovementMode", MOVE_FLYING, 0)])
            self.flying = True
            self.say("飞行穿墙：开（空格上升 / Ctrl 下降）")

    def drive_fly(self):
        up = key(VK["SPACE"]) - key(VK["CTRL"])
        pawn = self.body()
        cmc = self.m.ptr(pawn + O["Char_CMC"])
        calls = []
        if self.m.read(cmc + 0x168, 1) != bytes([MOVE_FLYING]):   # 游戏自己改回了行走（比如爬梯子后）
            calls.append((cmc, "SetMovementMode", MOVE_FLYING, 0))
        if up:
            calls.append((pawn, "AddMovementInput", (0.0, 0.0, float(up)), 1.0, True))
        if calls:
            self.c.batch(calls)

    # ---------------------------------------------------------- 加速 / 体力

    def set_speed(self, walk, sprint):
        """服务器 RPC 让房主那边也用这个速度（否则房客会被拉回），本地也写一份给客户端预测用。"""
        pawn = self.body()
        self.c.batch([(pawn, "SetWalkSpeedServer", walk), (pawn, "SetSprintSpeedServer", sprint)])
        self.m.write(pawn + O["Player_WalkSpeed"], struct.pack("<ff", walk, sprint))
        cmc = self.m.ptr(pawn + O["Char_CMC"])
        self.m.write(cmc + O["CMC_MaxWalkSpeed"], struct.pack("<f", walk))

    def toggle_boost(self):
        pawn = self.body()
        if self.boost:
            self.set_speed(*self.boost)
            self.boost = None
            self.say("加速：关")
        else:
            w, s = self.m.f32(pawn + O["Player_WalkSpeed"]), self.m.f32(pawn + O["Player_SprintSpeed"])
            self.boost = (w, s)
            self.set_speed(w * 1.8, s * 1.8)
            extra = "；房客的体力可能由房主同步，锁满不一定有效" if self.is_client else "，体力锁满"
            self.say(f"加速：开（行走 {w * 1.8:.0f} / 冲刺 {s * 1.8:.0f}{extra}）")

    # ---------------------------------------------------------- 第三人称

    def toggle_third(self):
        """相机直接挂在胶囊体上（弹簧臂只是带动手臂的子组件），所以把相机本身往后上方挪。"""
        pawn = self.body()
        cam = self.m.ptr(pawn + O["Fancy_Camera"])
        if self.third is not None:
            self.c.call(cam, "K2_SetRelativeLocation", self.third, {"bSweep": False, "bTeleport": True})
            self.third = None
            self.update_visibility()
            self.say("第三人称：关")
        else:
            self.third = self.m.vec(cam + O["Scene_RelLoc"])
            self.c.call(cam, "K2_SetRelativeLocation", THIRD_PERSON_OFFSET, {"bSweep": False, "bTeleport": True})
            self.update_visibility()
            self.say("第三人称：开")

    def update_visibility(self):
        """第三人称时显示完整身体、藏起第一人称手臂和无头的 Legs；
        第一人称且是原始外观或服装时恢复游戏默认；第一人称换成怪物模型时连 Legs 一起藏。"""
        pawn = self.body()
        mesh = self.m.ptr(pawn + O["Char_Mesh"])
        arms = self.m.ptr(pawn + O["Fancy_Arms"])
        legs = self.m.ptr(pawn + O["Fancy_Legs"])
        third = self.third is not None or bool(self.freecam)
        human = not self.skins or self.skins[self.skin_i]["kind"] in ("original", "costume")
        self.c.batch([(mesh, "SetOwnerNoSee", not third),
                      (arms, "SetVisibility", not third, False),
                      (legs, "SetVisibility", (not third) and human, False)])

    # ---------------------------------------------------------- 换肤

    def collect_skins(self):
        """候选：原始外观、游戏服装、当前关卡里各角色/怪物的模型（连同动画和材质）。"""
        pawn = self.body()
        mesh = self.m.ptr(pawn + O["Char_Mesh"])
        skins = [dict(kind="original", name="原始外观")]
        self.original_skin = self.mesh_state(mesh)
        comp = self.m.ptr(pawn + O["Fancy_CostumeComp"])
        self.original_costume = self.m.ptr(comp + O["Costume_Assigned"]) if comp else 0
        for o in self.find_instances("Costume"):
            n = self.name_of(o)
            if n.startswith("DA_Costume_"):
                skins.append(dict(kind="costume", name="服装 " + n[len("DA_Costume_"):], costume=o))
        seen = set()
        for a, r, cat, label in self.g.targets:
            if cat not in ("monster", "player") or a == pawn:
                continue
            comp = self.m.ptr(a + O["Char_Mesh"])
            st = self.mesh_state(comp)
            if st and st["mesh"] not in seen:
                seen.add(st["mesh"])
                skins.append(dict(kind="mesh", name=f"{label}（{self.name_of(st['mesh'])}）", **st))
        skins += self.custom_skin_entries()
        self.skins = skins
        self.skin_i = 0

    def mesh_state(self, comp):
        if not comp:
            return None
        sk = self.m.ptr(comp + O["Skinned_Mesh"])
        if not sk:
            return None
        mats_off = self._override_mats_off()
        arr, n = self.m.ptr(comp + mats_off), self.m.i32(comp + mats_off + 8) or 0
        mats = self.m.ptr_array(arr, min(n, 64)) if arr else []
        return dict(mesh=sk, anim=self.m.ptr(comp + O["Skel_AnimClass"]), mats=mats)

    def _override_mats_off(self):
        if not hasattr(self, "_mats_off"):
            cls = self.c.find_class("MeshComponent")
            p = self.m.ptr(cls + 0x50)
            self._mats_off = None
            while p:
                if self.g.ue.name(p + 0x28) == "OverrideMaterials":
                    self._mats_off = self.m.i32(p + 0x4C)
                p = self.m.ptr(p + 0x20)
        return self._mats_off

    def find_instances(self, class_name):
        cls = self.c.find_class(class_name)
        out = []
        objs = self.m.ptr(self.g.gobj)
        num = self.m.i32(self.g.gobj + 0x14)
        for ci in range((num + 65535) // 65536):
            chunk = self.m.ptr(objs + ci * 8)
            n = min(65536, num - ci * 65536)
            raw = self.m.read(chunk, n * 0x18) or b""
            for i in range(n):
                o = struct.unpack_from("<Q", raw, i * 0x18)[0]
                if o and self.m.ptr(o + 0x10) == cls and not self.name_of(o).startswith("Default__"):
                    out.append(o)
        return out

    def next_skin(self, step):
        if self.possess:
            self.say("附身期间不能换肤")
            return
        if not self.skins:
            self.collect_skins()
        self.skin_i = (self.skin_i + step) % len(self.skins)
        self.apply_skin(self.skins[self.skin_i])
        self.say(f"皮肤 {self.skin_i}/{len(self.skins) - 1}：{self.skins[self.skin_i]['name']}")

    def apply_skin(self, s):
        pawn = self.body()
        mesh = self.m.ptr(pawn + O["Char_Mesh"])
        if s["kind"] in ("costume", "original"):
            # 先还原成原始模型，再交给游戏自己的服装逻辑套用
            self.set_mesh(mesh, self.original_skin)
            costume = s["costume"] if s["kind"] == "costume" else self.original_costume
            if costume:
                self.assign_costume(pawn, costume)
        elif s["kind"] == "custom":
            sk = self.load_asset(s["path"])
            if not sk:
                self.say(f"加载失败：{s['path']}（pak 放进 Paks/~mods 了吗？放完要重启游戏）")
                return
            anim = self.load_asset(s["anim_path"]) if s["anim_path"] else self.original_skin["anim"]
            if anim and self.class_name(anim) == "AnimSequence":
                # 第三列是一段动画（比如自带的舞蹈）：不用动画蓝图，直接单动画循环播放
                self.set_mesh(mesh, dict(mesh=sk, anim=0, mats=[]))
                self.c.call(mesh, "PlayAnimation", anim, True)
            else:
                self.set_mesh(mesh, dict(mesh=sk, anim=anim, mats=[]))
        else:
            self.set_mesh(mesh, s)
        self.update_visibility()

    def assign_costume(self, pawn, costume):
        """优先走游戏正常选服装的 AssignCostumeRPC：会复制给所有人，房客用也是正常流程。"""
        comp = self.m.ptr(pawn + O["Fancy_CostumeComp"])
        if comp:
            self.c.call(comp, "AssignCostumeRPC", costume)
            return
        loader = (self.find_instances("CostumeLoaderSubsystem") or [None])[0]
        if loader:
            self.c.call(loader, "LoadAndApplyCostumeBP", costume, pawn)

    def set_mesh(self, mesh, st):
        calls = [(mesh, "SetSkeletalMesh", st["mesh"], True),
                 (mesh, "SetAnimClass", st["anim"] or 0)]
        for i in range(max(len(st["mats"]), 8)):
            calls.append((mesh, "SetMaterial", i, st["mats"][i] if i < len(st["mats"]) else 0))
        self.c.batch(calls[:ec.MAX_BATCH])

    # ---------------------------------------------------------- 生成道具

    def collect_items(self):
        """已加载的道具类：继承链里有 BP_Item_C 的蓝图类。"""
        base_cls = self.c.find_class("BP_Item_C")
        out = []
        for name, cls in self.c._classes.items():
            if cls == base_cls or not name.endswith("_C"):
                continue
            s = self.m.ptr(cls + 0x40)
            while s and s != base_cls:
                s = self.m.ptr(s + 0x40)
            if s:
                label = ov.translate(ov.clean_name(name).replace("Item_", ""), ov.ITEM_CN)
                out.append((f"{label}（{name}）" if label == ov.clean_name(name) else label, cls))
        self.items = sorted(out)
        self.item_i = 0

    def select_item(self, step):
        if not self.items:
            self.collect_items()
        if self.items:
            self.item_i = (self.item_i + step) % len(self.items)
            self.say(f"选中道具 {self.item_i + 1}/{len(self.items)}：{self.items[self.item_i][0]}")

    def give_item(self):
        if self.possess:
            self.say("附身期间不能生成道具")
            return
        if not self.items:
            self.collect_items()
        if not self.items:
            self.say("当前没有加载任何道具类")
            return
        name, cls = self.items[self.item_i]
        self.c.call(self.body(), "SpawnEquipItem_SERVER", cls)
        self.say(f"已生成：{name}")

    # ---------------------------------------------------------- 复活

    def is_player_body(self, pawn):
        return bool(pawn) and self.class_name(pawn) == "BPCharacter_Demo_C"

    def track_alive(self):
        if self.possess:
            return
        _, pawn = self.local()
        if self.is_player_body(pawn) and not self.m.read(pawn + O["Player_IsDead"], 1)[0]:
            r = self.m.ptr(pawn + ov.OFF["Actor_Root"])
            loc = self.m.vec(r + ov.OFF["Scene_WorldLoc"]) if r else None
            if loc:
                yaw = (self.m.vec(r + 0x128) or (0, 0, 0))[1]      # RelativeRotation.Yaw
                self.last_alive = (loc, yaw)

    def revive(self):
        if self.refuse("revive"):
            return
        pc, pawn = self.local()
        if self.possess:
            self.say("先按 F5 回到自己身体")
            return
        if self.is_player_body(pawn) and not self.m.read(pawn + O["Player_IsDead"], 1)[0]:
            self.say("你还活着")
            return
        gm = self.m.ptr(self.g.world() + O["World_GameMode"])
        if not gm:
            self.say("找不到 GameMode，无法复活")
            return
        if self.last_alive:
            (x, y, z), yaw = self.last_alive
        else:   # 没记录到死亡位置：用观战镜头当前的位置
            r = self.m.ptr(pawn + ov.OFF["Actor_Root"]) if pawn else 0
            (x, y, z), yaw = (self.m.vec(r + ov.OFF["Scene_WorldLoc"]) if r else (0.0, 0.0, 0.0)), 0.0
        half = math.radians(yaw) / 2
        # FTransform：Rotation(四元数 xyzw) + Translation(+pad) + Scale3D(+pad)，共 48 字节
        transform = struct.pack("<4f4f4f", 0.0, 0.0, math.sin(half), math.cos(half),
                                x, y, z + 30.0, 0.0, 1.0, 1.0, 1.0, 0.0)
        self.c.call(gm, "RestartPlayerAtTransform", pc, transform)
        time.sleep(0.2)
        _, new = self.local()
        if not self.is_player_body(new) or new == pawn:
            self.say("复活失败：GameMode 没有生成新角色")
            return
        calls = [(pc, "OC_RemoveKillScreen")]
        if pawn and pawn != new and "Spectator" in self.class_name(pawn):
            calls.append((pawn, "K2_DestroyActor"))      # 死后用的观战角色
        self.c.batch(calls)
        self.add_alive(new)
        if self.god:
            self.update_god_pawn()
        # 旧身体上的功能状态都作废了
        self.boost, self.third, self.flying, self.skins, self.skin_i = None, None, False, None, 0
        self.say("已在死亡位置复活")

    def add_alive(self, pawn):
        """把新角色加回 GameState.PlayersAlive，否则游戏可能以为人都死光了。容量不够就不动。"""
        gs = self.m.ptr(self.g.world() + O["World_GameState"])
        a = gs + O["GS_PlayersAlive"]
        data, num, cap = self.m.ptr(a), self.m.i32(a + 8) or 0, self.m.i32(a + 12) or 0
        items = self.m.ptr_array(data, num) if data else []
        if pawn in items:
            return
        if data and num < cap:
            self.m.write(data + num * 8, struct.pack("<Q", pawn))
            self.m.write(a + 8, struct.pack("<i", num + 1))

    # ---------------------------------------------------------- 无敌

    def god_head(self, pawn):
        """JumpIfNot(EqualEqual_ObjectObject(self, 我)) → 原代码；否则 Return。"""
        eq = self.c._funcs[("KismetMathLibrary", "EqualEqual_ObjectObject")]
        head = (bytes([EX_JUMP_IF_NOT]) + struct.pack("<I", GOD_HEAD_LEN) +
                bytes([EX_CALL_MATH]) + struct.pack("<Q", eq) +
                bytes([EX_SELF, EX_OBJECT_CONST]) + struct.pack("<Q", pawn) +
                bytes([EX_END_FUNCTION_PARMS, EX_RETURN, EX_NOTHING]))
        assert len(head) == GOD_HEAD_LEN
        return head

    def toggle_god(self):
        if self.god:
            self.restore_god()
            self.say("无敌：关")
            return
        if self.refuse("god"):
            return
        pawn = self.body()
        if not self.is_player_body(pawn):
            self.say("现在没有自己的角色（死了先按 Del 复活）")
            return
        patched = []
        for fn in GOD_FUNCS:
            f = self.c._funcs[("BPCharacter_Demo_C", fn)]
            a = f + UFUNC_SCRIPT
            data, num, cap = self.m.ptr(a), self.m.i32(a + 8), self.m.i32(a + 12)
            orig = self.m.read(data, num)
            code = self.god_head(pawn) + orig
            buf = self.m.alloc(0x1000)
            self.m.write(buf, code)
            # 先写长度再换指针；解释器按 EX_Return 结束，不依赖长度
            self.m.write(a + 8, struct.pack("<ii", len(code), len(code)))
            self.m.write(a, struct.pack("<Q", buf))
            patched.append((f, data, num, cap, buf))
        self.god, self.god_pawn = patched, pawn
        self.say("无敌：开（怪物、摔落、溺水等都杀不死你；被抓时的动画可能照样播放）")

    def update_god_pawn(self):
        pawn = self.body()
        if self.is_player_body(pawn) and pawn != self.god_pawn:
            for f, data, num, cap, buf in self.god:
                self.m.write(buf + GOD_PAWN_AT, struct.pack("<Q", pawn))
            self.god_pawn = pawn

    def restore_god(self):
        for f, data, num, cap, buf in self.god or []:
            self.m.write(f + UFUNC_SCRIPT, struct.pack("<Qii", data, num, cap))
        self.god, self.god_pawn = None, 0

    # ---------------------------------------------------------- 夜视（本地）

    def pp_fields(self):
        """PostProcessSettings 里要改的字段：{名字: (偏移, 位掩码或 None)}，bool 位字段按反射算出具体字节和位。"""
        if self._pp_fields is None:
            st = None
            cam_cls = self.c.find_class("CameraComponent")
            p = self.m.ptr(cam_cls + 0x50)
            while p:
                if self.g.ue.name(p + 0x28) == "PostProcessSettings":
                    st = self.m.ptr(p + 0x78)
                p = self.m.ptr(p + 0x20)
            want = set(NIGHT_VISION) | {"bOverride_" + k for k in NIGHT_VISION}
            out = {}
            p = self.m.ptr(st + 0x50)
            while p:
                n = self.g.ue.name(p + 0x28)
                if n in want:
                    off = self.m.i32(p + 0x4C)
                    if self.g.ue.name(self.m.ptr(p + 0x8)) == "BoolProperty":
                        out[n] = (off + self.m.read(p + 0x79, 1)[0], self.m.read(p + 0x7A, 1)[0])
                    else:
                        out[n] = (off, None)
                p = self.m.ptr(p + 0x20)
            self._pp_fields = out
        return self._pp_fields

    def toggle_night(self):
        if self.night:
            cam, backup = self.night
            if self.m.ptr(cam + 0x10):
                for addr, data in backup:
                    self.m.write(addr, data)
            self.night = None
            self.say("夜视：关")
        else:
            self.night = (0, [])
            self.apply_night()
            self.say("夜视：开")

    def apply_night(self):
        cam = self.m.ptr(self.body() + O["Fancy_Camera"])
        if not cam:
            return
        old_cam, backup = self.night
        if cam != old_cam:          # 第一次开或换了身体：备份新相机的原值
            backup = []
            fields = self.pp_fields()
            addrs = [cam + O["Cam_PPWeight"]] + [cam + O["Cam_PP"] + off for off, _ in fields.values()]
            for a in addrs:
                backup.append((a, self.m.read(a, 4)))
            self.night = (cam, backup)
        base = cam + O["Cam_PP"]
        for name, val in NIGHT_VISION.items():
            fields = self.pp_fields()
            if name in fields:
                self.m.write(base + fields[name][0], struct.pack("<f", val))
            ob = fields.get("bOverride_" + name)
            if ob:
                addr = base + ob[0]
                cur = self.m.read(addr, 1)[0]
                self.m.write(addr, bytes([cur | ob[1]]))
        self.m.write(cam + O["Cam_PPWeight"], struct.pack("<f", 1.0))

    # ---------------------------------------------------------- 自由镜头（本地）

    def toggle_freecam(self):
        pc, _ = self.local()
        pawn = self.body()
        cam = self.m.ptr(pawn + O["Fancy_Camera"])
        if self.freecam:
            fc = self.freecam
            self.freecam = None
            if self.m.ptr(fc["cam"] + 0x10):
                self.c.batch([(fc["cam"], "K2_SetRelativeLocation", fc["rel"], {"bSweep": False, "bTeleport": True}),
                              (pc, "ResetIgnoreMoveInput")])
            self.update_visibility()
            self.say("自由镜头：关")
            return
        if self.possess:
            self.say("附身期间不能用自由镜头")
            return
        if self.third is not None:
            self.toggle_third()
        pov = self.g.camera(pc)
        if not cam or not pov:
            return
        self.freecam = dict(cam=cam, rel=self.m.vec(cam + O["Scene_RelLoc"]), pos=list(pov[0]),
                            yaw=pov[1][1], pitch=pov[1][0])
        self.c.call(pc, "SetIgnoreMoveInput", True)
        self.update_visibility()
        self._last_t = time.time()
        self.say("自由镜头：开（WASD 移动、空格/Ctrl 升降、Shift 加速，身体留在原地）")

    def drive_freecam(self):
        pc, _ = self.local()
        fc = self.freecam
        if not self.m.ptr(fc["cam"] + 0x10):
            self.freecam = None
            return
        now = time.time()
        dt = min(now - self._last_t, 0.05)
        self._last_t = now
        y, p = math.radians(fc["yaw"]), math.radians(fc["pitch"])
        fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
        right = (-math.sin(y), math.cos(y), 0.0)
        f = key(VK["W"]) - key(VK["S"])
        r = key(VK["D"]) - key(VK["A"])
        u = key(VK["SPACE"]) - key(VK["CTRL"])
        speed = FREECAM_SPEED * (3.0 if key(VK["SHIFT"]) else 1.0) * dt
        for i in range(3):
            fc["pos"][i] += (fwd[i] * f + right[i] * r + (u if i == 2 else 0)) * speed
        res = self.c.batch([(fc["cam"], "K2_SetWorldLocation", tuple(fc["pos"]), {"bSweep": False, "bTeleport": True}),
                            (pc, "GetControlRotation")])
        rot = res[-1]["ReturnValue"]
        fc["pitch"], fc["yaw"] = rot[0] if rot[0] < 180 else rot[0] - 360, rot[1]

    # ---------------------------------------------------------- 服务器 RPC 类（房客也能触发）

    def my_ps(self):
        pc, _ = self.local()
        return self.m.ptr(pc + O["Controller_PlayerState"])

    def toggle_sanity(self):
        self.sanity_lock = not self.sanity_lock
        if self.sanity_lock:
            self.keep_sanity()
        self.say("理智锁满：" + ("开" if self.sanity_lock else "关"))

    def keep_sanity(self):
        ps = self.my_ps()
        if not ps:
            return
        san, mx = self.m.f32(ps + O["PS_Sanity"]) or 0.0, self.m.f32(ps + O["PS_MaxSanity"]) or 100.0
        self._last_sanity = san
        if san < mx - 0.5:
            self.c.call(ps, "SRV_AddSanity", mx - san)

    def game_boosts(self):
        pawn = self.body()
        self.c.batch([(pawn, "SpeedBoost"), (pawn, "StaminaBoost")])
        self.say("已触发游戏自带的加速 + 体力增益")

    def super_jump(self):
        pawn = self.body()
        z0 = self.my_loc()
        self.c.call(pawn, "SRV_Launch", SUPER_JUMP)
        self.say("超级跳！")
        if z0 and "超级跳" not in self.test_results:
            peak = [z0[2]]

            def sample(n=0):
                cur = self.my_loc()
                if cur:
                    peak[0] = max(peak[0], cur[2])
                if n < 15:
                    self.later(0.1, lambda: sample(n + 1))
                else:
                    gain = (peak[0] - z0[2]) / 100
                    self.result("超级跳", f"跳起 {gain:.1f}m" if gain > 1 else f"几乎没跳起来（{gain:.1f}m）")
            self.later(0.1, sample)

    def toggle_noclip(self):
        if not self.noclip and self.refuse("noclip"):
            return
        pawn = self.body()
        self.noclip = not self.noclip
        self.c.call(pawn, "SetCanCollide", not self.noclip)
        self.say("穿墙：" + ("开（试着往墙里走）" if self.noclip else "关"))

    def remote_pickup(self):
        pawn = self.body()
        origin = self.my_loc()
        items = [a for a, r, cat, l in self.g.targets
                 if cat == "item" and self.m.read(a + O["DroppedItem_CanPickup"], 1) == b"\x01"
                 and "DroppedItem" in "".join(self.g.ue.class_chain(self.m.ptr(a + 0x10)))]
        it, d = self.nearest(items, origin) if origin and items else (None, 0)
        if not it:
            self.say("附近没有能捡的掉落道具")
            return
        label = next((l for a, r, cat, l in self.g.targets if a == it), "道具")
        self.c.call(pawn, "PickUp_SERVER", it)
        self.say(f"远程拾取：{label}（{d / 100:.0f}m）")

        def check():
            gone = not self.m.ptr(it + 0x10) or self.m.read(it + O["DroppedItem_CanPickup"], 1) != b"\x01"
            self.result("远程拾取", f"成功捡到 {label}（{d / 100:.0f}m 外）" if gone
                        else f"没捡到：房主可能检查了距离（{d / 100:.0f}m），或者背包满了")
        self.later(1.0, check)

    def remote_interact(self):
        pc, _ = self.local()
        pov = self.g.camera(pc)
        if not pov:
            return
        (cx, cy, cz), (pitch, yaw, _), _ = pov
        p, y = math.radians(pitch), math.radians(yaw)
        fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
        best, best_ang, best_d, best_label = None, 12.0, 0, ""
        for a, r, cat, label in self.g.targets:
            if cat not in ("interact", "item"):
                continue
            loc = self.actor_loc(a)
            if not loc:
                continue
            v = (loc[0] - cx, loc[1] - cy, loc[2] - cz)
            d = math.sqrt(sum(x * x for x in v)) or 1
            ang = math.degrees(math.acos(max(-1, min(1, sum(fwd[i] * v[i] for i in range(3)) / d))))
            if ang < best_ang:
                best, best_ang, best_d, best_label = a, ang, d, label
        if not best:
            self.say("准星方向 12° 内没有可交互物（F10 可以显示它们）")
            return
        self.c.call(self.body(), "Interact", best)
        self.say(f"远程交互：{best_label}（{best_d / 100:.0f}m）")
        self.result("远程交互", f"已对 {best_d / 100:.0f}m 外的 {best_label} 发送交互，看看它有没有反应")

    def collect_inv_ids(self):
        """背包里存的是道具 ID（FName），从各个掉落物类的默认对象上读 ID 字段。"""
        ids = {}
        objs = self.m.ptr(self.g.gobj)
        num = self.m.i32(self.g.gobj + 0x14)
        for ci in range((num + 65535) // 65536):
            chunk = self.m.ptr(objs + ci * 8)
            n = min(65536, num - ci * 65536)
            raw = self.m.read(chunk, n * 0x18) or b""
            for i in range(n):
                o = struct.unpack_from("<Q", raw, i * 0x18)[0]
                if not o:
                    continue
                nm = self.name_of(o)
                if nm.startswith("Default__BP_DroppedItem_") and nm.endswith("_C"):
                    iid = self.g.ue.name(o + O["DroppedItem_ID"])
                    if iid and iid not in ("None", "?"):
                        ids[iid.lower().replace("_", "")] = iid
        self.inv_ids = ids

    # 道具类名和背包 ID 对不上的几个
    INV_ALIAS = {"plasticball": "ball", "scanner": "lidar", "almondbottle": "almondconcentrate"}

    def item_key(self, class_name):
        import re
        k = re.sub(r"_C$", "", class_name)
        k = re.sub(r"^BP_", "", k)
        k = re.sub(r"^Item_", "", k)
        k = re.sub(r"_BP$", "", k)
        k = k.lower().replace("_", "")
        return self.INV_ALIAS.get(k, k)

    def add_to_inventory(self):
        if not self.items:
            self.collect_items()
        if not self.items:
            self.say("先用 PgUp/PgDn 选一个道具")
            return
        if self.inv_ids is None:
            self.collect_inv_ids()
        name, cls = self.items[self.item_i]
        iid = self.inv_ids.get(self.item_key(self.name_of(cls)))
        if not iid:
            self.say(f"{name} 没有对应的背包 ID（可用：{', '.join(sorted(self.inv_ids.values()))}）")
            return
        ps = self.my_ps()
        a = ps + O["PS_Items"]
        data, num = self.m.ptr(a), self.m.i32(a + 8) or 0
        slots = [self.g.ue.name(data + i * 8) for i in range(num)] if data else []
        if "None" not in slots:
            self.say("背包已满")
            return
        slot = slots.index("None")
        self.c.call(ps, "SetInventoryItem", slot, iid)
        self.say(f"把 {name}（{iid}）写进背包第 {slot + 1} 格")

        def check():
            now = self.g.ue.name(self.m.ptr(a) + slot * 8)
            self.result("改背包", f"第 {slot + 1} 格变成了 {now}，按对应数字键看能不能拿出来用" if now == iid
                        else f"第 {slot + 1} 格没变（{now}）")
        self.later(1.0, check)

    # ---------------------------------------------------------- 屏蔽突脸（本地）

    def toggle_jumpscare(self):
        if self.jumpscare is not None:
            self.restore_jumpscare()
            self.say("屏蔽突脸：关")
            return
        self.jumpscare = {}
        n = self.patch_jumpscare(reindex=False)
        self.say(f"屏蔽突脸：开（{n} 个函数，之后加载的怪物会自动补上；只影响你看到的画面，不能免死）")

    def patch_jumpscare(self, reindex=True):
        """把突脸相关函数字节码的开头两个字节原地改成 Return、Nothing。

        不换缓冲区：怪物类跟着关卡加载 / 卸载，卸载时引擎会释放字节码内存，
        换成我们自己分配的内存会让引擎去释放它不认识的指针。原地改写就没有这个问题。
        """
        self._js_scan = time.time()
        self._js_numobj = self.m.i32(self.g.gobj + 0x14)
        if reindex:
            self.c._funcs = None          # 重建函数索引，拿到新加载的怪物类
            self.c._index()
        added = 0
        for (cls, fn), f in self.c._funcs.items():
            if fn not in JUMPSCARE_FUNCS or f in self.jumpscare:
                continue
            a = f + UFUNC_SCRIPT
            data, num = self.m.ptr(a), self.m.i32(a + 8) or 0
            if not data or num < 2:
                continue
            head = self.m.read(data, 2)
            if head == bytes([EX_RETURN, EX_NOTHING]):
                continue                  # 已经是返回（别的实例改过），不重复记录
            self.m.write(data, bytes([EX_RETURN, EX_NOTHING]))
            self.jumpscare[f] = (data, head, self.m.read(f + 0x18, 8))
            added += 1
        return added

    def restore_jumpscare(self):
        for f, (data, head, name) in (self.jumpscare or {}).items():
            # 类可能已经随关卡卸载：名字和字节码地址都还对得上才写回
            if self.m.read(f + 0x18, 8) == name and self.m.ptr(f + UFUNC_SCRIPT) == data:
                self.m.write(data, head)
        self.jumpscare = None

    # ---------------------------------------------------------- 自定义模型

    def ksl(self):
        if not self._ksl:
            objs = self.m.ptr(self.g.gobj)
            raw = self.m.read(self.m.ptr(objs), min(self.m.i32(self.g.gobj + 0x14), 65536) * 0x18) or b""
            for i in range(len(raw) // 0x18):
                o = struct.unpack_from("<Q", raw, i * 0x18)[0]
                if o and self.name_of(o) == "Default__KismetSystemLibrary":
                    self._ksl = o
                    break
        return self._ksl

    def load_asset(self, path):
        """按资源路径加载（/Game/... 形式）。先让引擎用 MakeSoftObjectPath 生成路径名，再 LoadAsset_Blocking。"""
        if path in self._loaded and self.m.ptr(self._loaded[path] + 0x10):
            return self._loaded[path]
        k = self.ksl()
        sp = self.c.call(k, "MakeSoftObjectPath", path)["ReturnValue"]
        obj = self.c.call(k, "LoadAsset_Blocking", bytes(16) + sp)["ReturnValue"]   # WeakPtr+Tag+填充 = 16 字节
        if obj:
            self._loaded[path] = obj
        return obj

    def custom_skin_entries(self):
        """custom_skins.txt：每行  显示名 | 模型路径 | 动画蓝图类路径（可选）。# 开头是注释。"""
        path = os.path.join(app_dir(), "custom_skins.txt")
        out = []
        if not os.path.exists(path):
            return out
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 2 and parts[1].startswith("/"):
                out.append(dict(kind="custom", name="自定义 " + parts[0], path=parts[1],
                                anim_path=parts[2] if len(parts) > 2 and parts[2] else None))
        return out

    # ---------------------------------------------------------- 传送

    def teleport_exit(self):
        if self.refuse("teleport"):
            return
        exits = [a for a, r, cat, l in self.g.targets if cat == "exit"]
        origin = self.my_loc()
        ex, d = self.nearest(exits, origin) if origin and exits else (None, 0)
        if not ex:
            self.say("这一关没找到出口")
            return
        r = self.m.ptr(ex + ov.OFF["Actor_Root"])
        x, y, z = self.m.vec(r + ov.OFF["Scene_WorldLoc"])
        self.c.call(self.body(), "K2_TeleportTo", (x, y, z + 60.0), (0.0, 0.0, 0.0))
        self.say(f"已传送到出口（原距离 {d / 100:.0f}m）")

    # ---------------------------------------------------------- 退出时还原

    def cleanup(self):
        steps = [
            ("附身", lambda: self.possess and self.toggle_possess()),
            ("怪物视角", lambda: self.spectate and self.toggle_spectate()),
            ("无敌", lambda: self.god and self.restore_god()),
            ("夜视", lambda: self.night and self.toggle_night()),
            ("屏蔽突脸", lambda: self.jumpscare is not None and self.restore_jumpscare()),
            ("自由镜头", lambda: self.freecam and self.toggle_freecam()),
            ("穿墙", lambda: self.noclip and self.toggle_noclip()),
            ("冻结", lambda: self.frozen and self.toggle_freeze()),
            ("飞行", lambda: self.flying and self.toggle_fly()),
            ("加速", lambda: self.boost and self.toggle_boost()),
            ("第三人称", lambda: self.third is not None and self.toggle_third()),
            ("皮肤", lambda: self.skins and self.skin_i and self.apply_skin(self.skins[0])),
            ("钩子", lambda: self.c.unhook()),
        ]
        for name, fn in steps:
            try:
                fn()
            except Exception:
                traceback.print_exc()

    def start(self):
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t


def ctypes_byref(x):
    return ov.ctypes.byref(x)
