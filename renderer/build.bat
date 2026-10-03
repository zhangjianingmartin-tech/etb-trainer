@echo off
rem 编译 GPU 渲染器：需要 MinGW-w64 的 g++（例如 winget install BrechtSanders.WinLibs.POSIX.UCRT）
cd /d "%~dp0"
g++ -O2 -std=c++17 -municode -mwindows etb_render.cpp -o etb_render.exe -ld3d11 -ldxgi -ld2d1 -ldwrite -ldcomp -luser32 -lshell32 -lwinmm -static -s
if errorlevel 1 (echo 编译失败 & pause) else echo 已生成 etb_render.exe
