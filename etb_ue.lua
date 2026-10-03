-- Escape the Backrooms (UE 4.27) 逆向辅助脚本
-- 用法：CE 附加 Backrooms-Win64-Shipping.exe 后，File -> Execute Script 执行本文件
-- 全局地址靠 AOB 定位，游戏小更新后通常仍然有效

local MOD = 'Backrooms-Win64-Shipping.exe'
UE = {}

local function scanOne(pat)
  local base, size = getAddress(MOD), getModuleSize(MOD)
  local ms = createMemScan()
  ms.firstScan(soExactValue, vtByteArray, rtRounded, pat, nil, base, base+size, '+X-C-W', fsmNotAligned, '1', true, false, false, false)
  ms.waitTillDone()
  local fl = createFoundList(ms); fl.initialize()
  local a = fl.Count > 0 and tonumber(fl.Address[0], 16) or nil
  fl.destroy(); ms.destroy()
  return a
end
local function rip(a) return a + 7 + readInteger(a + 3, true) end

UE.GNames = rip(scanOne('4C 8D 05 ?? ?? ?? ?? EB 16 48 8D 0D ?? ?? ?? ?? E8'))   -- FNamePool
UE.GObj   = rip(scanOne('48 8B 05 ?? ?? ?? ?? 48 8B 0C C8 48 8D 04 D1'))         -- GUObjectArray.ObjObjects
UE.GWorld = rip(scanOne('48 8B 1D ?? ?? ?? ?? 48 85 DB 74 ?? 41 B0 01'))         -- UWorld*

-- 名字解析（FNamePool，4.27 布局）
function UE.name(id)
  local b = readPointer(UE.GNames + 0x10 + (id >> 16) * 8); if not b then return '?' end
  local e = b + (id & 0xFFFF) * 2
  local hdr = readSmallInteger(e); if not hdr then return '?' end
  local len = hdr >> 6
  if len <= 0 or len > 1024 then return '?' end
  if (hdr & 1) == 1 then return readString(e + 2, len * 2, true) end
  return readString(e + 2, len)
end
function UE.fname(a)
  local s = UE.name(readInteger(a)); local n = readInteger(a + 4) or 0
  if n > 0 then s = s .. '_' .. (n - 1) end
  return s
end

-- UObject: Class@0x10 Name@0x18 Outer@0x20
function UE.objname(o) return UE.fname(o + 0x18) end
function UE.class(o) return readPointer(o + 0x10) end
function UE.obj(i)
  local chunk = readPointer(readPointer(UE.GObj) + (i // 65536) * 8); if not chunk then return nil end
  return readPointer(chunk + (i % 65536) * 0x18)
end
function UE.count() return readInteger(UE.GObj + 0x14) end

function UE.findClass(short)
  for i = 0, UE.count() - 1 do
    local o = UE.obj(i)
    if o and o ~= 0 and UE.objname(o) == short then
      local cn = UE.objname(UE.class(o))
      if cn == 'Class' or cn == 'BlueprintGeneratedClass' then return o end
    end
  end
end

-- 反射：UStruct.Super@0x40 Children@0x48 ChildProperties@0x50；FField.Next@0x20 Name@0x28；FProperty.Offset@0x4C
function UE.off(cls, prop)
  local s = cls
  while s and s ~= 0 do
    local f = readPointer(s + 0x50)
    while f and f ~= 0 do
      if UE.fname(f + 0x28) == prop then return readInteger(f + 0x4C) end
      f = readPointer(f + 0x20)
    end
    s = readPointer(s + 0x40)
  end
end

-- 常用对象
function UE.world() return readPointer(UE.GWorld) end
function UE.pc()
  local gi = readPointer(UE.world() + 0x180)            -- World::OwningGameInstance
  local lp = readPointer(readPointer(gi + 0x38))        -- GameInstance::LocalPlayers[0]
  return readPointer(lp + 0x30)                          -- Player::PlayerController
end
function UE.pawn() return readPointer(UE.pc() + 0x250) end  -- Controller::Pawn
function UE.loc(actor)
  local rc = readPointer(actor + 0x130)                  -- Actor::RootComponent
  return readFloat(rc + 0x11C), readFloat(rc + 0x120), readFloat(rc + 0x124)  -- RelativeLocation
end

-- 当前关卡的所有 Actor（ULevel::Actors 在 0x98，非反射字段）
function UE.actors()
  local lvl = readPointer(UE.world() + 0x30)            -- World::PersistentLevel
  local arr, n = readPointer(lvl + 0x98), readInteger(lvl + 0xA0)
  local r = {}
  for i = 0, n - 1 do
    local a = readPointer(arr + i * 8)
    if a and a ~= 0 then r[#r + 1] = a end
  end
  return r
end

print(string.format('[ETB] GNames=%X GObj=%X GWorld=%X objects=%d', UE.GNames, UE.GObj, UE.GWorld, UE.count()))
