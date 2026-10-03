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

## 复活（Delete）

- 房主 / 单人：`World+0x118 AuthorityGameMode` → `RestartPlayerAtTransform(PC, Transform)`（Transform 参数在偏移 0x10，48 字节：四元数 + 位置 + 缩放），位置用 trainer 每帧记录的最后存活位置（`IsDead`@0x874 为 0 时记录）。之后调用 `OC_RemoveKillScreen`、销毁死后切换的 `BP_Spectator_C`，并把新角色追加进 `GameState+0x2A0 PlayersAlive`（只在容量够时直接写数组）。
- 房客：GameMode 只在房主端存在，只能发引擎的 `ServerRestartPlayer`。房主只在 PC 处于 Inactive 或等待观战状态时受理，而本游戏死后会附身 `BP_Spectator_C`，状态仍是 Playing，所以大概率被忽略。
- `BPCharacter_Demo_C::CanKill`（0x96C）看名字像“能否被杀”，没验证。

## 无敌（F11）

- 扫描全部 UFunction 的字节码（`UStruct::Script` 在 +0x60，TArray<uint8>）：所有致死来源——细菌、笑魇、猎犬、飞蛾、窃皮者、动画体、骨窃贼、鱼、摔落 `BP_FallDamage_C`、烟花、刀、玩家自身的溺水逻辑——最终都调用玩家的 `KillServer` 和 `KillClient`（蓝图里按 FScriptName 调用，所以要按名字索引搜，不能按 UFunction 指针搜）。
- `CanKill`（0x96C）只被细菌、笑魇、动画体、绳索区读取，猎犬、飞蛾、窃皮者不看它，所以不用它做无敌。
- 两个函数原字节码都是 36 字节的桩：`EX_LetValueOnPersistentFrame` 存参数 → `EX_LocalFinalFunction ExecuteUbergraph_BPCharacter_Demo(入口)` → `Return`，没有内部跳转，可以安全地在前面插代码。
- 插入 27 字节：`07 <u32 27> 68 <EqualEqual_ObjectObject> 17 20 <我的 Pawn> 16 04 0B`，再接原字节码。新缓冲区用 VirtualAllocEx 分配，改写 Script 的 Data/Num/Max；关闭时写回原值。类是常驻的，补丁跨关卡有效；换关或复活后每秒把 +16 处的 Pawn 指针更新成新身体。
- 只对自己生效：别人的 Pawn 走 JumpIfNot 跳到原代码。已用 `CanSprint` 验证过这套前缀机制（常量是自己 → 返回默认值 False，常量是别人 → 正常返回 True）。
- 仅房主 / 单人：击杀在服务器上执行。房客端打补丁只会挡掉本地的 KillClient，造成“服务器认为你死了、你自己看不到”的不同步，所以房客直接拒绝。

## 第二批功能（F1、Alt+1~8）与覆盖层雷达 / 队友

- 队友：`GameState+0x238 PlayerArray`（PlayerState）→ `PawnPrivate`@0x280、`PlayerNamePrivate`@0x300（FString）、`Sanity`@0x338；存活判定 = Pawn 在 `PlayersAlive` 里、不是 `BP_Spectator_C`、`IsDead`=0。
- 雷达：按镜头 Yaw 旋转，前方朝上，40m 范围。
- FName 反查：把 FNamePool 的所有块（`GNames+0x8` 当前块号、`+0xC` 当前块游标、`+0x10` 块指针，每块 0x20000 字节）整块读下来解析，建字符串→索引表，约 0.3 秒。
- 背包：`MP_PS_C.Items_Rep`(0x398，12 格 FName，空格是 None)；`InventoryComponent`(PS+0x330) 的 `Inventory2` 是物品对象数组。道具 ID 和道具类名对不上的：PlasticBall→ball、Scanner→LiDAR、AlmondBottle→AlmondConcentrate。
- `SRV_Launch` 的参数是力度：Input=800 时竖直速度约 356；房客身份下实测生效。
- 夜视实测：同一场景开前几乎全黑，开后墙面门框清晰可见。
- PostProcessSettings 里 bool 位字段的真实地址 = Offset + ByteOffset(FBoolProperty+0x79)，位 = ByteMask(+0x7A)。

## 屏蔽突脸（Alt+9）与自定义模型

- 突脸过场是玩家身上的客户端 RPC `PlayJumpScare(Sequence, Entity, EntityBinding, CameraBinding)`；怪物侧的 `MC_Jumpscare` / `MC_KillAnimation` 是多播。补丁只改本地脚本：多播在服务器上是先发给各客户端再执行本地脚本，所以房主打补丁也不影响别人看到的画面。
- 带目标参数的 `MC_KillAnimation`（猎犬、窃皮者、鱼、动画体）用 `07 <u32 35> 68 <EqualEqual_ObjectObject> 00 <参数 FProperty*> 20 <我> 16 04 0B` 只拦自己；细菌、笑魇这类无参数的直接 `04 0B`。
- pak：v11，索引未加密，加密 GUID 全 0，挂载点 `../../../`，目录里没有 `.sig`。玩家模型 `/Game/Player/Hazmat`，骨骼 `/Game/Player/Standard_Walk_Skeleton`，动画蓝图 `/Game/Player/Player_AnimBP.Player_AnimBP_C`。
- 运行时加载：`MakeSoftObjectPath` 让引擎生成路径 FName（新路径在名字表里还不存在，不能自己反查），返回的 24 字节前面补 16 个 0 就是 `LoadAsset_Blocking` 的 FSoftObjectPtr 参数；不存在的路径返回 0。

## 房客实测结果（2026-10-03）与调整

- 房客身份实测无效：附身、冻结、飞行穿墙、传送出口、穿墙（SetCanCollide）、复活（ServerRestartPlayer）；无敌未确认。以上功能在房客身份下全部隐藏、热键不响应（`CLIENT_HIDDEN`）。实验模式及其检测代码已删除。
- 突脸屏蔽对笑魇无效的原因：这一关的笑魇是 `Smiler_BP2_C`，开屏蔽时这个类还没加载。现在每 3 秒检查一次 GUObjectArray 的对象总数，变了就重建函数索引，把新加载的类补上。
- 突脸屏蔽改成原地改写：只把原字节码的头两个字节写成 `04 0B`，不再换成自己分配的缓冲区。怪物类会随关卡卸载，卸载时引擎会 FMemory::Free 字节码数组；换成 VirtualAllocEx 的内存会让引擎去释放不认识的指针，有崩溃风险。代价是带 Target 参数的 MC_KillAnimation 没法只拦自己了。还原前校验 UFunction 的名字和字节码地址没变，防止往已卸载的对象里写。
- 无敌仍用换缓冲区的办法：只改玩家类 BPCharacter_Demo_C，这个类常驻不会卸载。
