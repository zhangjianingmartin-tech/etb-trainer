@echo off
rem 编译覆盖层的两个绘制组件：需要 MinGW-w64 的 g++（例如 winget install BrechtSanders.WinLibs.POSIX.UCRT）
rem   etb_hook.dll   注入游戏、在游戏画面里画（默认）
rem   etb_render.exe 独立透明窗口（注入不可用时的备用方案）
cd /d "%~dp0"
g++ -O2 -std=c++17 -shared etb_hook.cpp -o etb_hook.dll -ld3d11 -ldxgi -ld2d1 -ldwrite -luuid -static -s
if errorlevel 1 goto fail
g++ -O2 -std=c++17 -municode -mwindows etb_render.cpp -o etb_render.exe -ld3d11 -ldxgi -ld2d1 -ldwrite -ldcomp -luser32 -lshell32 -lwinmm -static -s
if errorlevel 1 goto fail
echo 已生成 etb_hook.dll 和 etb_render.exe
goto :eof
:fail
echo 编译失败
pause
