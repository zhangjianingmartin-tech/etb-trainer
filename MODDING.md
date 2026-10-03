# 用自己的模型换肤

本工具的 F4 换肤可以加载你自己做的模型。模型要先打包成模组 pak，放进游戏目录，再在 `custom_skins.txt` 里登记路径。只有你自己看得到（其他玩家没有这个 pak，也没有运行本工具）。

> 目前已验证：按路径加载资源、套用模型和动画蓝图的流程（用游戏自带资源测试）。
> 还没验证：游戏会不会加载 `~mods` 里的第三方 pak。从文件看，游戏的 pak 是 v11 格式、未加密、没有 `.sig` 签名文件，按 UE4 的默认行为应该会加载，但需要你做出第一个 pak 后实际确认。

## 你需要

- **Unreal Engine 4.27**（Epic Games Launcher 里安装，版本必须一致）
- 一个已经蒙皮（绑了骨骼）的模型，FBX 格式
- 可选：[FModel](https://fmodel.app/)，用来查看游戏的 pak 内容和导出玩家骨骼（游戏 pak 没加密，不需要密钥）

## 方式一：沿用玩家原有动画（推荐）

模型绑在游戏玩家骨骼上，走路、跑步、蹲下都能直接用游戏原来的动画。

1. 用 FModel 打开 `EscapeTheBackrooms\Content\Paks\EscapeTheBackrooms-WindowsNoEditor.pak`，找到 `/Game/Player/Hazmat` 和 `/Game/Player/Standard_Walk_Skeleton`，导出成 glTF 或 PSK。
2. 在 Blender 里把你的模型蒙皮到这套骨骼上：骨骼名称和层级必须完全一致，然后导出 FBX。
3. 在 UE 4.27 里新建一个空项目，**项目名必须叫 `EscapeTheBackrooms`**（这样 pak 里的路径才和游戏的 `/Game/` 对得上）。
4. 先把导出的 Hazmat 导入到 `/Game/Player/`，让编辑器里也有一个同路径的 `Standard_Walk_Skeleton` 骨骼资源。
5. 把你的模型导入到 `/Game/Mods/<你的名字>/`，导入时 Skeleton 选上一步的 `Standard_Walk_Skeleton`。
6. 项目设置 → Packaging：
   - 勾选 **Use Pak File**；
   - 在 **Directories to never cook** 里加上 `/Game/Player`，避免把游戏原有的骨骼打进你的 pak、覆盖掉原版。
7. File → Package Project → Windows (64-bit)。打包结果里的 `EscapeTheBackrooms\Content\Paks\EscapeTheBackrooms-WindowsNoEditor.pak` 就是你的模组，把它改名为 `MyModel_P.pak`（`_P` 结尾的 pak 加载优先级更高）。

## 方式二：自带骨骼和动画

模型用自己的骨骼，需要在 UE 里额外做一个动画蓝图：用 `Try Get Pawn Owner → Get Velocity` 读取速度，驱动待机和行走动画。打包步骤同上，`custom_skins.txt` 第三列填动画蓝图的类路径（以 `_C` 结尾）。

## 安装和使用

1. 在游戏目录 `EscapeTheBackrooms\Content\Paks\` 下新建文件夹 `~mods`，把 `MyModel_P.pak` 放进去。
2. 重启游戏。
3. 编辑工具目录下的 `custom_skins.txt`，加一行：
   ```
   我的模型 | /Game/Mods/MyName/SK_MyModel.SK_MyModel
   ```
   路径格式是 `/Game/文件夹/资源名.资源名`，和 UE 内容浏览器里右键 Copy Reference 得到的路径一致（去掉前面的 `SkeletalMesh'` 和结尾的引号）。
4. 进游戏按 F4 切到“自定义 我的模型”，按 F3 开第三人称查看。

切到这个皮肤时如果提示“加载失败”，按顺序检查：pak 是否在 `~mods` 里、游戏是否重启过、路径有没有写错、打包用的引擎版本是不是 4.27。

## 注意

- 不要把游戏原有资源（包括导出的骨骼和模型）重新打包发布。
- 联机时只有你自己能看到自定义模型。游戏会不会因为多了一个 pak 影响联机，目前还没测试。
