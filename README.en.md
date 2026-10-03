# Escape the Backrooms Trainer

[简体中文](README.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Русский](README.ru.md) | [Português](README.pt-BR.md)

An information overlay and fun-features tool for *Escape the Backrooms* (Steam 1943950, UE 4.27). Written in pure Python (standard library only). It reads and writes the game's memory from outside, and installs a small hook on `UObject::ProcessEvent` so it can call the game's own UFunctions on the game thread.

> For single-player or your own lobby (with friends who know about it), for fun and for learning UE reverse engineering only.
> This project is not affiliated with Fancy Games or Steam. Use at your own risk; offsets and signatures may break after game updates.
>
> Note: the on-screen panel and messages are currently in Simplified Chinese only.

## Features

**Overlay** (read-only, does not modify the game)
- Marks monsters, items, exits, fall zones and teammates on screen with their distance; off-screen targets get an arrow at the screen edge
- Top-left panel: level, coordinates, stamina, distance to the nearest monster (turns red within 15 m), exits and item list
- Hides automatically when the game is not in the foreground; exits automatically when the game closes

**Hotkeys** (your role is detected automatically: single-player / host / client)

| Key | Host / single-player | Client |
|---|---|---|
| F5 | Possess the nearest monster (WASD to move, mouse to turn, Space to jump, Shift to run); press again to return to your body | Switch to the nearest monster's view (view only) |
| F6 | Freeze / unfreeze all monsters | Not available |
| F7 | Fly + noclip (Space up, Ctrl down) | Not available |
| F2 | Speed boost + infinite stamina | Speed boost (via server RPC) |
| F3 | Third-person view | Same |
| F4 / Shift+F4 | Change skin: built-in costumes (visible to others) or models of monsters/characters in the level (only visible to you) | Same |
| Insert | Teleport to the nearest exit | Not available |
| Delete | Revive yourself at the spot where you died | Sends a respawn request to the host (usually ignored) |
| F11 | God mode: monsters, falls and drowning can't kill you (only you, not teammates) | Not available |
| PgUp / PgDn + Home | Pick an item and spawn it in your hands | Same |
| F8 / F9 / F10 | Hide overlay / toggle item markers / toggle interactable markers | Same |
| End | Revert all changes, remove the hook and exit | Same |

## Usage

1. Set the game to **windowed** or **borderless windowed** (exclusive fullscreen covers the overlay) and enter a level.
2. Either:
   - download `ETB-Trainer.exe` from Releases and double-click it (no Python needed), or
   - install Python 3.10+, download the source and double-click `启动覆盖层.bat` ("start overlay"), or run `python etb_overlay.py`.
3. Press **End** to quit. It first reverts possession, freezing, flying, skins, etc., then removes the hook.

The single-file exe is packed with PyInstaller and may be flagged by antivirus software as a false positive. If that bothers you, run from source.

## Files

| File | Description |
|---|---|
| `etb_overlay.py` | Entry point: overlay window, memory reading, actor classification, world-to-screen projection |
| `etb_trainer.py` | Hotkey features, running in a background thread of the overlay process |
| `etb_call.py` | ProcessEvent hook + UFunction caller that packs parameters via reflection (supports batching) |
| `etb_ue.lua` | Cheat Engine script: locates GNames / GObjects / GWorld by AOB, plus helpers for names, reflection and actor iteration |
| `NOTES.md` | Reverse-engineering notes (Chinese): globals, pointer chains, offsets, how the hook works |
| `FUNCTIONS.md` | Callable function list (Chinese descriptions; curated list + full signatures of 1729 functions in 212 game classes) |

## How it works

- At startup it scans the main module's executable sections with AOB signatures to find `GNames` (FNamePool), `GUObjectArray` and `GWorld`. Everything else is read using the UE 4.27 layout and runtime reflection.
- The first 19 bytes of `ProcessEvent` are replaced with a `jmp` to a code cave. The cave checks that the current thread is the game thread, claims the call flag with `lock cmpxchg`, runs the batch of calls written from outside, then executes the original prologue and jumps back. So every game function call happens on the game's own main thread.
- Role detection: if the local character's `Actor::Role` is Authority, `World::NetDriver` tells single-player from host; AutonomousProxy means client.

See [NOTES.md](NOTES.md) (Chinese) for details.

## Compatibility

Written and tested on Steam build 24997718. If after a game update it says "AOB 没找到" (AOB not found) or "ProcessEvent 开头字节和预期不同" (unexpected ProcessEvent prologue), the addresses need to be located again.

## License

[MIT](LICENSE)
