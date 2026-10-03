// etb_render：覆盖层的 GPU 渲染器。
//
// 从共享内存读取 Python 端写好的绘制命令，用 Direct2D / DirectWrite 画到一个
// DirectComposition 透明窗口上（预乘 alpha 的合成交换链），窗口置顶且鼠标可穿透。
// 用法：etb_render.exe <共享内存名> <父进程 PID>；父进程退出或共享内存里 quit=1 时自动退出。
//
// 共享内存布局（小端）：
//   Header（64 字节）+ 2 个命令缓冲区（双缓冲，各 BUF_SIZE 字节）
//   Python 写完一个缓冲区后设置 active、再把 seq 加 1；这边发现 seq 变了就复制 active 缓冲区来画。
// 命令（每条以 1 字节类型开头）：
//   1 文字   f32 x, f32 y, u32 argb, f32 字号(px), u8 粗体, u8 锚点(0~8), u16 字符数, wchar[字符数]
//   2 椭圆   f32 cx, f32 cy, f32 rx, f32 ry, u32 填充argb(0=不填), u32 描边argb(0=不描), f32 线宽
//   3 线段   f32 x1, f32 y1, f32 x2, f32 y2, u32 argb, f32 线宽
//   4 多边形 u16 点数, u32 填充argb, u32 描边argb, f32 线宽, 点数×(f32 x, f32 y)

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define _WIN32_WINNT 0x0A00   // Win10：NOREDIRECTIONBITMAP、每显示器 DPI 感知 V2
#define WINVER 0x0A00
#include <windows.h>
#include <shellapi.h>
#include <mmsystem.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <d2d1_1.h>
#include <dwrite.h>
#include <dcomp.h>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

static const uint32_t MAGIC = 0x4F425445;   // "ETBO"
static const uint32_t VERSION = 1;
static const uint32_t BUF_SIZE = 1 << 20;

#pragma pack(push, 1)
struct Header {
    uint32_t magic;
    uint32_t version;
    volatile LONG seq;
    uint32_t active;
    int32_t x, y, w, h;
    uint32_t visible;
    uint32_t quit;
    uint32_t used[2];
    uint32_t reserved[4];
};
#pragma pack(pop)
static_assert(sizeof(Header) == 64, "header must be 64 bytes");

template <class T> static void release(T *&p) {
    if (p) { p->Release(); p = nullptr; }
}

