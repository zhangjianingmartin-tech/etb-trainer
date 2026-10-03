// etb_render：覆盖层的独立窗口渲染器（DLL 注入不可用时的备用方案）。
//
// 从共享内存读取 Python 端写好的绘制命令，用 Direct2D / DirectWrite 画到一个
// DirectComposition 透明窗口上（预乘 alpha 的合成交换链），窗口置顶且鼠标可穿透。
// 用法：etb_render.exe <共享内存名> <父进程 PID>；父进程退出或共享内存里 quit=1 时自动退出。
// 低延迟：交换链最多排 1 帧（帧延迟等待对象），Python 每写完一帧就触发命名事件 <共享内存名>_evt 唤醒这边。
// 共享内存布局和命令格式见 overlay_draw.h。

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define _WIN32_WINNT 0x0A00   // Win10：NOREDIRECTIONBITMAP、每显示器 DPI 感知 V2
#define WINVER 0x0A00
#include <windows.h>
#include <shellapi.h>
#include <mmsystem.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <dcomp.h>
#include <vector>

#include "overlay_draw.h"

struct Renderer {
    HWND hwnd = nullptr;
    int w = 0, h = 0;
    ID3D11Device *d3d = nullptr;
    IDXGIDevice *dxgi = nullptr;
    IDXGISwapChain1 *swap = nullptr;
    HANDLE frameWait = nullptr;   // 交换链可以接收下一帧时触发
    ID2D1Factory1 *d2dFactory = nullptr;
    ID2D1Device *d2dDevice = nullptr;
    ID2D1DeviceContext *dc = nullptr;
    ID2D1Bitmap1 *target = nullptr;
    IDCompositionDevice *dcomp = nullptr;
    IDCompositionTarget *dcompTarget = nullptr;
    IDCompositionVisual *visual = nullptr;
    Painter painter;

