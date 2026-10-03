# Escape the Backrooms 逆向笔记

- 游戏：Escape the Backrooms（Steam 1943950，build 24997718），UE 4.27，无反作弊，联机走 EOS
- 主模块：`Backrooms-Win64-Shipping.exe`（ASLR，下面全部写成相对模块基址的偏移）
- 辅助脚本：`etb_ue.lua`（AOB 定位全局对象 + 名字/反射/Actor 遍历）

## 全局对象

| 名称 | 偏移 | AOB（RIP 相对，+3 取 disp32） |
|---|---|---|
| GNames（FNamePool） | `exe+5133A40` | `4C 8D 05 ?? ?? ?? ?? EB 16 48 8D 0D ?? ?? ?? ?? E8` |
| GUObjectArray.ObjObjects | `exe+516FEF0` | `48 8B 05 ?? ?? ?? ?? 48 8B 0C C8 48 8D 04 D1` |
| GWorld | `exe+52B44F8` | `48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01` |
| UObject::ProcessEvent | `exe+16E1B30` | 虚表索引 0x44（偏移 0x220） |
| Controller::Possess（exec thunk） | `exe+32F7020` | — |

## 指针链

```
GWorld -> UWorld
  +0x030 PersistentLevel -> ULevel  (+0x98 Actors TArray, +0xA0 Count)
  +0x120 GameState       (+0x238 PlayerArray)
  +0x180 OwningGameInstance
           +0x38 LocalPlayers[0] -> +0x30 PlayerController
                                     +0x250 Pawn
                                     +0x2A0 AcknowledgedPawn
                                     +0x2B8 PlayerCameraManager (+0x1AE0 CameraCachePrivate)
Actor +0x130 RootComponent -> +0x11C RelativeLocation (FVector)
Character +0x280 Mesh / +0x288 CharacterMovement / +0x290 CapsuleComponent
CharacterMovement +0x150 GravityScale / +0x158 JumpZVelocity / +0x168 MovementMode
                  +0x18C MaxWalkSpeed / +0x198 MaxFlySpeed / +0x1A0 MaxAcceleration
```

## 关键类

- 玩家：`BPCharacter_Demo_C` → `FancyCharacter` → `Character`
- 控制器：`MP_PlayerController_C` → `BP_BasePlayerController_C` → `FancyPlayerController`
- 怪物（Pawn / AI 控制器）：`Bacteria_BP_C`/`Bacteria_AIC_C`、`BP_Hound_C`/`AIC_Hound_C`、`BP_Moth_C`/`AIC_Moth_C`、`BP_Roaming_Smiler_C`/`AIC_Roaming_Smiler_C`、`BP_SkinStealer_C`/`AIC_SkinStealer_C`（只有当前关卡用到的才会加载）

## 玩家变量（BPCharacter_Demo_C / FancyCharacter）

| 变量 | 偏移 | 类型 |
|---|---|---|
| CanMove | 0x4B8 | bool |
| bIsDead | 0x4C0 | bool |
| CanCollide | 0x4C3 | bool |
| IsOverlapOnly | 0x4C4 | bool |
| IsDead | 0x874 | bool |
| Stamina | 0x878 | float |
| IsPossessed | 0x97A | bool |
| WalkSpeed | 0x988 | float |
| SprintSpeed | 0x98C | float |
| SanitySystem | 0xA18 | object |

## 可调用的 UFunction（通过 ProcessEvent）

| 函数 | 说明 |
|---|---|
| `Controller::Possess(Pawn)` | 仅权威端（BlueprintAuthorityOnly），“变成怪物”的核心 |
| `Controller::UnPossess()` | |
| `PlayerController::SetViewTargetWithBlend` | 切换到怪物视角，不改控制权 |
| `BPCharacter_Demo_C::MC_NoClip` / `OC_NoClip` | 游戏自带穿墙（掉进后室那段） |
| `BPCharacter_Demo_C::SpeedBoost` / `SetWalkSpeedServer` / `SetSprintSpeedServer` | 改速度（Server RPC） |
| `BPCharacter_Demo_C::HidePlayer` / `FancyCharacter::TogglePlayerVisibility` | 隐身 |
| `FancyCharacter::SetCanCollide` / `SetIsOverlapOnly` | 关碰撞 |
| `BPCharacter_Demo_C::KillServer` / `FancyCharacter::KillPlayer` | 击杀 |
| `MP_PlayerController_C::StartSpectating` | 观战模式 |
| `PlayerController::EnableCheats` | 开启 CheatManager（Shipping 版大概率被裁掉） |
| `Bacteria_BP_C::SetNewSpeed` / `StopMovement` / `ResetPosition` | 控制 Level 0 的怪物 |