struct Renderer {
    HWND hwnd = nullptr;
    int w = 0, h = 0;
    ID3D11Device *d3d = nullptr;
    IDXGIDevice *dxgi = nullptr;
    IDXGISwapChain1 *swap = nullptr;
    ID2D1Factory1 *d2dFactory = nullptr;
    ID2D1Device *d2dDevice = nullptr;
    ID2D1DeviceContext *dc = nullptr;
    ID2D1Bitmap1 *target = nullptr;
    ID2D1SolidColorBrush *brush = nullptr;
    IDWriteFactory *dw = nullptr;
    IDCompositionDevice *dcomp = nullptr;
    IDCompositionTarget *dcompTarget = nullptr;
    IDCompositionVisual *visual = nullptr;
    std::map<std::pair<int, bool>, IDWriteTextFormat *> formats;

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
        dc->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);   // 透明背景上只能用灰度抗锯齿
        dc->CreateSolidColorBrush(D2D1::ColorF(1, 1, 1, 1), &brush);
        if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                                       (IUnknown **)&dw)))
            return false;

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
        release(target);
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
            HRESULT hr = factory->CreateSwapChainForComposition(d3d, &sd, nullptr, &swap);
            release(factory);
            release(adapter);
            if (FAILED(hr)) return false;
            visual->SetContent(swap);
            dcompTarget->SetRoot(visual);
            dcomp->Commit();
        } else if (FAILED(swap->ResizeBuffers(2, w, h, DXGI_FORMAT_B8G8R8A8_UNORM, 0))) {
            return false;
        }
        IDXGISurface *surface = nullptr;
        swap->GetBuffer(0, __uuidof(IDXGISurface), (void **)&surface);
        D2D1_BITMAP_PROPERTIES1 bp = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
        HRESULT hr = dc->CreateBitmapFromDxgiSurface(surface, &bp, &target);
        release(surface);
        if (FAILED(hr)) return false;
        dc->SetTarget(target);
        return true;
    }

    IDWriteTextFormat *format(int px, bool bold) {
        auto key = std::make_pair(px, bold);
        auto it = formats.find(key);
        if (it != formats.end()) return it->second;
        IDWriteTextFormat *f = nullptr;
        dw->CreateTextFormat(L"Microsoft YaHei UI", nullptr,
                             bold ? DWRITE_FONT_WEIGHT_BOLD : DWRITE_FONT_WEIGHT_NORMAL,
                             DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, (float)px, L"zh-cn", &f);
        if (f) f->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
        formats[key] = f;
        return f;
    }

    void color(uint32_t argb) {
        brush->SetColor(D2D1::ColorF(((argb >> 16) & 0xFF) / 255.f, ((argb >> 8) & 0xFF) / 255.f,
                                     (argb & 0xFF) / 255.f, ((argb >> 24) & 0xFF) / 255.f));
    }

    void text(float x, float y, uint32_t argb, float size, bool bold, int anchor, const wchar_t *s, int n) {
        IDWriteTextFormat *f = format((int)(size + 0.5f), bold);
        if (!f) return;
        IDWriteTextLayout *layout = nullptr;
        if (FAILED(dw->CreateTextLayout(s, n, f, 4096.f, 512.f, &layout))) return;
        DWRITE_TEXT_METRICS m;
        layout->GetMetrics(&m);
        // 锚点：0 nw 1 n 2 ne 3 w 4 center 5 e 6 sw 7 s 8 se（和 tkinter 一致）
        float ax = (anchor % 3 == 0) ? 0.f : (anchor % 3 == 1 ? m.width / 2 : m.width);
        float ay = (anchor / 3 == 0) ? 0.f : (anchor / 3 == 1 ? m.height / 2 : m.height);
        color(argb);
        dc->DrawTextLayout(D2D1::Point2F(x - ax - m.left, y - ay), layout, brush);
        layout->Release();
    }

    void draw(const uint8_t *p, uint32_t n) {
        const uint8_t *end = p + n;
        auto f32 = [&](const uint8_t *&q) { float v; memcpy(&v, q, 4); q += 4; return v; };
        auto u32 = [&](const uint8_t *&q) { uint32_t v; memcpy(&v, q, 4); q += 4; return v; };
        auto u16 = [&](const uint8_t *&q) { uint16_t v; memcpy(&v, q, 2); q += 2; return v; };
        while (p < end) {
            uint8_t type = *p++;
            if (type == 1) {
                float x = f32(p), y = f32(p);
                uint32_t c = u32(p);
                float size = f32(p);
                bool bold = *p++;
                int anchor = *p++;
                uint16_t len = u16(p);
                if (p + len * 2 > end) return;
                std::wstring s((const wchar_t *)p, len);
                p += len * 2;
                text(x, y, c, size, bold, anchor, s.c_str(), len);
            } else if (type == 2) {
                float cx = f32(p), cy = f32(p), rx = f32(p), ry = f32(p);
                uint32_t fill = u32(p), outline = u32(p);
                float width = f32(p);
                D2D1_ELLIPSE e = D2D1::Ellipse(D2D1::Point2F(cx, cy), rx, ry);
                if (fill) { color(fill); dc->FillEllipse(e, brush); }
                if (outline) { color(outline); dc->DrawEllipse(e, brush, width); }
            } else if (type == 3) {
                float x1 = f32(p), y1 = f32(p), x2 = f32(p), y2 = f32(p);
                uint32_t c = u32(p);
                float width = f32(p);
                color(c);
                dc->DrawLine(D2D1::Point2F(x1, y1), D2D1::Point2F(x2, y2), brush, width);
            } else if (type == 4) {
                uint16_t count = u16(p);
                uint32_t fill = u32(p), outline = u32(p);
                float width = f32(p);
                if (p + count * 8 > end || count < 2) return;
                ID2D1PathGeometry *geo = nullptr;
                ID2D1GeometrySink *sink = nullptr;
                d2dFactory->CreatePathGeometry(&geo);
                geo->Open(&sink);
                const uint8_t *q = p;
                float x0 = f32(q), y0 = f32(q);
                sink->BeginFigure(D2D1::Point2F(x0, y0), D2D1_FIGURE_BEGIN_FILLED);
                for (int i = 1; i < count; i++) {
                    float x = f32(q), y = f32(q);
                    sink->AddLine(D2D1::Point2F(x, y));
                }
                sink->EndFigure(D2D1_FIGURE_END_CLOSED);
                sink->Close();
                if (fill) { color(fill); dc->FillGeometry(geo, brush); }
                if (outline) { color(outline); dc->DrawGeometry(geo, brush, width); }
                sink->Release();
                geo->Release();
                p += count * 8;
            } else {
                return;   // 未知命令：丢弃这一帧剩下的部分
            }
        }
    }

    void frame(const uint8_t *cmds, uint32_t n) {
        if (!target) return;
        dc->BeginDraw();
        dc->Clear(D2D1::ColorF(0, 0, 0, 0));
        if (n) draw(cmds, n);
        dc->EndDraw();
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
    auto *hdr = (Header *)base;
    if (hdr->magic != MAGIC || hdr->version != VERSION) return 4;

    Renderer r;
    if (!r.init(inst)) return 5;

    std::vector<uint8_t> local(BUF_SIZE);
    LONG lastSeq = -1;
    bool shown = false;
    int rx = 0, ry = 0, rw = 0, rh = 0;
    for (;;) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        if (hdr->quit) break;
        if (parent && WaitForSingleObject(parent, 0) == WAIT_OBJECT_0) break;

        LONG seq = hdr->seq;
        if (seq == lastSeq) {
            Sleep(1);
            continue;
        }
        lastSeq = seq;
        if (hdr->x != rx || hdr->y != ry || hdr->w != rw || hdr->h != rh) {
            rx = hdr->x; ry = hdr->y; rw = hdr->w; rh = hdr->h;
            if (!r.resize(rx, ry, rw, rh)) continue;
        }
        if (!hdr->visible) {
            if (shown) { r.frame(nullptr, 0); shown = false; }
            continue;
        }
        uint32_t act = hdr->active & 1;
        uint32_t used = hdr->used[act];
        if (used > BUF_SIZE) used = 0;
        memcpy(local.data(), base + sizeof(Header) + act * BUF_SIZE, used);
        r.frame(local.data(), used);
        shown = true;
    }
    return 0;
}