    bool init(HINSTANCE inst) {
        WNDCLASSW wc = {};
        wc.lpfnWndProc = DefWindowProcW;
        wc.hInstance = inst;
        wc.lpszClassName = L"ETBOverlayRenderer";
        RegisterClassW(&wc);
        // NOREDIRECTIONBITMAP：内容完全由 DirectComposition 提供；LAYERED+TRANSPARENT：鼠标点击穿透
        hwnd = CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOPMOST | WS_EX_TOOLWINDOW |
                                   WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT,
                               wc.lpszClassName, L"ETB Overlay", WS_POPUP, 0, 0, 16, 16,
                               nullptr, nullptr, inst, nullptr);
        if (!hwnd) return false;
        SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA);

        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags, nullptr, 0,
                                     D3D11_SDK_VERSION, &d3d, nullptr, nullptr)))
            return false;
        d3d->QueryInterface(__uuidof(IDXGIDevice), (void **)&dxgi);

        D2D1_FACTORY_OPTIONS fo = {};
        if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory1), &fo,
                                     (void **)&d2dFactory)))
            return false;
        if (FAILED(d2dFactory->CreateDevice(dxgi, &d2dDevice))) return false;
        if (FAILED(d2dDevice->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &dc))) return false;
        if (!painter.setup(d2dFactory, dc)) return false;

        if (FAILED(DCompositionCreateDevice(dxgi, __uuidof(IDCompositionDevice), (void **)&dcomp)))
            return false;
        if (FAILED(dcomp->CreateTargetForHwnd(hwnd, TRUE, &dcompTarget))) return false;
        if (FAILED(dcomp->CreateVisual(&visual))) return false;
        return true;
    }

    bool resize(int x, int y, int nw, int nh) {
        if (nw <= 0 || nh <= 0) return false;
        SetWindowPos(hwnd, HWND_TOPMOST, x, y, nw, nh, SWP_NOACTIVATE | SWP_SHOWWINDOW);
        if (nw == w && nh == h && swap) return true;
        w = nw;
        h = nh;
        dc->SetTarget(nullptr);
        etb_release(target);
        if (!swap) {
            IDXGIAdapter *adapter = nullptr;
            IDXGIFactory2 *factory = nullptr;
            dxgi->GetAdapter(&adapter);
            adapter->GetParent(__uuidof(IDXGIFactory2), (void **)&factory);
            DXGI_SWAP_CHAIN_DESC1 sd = {};
            sd.Width = w;
            sd.Height = h;
            sd.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
            sd.SampleDesc.Count = 1;
            sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
            sd.BufferCount = 2;
            sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
            sd.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED;
            sd.Flags = DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
            HRESULT hr = factory->CreateSwapChainForComposition(d3d, &sd, nullptr, &swap);
            etb_release(factory);
            etb_release(adapter);
            if (FAILED(hr)) return false;
            IDXGISwapChain2 *swap2 = nullptr;
            if (SUCCEEDED(swap->QueryInterface(__uuidof(IDXGISwapChain2), (void **)&swap2))) {
                swap2->SetMaximumFrameLatency(1);      // 默认会排 3 帧
                frameWait = swap2->GetFrameLatencyWaitableObject();
                swap2->Release();
            }
            visual->SetContent(swap);
            dcompTarget->SetRoot(visual);
            dcomp->Commit();
        } else if (FAILED(swap->ResizeBuffers(2, w, h, DXGI_FORMAT_B8G8R8A8_UNORM,
                                              DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT))) {
            return false;
        }
        IDXGISurface *surface = nullptr;
        swap->GetBuffer(0, __uuidof(IDXGISurface), (void **)&surface);
        D2D1_BITMAP_PROPERTIES1 bp = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
        HRESULT hr = dc->CreateBitmapFromDxgiSurface(surface, &bp, &target);
        etb_release(surface);
        if (FAILED(hr)) return false;
        dc->SetTarget(target);
        return true;
    }

    void frame(const uint8_t *cmds, uint32_t n) {
        if (!target) return;
        dc->BeginDraw();
        dc->Clear(D2D1::ColorF(0, 0, 0, 0));
        if (n) painter.draw(cmds, n);
        dc->EndDraw();
        painter.endFrame();
        swap->Present(1, 0);   // 跟随显示器刷新
    }
};

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int) {
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argc < 3) return 1;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    timeBeginPeriod(1);

    HANDLE parent = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)_wtoi(argv[2]));
    HANDLE map = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, argv[1]);
    if (!map) return 2;
    auto *base = (uint8_t *)MapViewOfFile(map, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, 0);
    if (!base) return 3;
    auto *hdr = (EtbHeader *)base;
    if (hdr->magic != ETB_MAGIC || hdr->version != ETB_VERSION) return 4;

    Renderer r;
    if (!r.init(inst)) return 5;

    std::wstring evtName = std::wstring(argv[1]) + L"_evt";
    HANDLE evt = OpenEventW(SYNCHRONIZE, FALSE, evtName.c_str());   // 旧版 Python 端没有这个事件，退回 1ms 轮询

    std::vector<uint8_t> local(ETB_BUF_SIZE);
    bool needWait = false;
    LONG lastSeq = -1;
    bool shown = false;
    int rx = 0, ry = 0, rw = 0, rh = 0;
    for (;;) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        if (hdr->quit) break;
        if (parent && WaitForSingleObject(parent, 0) == WAIT_OBJECT_0) break;

        // 先等交换链空出位置，再取最新的一帧数据来画，这样画上去的总是最新的
        if (needWait && r.frameWait) {
            WaitForSingleObjectEx(r.frameWait, 100, TRUE);
            needWait = false;
        }
        LONG seq = hdr->seq;
        if (seq == lastSeq) {
            if (evt) WaitForSingleObject(evt, 20);
            else Sleep(1);
            continue;
        }
        lastSeq = seq;
        if (hdr->x != rx || hdr->y != ry || hdr->w != rw || hdr->h != rh) {
            rx = hdr->x; ry = hdr->y; rw = hdr->w; rh = hdr->h;
            if (!r.resize(rx, ry, rw, rh)) continue;
        }
        if (!hdr->visible) {
            if (shown) { r.frame(nullptr, 0); needWait = true; shown = false; }
            continue;
        }
        uint32_t act = hdr->active & 1;
        uint32_t used = hdr->used[act];
        if (used > ETB_BUF_SIZE) used = 0;
        memcpy(local.data(), base + sizeof(EtbHeader) + act * ETB_BUF_SIZE, used);
        r.frame(local.data(), used);
        needWait = true;
        shown = true;
    }
    return 0;
}
