# Escape the Backrooms 可调用函数清单

调用方式：`etb_call.Caller().call(对象, "函数名", 参数...)`，或用 `batch([...])` 在同一帧里连续调用多个。
参数可以按位置传，也可以在末尾放一个 dict 按参数名传：`call(actor, "K2_SetActorLocation", (x, y, z), {"bSweep": True})`。

标记说明：`[Server]` 服务端 RPC，`[Client]` 只发给拥有者客户端，`[Multicast]` 广播给所有人，`[仅房主]` 只在权威端生效。
你是房主（单人或自己开房）时，这些函数全部会直接在本机执行。

## 已经做成热键的

| 热键 | 功能 | 用到的函数 / 字段 |
|---|---|---|
| F5 | 房主：附身最近的怪物 / 回到自己身体；房客：切到怪物视角（`SetViewTargetWithBlend`） | `Controller::Possess`；附身时每帧调用 `AddYawInput`、`AddPitchInput`、`K2_SetActorLocation`(sweep)、`K2_SetActorRotation`、`Jump`、`GetInputMouseDelta` |
| F6 | 冻结 / 解冻所有怪物（仅房主） | 写 `Actor::CustomTimeDilation`（+0x98）= 0 |
| F7 | 飞行穿墙（仅房主） | `SetActorEnableCollision(false)`、`CharacterMovementComponent::SetMovementMode(Flying)`、`AddMovementInput` |
| F2 | 加速 + 无限体力 | `SetWalkSpeedServer`、`SetSprintSpeedServer`（房客也生效）+ 写 `Stamina` |
| F3 | 第三人称 | `SceneComponent::K2_SetRelativeLocation`（相机）、`SetOwnerNoSee`、`SetVisibility` |
| F4 / Shift+F4 | 换肤（游戏服装 + 关卡里角色/怪物的模型） | `FancyPlayerCostumeComponent::AssignCostumeRPC`（会同步给其他人）、`SetSkeletalMesh`、`SetAnimClass`、`SetMaterial` |
| Insert | 传送到最近的出口（仅房主） | `Actor::K2_TeleportTo` |
| Delete | 复活：房主 / 单人在死亡位置重生；房客只能请求 | `GameModeBase::RestartPlayerAtTransform`、`MP_PlayerController_C::OC_RemoveKillScreen`、把新角色加回 `MP_GameState_C.PlayersAlive`；房客发 `PlayerController::ServerRestartPlayer` |
| PgUp/PgDn + Home | 选择并生成道具到手上 | `BPCharacter_Demo_C::SpawnEquipItem_SERVER(ItemClass)` |

## 还没做、值得玩的

### 玩家（BPCharacter_Demo_C / FancyCharacter）

| 函数 | 效果 |
|---|---|
| `MC_NoClip()` / `OC_NoClip()` | 游戏自带的“穿模掉进后室”过场 |
| `SpeedBoost()` `[Server]` | 游戏自带的加速效果（杏仁水那种） |
| `SetLiquidPain(float Bluriness, float Vignette)` | 液态痛苦的视觉效果（模糊 + 暗角） |
| `HidePlayer(bool)` / `TogglePlayerVisibility(bool)` | 隐身 |
| `SetCanCollide(bool)` `[Server]` / `SetIsOverlapOnly(bool)` | 关掉和其他玩家/物体的碰撞 |
| `KillServer(bool)` / `KillPlayer()` | 自杀（测试死亡流程用） |
| `SpawnCard()` `[Server]` | 生成身份卡 |
| `ToggleFlashlight()` / `ToggleFOV()` / `ToggleVHS()` / `Toggle Post Processing()` | 手电、视野、VHS 滤镜、后处理开关 |
| `TeleportWater(Array Locations)` | 水下关卡的传送 |

### 怪物

| 函数 | 效果 |
|---|---|
| `BP_Hound_C::BlindHound()` `[Server]` / `Retreat()` / `PlayHowl()` | 致盲猎犬 / 让它撤退 / 嚎叫 |
| `*::Jumpscare(Player)` `[Server]` / `MC_Jumpscare()` | 触发怪物的惊吓动画（可以对朋友用） |
| `*::AttackPlayer(Player)` | 让怪物攻击指定玩家 |
| `*::StopMovement()` / `ResetPosition()` | 停下 / 回到出生点 |
| `Bacteria_BP_C::SetNewSpeed(int, out float)` / `UpdateTeleport()` | 细菌的速度、瞬移逻辑 |
| `AIController::MoveToActor(Goal, ...)` / `MoveToLocation(Dest, ...)` | 指挥怪物走到某个 Actor 或坐标（比如跟着你当宠物） |
| `AIController::K2_SetFocus(Actor)` | 让怪物一直盯着某个目标 |

### 引擎通用（任何 Actor 都能用）

| 函数 | 效果 |
|---|---|
| `Actor::SetActorScale3D((x, y, z))` | 变巨人 / 缩小（自己或怪物都行） |
| `Actor::SetActorHiddenInGame(bool)` | 隐藏任意物体 |
| `Actor::K2_DestroyActor()` | 删掉任意物体（墙、怪物……） |
| `Actor::SetLifeSpan(float)` | 几秒后自动消失 |
| `Character::LaunchCharacter((x, y, z), bXY, bZ)` | 把角色弹飞 |
| `GameplayStatics::BeginDeferredActorSpawnFromClass` + `FinishSpawningActor` | 生成任意已加载的 Actor（比如多刷几只怪） |
| `GameplayStatics::GetAllActorsOfClass(World, Class, out Array)` | 按类找全部实例 |
| `PlayerController::SetViewTargetWithBlend(Actor, ...)` | 镜头切到任意物体（怪物视角、监控视角） |
| `PlayerController::EnableCheats()` + `CheatManager::*` | UE 自带作弊管理器（Slomo、Ghost、Summon 等）；Shipping 版里可能被裁剪掉了，没验证 |

### 关卡 / 游戏模式（MP_GameMode_C）

| 函数 | 效果 |
|---|---|
| `LoadLevel(FName Map, bool IsFromHub, bool IsExit)` | 跳关（需要 FName 参数，调用模块还不支持） |
| `Initiate Game Ending()` / `EndGame()` | 直接结束游戏 |
| `UnlockHUBForAllPlayers()` | 解锁大厅 |
| `MP_PlayerController_C::StartSpectating()` `[Server]` | 进入观战模式 |

## 完整列表（游戏自己的类，已去掉 Timeline/动画通知/输入事件等自动生成的函数）

### AIC_Hound_C（继承 AIController）

- `ResetAggressive()`
- `ResetFlashlightCheck()`
- `Retreat()`
- `Setup AI(BehaviorTree BTAsset)`
- `TriggerAggressive(BPCharacter_Demo_C Target)`
- `WarnPlayer(BPCharacter_Demo_C Target)`

### AIC_Moth_C（继承 AIController）

- `OnSensedPlayer(BPCharacter_Demo_C Player)`  `[Server]`
- `ResetAggressive()`
- `ResetSensing()`
- `Retreat()`
- `Setup AI()`
- `TriggerAggressive(BPCharacter_Demo_C Target)`

### AIC_Roaming_Smiler_C（继承 AIController）

- `OnSeePlayer(BPCharacter_Demo_C Player)`
- `OnStopSeePlayer()`
- `Setup AI(BehaviorTree Behavior Tree)`
- `StartChase(BPCharacter_Demo_C Character)`  `[Server]`

### AIC_SkinStealer_C（继承 AIController）

- `OnSeePlayer(BPCharacter_Demo_C Player)`
- `OnStopSeePlayer()`
- `Setup AI(BehaviorTree Behavior Tree, bool ExtraHearing)`
- `StartChase(BPCharacter_Demo_C Character)`  `[Server]`

### Bacteria_AIC_2_C（继承 AIController）

- `ReceiveBeginPlay()`
- `SetCanTeleport()`

### Bacteria_AIC_C（继承 AIController）

- `OnQueryFinish(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `ReceiveBeginPlay()`
- `SetCanTeleport()`
- `SetChase()`
- `Setup AI(BehaviorTree Behavior Tree)`

### Bacteria_BP_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `CalcLookAtRotation(Actor MyActor, Actor Target)`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `CheckPlayersTimer()`
- `CheckShakeTime()`
- `FaceClosestPlayer()`
- `GetClosestPlayer(out BPCharacter_Demo_C Closest)`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `MC_KillAnimation()`  `[Multicast]`
- `MC_KillSound()`  `[Multicast]`
- `OnStateChanged(Enum PlayState)`
- `ReceiveBeginPlay()`
- `ResetPosition()`
- `SetNewSpeed(int Count, out float NewSpeed)`
- `SetupWorldShakes()`
- `StartSound()`  `[Multicast]`
- `StopMovement()`
- `StopSound()`  `[Multicast]`
- `UpdateSpeed()`
- `UpdateTeleport()`

### Bacteria_Roaming_BP_C（继承 Character）

- `Activate()`
- `AttackPlayer(BPCharacter_Demo_C Player)`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `CheckPlayersTimer()`
- `CheckShakeTime()`
- `FaceClosestPlayer()`
- `GetClosestPlayer(out BPCharacter_Demo_C Closest)`
- `GetRoamLocation(out BP_Bacteria_RoomPoint_C RoamPoint)`
- `HasSeenPlayer()`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `MC_KillAnimation()`  `[Multicast]`
- `MC_KillSound()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `SetShouldPatrol()`
- `SetSpeed(float Speed)`
- `StartSound()`  `[Multicast]`
- `StopMovement()`
- `StopSound()`  `[Multicast]`
- `TeleportToRoam()`
- `UpdateSpeed()`
- `UpdateToPatrol()`

### BP_Animation_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `Jumpscare(BPCharacter_Demo_C Player)`  `[Server]`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `MC_ChangeEyeColor()`  `[Multicast]`
- `MC_KillAnimation(BPCharacter_Demo_C Player)`  `[Multicast]`
- `MC_KillSound(BPCharacter_Demo_C Character)`  `[Multicast]`
- `MC_StartSound()`  `[Multicast]`
- `MC_StopSound()`  `[Multicast]`
- `OnMoveFinished_7E70DA774128EF044FF5A1902873E256(Byte Result, AIController AIController)`
- `OnMoveFinished_FA9FB91748D8CD6E57E2CFB9369E87DF(Byte Result, AIController AIController)`
- `OnQueryFinish(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `OnRequestFailed_7E70DA774128EF044FF5A1902873E256()`
- `OnRequestFailed_FA9FB91748D8CD6E57E2CFB9369E87DF()`
- `ReceiveBeginPlay()`
- `Retreat(Vector Location)`
- `StartChasing()`
- `StopMovement()`
- `StopSound()`

### BP_Antize_C（继承 BlueprintFunctionLibrary）

- `ConvertStringToFloat(FString In, Object __WorldContext, out float Out)`
- `Create New Save File(Object __WorldContext, out BP_MySaveGame_C SaveGame)`
- `CreateNewLobbySave(Object __WorldContext, out BP_LobbySaveGame_C SaveGame)`
- `Finished Level Lobby Easy(int LevelIndex, float Time, Object __WorldContext)`
- `Finished Level Lobby Hard(int LevelIndex, float Time, Object __WorldContext)`
- `Finished Level Lobby Normal(int LevelIndex, float Time, Object __WorldContext)`
- `FinishedCutscene(Object __WorldContext)`
- `FinishedEndScene(Object __WorldContext)`
- `FinishedLevel(int LevelIndex, float Time, Object __WorldContext)`
- `Get Save Game(Object __WorldContext, out BP_MySaveGame_C SaveGame)`
- `GetLobbySaveGame(Object __WorldContext, out BP_LobbySaveGame_C SaveGame)`
- `Load Saves(Object __WorldContext, out BP_MySaveGame_C SaveGame)`
- `Save Slot(BP_MySaveGame_C SaveGame, Object __WorldContext, out bool Success)`
- `SaveGame(BP_MySaveGame_C SaveGame, Object __WorldContext)`
- `SaveMainGame(BP_MySaveGame_C SaveGame, Object __WorldContext)`
- `UnlockMission(FString MissionDTRow, Object __WorldContext)`

### BP_BoneThief_C（继承 Pawn）

- `Apply Costume To Skeletal Mesh(BPCharacter_Demo_C InTargetPlayer)`  `[Multicast]`
- `Attack(BPCharacter_Demo_C TargetPlayer)`  `[Server]`
- `FindClosestPlayer()`
- `FinishEat()`
- `GrabPlayer()`  `[Server]`
- `HideBoneThief()`
- `MC_Breathe()`  `[Multicast]`
- `MC_Montage()`  `[Multicast]`
- `MC_Scream()`  `[Multicast]`
- `MC_SlowBreathe()`  `[Multicast]`
- `OnRep_IsHidden()`
- `OnRep_ShouldTick()`
- `OnRep_TargetPlayer()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `ResetAttack()`  `[Server]`

### BP_Hound_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `BlindHound()`  `[Server]`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `GetStunDuration(out float Delay)`
- `Jumpscare(BPCharacter_Demo_C Player)`  `[Server]`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `LookAtTarget(BPCharacter_Demo_C Target)`
- `MC_KillAnimation(BPCharacter_Demo_C Target)`  `[Multicast]`
- `MC_KillSound()`  `[Multicast]`
- `MC_Stop(float Delay)`  `[Multicast]`
- `OnRep_CanHowl()`
- `OnRep_IsTargetting()`
- `PlayBlinded()`  `[Multicast]`
- `PlayHowl()`
- `ReceiveBeginPlay()`
- `ResetBlinded()`
- `ResetHowl()`
- `ResetRetreat()`
- `Retreat()`  `[Server]`
- `StartSound()`
- `StopMovement()`
- `StopSound()`