## 覆盖层 etb_overlay.py

- 外部只读（ReadProcessMemory），不注入；启动时 AOB 定位 GNames/GObjects/GWorld。
- 相机：`PlayerController+0x2B8 → PlayerCameraManager+0x1AF0`（CameraCachePrivate.POV：Location@0 Rotation@0xC FOV@0x18）。
- 世界坐标：`RootComponent+0x1D0`（ComponentToWorld.Translation），比 RelativeLocation 可靠。
- 分类靠继承链：Pawn（排除 FancyCharacter/InteractablePawn 等）=怪物，DroppedItem/ItemActor=道具，*ExitZone=出口，*FallZone=坠落区，InteractableActor=可交互物。
- 遍历 `World+0x138 Levels` 下所有关卡的 Actors，每 0.5 秒刷新一次，类信息按 UClass 指针缓存。

## 游戏线程调用 etb_call.py

- 在 `UObject::ProcessEvent`（exe+16E1B30）开头 19 字节打 `jmp [rip]` 到代码洞；代码洞检查 `gs:[48h]`（当前线程 ID）是否为主线程、再用 `lock cmpxchg` 抢占调用标志，然后批量执行队列里的调用（最多 32 个），最后执行原开头指令并跳回 ProcessEvent+19。
- 代码洞布局：+0 标志（0 空闲 / 1 待执行 / 2 执行中 / 3 完成）、+4 主线程 ID、+8 调用数、+0x100 队列（obj, func, params 各 8 字节）、+0x400 代码、+0x1000 起每个调用 0x400 字节参数区；+0x28 魔数 `ETBHOOK2`。
- 参数布局完全按反射读取：FProperty `PropertyFlags@0x40`、`Offset@0x4C`、`ElementSize@0x3C`，BoolProperty `FieldMask@0x7B`。
- 主线程 = 进程里创建时间最早的线程。ProcessEvent 大约每帧在主线程上至少调用一次，所以一次批量调用的延迟约一帧。
- 退出覆盖层（End）时会还原所有功能并把 19 字节写回去；代码洞内存不释放（避免有线程正停在里面）。

## 功能 etb_trainer.py

- 附身：`PC.Possess(怪物)`，退出时 `PC.Possess(原身体)` + `原AI控制器.Possess(怪物)`。怪物蓝图没有绑定输入，而且细菌会被自身逻辑每帧刹停，所以移动改成 `K2_SetActorLocation(sweep)` 直接推位置。
- 第三人称：相机 `FirstPersonCamera` 直接挂在胶囊体上（相对位置 19,0,55.2），弹簧臂是相机的子组件，只带动手臂；所以是挪相机本身。
- 玩家有三个骨骼网格：`Mesh`(0x280，完整 Hazmat，OwnerNoSee)、`Arms`(0x4F0，第一人称手臂)、`Legs`(0x578，去掉头的 Hazmat，第一人称低头看到的身体)。
- 动画类是 `AnimBlueprintGeneratedClass`，按类名找类时要把这种类型也收录进来。
- 道具类都继承 `BP_Item_C`（不是原生的 ItemActor），`SpawnEquipItem_SERVER(ItemClass)` 直接塞到手上。

## 身份判断（etb_trainer.detect_role，每秒一次）

- 本地 Pawn（没有就用 PC）的 `Actor::Role`（+0xF0）：3 = Authority → 再看 `World::NetDriver`（+0x38），空 = 单人，非空 = 联机房主；2 = AutonomousProxy → 房客。
- 身份变化（换战局）时只清本地状态，不再调用旧对象。
- 房客：F5 改为 `SetViewTargetWithBlend` 看怪物；F6/F7/Insert 直接提示不可用；加速改走 `SetWalkSpeedServer`/`SetSprintSpeedServer`（两种身份都走，本地也同步写一份）；服装走 `FancyPlayerCostumeComponent::AssignCostumeRPC`（组件在 Pawn+0x528，`AssignedCostume`@0xB0）；刷道具本来就是服务器 RPC。
- 覆盖层检测到游戏进程退出（GetExitCodeProcess != STILL_ACTIVE）就自动退出，游戏重开后要重新启动覆盖层。