### BP_Moth_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `BringToHive()`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `DropPlayer(bool ShouldAttack)`  `[Server]`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `LookAtTarget(BPCharacter_Demo_C Target)`
- `MC_AttackAnimation()`  `[Multicast]`
- `MC_KillSound()`  `[Multicast]`
- `MC_WarnPlayer()`  `[Multicast]`
- `OnRep_IsIdle()`
- `ReceiveBeginPlay()`
- `ResetAttack()`
- `ResetBringToHive()`
- `ResetRetreat()`
- `Retreat()`  `[Server]`
- `StartCarry()`  `[Multicast]`
- `StartSound()`  `[Multicast]`
- `StopCarry()`  `[Multicast]`
- `StopMovement()`
- `StopSound()`  `[Multicast]`
- `ToggleIdle(bool IsIdle)`
- `WarnPlayer()`  `[Server]`

### BP_MothJelly_C（继承 BP_Item_C）

- `OnEventLoaded(Byte EventType)`
- `PlayAnimation()`  `[Multicast]`
- `SRV_FinishEat()`  `[Server]`
- `ToggleEvent(bool Enable)`
- `UseItem()`

### BP_Roaming_Smiler_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `CheckPlayersTimer()`
- `FadeIn()`
- `FadeInParticles()`
- `FadeOut()`
- `FadeOutParticles()`
- `FindTeleportLocation()`  `[Server]`
- `LookAtPlayer(BPCharacter_Demo_C Target)`
- `MC_Jumpscare()`  `[Multicast]`
- `OnQueryFinished(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `OnRep_IsVisible()`
- `OnSpotted()`  `[Server]`
- `ReceiveBeginPlay()`
- `ResetSpotted()`  `[Server]`
- `SetupSmilerParticles()`
- `StopMovement()`
- `ToggleSprint(bool IsSprinting)`
- `lookAt(BPCharacter_Demo_C Target)`

### BP_SkinStealer_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `Dissolve()`  `[Multicast]`
- `Jumpscare(BPCharacter_Demo_C Player)`  `[Server]`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `MC_Jumpscare()`  `[Multicast]`
- `MC_KillAnimation(BPCharacter_Demo_C Target)`  `[Multicast]`
- `MC_Material()`
- `OnRep_IsDisguised()`
- `OnRep_Player Costume()`
- `ReceiveBeginPlay()`
- `SetPlayerMaterials(BPCharacter_Demo_C Player Character)`
- `StartSound()`  `[Multicast]`
- `StopMovement()`
- `StopSound()`  `[Multicast]`
- `ToggleSprint(bool IsSprinting)`
- `UpdateEvent()`

### BP_SkinStealer_Level07_C（继承 BP_SkinStealer_C）

- `JumpTimer()`
- `ReceiveBeginPlay()`
- `ToggleSprint(bool IsSprinting)`
- `UpdateEvent()`

### BPCharacter_Demo_C（继承 FancyCharacter）

- `AddHeat()`  `[Client]`
- `AddHelmetEffects()`  `[Client]`
- `AddStamina()`
- `AddTag_MC(FString Tag)`  `[Multicast]`
- `ApplyCostume(Costume Costume)`
- `ArmSwimming(bool Swimming)`
- `BobWater()`  `[Client]`
- `Burnout()`
- `CanAction(out bool Variable)`
- `CanLookAround() → Bool`
- `CanOpenUI() → Bool`
- `CanSprint(out bool CanSprint)`
- `ChangeCrosshairVisibility(bool IsVisible)`
- `CheckCrouchMovementInput()`
- `CheckFlashlight()`
- `CheckForwardMovementInput(float Input, Vector Direction)`
- `CheckGamepadPushableActorExit()`
- `CheckJumpMovementInput()`
- `CheckLegsOffset()`
- `CheckSpawnedItems()`
- `CheckStamina()`
- `CheckStopCrouchMovementInput()`
- `CheckStopJumpMovementInput()`
- `ClampMovement(float In, out float Clamped)`
- `ClearScreen()`
- `ClearWidgets()`
- `Climb94Rope()`  `[Client]`
- `ClimbCaveLadder()`  `[Client]`
- `ClimbLadder()`  `[Multicast]`
- `ClimbRope(Transform StartingTransform, Transform TargetTransform)`  `[Client]`
- `ConsumeCurrent(bool Drop, bool ResetUsage)`  `[Client]`
- `Create Static Sound()`
- `Create Whisper Sound()`
- `CreateLegs()`  `[Client]`
- `DeleteVoice()`  `[Client]`
- `DestroyEquipItem_SERVER()`  `[Server]`
- `DestroySpawnedItems()`
- `DropAll()`  `[Server]`
- `DropItem_SERVER(FName ItemType)`  `[Server]`
- `EndSanity()`  `[Client]`
- `Equip()`
- `EquipHelmet()`  `[Client]`
- `FadeHelmet()`  `[Client]`
- `Fall()`  `[Client]`
- `Fear(HE_Fear Fear)`  `[Client]`
- `FinishKeySequence()`
- `Footstep/Headshake(Byte FootstepType)`
- `GarageStepHeight()`  `[Client]`
- `GetBurnoutDuration(out float Delay)`
- `GetOppositeOffset(Array Actors, float OffsetLength, out Vector OffsetDirection)`
- `GetPawnsAtLocation(out bool FoundActors, out Array OverlappedActors)`
- `HE_LookAtActorSeq()`
- `HE_LookAtLocation_Seq()`
- `HasRoom(float Distance, out bool CanLean)`
- `HideItem(bool IsVisible)`
- `HideLeftArm(bool Hide)`  `[Client]`
- `HideLegs(bool Visible)`  `[Client]`
- `HidePlayer(bool Hidden)`  `[Client]`
- `HideRightArm(bool Hide)`  `[Client]`
- `HideSwimmingArms(Vector Loc)`  `[Client]`
- `HideTime()`
- `InvAdd(DroppedItem DroppedItem)`
- `InvAddByName(FName ItemName)`
- `InvCheckItem()`
- `InvFindFreeSlot(out int Array Index, out bool Found)`
- `InvItemCount(out int ItemCount)`
- `InvMove(int Index1, int Index2)`
- `InvRemove(int Index)`
- `InvRemoveCurrent(bool ShouldDrop)`
- `InvSwap(int Index1, int Index2)`
- `K2_OnEndCrouch(float HalfHeightAdjust, float ScaledHalfHeightAdjust)`
- `K2_OnMovementModeChanged(Byte PrevMovementMode, Byte NewMovementMode, Byte PrevCustomMode, Byte NewCustomMode)`
- `K2_OnStartCrouch(float HalfHeightAdjust, float ScaledHalfHeightAdjust)`
- `KillClient(FName DeathCause)`  `[Client]`
- `KillServer(bool bResetInteractable)`  `[Server]`
- `LiquidPain()`  `[Client]`
- `LookAtActor(HE_LookAtActor LookAtActors)`  `[Client]`
- `LookAtLocation(HE_LookAtLocation Settings)`  `[Client]`
- `MC_Drop(Vector Location)`  `[Multicast]`
- `MC_NoClip()`  `[Multicast]`
- `MC_PassOut()`  `[Multicast]`
- `MC_Pickup(Vector Location)`  `[Multicast]`
- `MC_RopePosition(Vector AttachEnd, Actor Actor)`  `[Multicast]`
- `MC_Shocked()`  `[Multicast]`
- `MC_ShowCard()`  `[Multicast]`
- `MC_Slipped()`  `[Multicast]`
- `MoveToBottom()`  `[Multicast]`
- `MoveToTop()`  `[Multicast]`
- `OC_CaveExit()`  `[Client]`
- `OC_Dive()`  `[Client]`
- `OC_FadeOut()`  `[Client]`
- `OC_NoClip()`  `[Client]`
- `OC_PassOut()`  `[Client]`
- `OC_SetupVoice()`
- `OC_StartSwimming()`  `[Client]`
- `OC_UnderwaterMix()`
- `OC_UpdateBuoyancy()`  `[Client]`
- `OffsetJump()`
- `OnBalance()`
- `OnFall()`
- `OnFlashlightEntity(Actor Entity)`  `[Server]`
- `OnLanded(HitResult Hit)`
- `OnLandedCrouchCheck()`  `[Client]`
- `OnPossess()`  `[Client]`
- `OnQueryFinished(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `OnRep_Card()`
- `OnRep_Color()`
- `OnRep_CrouchWalkSpeed()`
- `OnRep_CurrentItem_Rep()`
- `OnRep_HasDivingHelmet()`
- `OnRep_HasWaterPhysics()`
- `OnRep_IsAffectingWheat()`
- `OnRep_IsDead()`
- `OnRep_IsFlashlightOn()`
- `OnRep_IsHoldingGlowstick()`
- `OnRep_IsHoldingRope()`
- `OnRep_IsLiDAROn()`
- `OnRep_IsMotionScanner()`
- `OnRep_IsPossessed()`
- `OnRep_IsUsingFlaregun()`
- `OnRep_ShouldUseStamina()`
- `OnRep_ShowCamera()`
- `OnRep_SprintSpeed()`
- `OnRep_WalkSpeed()`
- `OrientMovement()`  `[Client]`
- `PickUp_SERVER(DroppedItem Item)`  `[Server]`
- `PlagueBoat()`  `[Client]`
- `PlayBrightness()`  `[Client]`
- `PlayCameraShake(Class Shake, float Duration)`  `[Client]`
- `PlayInsanity()`  `[Client]`
- `PlayItemMontage(AnimMontage Montage, StaticMesh ItemMesh, Transform Offset)`
- `PlayJumpScare(LevelSequence Sequence, Actor Entity, MovieSceneObjectBindingID EntityBinding, MovieSceneObjectBindingID CameraBinding)`  `[Client]`
- `PlayRumble(ForceFeedbackEffect Rumble)`
- `PlayStatic()`  `[Client]`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `ReceiveTick(float DeltaSeconds)`
- `Reduce PP Barrel Distortion()`  `[Multicast]`
- `RemoveHeat()`  `[Client]`
- `RemovePlague()`  `[Client]`
- `RemoveStamina()`
- `RemoveTag_MC(FString Tag)`  `[Multicast]`
- `ResetJumpOffset()`
- `ResetPlague()`
- `ResetSanityWarning()`  `[Client]`
- `ResetWarning()`
- `Restore PP Barrel Distortion()`  `[Multicast]`
- `RopePitch(bool Activate)`  `[Client]`
- `SRV_BlockPushing(BP_Pushable_C Pushable)`  `[Server]`
- `SRV_Dive()`  `[Server]`
- `SRV_Drown()`  `[Server]`
- `SRV_Launch(float Input)`  `[Server]`
- `SRV_OrientMovement()`  `[Server]`
- `SRV_PassOut()`  `[Server]`
- `SRV_ResetSanityWarning()`  `[Server]`
- `SRV_ToggleRadio(bool Enabled)`  `[Server]`
- `SRV_UpdateBuoyancy()`  `[Server]`
- `SRV_WarnSanity()`  `[Server]`
- `SendPlayerDeathTelemetryEvent(FString DeathCause)`
- `SenseClient()`  `[Client]`
- `Set Input(bool Enabled)`
- `SetCrouchWalkSpeedServer(float Speed)`
- `SetIsClimbing(bool IsClimbing)`  `[Client]`
- `SetLiquidPain(float Bluriness, float Vignette)`
- `SetMinPitch()`  `[Client]`
- `SetPostProcessing(float Chromatic Distance, float Tracking Noise Level, float Signal Distortion Intensity, float Color Tornado Intensity, float Warp Belt Intensity, float Screen Hop Frequency, float Random Horizontal Offset Frequency, float Screen Hop Intensity, float Random Horizontal Offset Strength)`
- `SetSprintSpeedServer(float Speed)`  `[Server]`
- `SetWalkSpeedServer(float Speed)`  `[Server]`
- `ShockedClient()`  `[Client]`
- `ShockedServer()`  `[Server]`
- `ShowCard_Server()`  `[Server]`
- `ShowInteractText(Text Text)`
- `ShowSwimmingArms()`
- `ShowTime()`
- `SnapToLand()`  `[Server]`
- `SpawnCard()`  `[Server]`
- `SpawnEquipItem_SERVER(Class ItemClass)`  `[Server]`
- `SpeedBoost()`  `[Server]`
- `SpeedBoostClient()`  `[Client]`
- `StaminaBoost()`  `[Server]`
- `StartBalance(bool Direction, bool First)`  `[Client]`
- `StartClimbDown()`  `[Multicast]`
- `StartClimbing()`  `[Multicast]`
- `StartClimbingBot_SERVER()`  `[Server]`
- `StartClimbingLadder(BP_Pool_Ladder_C PoolLadder, float SpeedMultiplier)`  `[Multicast]`
- `StartClimbingTop()`  `[Multicast]`
- `StartFlashlightCheck(bool ShouldAdd, FName Tag)`  `[Client]`
- `StartPlague()`  `[Client]`
- `StartPushingActor(BP_Pushable_C PushableActor)`  `[Server]`
- `StartPushingActor_MC(BP_Pushable_C PushableActor, Vector NewLocation, Rotator NewRotation)`  `[Multicast]`
- `StartPushingActor_SERVER(BP_Pushable_C PushableActor, Vector B, Rotator NewRotation)`  `[Server]`
- `StartSprint()`
- `StartTransition(BP_Pool_Ladder_C PoolLadder, float SpeedMultiplier)`  `[Multicast]`
- `StartUnderwater()`  `[Client]`
- `StopAllMovement()`  `[Client]`
- `StopBalance()`  `[Client]`
- `StopBob()`  `[Client]`
- `StopClimbRope()`  `[Client]`
- `StopClimbingLadder()`  `[Multicast]`
- `StopFear()`  `[Client]`
- `StopFlashlightCheck(bool ShouldCheck, FName Tag)`  `[Client]`
- `StopInsanity()`  `[Client]`
- `StopPlague()`  `[Client]`
- `StopPushing()`
- `StopPushingActor()`  `[Server]`
- `StopPushingActor_MC(BP_Pushable_C PushableActor)`  `[Multicast]`
- `StopPushingActor_SERVER(BP_Pushable_C PushableActor)`  `[Server]`
- `StopSprint(bool ShouldStop)`
- `TeleportWater(Array Locations)`
- `Toggle Post Processing(bool Activated)`
- `Toggle Render Clarity Boost(bool bEnable)`
- `ToggleBlur(bool ShouldBlur)`
- `ToggleBody(bool IsActivated)`
- `ToggleCrosshair(bool IsVisible)`
- `ToggleFOV(int FOV)`
- `ToggleFlash(Actor Actor)`  `[Multicast]`
- `ToggleFlashlight()`
- `ToggleInteractText(Text Text)`
- `ToggleInventory(bool Visible)`
- `ToggleItem(Actor Actor)`  `[Client]`
- `ToggleItemVisible()`
- `TogglePlayerLegs(bool IsHidden)`
- `TogglePushToTalk(bool UsingPushToTalk)`
- `ToggleVHS()`
- `TryPickup()`
- `UnequipItem()`
- `UpdateFOV()`  `[Client]`
- `UseItem_SERVER(BP_Item_C Item)`  `[Server]`
- `WarnSanity()`  `[Client]`

### FancyCarrySystemCarrier（继承 SceneComponent）

- `ForceDropCarry()`  `[Multicast]`
- `GetCurrentCarryable() → FancyCarrySystemCarryable`
- `GetCurrentFocusedCarryable() → FancyCarrySystemCarryable`
- `IsCarrying() → Bool`
- `OnRep_CurrentCarryable(FancyCarrySystemCarryable PreviousCarryable)`
- `StartCarry(FancyCarrySystemCarryable Carryable)`  `[Server]`
- `StopCarry()`  `[Server]`

### FancyCarrySystemCarryable（继承 SceneComponent）

- `CanBeCarried() → Bool`
- `IsBeingCarried() → Bool`
- `OnRep_CurrentCarrier()`
- `SetCanBeCarried(bool CanBeCarried)`  `[Server]`

### FancyCharacter（继承 Character）

- `ChangeCrosshairVisibility(bool IsVisible)`
- `CheckPawn()`  `[Server]`
- `CheckSpawnedItems()`
- `GetCurrentInteractableActor() → Actor`
- `HideItem(bool IsVisible)`
- `Interact(Actor Actor)`  `[Server]`
- `InteractCallBackVR(Actor Actor)`
- `KillPlayer(bool bResetInteractable)`  `[Server]`
- `OnRep_CanCollide()`
- `OnRep_IsOverlapOnly()`
- `OnSanityUpdate(float Sanity)`
- `SetCanCollide(bool ShouldCollide)`  `[Server]`
- `SetIsOverlapOnly(bool ShouldOverlapOnly)`  `[Server]`
- `StopPushing()`
- `ToggleBlur(bool ShouldBlur)`
- `TogglePlayerLegs(bool IsHidden)`
- `TogglePlayerVisibility(bool IsHidden)`  `[Client]`
- `TryPickup()`

### FancyCustomModal（继承 Interface）

- `BindCustomModalCompleteCallback(Delegate CompleteCallback)`

### FancyEntitySightingManager（继承 ActorComponent）

- `GetNumEntitySightings() → Int`
- `OnEntitySighting(FancyEntitySightingComponent Entity)`

### FancyGameInstance（继承 AdvancedFriendsGameInstance）

- `CheckCurrentEvent()`
- `CompleteMission(float TimeCompleted) → MissionStructure`
- `CreateMission(FString TargetEscapeLevel, float LevelBaseXP, float LevelTimeLimit, FString MissionStructRowName)`
- `HandleSageGameChatActive(bool bActive)`
- `HandleSeamlessTravelStart(World World, FString String)`
- `InitializeCPPElements() → Bool`
- `InitializeStats()`
- `OnInputDeviceChange(Enum NewInputDevice)`
- `OnInputDeviceChangedEvent(Byte NewInputDevice)`
- `OnPreLoadMap(FString String)`
- `OnSteamOverlayIsActive(bool isOverlayActive)`
- `ResetAchievements()`
- `ResolveGameplayActivityEndStatusEvent(FString PendingMapOptions)`
- `SageGameChatActive(bool bActive)`
- `UpdateCurrentGameLanguage()`

### FancyGameMode（继承 GameMode）

- `OnDecreaseSanity()`

### FancyMovementComponent（继承 CharacterMovementComponent）

- `SetSprinting(bool Sprint)`

### FancyPlayerController（继承 PlayerController）

- `ClientHUDInit()`
- `GetInputMode() → Enum`
- `GetObjectScreenRadius(StaticMeshComponent MeshComponent) → Float`
- `HandleKickedBP()`
- `OnPlayerTravel()`
- `PrintLevelTimes()`
- `PrintLevelTimesToLog()`

### FancyPlayerCostumeComponent（继承 ActorComponent）

- `AssignCostumeRPC(Costume Costume)`  `[Server]`
- `HandleLocalCostumeChanged(Costume Costume)`
- `OnRep_AssignedCostume()`

### FancyPlayerState（继承 PlayerState）

- `AddSanity(float Amount)`  `[Server]`
- `HandleUserReportingStatusChanged(BPUniqueNetId NetId)`
- `InvokePlayerStateUpdatedEvent()`
- `OnKillPlayer()`
- `OnRep_Sanity()`
- `RemoveSanity(float Amount)`  `[Server]`
- `SetBlockedPlayersList(Array InBlockedPlayers)`  `[Server]`
- `SetPlatform(Enum InPlatform)`  `[Server]`
- `SubscribeToPlayerArrayChanged(Object Subscriber, Delegate PlayerStateUpdated)`
- `UnsubscribeFromPlayerArrayChanged(Object Subscriber)`

### FancyUserControllerSystem（继承 GameInstanceSubsystem）

- `GetActiveUserIcon() → SlateBrush`
- `InitiateEOSLogin()`
- `IsConnectToInternet() → Bool`

### FancyVoipManagerComponent（继承 VoipManagerComponent）

- `FancyInitVoice(Controller Controller) → Bool`
- `TryMuteEOSVoip()`

### FancyVotingComponent（继承 ActorComponent）

- `ChangeVoteServer(PlayerState PlayerState, bool NewVote)`  `[Server]`
- `CheckVoteFinishedCondition() → Bool`
- `FinishVoteMulticast(bool Result)`  `[Multicast]`
- `FinishVoteServer()`  `[Server]`
- `IsVotingActive() → Bool`
- `StartVoteMulticast(VoteParameters VoteParameters)`  `[Multicast]`
- `StartVoteServer(VoteParameters VoteParameters)`  `[Server]`
- `VoteUpdated(PlayerState PlayerState, bool NewVote)`  `[Multicast]`

### MP_GameMode_C（继承 FancyGameMode）

- `AddToZone(FName Level, bool IsFromHub, bool IsAnExit, out bool DidFinish)`
- `CancelMission()`
- `CheckAchievements()`
- `CheckMissionComplete(FName Map, bool IsExit, out bool Complete)`
- `CheckMissionUnlock()`
- `CheckNetworkDisconnect()`
- `CheckZone(FName Level, bool IsFromHub, bool IsAnExit, out bool DidFinish)`
- `ChoosePlayerStart(Controller Player) → Actor`
- `DisconnectAllPlayers()`  `[Server]`
- `EndActivityForPlayer(MP_PlayerController_C PlayerController, FString ActivityName, Byte Status)`
- `EndGame()`
- `FinishGameAchievement()`
- `GetAdjustedTime(out float AdjustedTime)`
- `GetDefaultPawnClassForController(Controller InController) → Class`
- `GetPlayerStarts()`
- `HandleStartingNewPlayer(PlayerController NewPlayer)`
- `Initiate Game Ending()`
- `IsOnline() → Bool`
- `IsSingleplayer(out bool Singleplayer)`
- `K2_OnLogout(Controller ExitingController)`
- `K2_OnRestartPlayer(Controller NewPlayer)`
- `K2_PostLogin(PlayerController NewPlayer)`
- `KickPlayer(PlayerState PlayerState)`
- `LoadBackIntoLobby(bool HasFailedMission)`
- `LoadLevel(FName Map, bool IsFromHub, bool IsExit)`
- `OnDecreaseSanity()`
- `OnPlayerDestroyed(bool HasBeenKilled)`  `[Server]`
- `OnPlayerSpawn(BPCharacter_Demo_C Player)`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `RemoveFromZone()`
- `ResetMission()`
- `SaveAll()`
- `SetPlayerColor(BPCharacter_Demo_C PlayerState)`
- `StartActivityForPlayer(MP_PlayerController_C PlayerController)`
- `UnlockAchivement(FName Achievement)`
- `UnlockHUBForAllPlayers()`
- `UpdateActivityCompletion(Byte Status)`
- `UpdateAllScoreboards()`  `[Server]`
- `UpdateCanJoin()`  `[Server]`

### MP_GameState_C（继承 GameState）

- `Generate Encrypted Name(Text Level, out FString Name)`
- `GenerateUUID()`
- `OnLobbyDataChanged__DelegateSignature()`
- `OnRep_MaxPlayers()`
- `ReceiveBeginPlay()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `SendTelemetryEventEnd(Byte EndPlayReason)`
- `SendTelemetryEventStart()`
- `SetMEGUnlocked()`  `[Server]`
- `UpdateLevelData()`

### MP_Level0_C（继承 MP_GameMode_C）

- `ChoosePlayerStart(Controller Player) → Actor`
- `HandleStartingNewPlayer(PlayerController NewPlayer)`
- `LoadCheckpoints()`
- `OnPlayerSpawn(BPCharacter_Demo_C Player)`
- `ReceiveBeginPlay()`
- `SetExit()`
- `ShouldRetrySpawn(out bool Retry)`
- `UnlockSurvivalistAfter15min()`

### MP_Level94_C（继承 MP_GameMode_C）

- `ChoosePlayerStart(Controller Player) → Actor`
- `LoadCheckpoints()`
- `OnPlayerSpawn(BPCharacter_Demo_C Player)`
- `OnQueryFinish(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `ReceiveBeginPlay()`
- `RemoveAnimations()`
- `SpawnAnimations()`

### MP_PlayerController_C（继承 BP_BasePlayerController_C）

- `AddMissionStructUIData(MissionStructure MissionStructureIn, bool Failed, out MissionStructure MissionStructureOut)`
- `CaveHint()`  `[Client]`
- `ClientHUDInit()`
- `Client_ReceiveVoiceDataViaInteractable(InteractablePawn InteractablePawn, Array Voice, bool bUseRadio, BPUniqueNetId Sender)`  `[Client]`
- `Client_RecieveVoiceData(BPCharacter_Demo_C Player, Array Voice, bool bUseRadio, BPUniqueNetId Sender)`  `[Client]`
- `CreateVoipPlayerList()`
- `DeleteVoice()`  `[Client]`
- `GetGameplayAllowTalking(out bool CanTalk)`
- `GetUsingPushToTalk(out bool UsingPushToTalk)`
- `GetUsingRadio(out bool UsingRadio)`
- `HE_Subtitle(HE_SubtitleSeq Subtitle)`  `[Client]`
- `HandleHostConnectionLoss()`  `[Client]`
- `OC_CompleteMission(MissionStructure Mission, bool Failed)`  `[Client]`
- `OC_KickedFromLobby()`  `[Client]`
- `OC_RemoveKillScreen()`  `[Client]`
- `OC_SetSpectating(FString Spectating, Enum PlayerPlatform)`  `[Client]`
- `OC_SetupVoice()`
- `OnPlayerTravel()`
- `OpenVRSettings()`
- `PlayNoiseAtLocation()`  `[Server]`
- `ReceiveBeginPlay()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `ResetInputModeToDefault(Widget PreviousFocusedWidget)`
- `SRV_SendVoiceData(Array CompressedVoiceData, bool bUseRadio, bool IsUnderwater, BPUniqueNetId Sender)`  `[Server]`
- `SaveMissionProgress(MissionStructure MissionStructure)`
- `ScoreboardDelay()`
- `SetSpawnRotation(Rotator Rotation)`  `[Client]`
- `ShowCameraFade()`  `[Client]`
- `ShowEndCutscene()`  `[Client]`
- `ShowLoadingScreen()`  `[Client]`
- `ShowNonModalMessage(Text Message)`
- `StartSpectating()`  `[Server]`
- `TogglePushToTalk(bool Activated)`
- `ToggleScoreboard(bool Pressed)`
- `Unlock HUB()`  `[Client]`
- `UpdatePushToTalk()`
- `UpdateScoreboard()`  `[Client]`
- `VR_Subtitle(HE_SubtitleSeq Subtitle)`  `[Client]`
- `ValveHint()`  `[Client]`

### MP_PoolRooms_C（继承 MP_GameMode_C）

- `CheckPlayer()`
- `CheckWater()`
- `ChoosePlayerStart(Controller Player) → Actor`
- `DarkRoomsSubtitle()`
- `LoadCheckpoints()`
- `OnPlayerSpawn(BPCharacter_Demo_C Player)`
- `ReceiveBeginPlay()`

### MP_PS_C（继承 FancyPlayerState）

- `ClearInventory()`  `[Server]`
- `InvSwap(int Index1, int Index2)`  `[Server]`
- `LoadPlayer()`
- `LoadPlayerStats()`  `[Server]`
- `Load_Player_ConnectionInfo(bool Client_ReadyStatus)`
- `Load_Player_UserProfile()`
- `OnKillPlayer()`
- `OnLevelUpdated__DelegateSignature(int NewLevel)`
- `OnRep_Kills()`
- `OnRep_Level()`
- `OnRep_PlayerConnection()`
- `OnRep_Player_ConnectionInfo_OR()`
- `OnRep_Player_UserProfile_OR()`
- `OnRep_Points()`
- `OnRep_UserInfo()`
- `ReceiveBeginPlay()`
- `ReceiveCopyProperties(PlayerState NewPlayerState)`
- `RefreshPlayer()`  `[Client]`
- `SRV_AddSanity(float Amount)`  `[Server]`
- `SRV_SetHeadsetType(Byte HeadsetType)`  `[Server]`
- `SR_Update_Player_ConnectionInfo(S_PlayerConnectionInfo Player_ConnectionInfo)`  `[Server]`
- `SR_Update_Player_UserProfile(S_UserProfile Player_UserProfile)`  `[Server]`
- `SaveInventory(Array Inventory)`  `[Server]`
- `SavePlayer(bool ForceSave)`
- `SavePlayerStats()`  `[Server]`
- `SetInventoryItem(int Index, FName Name)`  `[Server]`
- `UpdateLevel(int Level)`  `[Server]`

### 8_FFT_H_Ocean_Sim_C（继承 Actor）

- `FFT_Calculator(TextureRenderTarget2D Spectrum Input, TextureRenderTarget2D Final Write)`
- `Get Height RT(int Index, out TextureRenderTarget2D HeightRT)`
- `GetHeightAtComponent(PrimitiveComponent ActorComponent, out Vector Height)`
- `GetHeightAtLoc(PrimitiveComponent C, out Vector L)`
- `GetLastHeight(int CurrentHeightIndex, int NumFramesOld, out TextureRenderTarget2D HeightRT)`
- `Live Ocean()`
- `POV Tracker(out Vector POV Location, out Vector POV Forward Vector)`
- `Pause()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`

### AC_Swimming_C（继承 ActorComponent）

- `CustomDiveMovementLogic(float ScaleValue)`
- `Destroy underwater ambient particle()`
- `DiveMovementLogic(float ScaleValue)`
- `Event Sprint swim()`
- `Event normal swim()`
- `Event switch diving mode()`
- `EventIsInWater(bool IsInWater)`
- `EventIsUnderwater(bool IsUnderwater)`
- `GetSwimSpeed(out float Speed)`
- `GetSwimSprintSpeed(out float Speed)`
- `Is In Water Event__DelegateSignature(bool Is in Water)`
- `Is Underwater Event__DelegateSignature(bool Is Underwater)`
- `MC_Surface()`  `[Multicast]`
- `MC_Swim()`  `[Multicast]`
- `On Begin Play Logic - Swimming()`
- `On Tick logic - Swimming()`
- `OnMovementModeChanged(Byte PrevMovementMode, Byte NewMovementMode, Byte PrevCustomMode, Byte NewCustomMode)`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `ReplicateRotationToServer(Rotator DesiredRotation)`  `[Server]`
- `Set Sprint speed on client()`  `[Client]`
- `Set Sprint speed on server()`  `[Server]`
- `Set normal swim speed on client()`  `[Client]`
- `Set normal swim speed on server()`  `[Server]`
- `SetSmoothCharacterRotationOnStrafeMovement()`
- `Spawn sound(SoundBase Sound)`
- `Spawn swimming ambient particle()`
- `Start underwater ambient particle timer()`
- `SwimDownMovementLogic()`
- `SwimUpMovementLogic()`
- `ToggleSurface()`
- `ToggleUnderwater()`
- `pause underwater ambient particle()`
- `unpause underwater ambient particle()`

### AC_VineGrowth_C（继承 ActorComponent）

- `CheckAllPlayersTangled(out bool AllTangled, out Array Characters)`
- `GrowVines()`
- `Is Player Compromised(out bool IsInGrass)`
- `KillAllPlayers()`
- `OnRep_GrowVinesClient()`
- `ReceiveBeginPlay()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `ReceiveTick(float DeltaSeconds)`
- `ResetAfterFullyUntangled()`
- `ResetTangle()`
- `ResetUntangle()`
- `ResetVines()`
- `SpawnClientVisuals()`
- `TanglePlayer()`
- `UntanglePlayer()`

### AI_ObjectWC（继承 Object）

- `FinishExecute()`
- `GetWeight() → Bool`
- `OnUpdate()`
- `StartExecute()`

### AimAssistComponent（继承 ActorComponent）

- `CheckCanMove() → Bool`
- `GetCurrentTargetOrDefault() → AimAssistTarget`
- `OnAimAssistDeviceEnabled(bool IsGamepad)`
- `ProcessAimAssist(float DeltaTime) → Rotator`

### BackroomsBPFunctionLibrary（继承 BlueprintFunctionLibrary）

- `AddXP(float xpToAdd) → Float`
- `CanNavigationReachPoint(Pawn Pawn, Vector StartLocation, Vector EndLocation) → Bool`
- `ClearCharacterFloor(Character Character)`
- `ClearVoice()`
- `DeleteInputSettings()`
- `GetAllSaveGameSlotNames() → Array`
- `GetDateFromSeconds(int Seconds) → DateTime`
- `GetIndexOfClosestSplinePoint(SplineComponent SplineComponent, Vector WorldLocation) → Int`
- `GetPlayerStateArray(GameStateBase GameState) → Array`
- `GetSaveGameSlotsByType(FString Prefix) → Array`
- `GetSplinePoints(SplineComponent SplineComponent) → Array`
- `GetSystemTimeSeconds(DateTime DateTime) → Int`
- `GetViewDistanceScale() → Float`
- `IsNoHMDMode() → Bool`
- `IsSteamDeckActive() → Bool`
- `K2_IsTearingDown(Object caller, out bool isTearingDown)`
- `LoadXP() → Float`
- `LogStringWithPlayerId(Object PawnOrComponent, FString Text)`
- `PatchMissingInputActions(Array NewActions)`
- `PlayRate(TimelineComponent Timeline, float Sec) → TimelineComponent`
- `ReloadBindings()`
- `ResetInputSettings()`
- `ResetWorldTime(GameMode GameMode)`
- `SaveToClipboard(FString ToClipboard)`
- `SetCurrentLevelLogs(FString LevelName)`
- `SetLogValue(FString Key, FString Value)`

### Base_GM_C（继承 GameMode）

- `GetPlayerControllerFromPlayerState(PlayerState PlayerState, out BP_BasePlayerController_C PlayerController)`
- `Handle Player Disconnection(Controller Player)`
- `HandleStartingNewPlayer(PlayerController NewPlayer)`
- `Handle_PlayerConnection(PlayerController NewPlayer)`
- `K2_OnLogout(Controller ExitingController)`
- `K2_OnSwapPlayerControllers(PlayerController OldPC, PlayerController NewPC)`
- `K2_PostLogin(PlayerController NewPlayer)`
- `KickPlayer(int PlayerId)`
- `ServerTravel_ToGameplayMap(FName Map)`

### BasePS_C（继承 FancyPlayerState）

- `Load_Player_ConnectionInfo(bool Client_ReadyStatus)`
- `Load_Player_Headset()`
- `Load_Player_UserProfile()`
- `OC_Init()`  `[Client]`
- `OnRep_PlayerConnection()`
- `OnRep_Player_ConnectionInfo_OR()`
- `OnRep_Player_UserProfile_OR()`
- `OnRep_UserInfo()`
- `ReceiveBeginPlay()`
- `SR_LoadHeadset(Byte HeadsetType, int PlayerId)`  `[Server]`
- `SR_Update_Player_ConnectionInfo(S_PlayerConnectionInfo Player_ConnectionInfo)`  `[Server]`
- `SR_Update_Player_UserProfile(S_UserProfile Player_UserProfile)`  `[Server]`

### BFL_SetMaxDrawDistance_C（继承 BlueprintFunctionLibrary）

- `GetObjectBoundsSize(StaticMeshComponent StaticMesh, float Scale, bool Debug, Object __WorldContext, out float Size)`
- `ReverseSortCullDistances(Array CullDistances, Object __WorldContext, out Array SortedCullDistances)`
- `Set Instance Draw Distance(bool EnableCullDistances, InstancedStaticMeshComponent InstancedStaticMesh, Array CullDistances, StaticMesh StaticMesh, float FalloffPercentage, Object __WorldContext)`
- `Set Max Draw Distance(bool EnableCullDistances, Array StaticMeshes, Array CullDistances, float ScaleMin, float ScaleMax, float ScaleUniform, bool Debug, Object __WorldContext)`

### BI_ComputersEvents_C（继承 Interface）

- `LaunchShortcut(int Program ID, Texture2D Texture2D (if applicatable), Text Text (if applicatable), SoundBase Sounnd (if applicatable), FileMediaSource Media (if applicatable), FString Level FName (if applicatable))`
- `onClose()`

### BoatComponent（继承 ActorComponent）

- `DisableAllEngines()`
- `DisableAllFloaters()`
- `EnableAllEngines()`
- `EnableAllFloaters()`
- `GetShipBoundsRadius() → Float`
- `GetXShipPawn() → BoatPawn`
- `IsEngineInWater() → Bool`
- `Server_PassMovementInfo(RepXShipMovement NewRepXShipMovement)`  `[Server]`

### BoatPawn（继承 InteractablePawn）

- `AddRotationInput(float ScaleValue)`
- `GetWaterDensity(Vector2D InLocation) → Float`
- `GetWaterNormal(Vector2D InLocation) → Vector`
- `GetWaterWorldZ(Vector2D InLocation) → Float`
- `GetXShipComponent() → BoatComponent`

### BP_AimAssistComponent_C（继承 AimAssistComponent）

- `CheckCanMove() → Bool`
- `OnAimAssistDeviceEnabled(bool IsGamepad)`
- `ReceiveBeginPlay()`

### BP_Ambience_Manager_C（继承 Actor）

- `EnterHouse()`
- `ExitHouse()`
- `ResetAmbience()`

### BP_BalanceHintTrigger_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`

### BP_BalanceZone_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`
- `ReceiveActorEndOverlap(Actor OtherActor)`

### BP_BallProjectile_C（继承 Actor）

- `ReceiveDestroyed()`
- `SpawnGrabableBall()`  `[Server]`

### BP_BasePlayerController_C（继承 FancyPlayerController）

- `ClientHUDInit()`
- `EndActivity(FString ActivityName, Byte Status)`  `[Client]`
- `EndCurrentActivity(Byte Status)`  `[Client]`
- `FadeOutOnBegin()`
- `GetPlayerControllerFromPlayerState(PlayerState PlayerState, out BP_BasePlayerController_C PlayerController)`
- `HandleKickedBP()`
- `InitializeAllRemoteTalkers()`
- `InitializeRemotePlayerVoice(PlayerState NewPlayerState)`  `[Client]`
- `IsLocalXBOXOrGDKPlayer() → Bool`
- `PrintLevelTimes()`
- `ReceiveBeginPlay()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `RemoveRemotePlayerVoice(PlayerState PlayerState)`  `[Client]`
- `ServerInitializeRemotePlayerVoice(PlayerState TargetPlayerState)`  `[Server]`
- `ServerRemoveRemoteVoiceForPlayer(PlayerState TargetPlayerState)`  `[Server]`
- `Should Block VOIPAudio for Player(BPUniqueNetId Player, out bool ShouldBlock)`
- `StartActivity(FString ActivityName)`  `[Client]`
- `UnlockAchievement(FName AchievementName)`  `[Client]`
- `UnlockMission(FName LevelName)`  `[Client]`
- `UpdatePlayersOnBlockList(Array PlayerBlockList)`
- `UpdateUsingMultiplayerFeatures(bool bUsingMP)`  `[Client]`
- `VoteToSkipVideo()`  `[Server]`
- `XboxUpdateCommBlocked()`

### BP_Breakable_C（继承 Interface）

- `Damage(Character Character)`

### BP_Camera_Screen_C（继承 Actor）

- `OnRep_IsCorrect()`
- `OnRep_ShouldReset()`
- `OnRep_UsePlaceholder()`
- `ReceiveBeginPlay()`
- `SetFirstTexture(out Texture Texture)`

### BP_Card_C（继承 Actor）

- `OnRep_IsVisible()`
- `RefreshPlayerInfo()`
- `ToggleVisibility(bool IsVisible)`

### BP_Ceiling_Gate_C（继承 Actor）

- `OnRep_IsOpen()`

### BP_ChunkActor_C（继承 Actor）

- `ReceiveBeginPlay()`

### BP_CloseableInterface_C（继承 Interface）

- `CanClose()`

### BP_Computer_C（继承 InteractablePawn）

- `MulticastHUBUnlock()`  `[Multicast]`
- `OnPossess()`
- `OnRep_UpdateLogin()`
- `OnVRPossess(bool bPossess)`
- `ReceiveBeginPlay()`
- `ReceivePossessed(Controller NewController)`
- `SetActivated()`  `[Server]`
- `ToggleScreen(bool IsHidden, bool BypassPassword)`  `[Client]`
- `ToggleWidgetInteraction(bool Enable)`
- `UnPossess()`  `[Server]`
- `Update Beam()`

### BP_Destructible_C（继承 Interface）

- `Damage(Character Character)`

### BP_DismemberComponent_C（继承 ActorComponent）

- `ApplyCostume(Costume Costume)`
- `BoneIsNonMush() → Bool`
- `BrokenBoneIs(FString Substring) → Bool`
- `CalculateBloodEffectRotation() → Rotator`
- `ChooseMeatMaterial(bool GetBoneMaterial) → MaterialInterface`
- `ChooseMeatPiece(bool GetBoneMesh) → StaticMesh`
- `Dismember(FName Bone, Vector ImpactNormal)`  `[Client]`
- `GetBoneAsDismembermentPart(out Enum DismembermentPart)`
- `SpawnDecal()`
- `SpawnRandomSpatter(Vector Location, Rotator Rotation, out DecalComponent DecalComponent)`

### BP_Dismembered_C（继承 Actor）

- `MC_Sound()`  `[Multicast]`
- `ReceiveBeginPlay()`

### BP_Diving_Helmet_C（继承 BP_Item_C）

- `MC_BlockPickup()`  `[Client]`
- `PlayAnimation()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `SRV_EquipHelmet()`  `[Server]`
- `UseItem()`

### BP_DivingHelmet_C（继承 Actor）

- `UpdateLight(Actor Player)`

### BP_DroppedItem_AlmondWater_C（继承 BP_DroppedItem_C）

- `OnEventLoaded(Byte EventType)`
- `ToggleEvent(bool Enable)`

### BP_DroppedItem_C（继承 DroppedItem）

- `CollisionOff()`  `[Multicast]`
- `CollisionOn()`  `[Multicast]`
- `ExamineModeOff()`
- `ExamineModeOn()`
- `OnBeginFocus()`
- `OnEndFocus()`
- `OnEventLoaded(Byte EventType)`
- `ReceiveBeginPlay()`
- `ToggleEvent(bool Enable)`

### BP_DroppedItem_Glowstick_C（继承 BP_DroppedItem_C）

- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`

### BP_DroppedItem_Jelly_C（继承 BP_DroppedItem_C）

- `DropJelly()`  `[Multicast]`
- `OnEventLoaded(Byte EventType)`
- `ToggleEvent(bool Enable)`

### BP_DroppedItem_LiquidPain_C（继承 BP_DroppedItem_C）

- `ReceiveBeginPlay()`

### BP_DroppedItem_Toy_C（继承 BP_DroppedItem_C）

- `GlowEyes()`
- `ReceiveBeginPlay()`

### BP_Elevator_C（继承 Actor）

- `MoveElevator(bool Down)`  `[Server]`
- `OnRep_Is Moving?()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `SetComplete()`  `[Server]`
- `StopElevator()`  `[Server]`

### BP_EnergyBar_C（继承 BP_Item_C）

- `PlayAnimation()`  `[Multicast]`
- `SRV_FinishEat()`  `[Server]`
- `SetMaterial(bool EnabledFOV)`
- `UseItem()`

### BP_EntitySpawn_Zone_C（继承 TriggerBox）

- `SpawnEntity()`

### BP_EventManager_C（继承 Actor）

- `OnEventLoaded(Enum EventType)`
- `ReceiveBeginPlay()`
- `ToggleEvent(bool Enable)`

### BP_ExitZone_C（继承 Actor）

- `CheckPlayers()`
- `OnEnterZone(Actor Actor)`
- `OnExit()`  `[Server]`
- `OnExitZone(Actor Actor)`

### BP_Explorer_C（继承 Character）

- `ReceiveBeginPlay()`
- `ResetMaterial()`
- `SetFOVMaterial()`
- `TogglePassOut(bool IsPassedOut)`  `[Server]`

### BP_FallDamage_C（继承 ActorComponent）

- `MC_FallSound(Vector Location)`  `[Multicast]`
- `OnLanded()`

### BP_FallingPlank_C（继承 Actor）

- `MC_ImpactSound(Vector Location)`  `[Multicast]`
- `OnRep_DidFall()`
- `PlankFall()`
- `ResetPhysics()`
- `StopPhysics()`

### BP_FallZone_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`

### BP_FireworkProjectile_C（继承 Actor）

- `Explode()`  `[Server]`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`

### BP_Fish_C（继承 Character）

- `AttackPlayer(BPCharacter_Demo_C Player)`
- `CanSeePlayer(BPCharacter_Demo_C Target, out bool CanSee)`
- `Jumpscare(BPCharacter_Demo_C Player)`  `[Server]`
- `LookAtEntity(BPCharacter_Demo_C Target)`
- `MC_KillAnimation(BPCharacter_Demo_C Target)`  `[Multicast]`
- `MC_KillSound()`  `[Multicast]`
- `MC_Stop(float Delay)`  `[Multicast]`
- `OnRep_IsTargetting()`
- `PlayFlip()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `StartSound()`
- `StopMovement()`
- `StopSound()`

### BP_Fish_Scare_C（继承 Character）

- `CheckIsTarget()`
- `MC_Eat()`  `[Multicast]`
- `MC_Scream()`  `[Multicast]`
- `MC_Splash(Vector Location)`  `[Multicast]`
- `MoveToPlayer()`
- `OnRep_IsHidden()`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `ReceiveTick(float DeltaSeconds)`

### BP_FL_GameSettings_C（继承 BlueprintFunctionLibrary）

- `Load/Set_AudioSettings(Object __WorldContext)`
- `LoadSettings(Object __WorldContext, out BP_SG_GameSettings_C SaveGame)`
- `Load_ControlSettings(Object __WorldContext, out float Sensitivity, out bool InvertMouse, out Byte CameraSetting, out bool ShowBody, out bool UsingPushToTalk, out int FOV, out bool SmoothRotation, out bool HideGore, out float Gamma, out bool CameraShake, out bool ShowEventContent, out bool AimAssist, out bool ControllerFeedback, out bool ShowChat)`
- `SetHasSeenVHS(Object __WorldContext)`

### BP_FlareGun_C（继承 BP_Item_C）

- `MC_Fire()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `UseItem()`

### BP_FlareProjectile_C（继承 Actor）

- `ReceiveTick(float DeltaSeconds)`

### BP_GarageDoor_C（继承 InteractableActor）

- `CloseDoor()`
- `OnActorUsed(Character Character)`
- `OnUsedNotify()`
- `Open()`

### BP_Glowstick_Component_C（继承 ActorComponent）

- `TickPointlight(PointLightComponent PointLight, Vector ForwardVector)`
- `TickSpotlight(SpotLightComponent SpotLight)`

### BP_Init_C（继承 Actor）

- `Logined(UI_SignIn_C Widget)`
- `ReceiveBeginPlay()`

### BP_Item_AlmondBottle_C（继承 BP_Item_C）

- `SetMaterial(bool EnabledFOV)`

### BP_Item_AlmondWater_C（继承 BP_Item_C）

- `Damage_SERVER(Object Target, FancyCharacter Character)`  `[Server]`
- `OnEventLoaded(Byte EventType)`
- `PlayAnimation()`  `[Multicast]`
- `SetMaterial(bool EnabledFOV)`
- `ToggleEvent(bool Enable)`
- `UseItem()`

### BP_Item_BugSpray_C（继承 BP_Item_C）

- `Damage_SERVER(Object Target, FancyCharacter Character)`  `[Server]`
- `MC_Spray()`  `[Multicast]`
- `ResetCounter()`
- `UseItem()`

### BP_Item_C（继承 Actor）

- `OnEventLoaded(Byte EventType)`
- `OnFinishConsume(FancyCharacter Player)`
- `ReceiveBeginPlay()`
- `SetMaterial(bool EnabledFOV)`
- `ToggleEvent(bool Enable)`
- `UnHide()`  `[Client]`
- `UseItem()`

### BP_Item_Camera_C（继承 BP_Item_C）

- `MC_StartPicture(FancyCharacter Player)`  `[Multicast]`
- `MC_SwitchPhotos()`  `[Multicast]`
- `OnRep_CurrentPicture()`
- `OnRep_IsFlashlightOn()`
- `PlayAnimation()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `SRV_ToggleLight(bool Enabled)`  `[Server]`
- `SetMaterial(bool EnabledFOV)`
- `SnapPicture()`
- `StopPicture()`
- `Update()`  `[Multicast]`
- `UseItem()`

### BP_Item_Chainsaw_C（继承 BP_Item_C）

- `Damage_SERVER(Object Target, FancyCharacter Character)`  `[Server]`
- `OC_Trace()`  `[Client]`
- `PlayAnimation()`  `[Multicast]`
- `ReceiveDestroyed()`
- `SetMaterial(bool EnabledFOV)`
- `UseItem()`

### BP_Item_Crowbar_C（继承 BP_Item_C）

- `Damage_SERVER(Object Target, FancyCharacter Character)`  `[Server]`
- `OC_Trace()`  `[Client]`
- `PlayAnimation()`  `[Multicast]`
- `UseItem()`

### BP_Item_Firework_C（继承 BP_Item_C）

- `MC_Prime()`  `[Multicast]`
- `MC_Throw()`  `[Multicast]`
- `StartTimer()`
- `UseItem()`

### BP_Item_Flashlight_C（继承 BP_Item_C）

- `FadeLight(bool FadeOut)`
- `GetAdjustedIntensity(float Intensity, out float Adjusted)`
- `GetAdjustedRadius(float Radius, out float Adjusted)`
- `OnRep_IsFlashlightOn()`
- `PlayAnimation()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `SetMaterial(bool EnabledFOV)`
- `StartFlicker()`
- `ToggleFadePower(bool FadeOut)`
- `ToggleFlashlightPower(bool Power)`
- `UseItem()`

### BP_Item_Glowstick_C（继承 BP_Item_C）

- `GetAdjustedIntensity(float Intensity, out float Adjusted)`
- `GetAdjustedRadius(float Radius, out float Adjusted)`
- `MC_Fire()`  `[Multicast]`
- `PlaySubtitle()`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `ReceiveTick(float DeltaSeconds)`
- `UseItem()`

### BP_Item_Knife_C（继承 BP_Item_C）

- `Damage_SERVER(Object Target, FancyCharacter Character)`  `[Server]`
- `MC_Splat(Vector Location, Rotator Rotation)`  `[Multicast]`
- `MC_Untangle(Vector Location)`  `[Multicast]`
- `PlayAnimation()`  `[Multicast]`
- `SRV_StabPlayer(FancyCharacter Instigator, BPCharacter_Demo_C Player, Vector ImpactPoint)`
- `TraceForHit()`
- `UseItem()`

### BP_Item_PlasticBall_C（继承 BP_Item_C）

- `MC_Throw()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `UseItem()`

### BP_Item_Ticket_C（继承 BP_Item_C）

- `PlayAnimation()`  `[Multicast]`
- `UseItem()`

### BP_Item_Toy_C（继承 BP_Item_C）

- `MC_Drop()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `UseItem()`

### BP_Juice_C（继承 BP_Item_C）

- `PlayAnimation()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `SRV_FinishDrink()`  `[Server]`
- `SetMaterial(bool EnabledFOV)`
- `UseItem()`

### BP_Ladder_C（继承 InteractableActor）

- `MC_Sound()`  `[Multicast]`
- `OnActorUsed(Character Character)`
- `OnRep_UpdateCount()`
- `ReceiveBeginPlay()`
- `RefreshLadders(int Count)`

### BP_LadderCamera_C（继承 InteractablePawn）

- `ReceiveBeginPlay()`
- `ReceivePossessed(Controller NewController)`
- `UnPossess()`  `[Server]`

### BP_LadderDoor_C（继承 InteractableActor）

- `MC_Sound(SoundBase Sound)`  `[Multicast]`
- `OnActorUsed(Character Character)`
- `OnRep_Opened()`
- `OpenDoor()`
- `ReceiveBeginPlay()`

### BP_LadderManager_C（继承 Actor）

- `FoundLadder()`
- `ReceiveBeginPlay()`
- `SetLadders(int Count)`

### BP_LadderPiece_C（继承 InteractableActor）

- `OnActorUsed(Character Character)`
- `OnBeginHighlight()`
- `OnEndHighlight()`
- `ReceiveBeginPlay()`

### BP_Lever_C（继承 InteractableActor）

- `NextState()`  `[Server]`
- `OnActorUsed(Character Character)`
- `ToggleElevator()`

### BP_LightFade_Box_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`
- `ReceiveActorEndOverlap(Actor OtherActor)`

### BP_LightFade_Box_Fun_C（继承 BP_LightFade_Box_C）

- `ReceiveActorBeginOverlap(Actor OtherActor)`
- `ReceiveActorEndOverlap(Actor OtherActor)`

### BP_Lighthouse_C（继承 Actor）

- `FadeIn()`
- `FadeOut()`
- `OnRep_IsOn()`
- `Play Lighthouse()`
- `ReceiveBeginPlay()`
- `Start()`
- `StartTimer()`  `[Server]`
- `StopTimer()`  `[Server]`

### BP_Liquid_Pain_C（继承 BP_Item_C）

- `PlayAnimation()`  `[Multicast]`
- `ReceiveBeginPlay()`
- `SRV_FinishDrink()`  `[Server]`
- `SetMaterial(bool EnabledFOV)`
- `UseItem()`

### BP_LobbyActor_C（继承 Pawn）

- `CloseSettings()`
- `OpenSettings()`
- `ReceiveBeginPlay()`
- `RefreshFocus()`
- `ToggleKeyboard(bool Hide)`
- `ToggleWidgetInteraction()`
- `Update Beam()`

### BP_MyGameInstance_C（继承 FancyGameInstance）

- `BindEOSLoginCallback()`
- `BindOnControllerDisconnect()`
- `CheckAchievementQueue()`
- `CheckCanCommunicateOnlinePrivilege()`
- `CheckCanCrossplayPrivilege(bool bForceAttemptToResolve, Delegate Event)`
- `CheckCanPlayOnlinePrivilege()`
- `CheckCodeUnique(SessionsSearchSetting Code)`
- `CheckPremiumState()`
- `CheckShouldDisplayEvent()`
- `CreateServer(PlayerController PlayerController, Widget WidgetRef, Widget ParentRef, FName LevelName, int MaxPlayer, bool IsPrivate)`
- `CreateSessionSettings(bool IsPrivate, PlayerController InPlayerController, out Array Array)`
- `FixResolutionOnSteamDeck()`
- `FramePacingOnXSS()`
- `GenerateCode()`
- `HandleConnectionStatusChanged(bool NewConnectionStatus)`
- `HandleNetworkError(Byte FailureType, bool bIsServer)`
- `HideLoadingScreen()`
- `InitializeUserHandlingEvents()`
- `Initialize_AudioSettings()`
- `InlineLogin()`
- `IsOnline() → Bool`
- `IsPremiumAvailable() → Bool`
- `JoinServerSession(BlueprintSessionResult Session, PlayerController PlayerController, Widget ParentRef, bool ShowLoadingScreen)`
- `OnApplicationDeactivate()`
- `OnApplicationReactivate()`
- `OnCheckCrossplayPrivilegeComplete__DelegateSignature(bool bSuccess)`
- `OnCheckPremiumStateDone_Login(bool JustGotPremium)`
- `OnCheckPremiumStateDone__DelegateSignature(bool JustGotPremium)`
- `OnControllerDisconnected()`
- `OnEOSLoginDone(bool bSuccess)`
- `OnInlineLoginDone__DelegateSignature(bool Success)`
- `OnInputDeviceChangedEvent(Byte NewInputDevice)`
- `OnPlayerLoginChanged(int PlayerNum)`
- `OnPlayerLoginStatusChange__DelegateSignature(int PlayerNum, Enum PreviousStatus, Enum NewStatus, BPUniqueNetId NewPlayerUniqueNetID)`
- `OnPlayerLoginStatusChanged(int PlayerNum, Enum PreviousStatus, Enum NewStatus, BPUniqueNetId NewPlayerUniqueNetID)`
- `OnPlayerTalkingStateChanged(BPUniqueNetId PlayerId, bool bIsTalking)`
- `OnSessionInviteAccepted(bool bWasSuccessful, int LocalPlayerNum, BPUniqueNetId PersonInvited, BlueprintSessionResult SessionToJoin)`
- `OnSteamOverlayIsActive(bool isOverlayActive)`
- `PatchInputIni()`
- `ReceiveInit()`
- `ReceiveShutdown()`
- `RefreshGameplayActivityEventData(PlayerState NewPlayerState)`
- `RefreshPlayerCommPrivileges()`
- `ResetAfterErrorFocus(PlayerController PlayerController, Widget Widget)`
- `ResetInput()`
- `ResolveGameplayActivityEndStatus(FString Options)`
- `ResolveGameplayActivityEndStatusEvent(FString PendingMapOptions)`
- `ReturnToMainMenu()`
- `SageGameChatActive(bool bActive)`
- `SendGameplayActivityEndEvent(Byte LevelMode, Byte LevelDifficulty)`
- `SendGameplayActivityStartEvent()`
- `SendPlayerDisconnectEvent(Enum DisconnectReason)`
- `ShowLoadingScreen(PlayerController PlayerController, Text Message)`
- `ShowPremiumAccountUpgradeDialog()`
- `StartAchievementCheckTimer()`
- `UnBindEOSLoginCallback()`
- `UnlockAchievement(FName AchievementName, PlayerController PlayerController)`
- `UnlockAchievementFromQueue(FName Name)`
- `UpdateMissionTime(float DeltaSeconds)`
- `UpdatePlayerSpeakingInScoreboard(BPUniqueNetId NetId, bool IsSpeaking)`
- `_CheckCanCrossplayPrivilege_Internal(bool bForceAttemptToResolve)`

### BP_MySaveGame_C（继承 SaveGame）

- `DoesSimilarGameEntryExist(FString DisplayName, Byte Difficulty, out bool Result)`
- `GenerateNewSaveGameName(Byte Difficulty, out FString SlotName)`
- `GetDifficultyForSlot(FString Slot) → Byte`
- `GetSaveGameDisplayName(FString SlotName, out FString Value)`

### BP_Note_C（继承 ClientInteractableActor）

- `OnActorUsed(Character Character)`
- `ReceiveBeginPlay()`

### BP_Ocean_Manager_C（继承 Actor）

- `Find Target Player(out BPCharacter_Demo_C TargetPlayer)`
- `FindTarget()`
- `ReceiveBeginPlay()`
- `StartRisingWaves()`
- `StartSpawnTimer()`  `[Server]`
- `StopRisingWaves()`
- `StopSpawnTimer()`  `[Server]`
- `UpdateBuoyancy(bool Rising)`
- `UpdateDrowning(bool Rising)`
- `UpdateWaterSettings()`

### BP_Photo_Image_C（继承 ClientInteractableActor）

- `MC_UpdateImage(int Players)`  `[Multicast]`
- `OnActorUsed(Character Character)`

### BP_Pool_Ladder_C（继承 Actor）

- `CanClimb(Pawn Pawn) → Bool`
- `GetHeightPoint() → Vector`
- `GetStartPoint() → Vector`

### BP_Pushable_C（继承 PushableActor）

- `Can Push(BPCharacter_Demo_C Target, float NewParam, bool MoveForward, out bool NewParam2)`
- `Get Forward Collision Points(BPCharacter_Demo_C PushingActor, float Axis, out Array CollisionPoints)`
- `Get Right Collision Points(BPCharacter_Demo_C PushingActor, float Axis) → Array`
- `OnActorUsed(Character Character)`
- `OnRep_Active()`
- `OnRep_CanPush()`
- `OnRep_Index()`

### BP_Ragdoll_C（继承 Actor）

- `ReceiveBeginPlay()`

### BP_RefreshWaterBodies_C（继承 Actor）

- `ReceiveActorBeginOverlap(Actor OtherActor)`

### BP_Rope_C（继承 BP_Item_C）

- `AnimateRopeThrow()`
- `MC_ThrowCosmetics()`  `[Multicast]`
- `OnRep_RopeZone()`
- `ReceiveDestroyed()`
- `RemoveRope()`
- `SRV_TossRope(Vector Location)`  `[Server]`
- `TraceForRopeLocation()`  `[Client]`
- `UseItem()`

### BP_Rope_Trigger_C（继承 TriggerBox）

- `BreakRope(FancyCharacter Player)`
- `DestroyBlockingVolume()`  `[Multicast]`
- `OnRep_bSnapRope()`
- `SnapRope()`

### BP_Rope_Zone_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`
- `ReceiveActorEndOverlap(Actor OtherActor)`

### BP_RopeZone_C（继承 InteractableActor）

- `OnActorUsed(Character Character)`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `StopClimb()`
- `TeleportPlayer()`

### BP_RowBoat_C（继承 BoatPawn）

- `FindLand()`  `[Server]`
- `GetWaterWorldZ(Vector2D InLocation) → Float`
- `GetWaterWorldZ_0(Vector2D InLocation) → Float`
- `LookUp(float Value)`
- `Lookat2(SkeletalMeshComponent Mesh)`
- `OnPossess()`
- `OnQueryFinished(EnvQueryInstanceBlueprintWrapper QueryInstance, Byte QueryStatus)`
- `OnRep_DidPossess()`
- `OnRep_IsVisible()`
- `PlayScare()`  `[Client]`
- `PlayWarning()`  `[Client]`
- `ReceiveBeginPlay()`
- `ReceivePossessed(Controller NewController)`
- `ReceiveTick(float DeltaSeconds)`
- `ReceiveUnpossessed(Controller OldController)`
- `ResetDelay()`
- `SetInput(bool Enabled)`
- `StartBuoyancy()`
- `StartDelay()`
- `StartLookAt(Rotator StartRot, Rotator EndRot)`
- `StartSway()`
- `StopBuoyancy()`
- `Turn(float Value)`
- `UnPossess()`  `[Server]`
- `UpdateWaterLevel()`

### BP_Scanner_C（继承 BP_Item_C）

- `AddTarget(TargetsStruct TargetsStruct)`
- `FixUVStretching(Vector HitLocation, Vector HitNormal, PrimitiveComponent HitComponent, int FaceIndex, Vector2D HitUVLocation, out float FixedSize, out Vector FixedStretch)`
- `GetMaterial(MaterialInterface Material, out MaterialInterface Adjusted)`
- `Initialize()`  `[Client]`
- `InitializeColors()`
- `InitializeMaterials()`
- `LiDAR(float Delta)`
- `MC_Fire()`  `[Multicast]`
- `OC_Fire()`  `[Client]`
- `OnRep_bIsLiDAREnable()`
- `OnRep_bIsMotionScannerEnable()`
- `OnRep_bIsWaveScannerEnbale()`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `ReceiveTick(float DeltaSeconds)`
- `ResetSKCollisionUVBool()`
- `SRV_Lidar(HitResult HitResult, Color Color)`  `[Server]`
- `ScannerTraceCalc(out Vector TraceStart, out Vector TraceEnd)`
- `SetEnableLiDAR(bool Enable)`
- `SetEnableMotionScanner(bool bEnable)`  `[Server]`
- `SetEnableWaveScan(bool bEnable)`
- `SetMaterial(bool EnabledFOV)`
- `SetNewPositionTarget(Vector SecondLocation, out Vector ReturnPosition)`
- `SetScanDistance(float NewDistance)`
- `SetStartEnableMotionScanner(bool Activate)`
- `SetTargetPosition(bool OneTarget, MotionScannerComponent SetMotionScanner, StaticMeshComponent SetNpcMesh)`
- `SetTargets()`
- `SoundChangeDistance(float NewDistance)`
- `SpawnScannerBeam(Vector BeamStart, Vector BeamEnd)`
- `UpdateMinDistance() → Float`
- `UpdateScanPercent()`
- `UpdateTargetSound(float InFloat, bool bEnable)`
- `UseItem()`

### BP_ScannerComponent_C（继承 MotionScannerComponent）

- `EndWaveEvent()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `SetWavePosition()`
- `StartWaveEvent()`
- `UpdateMaterial(bool UseFOV)`

### BP_ScannerDirector_C（继承 MotionScannerDirector）

- `CheckForExistingRT(Actor HitActor, PrimitiveComponent HitComponent, out TextureRenderTarget2D RenderTarget)`
- `ClearRenderTargets()`
- `FixUVStretching(Vector HitLocation, Vector HitNormal, PrimitiveComponent HitComponent, int FaceIndex, Vector2D HitUVLocation, out float FixedSize, out Vector FixedStretch)`
- `InitializeMaterials()`
- `MC_LidarDot(HitResult HitResult, Color Color)`  `[Multicast]`
- `ReceiveBeginPlay()`

### BP_SimpleFancyError_C（继承 FancyUserFlow）

- `Run()`

### BP_Spectator_C（继承 Pawn）

- `ClientPossessed(MP_PlayerController_C PlayerController)`  `[Client]`
- `GetPlayerNamePlatform(PlayerState PlayerState, out FString PlayerName, out Enum PlayerPlatform)`
- `OnTargetDestroyed(Actor DestroyedActor)`
- `ReceivePossessed(Controller NewController)`
- `ResetSpectateToIndex0()`  `[Client]`
- `SpectateIndex(int SpectateIndex)`
- `SpectateNext()`
- `SpectateNextPlayer()`  `[Client]`
- `SpectatePrevious()`
- `SpectatePreviousPlayer()`  `[Client]`
- `UpdateSpectating(FString Spectating, Enum PlayerPlatform)`  `[Client]`

### BP_Storm_Volume_C（继承 TriggerBox）

- `ReceiveActorBeginOverlap(Actor OtherActor)`
- `ReceiveActorEndOverlap(Actor OtherActor)`
- `ResetRising()`
- `ResetStop()`
- `StartRising()`
- `StopRising()`

### BP_Thermometer_C（继承 BP_Item_C）

- `Has Spawned Display(out bool HasSpawned)`
- `OnRep_Temperature()`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `SetMaterial(bool EnabledFOV)`

### BP_Thermometer_Display_C（继承 Actor）

- `Construct Core()`
- `Construct Update()`
- `MaterialSettings(MeshComponent Mesh)`
- `SetDisplayValue(MeshComponent Mesh, FString Value)`
- `SetLength()`
- `SetSegmentType(PrimitiveComponent Mesh)`
- `Update()`

### BP_TimeStampCapture_C（继承 Actor）

- `ReceiveBeginPlay()`
- `Test()`

### BP_Tunnel_CameraManager_C（继承 Actor）

- `CheckPhotograph(FancyCharacter Player)`  `[Server]`
- `CheckPlayers()`
- `CheckTargets(Array Targets, FancyCharacter Player, out bool Completed)`
- `OnRep_CurrentIndex()`
- `ReceiveBeginPlay()`
- `Set Prop(Class Actor, int ObjectsNeeded)`
- `SetComplete()`  `[Server]`
- `UpdatePlayers()`

### BP_Vent_C（继承 InteractableActor）

- `Damage(Character Character)`
- `MC_Break()`  `[Multicast]`
- `OnRep_WasBroken()`
- `OnUsed()`
- `ReceiveBeginPlay()`

### BP_WalkieTalkie_C（继承 BP_Item_C）

- `ActivateRadio()`
- `MC_Alarm()`  `[Multicast]`
- `MC_Connect()`  `[Multicast]`
- `OnRep_NumConnected()`
- `PlaySubtitle()`
- `ReceiveBeginPlay()`
- `ReceiveDestroyed()`
- `ResetAlarm()`
- `SetMaterial(bool EnabledFOV)`
- `UseItem()`

### BP_WalkieTalkie_Display_C（继承 Actor）

- `Construct Core()`
- `Construct Update()`
- `MaterialSettings(MeshComponent Mesh)`
- `SetDisplayValue(MeshComponent Mesh, FString Value)`
- `SetLength()`
- `SetSegmentType(PrimitiveComponent Mesh)`
- `Update()`

### BPFL_ChatUtilities_C（继承 BlueprintFunctionLibrary）

- `CensorProfanity(FString Text, Object __WorldContext, out FString CleanMessageText, out bool ContainsProfanity)`
- `GetCensoredPlayerName(PlayerState PlayerState, Object __WorldContext, out FString CleanPlayerName)`

### BPFL_ControllerSupport_C（继承 BlueprintFunctionLibrary）

- `GetGridNavigationNextIndex(int CurrentIndex, int ArrayLength, int Columns, Enum Direction, Object __WorldContext, out int NewIndex)`

### BPFL_EntitySighting_C（继承 BlueprintFunctionLibrary）

- `CallOnEntitySighted_Actor(Actor OwningActor, Object __WorldContext)`
- `CallOnEntitySighted_Controller(Controller OwningController, Object __WorldContext)`

### BPFL_OnlineInteractions_C（继承 BlueprintFunctionLibrary）

- `CheckForBlockedPlayer(BP_BasePlayerController_C Player, Object __WorldContext, out bool IsBlocked)`

### BPFL_SaveSystem_C（继承 BlueprintFunctionLibrary）

- `ActivateControlPanel(int Index, Object __WorldContext)`
- `Add Placed Plushie(Object __WorldContext)`
- `AddDroppedGlowstick(Guid GlowstickID, S_Glowstick_Data GlowstickData, Object __WorldContext)`
- `CalculateGameTime(Array AdditionalLevelsToCount, Object __WorldContext, out float Time)`
- `ConvertStringToFloat(FString In, Object __WorldContext, out float Out)`
- `Create New Slot(FString SaveGameName, Byte Difficulty, Object __WorldContext, out bool Success, out FString SlotName)`
- `FinishedLevel(FName Level, float Speed, Object __WorldContext)`
- `FinishedValve(int LevelIndex, int ValveIndex, Object __WorldContext)`
- `Found Ladder(Object __WorldContext)`
- `FoundHotelKey(Object __WorldContext)`
- `FoundKey(Object __WorldContext)`
- `Get Difficulty(Object __WorldContext, out Byte Difficulty)`
- `GetCompletedLevels(Object __WorldContext, out Array LevelsCompleted)`
- `GetPlacedCans(Object __WorldContext, out int CansPlaced)`
- `GetSlotNameForSaveGameName(FString SaveGameName, Byte Difficulty, Object __WorldContext) → Str`
- `Load Game(Object __WorldContext, out BP_New_SaveGame_C SaveGame)`
- `LoadPlayerData(FString UUID, Object __WorldContext, out bool DidFind, out S_PlayerData Inventory)`
- `PlacedCan(Object __WorldContext)`
- `RemoveDroppedGlowstick(Guid GlowstickID, Object __WorldContext)`
- `Save Fuseboxes(FName Tag, Map Fuseboxes, Object __WorldContext)`
- `SaveGame(BP_New_SaveGame_C SaveGame, bool ForceSync, Object __WorldContext)`
- `SaveLevelItems(FName Level, Object __WorldContext)`
- `SavePlayerData(FString UUID, S_PlayerData PlayerData, Object __WorldContext)`
- `Set Collected Key(Object __WorldContext)`
- `Set Powered All(Object __WorldContext)`
- `Set Spawn in Elevator(bool ShouldSpawn, Object __WorldContext)`
- `SetActivatedComputer(Object __WorldContext)`
- `SetActivatedMap(Array Activated, Object __WorldContext)`
- `SetBoilerCheckpoint(int Progress, Object __WorldContext)`
- `SetBoilerOpened(Object __WorldContext)`
- `SetCaveCheckpoint(int Progress, Object __WorldContext)`
- `SetCheckpointReached(Object __WorldContext)`
- `SetCollectedAllPlushies(Object __WorldContext)`
- `SetCompletedBallonPuzzle(Object __WorldContext)`
- `SetCurrentLevel(FName Level, Object __WorldContext)`
- `SetDidResetPictures(Object __WorldContext)`
- `SetDifficulty(Byte Difficulty, Object __WorldContext)`
- `SetDoorBroken(FString DoorID, Object __WorldContext)`
- `SetDoorUnlocked(FString DoorID, Object __WorldContext)`
- `SetEastSubstationUnlocked(Object __WorldContext)`
- `SetExitIndex(int Index, Object __WorldContext)`
- `SetEyeDisarmed(FString EyeID, Object __WorldContext)`
- `SetFacelingSpawned(Object __WorldContext)`
- `SetFinishedElevator(Object __WorldContext)`
- `SetFloorIndex(int Index, Object __WorldContext)`
- `SetFoundCassette(Object __WorldContext)`
- `SetGarageElevatorIndex(int Index, Object __WorldContext)`
- `SetGarageExitIndex(int Index, Object __WorldContext)`
- `SetGaragePowerOn(Object __WorldContext)`
- `SetGeneratorUnlocked(Object __WorldContext)`
- `SetGrassroomsCheckpoint(int Checkpoint, Object __WorldContext)`
- `SetHasOpenedDeathSlidesGates(Object __WorldContext)`
- `SetHasUnlocked974Ending(Object __WorldContext)`
- `SetHasUnlockedCityEnding(Object __WorldContext)`
- `SetHasUnlockedFinalEnding(Object __WorldContext)`
- `SetHasUnlockedHillsEnding(Object __WorldContext)`
- `SetHasUnlockedMainEnding(Object __WorldContext)`
- `SetHasWatchedVideo(Object __WorldContext)`
- `SetHasZone1Key(Object __WorldContext)`
- `SetHasZone2Key(Object __WorldContext)`
- `SetHasZone3Key(Object __WorldContext)`
- `SetHasZone4Key(Object __WorldContext)`
- `SetHeavyDoorOpened(Object __WorldContext)`
- `SetHotelLobbyOpened(Object __WorldContext)`
- `SetKeyPlaced(int Index, Object __WorldContext)`
- `SetLevel05Checkpoint(int Progress, Object __WorldContext)`
- `SetLevel10Checkpoint(Object __WorldContext)`
- `SetLevel7Checkpoint(int Progress, Object __WorldContext)`
- `SetLevel94Checkpoint(int Progress, Object __WorldContext)`
- `SetLevelDashCheckpoint(int Progress, Object __WorldContext)`
- `SetMEGCardCollected(Object __WorldContext)`
- `SetMEGGateOpened(Object __WorldContext)`
- `SetMEGPowerOn(Object __WorldContext)`
- `SetMEGSecurityUnlocked(Object __WorldContext)`
- `SetMembriSpawned(Object __WorldContext)`
- `SetNPCDropped(Array InputPin, Object __WorldContext)`
- `SetNotesPlaced(Map Notes, Object __WorldContext)`
- `SetOpenedVendingMachine(Object __WorldContext)`
- `SetPicturesTaken(int Progress, Object __WorldContext)`
- `SetPlacedAllTVs(Object __WorldContext)`
- `SetPlasticMarianaCheckpoint(int Checkpoint, Object __WorldContext)`
- `SetPlasticMarianaFlowerLocations(Map RandomRoomsUsed, Map RandomSolverRoomsUsed, bool bLoadFromSave, Object __WorldContext)`
- `SetPoolsActivated(int PoolsActivated, Object __WorldContext)`
- `SetPoppedBalloon(FString BalloonID, Object __WorldContext)`
- `SetPoweredAllGenerators(Object __WorldContext)`
- `SetReachedCheckpoint(Object __WorldContext)`
- `SetSeenFirstHound(Object __WorldContext)`
- `SetSlidesDropped(Array Slides, Object __WorldContext)`
- `SetTVsPlaced(Array TVsPlaced, Object __WorldContext)`
- `SetTapesCollected(int TapesCollected, Object __WorldContext)`
- `SetTeethOpened(Object __WorldContext)`
- `SetTurbinesActivated(int Activated, Object __WorldContext)`
- `SetUnlockedBottom(Object __WorldContext)`
- `SetUnlockedElevator(Object __WorldContext)`
- `SetUnlockedFun(Object __WorldContext)`
- `SetUnlockedMEG(Object __WorldContext)`
- `SetUnlockedSafe(Object __WorldContext)`
- `SetUnlockedSnackrooms(Object __WorldContext)`
- `SetVentBroken(Object __WorldContext)`
- `SetWatchedElevatorVideo(Object __WorldContext)`
- `SetWestSubstationUnlocked(Object __WorldContext)`
- `UnlockedHub(FName Level, Object __WorldContext)`
- `UnlockedManillaRoom(Object __WorldContext)`

### BPFL_TelemetryUtilities_C（继承 BlueprintFunctionLibrary）

- `RefreshGameplayActivityTelemetryData(PlayerState NewPlayerState, Object __WorldContext)`
- `SendDisconnectTelemetryEvent(Enum DisconnectReason, Object __WorldContext)`
- `SendQuitGameTelemetryEvent(Object __WorldContext)`

### BPFL_UserPrivileges_C（继承 BlueprintFunctionLibrary）

- `CanCrossplay(Object __WorldContext, out bool CanCrossplay)`
- `CanPlayOnline(Object __WorldContext, out bool CanPlayOnline)`
- `CanUseCommunication(Object __WorldContext, out bool CanCommunicateOnline)`

### BPFL_XP_C（继承 BlueprintFunctionLibrary）

- `AddEXP(float XP, Object __WorldContext)`
- `CalculateXPNeededForNextLevel(int CurrentXP, Object __WorldContext, out int CurrentLevel, out int CurrentLevelBaseXP, out int NextLevelXP, out int XPNeeded)`
- `LoadEXP(Object __WorldContext, out float Exp)`
- `LoadLevelFromXP(int XP, Object __WorldContext, out int Level, out int VisualLevel)`

### BPP_HISM_C（继承 Actor）

- `ReceiveBeginPlay()`
- `SetMaxDrawDistance()`
- `TODO_SetBBOxOfActor()`

### BPP_ISM_C（继承 Actor）

- `ReceiveBeginPlay()`
- `SetMaxDrawDistance()`

### BT_CallEntitySighted_Mission_C（继承 BTTask_BlueprintBase）

- `ReceiveExecuteAI(AIController OwnerController, Pawn ControlledPawn)`

### BTDecorator_CanMove_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTDecorator_IsCarrying_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTDecorator_ShouldMove_2_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTDecorator_ShouldMove_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`
- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTDecorator_ShouldMove_Smiler_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTDecorator_ShouldRoam_C（继承 BTDecorator_BlueprintBase）

- `PerformConditionCheckAI(AIController OwnerController, Pawn ControlledPawn) → Bool`

### BTService_CheckVisiblePlayers_C（继承 BTService_BlueprintBase）

- `ReceiveTickAI(AIController OwnerController, Pawn ControlledPawn, float DeltaSeconds)`

### BTTask_PlaySound_C（继承 BTTask_BlueprintBase）

- `MC_PlaySound(Vector Location)`  `[Multicast]`
- `ReceiveExecuteAI(AIController OwnerController, Pawn ControlledPawn)`

### BTTask_RoamLocation_C（继承 BTTask_BlueprintBase）

- `ReceiveExecuteAI(AIController OwnerController, Pawn ControlledPawn)`

### BTTask_RoamLocation_Level05_C（继承 BTTask_BlueprintBase）

- `ReceiveExecuteAI(AIController OwnerController, Pawn ControlledPawn)`

### BTTask_Teleport_C（继承 BTTask_BlueprintBase）

- `ReceiveExecuteAI(AIController OwnerController, Pawn ControlledPawn)`

### ChatComponent_C（继承 ActorComponent）

- `Clear_Chat()`
- `Create_Chat_Widget(bool IsInGame)`
- `Focus_Chat()`
- `Get All ChatComponents(out Array PlayerControllers)`
- `GetSenderPlayerState(S_ChatMessage ChatMessage, out PlayerState PlayerState, out bool Success)`
- `OC_Setup_Chat_Widget(bool IsInGame)`  `[Client]`
- `OC_Update_Chat(S_ChatMessage Message)`  `[Client]`
- `ReceiveBeginPlay()`
- `SR_Update_Chat(S_ChatMessage Message)`  `[Server]`
- `ToggleChatBox(bool IsVisible)`

### ClientInteractableActor（继承 InteractableActor）

- `OnUsed()`

### ClientInteractablePawn（继承 InteractablePawn）

- `OnUsed()`

### Costume（继承 PrimaryDataAsset）

- `GetCostumeSourceDisplayName(Costume Costume) → Str`

### CostumeCharacter（继承 Interface）

- `ApplyCostume(Costume Costume)`

### CostumeCharacterFunctionLibrary（继承 BlueprintFunctionLibrary）

- `ApplyCostumeToDismembermentMesh(StaticMeshComponent MeshComponent, Costume Costume, Enum DismembermentPart)`
- `ApplyCostumeToFirstPersonArmsSkeletalMesh(SkeletalMeshComponent SkeletalMesh, Costume Costume, bool bApplyAnimBP)`
- `ApplyCostumeToFirstPersonArmsSkeletalMeshViaLevelSequenceBinding(MovieSceneSequencePlayer Player, MovieSceneObjectBindingID BindingID, Costume Costume)`
- `ApplyCostumeToFirstPersonLegsSkeletalMesh(SkeletalMeshComponent SkeletalMesh, Costume Costume, bool bApplyAnimBP)`
- `ApplyCostumeToFirstPersonLegsSkeletalMeshViaLevelSequenceBinding(MovieSceneSequencePlayer Player, MovieSceneObjectBindingID BindingID, Costume Costume)`
- `ApplyCostumeToThirdPersonSkeletalMesh(SkeletalMeshComponent SkeletalMesh, Costume Costume, bool bApplyAnimBP)`
- `ApplyCostumeToThirdPersonSkeletalMeshViaLevelSequenceBinding(MovieSceneSequencePlayer Player, MovieSceneObjectBindingID BindingID, Costume Costume)`
- `GetDismembermentPartMeshAndMaterialSet(Costume Costume, Enum DismembermentPart, out StaticMesh Mesh, out Map MaterialSet)`

### CostumeLoaderSubsystem（继承 WorldSubsystem）

- `LoadAndApplyCostumeBP(Costume Costume, Actor Actor)`
- `LoadAndApplyCostumeBPWithCallback(Costume Costume, Actor Actor, Delegate OnAppliedCostume)`

### CostumeSelector（继承 Actor）

- `ApplySelectedCostume()`
- `EndCostumeSelect()`
- `HandleFinishedLoadedFeedback()`
- `HandleFinishedLoadingFeedback()`
- `HandleTransitionFromCostumeSelectorComplete()`
- `OnExitCostumeSelect()`
- `OnStartedCostumeSelect()`
- `SelectCostume(Costume Costume)`
- `ShowLoadedFeedback(Delegate FeedbackCompleteCallback)`
- `ShowLoadingFeedback(Delegate FeedbackCompleteCallback)`
- `StartCostumeSelect(UserWidget CostumeSelectorWidget)`
- `TransitionFromCostumeSelector(Actor TransitionToViewTarget, Delegate FeedbackCompleteCallback)`
- `TransitionToCostumeSelector()`
- `TryFireSafeLoadingStateCallback()`

### CostumeSelectorWidget（继承 Interface）

- `HideLoadingWheel()`
- `SetUp(CostumeSelector CostumeSelectorActor, Array CostumeList)`
- `ShowLoadingWheel()`

### CostumeSubsystem（继承 GameInstanceSubsystem）

- `GetLocalArmedCostume() → Costume`
- `SetLocalArmedCostume(Costume Costume)`
- `SetLocalArmedCostumeByName(FName CostumeName)`

### CustomUserWidget（继承 UserWidget）

- `RefreshInventory() → Bool`
- `SetHotbarSlot(int ItemSlot)`
- `ToggleInventory(bool IsVisible)`

### DroppedItem（继承 Actor）

- `EvaluatePhysics()`  `[Multicast]`
- `OnBeginFocus()`
- `OnEndFocus()`
- `StopPhysics()`
- `UpdatePhysicsLocation()`

### Flaregun_BP_C（继承 Actor）

- `ReceiveBeginPlay()`

### Flashlight_BP_C（继承 Actor）

- `ReceiveBeginPlay()`

### Glowstick_BP_C（继承 Actor）

- `ReceiveBeginPlay()`

### GripMotionControllerComponent（继承 MotionControllerComponent）

- `BP_IsLocallyControlled() → Bool`
- `GetPhysicsVelocity(out Vector AngularVelocity, out Vector LinearVelocity)`
- `OnRep_ReplicatedControllerTransform()`
- `Server_SendControllerTransform(Transform NewTransform)`  `[Server]`

### InspectableActor（继承 Actor）

- `GetMesh() → StaticMeshComponent`
- `SetCameraLocation(CameraComponent CameraComponent)`
- `SetPlayerRef(Character Ref)`
- `SetViewing()`

### InteractableActor（继承 Actor）

- `BlockUsage()`
- `OnBeginHighlight()`
- `OnEndHighlight()`
- `OnInteractStartedLocal()`
- `OnRep_IsUsable()`
- `OnRep_WasUsed()`
- `OnUsedAll()`
- `OnUsedMulticast()`  `[Multicast]`
- `OnUsedNotify()`
- `OnUsedServer()`  `[Server]`
- `ResetUsage()`

### InteractableComponent（继承 StaticMeshComponent）

- `BlockUsage()`
- `OnRep_WasUsed()`
- `OnUsedAll()`
- `OnUsedMulticast()`  `[Multicast]`
- `OnUsedNotify()`
- `OnUsedServer(Character Character)`  `[Server]`
- `ResetUsage()`

### InteractableInterface（继承 Interface）

- `OnActorUsed(Character Character)`

### InteractablePawn（继承 Pawn）

- `BlockUsage()`
- `OnAttemptUse(bool CanUse)`
- `OnHiddenPossess(Character Character)`
- `OnPermanentlyDisabled()`  `[Server]`
- `OnPossess()`
- `OnRep_IsUsable()`
- `OnRep_WasUsed()`
- `OnStartInteracting(Character Character)`  `[Server]`
- `OnStopInteracting()`  `[Server]`
- `OnUnPossess()`
- `OnUsedAll()`
- `OnUsedMulticast()`  `[Multicast]`
- `OnUsedNotify()`
- `OnUsedServer(Character Character)`  `[Server]`
- `OnVRPossess(bool bPossess)`
- `ResetUsage()`
- `SetCameraPostProcessing(Character Character)`  `[Multicast]`
- `SetUsingVR(Character Character, bool bPossess)`  `[Multicast]`
- `ToggleMouse(bool bHide)`  `[Multicast]`

### INTERACTIVE_FoliageComp_BP_C（继承 FoliageInstancedStaticMeshComponent）

- `AddInstanceStatus(int InstanceIndex, Byte Status)`
- `Copy&SetFoliageParameters(INTERACTIVE_FoliageComp_BP_C copyFrom)`
- `Copy&SetFoliageParameters_FromClass(Class copyFrom, StaticMesh meshToSet)`
- `DivideIntoChunks_InfLoopWorkaround(float chunkSize)`
- `ForceMarkDirty()`
- `GetCurrentInstanceDeformAlpha(int InstanceIndex, out bool hasInstanceData, out float CurrentAlpha)`
- `GetCurrentInstanceGPU_Offset(int InstanceIndex, bool AtSpecifiedAlpha, float SpecifiedAlpha, out Vector CurrentOffset)`
- `GetCurrentInstanceUN-DeformAlpha(int InstanceIndex, out bool hasInstanceData, out float CurrentAlpha)`
- `IsTrampled?(int InstanceIndex, out bool ?)`
- `ReceiveBeginPlay()`
- `ReceiveEndPlay(Byte EndPlayReason)`
- `RemoveAnyActiveStatuses(int InstanceIndex)`
- `RemoveInstanceStatus(int InstanceIndex, Byte Status)`
- `Start New Instance Offset(int Instance, Vector NewOffset, float DeformDuration, float UnDeformSpeed, bool UpdateComponent, float IgnoreIfGrowing)`
- `UnloadedViaStreaming__DelegateSignature()`

### InteractiveGrassManager_BP_C（继承 Actor）

- `AddFoliageChunkActor(Vector ChunkCenter, INTERACTIVE_FoliageComp_BP_C SourceComponent, bool replaceWithSourceComponent, bool leaveDefaultComponent, out InteractiveFoliageChunk_BP_C addedChunk)`
- `DistanceToViewTarget(Vector fromLocation, out float Distance)`
- `FreeUpMaterialInteractionChannel(int nrOfChannel)`
- `GetFreeMaterialInteractionChannel(out bool Found, out int foundChannel)`
- `PopulateMapWithGrass()`
- `ReceiveBeginPlay()`
- `SmoothlyChangeWindDirection(Vector newDirection)`
- `SmoothlyChangeWindStrength(float newStrength)`
- `SpawnFoliage(bool spawnUnderCursor, Vector locationIfNotUnderCursor, Vector normalIfNotUnderCursor, Vector minScale, Vector MaxScale, FoliageToSpawn_Struct FoliageToSpawn, bool fromCluster, bool clusterLastIndex)`
- `SpawnFoliageCluster(Vector CenterLocation, float sizeX_, float sizeY_, float density_, float nonUniformDistribution, FoliageToSpawn_Struct FoliageToSpawn, Vector minScale, Vector MaxScale, bool useGrassSpawnAreas, GrassSpawnArea_BP_C grassSpawnArea)`

### InteractWithGrass_BP_C（继承 SceneComponent）

- `CheckIfComponentsStillNear()`
- `CheckIfShouldTurn_OFF_DispInteraction()`
- `CheckIfShouldTurn_ON_DispInteraction()`
- `CheckIfShould_DISABLE_MatInteraction()`
- `CheckIfShould_ENABLE_MatInteraction()`
- `CheckNearbyGrass()`
- `DetectNearbyComponents()`
- `FreeUpInteractionChannel()`
- `IsInDistanceToViewTarget(float inDistance, out bool isInDistance, out float currentDistance)`
- `OnOwnerDestroyed(Actor DestroyedActor)`
- `ReceiveBeginPlay()`
- `Start Interacting()`
- `TurnOFF()`
- `TurnON()`
- `UpdateMatInterParamForMainActor()`
- `UpdateMatInteractionParam()`

### InventoryComponent（继承 ActorComponent）

- `AddToInventory(InventoryItem Item) → Bool`
- `DropItem(Byte Slot)`
- `GetItemAtSlot(int SlotIndex) → InventoryItem`
- `IsSlotEmpty(int SlotIndex) → Bool`
- `RemoveFromInventory(InventoryItem Item)`
- `SwapInventoryItems(int FirstIdx, int SecondIdx)`

### ItemActor（继承 Actor）

- `CustomInventoryUse()`
- `Use()`

### Level0Generator（继承 Actor）

- `Generate()`

### LIDARBlueprintFunctionLibrary（继承 BlueprintFunctionLibrary）

- `CreateLiDarDot(Object caller, TextureRenderTarget2D RenderTarget) → LIDARDotStruct`
- `FindCollisionUVSkeletalMesh(HitResult Hit, out Vector2D UV) → Bool`

### LIDARComponent（继承 ActorComponent）

- `ScannerTrace(StaticMeshComponent Mesh) → HitResult`
- `ShootAuto()`  `[Client]`
- `ShootGun()`  `[Client]`
- `ShootReset()`

### MapEditorCharacterMovement（继承 CharacterMovementComponent）

- `DecreaseSpeedMultiplier(float DecreaseAmount)`
- `EnterMovementMode(bool Enter)`
- `InMovementMode() → Bool`
- `IncreaseSpeedMultiplier(float IncreaseAmount)`
- `Init()`
- `LookUp(float Value)`
- `MoveForward(float Value)`
- `MoveRight(float Value)`
- `MoveUp(float Value)`
- `Server_SetSpeedMultiplier(float SpeedMultiplier)`  `[Server]`
- `Turn(float Value)`

### MapEditorHandlerComponent（继承 ActorComponent）

- `DeleteActor()`
- `DeselectActor()`
- `GetActorName() → Str`
- `GetActorTransform() → Transform`
- `GetGizmoType() → Enum`
- `GetReplicationRate() → Float`
- `GetSnapAmount() → MapEditorSnapping`
- `Grab()`
- `HasValidReturnPawn() → Bool`
- `Init()`
- `MouseTrace(float Distance, out bool bHitGizmo, bool bDrawDebugLine) → HitResult`
- `OnRep_CurrentActor()`
- `Release()`
- `Server_DeleteActor(Actor Actor)`  `[Server]`
- `Server_ReplicateTransform(Actor Actor, Transform Transform)`  `[Server]`
- `Server_SpawnActor(Class ActorClass)`  `[Server]`
- `Server_UnpossessToReturnPawn()`  `[Server]`
- `SetActor(Actor Actor)`
- `SetActorTransform(Transform NewTransform)`
- `SetReturnPawn(Pawn Pawn)`
- `SetSnapAmount(MapEditorSnapping SnappingAmounts)`
- `ShowMovement()`
- `ShowRotation()`
- `ShowScale()`
- `SpawnActor(Class ActorClass)`
- `Undo()`
- `UnpossessToReturnPawn()`

### MapEditorInterface（继承 Interface）

- `OnDeleted()`
- `OnGrabbed()`
- `OnMaterialLoaded(MapEditorItemMaterial MapEditorItemMaterial)`
- `OnRelease()`
- `OnScaleChanged(Vector NewScale)`
- `OnUndo()`

### MapEditorStatics（继承 BlueprintFunctionLibrary）

- `ClearMap(Actor WorldActor)`
- `DeSerializeLevel(FString JsonString, out bool Success) → MapEditorItems`
- `DoesMapExist(Actor WorldActor, FString MapDirectory, FString MapName) → Bool`
- `GetMapList(Actor WorldActor, FString Directory, bool bCutLevelname, bool bShowAllMaps) → Array`
- `GetRealMapName(FString MapName) → Str`
- `LoadMapFromFile(Actor WorldActor, FString MapDirectory, FString MapName, FString Extension, out FString OutString, out FString FullMapName) → Bool`
- `RemoveExtension(FString String) → Str`
- `SaveMapToFile(Actor WorldActor, FString MapDirectory, FString MapName, FString StringToSave, out FString FullMapName) → Bool`
- `SerializeLevel(Actor WorldActor, out bool Success) → Str`
- `SetMaterials(MapEditorItemMaterial MapEditorItemMaterial)`
- `SpawnMapItems(Actor WorldActor, MapEditorItems MapItems)`
- `SpawnMapItemsFromJson(Actor WorldActor, FString JsonString)`

### MissionData（继承 Object）

- `AddEntitySighting()`
- `AddLowSanityAmount()`
- `AddPlayerDeath()`
- `SetTimeCompleted(float Time)`

### MotionScannerComponent（继承 ActorComponent）

- `EndWaveEvent()`
- `SetNewScanDistance(float setDistance)`
- `StartWaveEvent()`

### MotionScannerDirector（继承 Actor）

- `CheckLIDARDots()`

### Old_Instance_C（继承 AdvancedFriendsGameInstance）

- `CheckCodeUnique(SessionsSearchSetting Code)`
- `CreateServer(PlayerController PlayerController, Widget WidgetRef, Widget ParentRef, FName LevelName, int MaxPlayer, bool IsPrivate, Text ServerName)`
- `GenerateCode()`
- `Initialize_AudioSettings()`
- `JoinServerCode(FString Code, PlayerController PlayerController, Widget ParentRef)`
- `JoinServerSession(BlueprintSessionResult Session, PlayerController PlayerController, Widget ParentRef, bool ShowLoadingScreen)`
- `OnPlayerTalkingStateChanged(BPUniqueNetId PlayerId, bool bIsTalking)`
- `OnSessionInviteAccepted(bool bWasSuccessful, int LocalPlayerNum, BPUniqueNetId PersonInvited, BlueprintSessionResult SessionToJoin)`
- `ReceiveInit()`
- `ResetAfterErrorFocus(PlayerController PlayerController, Widget Widget)`
- `ShowLoadingScreen(PlayerController PlayerController, Text Message)`
- `ToggleVoiceIngame(bool IsActivated)`
- `UnlockAchievement(FName AchievementName)`

### PlayerEQSQuery_C（继承 EnvQueryContext_BlueprintBase）

- `ProvideActorsSet(Object QuerierObject, Actor QuerierActor, out Array ResultingActorsSet)`
- `ProvideActorsSet(Object QuerierObject, Actor QuerierActor, out Array ResultingActorsSet)`

### PushableActor（继承 InteractableActor）

- `GetClosesPoint(Actor InActor) → Vector`
- `GetForwardBoundingPoints(bool InInvert) → Array`
- `GetRightBoundingPoints(bool InInvert) → Array`

### RadarPlayerComponent（继承 ActorComponent）

- `EndWaveEvent()`
- `SetNewScanDistance(float setDistance)`
- `StartWaveEvent()`

### Rope_BP_C（继承 Actor）

- `ReceiveBeginPlay()`

### Scanner_BP_C（继承 Actor）

- `ReceiveBeginPlay()`

### SequenceDirector_C（继承 LevelSequenceDirector）

- `SequenceEvent_0()`
- `SequenceEvent_0()`
- `SequenceEvent_0()`
- `SequenceEvent_0()`
- `SequenceEvent__ENTRYPOINTSequenceDirector_0()`
- `SequenceEvent__ENTRYPOINTSequenceDirector_0()`
- `SequenceEvent__ENTRYPOINTSequenceDirector_0()`
- `SequenceEvent__ENTRYPOINTSequenceDirector_0(SkeletalMeshComponent SkeletalMeshComponent0)`
- `SkeletalMeshComponent0_Event_0(SkeletalMeshComponent SkeletalMeshComponent0)`

### VineGrow_BP_C（继承 Actor）

- `Get Max Number Of Segments(out int Segments)`
- `GrowVines()`
- `ReceiveBeginPlay()`
- `ReceiveTick(float DeltaSeconds)`
- `ResetVines()`
- `UpdateCurrentSegment()`
- `UpdateSplineVisibility()`