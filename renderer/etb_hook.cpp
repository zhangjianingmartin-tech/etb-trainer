// etb_hook.dll：注入游戏进程，在游戏自己的 IDXGISwapChain::Present 里用 Direct2D 把覆盖层画进画面。
//
// 和独立窗口相比：标记和游戏画面是同一帧，没有窗口合成的延迟；世界坐标标记的投影在 DLL 里做，
// 相机和 Actor 位置都在 Present 那一刻直接从内存读，Python 端只负责“画什么”。
//
// 共享内存名 Local\ETB_Inject_<游戏 PID>，由 Python 端创建，布局和 1~4 号命令见 overlay_draw.h。
// 额外命令：
//   6 相机   u64 POV 地址（FMinimalViewInfo：位置 3f、旋转 3f、FOV）, u64 玩家位置地址（3f，0=用相机位置）,
//            f32 雷达中心 x, f32 雷达中心 y, f32 雷达半径(0=没有雷达), f32 雷达量程(米)
//   5 标记   u64 位置地址（3f，0=用下面的备用坐标）, f32 备用 x, y, z, u32 argb, f32 字号(px),
//            f32 屏幕外提示字号(px), u8 粗体, u8 标志, u16 字符数, wchar[字符数]
//            标志：1 屏幕外画方向箭头，2 画到雷达上，4 超出雷达量程时钉在边缘，8 雷达上画大点
// 读游戏内存一律用 ReadProcessMemory(自己)，Actor 被销毁时只会读失败，不会让游戏崩溃。
// D3D11 直接在游戏设备上画；D3D12 先截下游戏的直接命令队列，再用 D3D11On12 包装后台缓冲。
// D3D12 下 Direct2D 先画到一张自己的 BGRA 透明贴图上，再用一个全屏三角形按预乘 alpha 混合到后台缓冲，
// 所以后台缓冲是 R10G10B10A2 这类 Direct2D 不能直接画的格式也没关系。
// 初始化失败（其他图形接口、后台缓冲格式 Direct2D 画不了）时写 loaded=2，Python 改用独立窗口。
// Python 写 quit=1 时恢复虚表、释放资源并卸载自己。

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define _WIN32_WINNT 0x0A00
#define WINVER 0x0A00
#include <windows.h>
#include <d3d11_1.h>
#include <d3d11on12.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <vector>

#include "overlay_draw.h"

static HMODULE g_self = nullptr;

static void logf(const char *fmt, ...) {
    wchar_t dir[MAX_PATH];
    GetTempPathW(MAX_PATH, dir);
    std::wstring path = std::wstring(dir) + L"etb_hook.log";
    FILE *f = _wfopen(path.c_str(), L"a");
    if (!f) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(f, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

// 读本进程内存，地址无效时返回 false 而不是崩溃
static bool rd(uint64_t addr, void *out, size_t n) {
    if (addr < 0x10000) return false;
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), (LPCVOID)addr, out, n, &got) && got == n;
}

// ---------------------------------------------------------------- 世界坐标标记

struct WorldPainter : Painter {
    float W = 0, H = 0;               // 绘制坐标系 = 游戏客户区尺寸（Python 端给的）
    uint32_t delay = 0;
    bool haveCam = false;
    float cam[7] = {};                // 位置 3、旋转（pitch, yaw, roll）3、FOV
    float origin[3] = {};
    float rcx = 0, rcy = 0, rR = 0, rRange = 40;
    std::vector<std::pair<float, float>> placed;

    static const int RING = 16;       // 最近几帧的相机，对齐补偿时取较早的那一份
    float ring[RING][7] = {};
    int ringCount = 0, ringPos = 0;
    uint64_t ringSrc = 0;

    void beginFrame(float w, float h, uint32_t d) {
        W = w;
        H = h;
        delay = d < RING - 1 ? d : RING - 1;
        haveCam = false;
        placed.clear();
    }

    bool w2s(const float *t, float &sx, float &sy) {
        const float D = 3.14159265f / 180.f;
        float sp = sinf(cam[3] * D), cp = cosf(cam[3] * D);
        float sy_ = sinf(cam[4] * D), cy_ = cosf(cam[4] * D);
        float sr = sinf(cam[5] * D), cr = cosf(cam[5] * D);
        float ax[3] = {cp * cy_, cp * sy_, sp};
        float ay[3] = {sr * sp * cy_ - cr * sy_, sr * sp * sy_ + cr * cy_, -sr * cp};
        float az[3] = {-(cr * sp * cy_ + sr * sy_), cy_ * sr - cr * sp * sy_, cr * cp};
        float d[3] = {t[0] - cam[0], t[1] - cam[1], t[2] - cam[2]};
        float tx = d[0] * ay[0] + d[1] * ay[1] + d[2] * ay[2];
        float ty = d[0] * az[0] + d[1] * az[1] + d[2] * az[2];
        float tz = d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2];
        float hw = W / 2, hh = H / 2;
        float f = hw / tanf(cam[6] * D / 2);
        if (tz < 1.0f) {                // 在身后：只保留方向，供屏幕边缘箭头使用
            sx = hw + tx * 1e4f;
            sy = hh - ty * 1e4f;
            return false;
        }
        sx = hw + tx * f / tz;
        sy = hh - ty * f / tz;
        return true;
    }

    const uint8_t *camera(const uint8_t *p, const uint8_t *end) {
        if (p + 32 > end) return nullptr;
        uint64_t povAddr = ru64(p), originAddr = ru64(p);
        rcx = rf32(p); rcy = rf32(p); rR = rf32(p); rRange = rf32(p);
        float v[7];
        if (rd(povAddr, v, sizeof(v)) && v[6] > 1.f && v[6] < 179.f) {
            if (povAddr != ringSrc) { ringCount = 0; ringSrc = povAddr; }   // 换关后旧相机作废
            ringPos = (ringPos + 1) % RING;
            memcpy(ring[ringPos], v, sizeof(v));
            if (ringCount < RING) ringCount++;
            int back = (int)delay < ringCount ? (int)delay : ringCount - 1;
            memcpy(cam, ring[(ringPos - back + RING) % RING], sizeof(cam));
            haveCam = true;
        }
        if (!(originAddr && rd(originAddr, origin, sizeof(origin))))
            memcpy(origin, cam, sizeof(origin));
        return p;
    }

    const uint8_t *marker(const uint8_t *p, const uint8_t *end) {
        if (p + 36 > end) return nullptr;
        uint64_t locAddr = ru64(p);
        float loc[3];
        loc[0] = rf32(p); loc[1] = rf32(p); loc[2] = rf32(p);
        uint32_t c = ru32(p);
        float px = rf32(p), arrowPx = rf32(p);
        bool bold = *p++;
        uint8_t flags = *p++;
        uint16_t len = ru16(p);
        if (p + len * 2 > end) return nullptr;
        std::wstring s((const wchar_t *)p, len);
        p += len * 2;
        if (!haveCam) return p;
        if (locAddr) {
            float live[3];
            if (rd(locAddr, live, sizeof(live))) memcpy(loc, live, sizeof(loc));
        }
        if (loc[0] == 0 && loc[1] == 0 && loc[2] == 0) return p;

        float dx = loc[0] - origin[0], dy = loc[1] - origin[1], dz = loc[2] - origin[2];
        float dist = sqrtf(dx * dx + dy * dy + dz * dz) / 100.f;
        s += L" " + std::to_wstring((int)lroundf(dist)) + L"m";

        float sx, sy;
        bool vis = w2s(loc, sx, sy);
        if (vis && sx >= 0 && sx <= W && sy >= 0 && sy <= H) {
            ellipse(sx, sy, 3, 3, c, 0xFF000000, 1);
            float ly = sy - 6;
            for (bool moved = true; moved;) {     // 和已画的标签重叠就往上错开
                moved = false;
                for (auto &q : placed)
                    if (fabsf(q.first - sx) < 70 && fabsf(q.second - ly) < 15) { ly -= 15; moved = true; break; }
            }
            placed.emplace_back(sx, ly);
            if (ly < sy - 6) line(sx, sy - 3, sx, ly, c, 1);
            shadowText(sx, ly, c, px, bold, 7, s.c_str(), (int)s.size());
        } else if (flags & 1) {
            float cx = W / 2, cy = H / 2;
            float ang = atan2f(sy - cy, sx - cx);
            float ca = cosf(ang), sa = sinf(ang);
            float ex = cx + ca * (W / 2 - 40), ey = cy + sa * (H / 2 - 40);
            float tri[6] = {ex + ca * 12, ey + sa * 12,
                            ex - ca * 8 - sa * 8, ey - sa * 8 + ca * 8,
                            ex - ca * 8 + sa * 8, ey - sa * 8 - ca * 8};
            polygon(tri, 3, c, 0xFF000000, 1);
            shadowText(ex, ey + 14, c, arrowPx, bold, 1, s.c_str(), (int)s.size());
        }

        if ((flags & 2) && rR > 0) {
            float a = cam[4] * 3.14159265f / 180.f, ca = cosf(a), sa = sinf(a);
            float fwd = (dx * ca + dy * sa) / 100.f;        // 前方为正
            float right = (-dx * sa + dy * ca) / 100.f;     // 右方为正
            float d = hypotf(fwd, right);
            if (d > rRange) {
                if (!(flags & 4)) return p;
                fwd = fwd / d * rRange;
                right = right / d * rRange;
            }
            float rad = (flags & 8) ? 5.f : 3.f;
            ellipse(rcx + right / rRange * rR, rcy - fwd / rRange * rR, rad, rad, c, 0xFF000000, 1);
        }
        return p;
    }

    const uint8_t *ext(uint8_t type, const uint8_t *p, const uint8_t *end) override {
        if (type == 6) return camera(p, end);
        if (type == 5) return marker(p, end);
        return nullptr;
    }
};

// ---------------------------------------------------------------- 钩子状态

typedef HRESULT(STDMETHODCALLTYPE *PresentFn)(IDXGISwapChain *, UINT, UINT);
typedef HRESULT(STDMETHODCALLTYPE *Present1Fn)(IDXGISwapChain1 *, UINT, UINT, const DXGI_PRESENT_PARAMETERS *);
typedef HRESULT(STDMETHODCALLTYPE *ResizeBuffersFn)(IDXGISwapChain *, UINT, UINT, UINT, DXGI_FORMAT, UINT);
typedef HRESULT(STDMETHODCALLTYPE *ResizeBuffers1Fn)(IDXGISwapChain3 *, UINT, UINT, UINT, DXGI_FORMAT, UINT,
                                                    const UINT *, IUnknown *const *);
typedef void(STDMETHODCALLTYPE *ExecuteFn)(ID3D12CommandQueue *, UINT, ID3D12CommandList *const *);

static void **g_vtbl = nullptr;        // DXGI 交换链虚表（dxgi.dll 里所有交换链共用）
static void **g_qvtbl = nullptr;       // D3D12 命令队列虚表
static PresentFn oPresent = nullptr;
static Present1Fn oPresent1 = nullptr;
static ResizeBuffersFn oResize = nullptr;
static ResizeBuffers1Fn oResize1 = nullptr;
static ExecuteFn oExecute = nullptr;
static bool g_hasPresent1 = false, g_hasResize1 = false;
static volatile LONG g_unloading = 0;
static ID3D12CommandQueue *volatile g_queue = nullptr;   // 游戏的直接命令队列，D3D11On12 往这里提交

static struct State {
    HANDLE map = nullptr;
    uint8_t *base = nullptr;
    EtbHeader *hdr = nullptr;
    DWORD lastOpenTry = 0;

    int api = 0;                      // 11 = D3D11，12 = D3D12（经 D3D11On12）
    bool unsupported = false;
    bool ready = false;
    IDXGISwapChain *sc = nullptr;     // 只作比较用，不持有引用
    // D3D11：直接用游戏的设备，画之前切到独立的管线状态
    ID3D11Device *dev = nullptr;
    ID3D11DeviceContext1 *ctx1 = nullptr;
    ID3DDeviceContextState *state = nullptr;
    ID2D1Bitmap1 *target = nullptr;
    // D3D12：在游戏的 D3D12 设备上建一个 D3D11On12 设备，把每个后台缓冲包装成 D3D11 资源
    ID3D12Device *dev12 = nullptr;
    ID3D11Device *d11 = nullptr;
    ID3D11DeviceContext *ctx11 = nullptr;
    ID3D11On12Device *on12 = nullptr;
    std::vector<ID3D11Resource *> wrapped;
    std::vector<ID3D11RenderTargetView *> rtvs;
    ID3D11Texture2D *ovTex = nullptr;          // Direct2D 画在这上面
    ID3D11ShaderResourceView *ovSrv = nullptr;
    ID2D1Bitmap1 *ovBitmap = nullptr;
    ID3D11VertexShader *vs = nullptr;
    ID3D11PixelShader *ps = nullptr;
    ID3D11BlendState *blend = nullptr;
    // Direct2D
    ID2D1Factory1 *factory = nullptr;
    ID2D1Device *d2dDev = nullptr;
    ID2D1DeviceContext *dc = nullptr;
    UINT bbW = 0, bbH = 0;
    WorldPainter painter;
    std::vector<uint8_t> local;
} g;

static void releaseTarget() {
    if (g.dc) g.dc->SetTarget(nullptr);
    etb_release(g.target);
    etb_release(g.ovBitmap);
    etb_release(g.ovSrv);
    etb_release(g.ovTex);
    for (auto *r : g.rtvs) r->Release();
    for (auto *w : g.wrapped) w->Release();
    g.rtvs.clear();
    g.wrapped.clear();
    if (g.ctx11) g.ctx11->Flush();     // 让 D3D11On12 真正放掉后台缓冲的引用
}

static void releaseDevice() {
    releaseTarget();
    g.painter.releaseAll();
    etb_release(g.dc);
    etb_release(g.d2dDev);
    etb_release(g.factory);
    etb_release(g.state);
    etb_release(g.ctx1);
    etb_release(g.dev);
    etb_release(g.vs);
    etb_release(g.ps);
    etb_release(g.blend);
    etb_release(g.on12);
    etb_release(g.ctx11);
    etb_release(g.d11);
    etb_release(g.dev12);
    g.ready = false;
    g.api = 0;
    g.sc = nullptr;
}

static void setVtbl(void **tbl, int idx, void *fn) {
    DWORD old;
    VirtualProtect(&tbl[idx], sizeof(void *), PAGE_EXECUTE_READWRITE, &old);
    InterlockedExchangePointer(&tbl[idx], fn);
    VirtualProtect(&tbl[idx], sizeof(void *), old, &old);
}

static DWORD WINAPI unloadThread(LPVOID) {
    Sleep(1000);                       // 等正在执行的钩子函数都返回
    logf("unloaded");
    FreeLibraryAndExitThread(g_self, 0);
}

static void beginUnload() {
    if (InterlockedExchange(&g_unloading, 1)) return;
    setVtbl(g_vtbl, 8, (void *)oPresent);
    setVtbl(g_vtbl, 13, (void *)oResize);
    if (g_hasPresent1) setVtbl(g_vtbl, 22, (void *)oPresent1);
    if (g_hasResize1) setVtbl(g_vtbl, 39, (void *)oResize1);
    if (g_qvtbl) setVtbl(g_qvtbl, 10, (void *)oExecute);
    releaseDevice();
    ID3D12CommandQueue *q = (ID3D12CommandQueue *)InterlockedExchangePointer((void *volatile *)&g_queue, nullptr);
    if (q) q->Release();
    if (g.hdr) InterlockedExchange(&g.hdr->loaded, 0);
    if (g.base) UnmapViewOfFile(g.base);
    if (g.map) CloseHandle(g.map);
    g.base = nullptr;
    g.hdr = nullptr;
    g.map = nullptr;
    CloseHandle(CreateThread(nullptr, 0, unloadThread, nullptr, 0, nullptr));
}

static bool openShared() {
    if (g.hdr) return true;
    DWORD now = GetTickCount();
    if (now - g.lastOpenTry < 500) return false;
    g.lastOpenTry = now;
    wchar_t name[64];
    swprintf(name, 64, L"Local\\ETB_Inject_%lu", GetCurrentProcessId());
    g.map = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
    if (!g.map) return false;
    g.base = (uint8_t *)MapViewOfFile(g.map, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, 0);
    if (!g.base) { CloseHandle(g.map); g.map = nullptr; return false; }
    g.hdr = (EtbHeader *)g.base;
    if (g.hdr->magic != ETB_MAGIC || g.hdr->version != ETB_VERSION) {
        UnmapViewOfFile(g.base);
        CloseHandle(g.map);
        g.base = nullptr; g.hdr = nullptr; g.map = nullptr;
        return false;
    }
    g.local.resize(ETB_BUF_SIZE);
    logf("shared memory opened");
    return true;
}

static bool initD2D(ID3D11Device *d) {
    IDXGIDevice *dxgi = nullptr;
    d->QueryInterface(__uuidof(IDXGIDevice), (void **)&dxgi);
    D2D1_FACTORY_OPTIONS fo = {};
    HRESULT hr = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory1), &fo, (void **)&g.factory);
    if (SUCCEEDED(hr) && dxgi) hr = g.factory->CreateDevice(dxgi, &g.d2dDev);
    if (dxgi) dxgi->Release();
    if (FAILED(hr) || !g.d2dDev) {
        logf("Direct2D device creation failed (hr=%08lx, BGRA support=%d)", hr,
             (d->GetCreationFlags() & D3D11_CREATE_DEVICE_BGRA_SUPPORT) != 0);
        return false;
    }
    if (FAILED(g.d2dDev->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &g.dc))) { logf("CreateDeviceContext failed"); return false; }
    if (!g.painter.setup(g.factory, g.dc)) { logf("painter setup failed"); return false; }
    return true;
}

static bool init11(IDXGISwapChain *sc) {
    UINT cf = g.dev->GetCreationFlags();
    D3D_FEATURE_LEVEL fl = g.dev->GetFeatureLevel();
    logf("D3D11 device: flags=%x feature level=%x", cf, fl);
    ID3D11DeviceContext *ctx = nullptr;
    g.dev->GetImmediateContext(&ctx);
    HRESULT hr = ctx->QueryInterface(__uuidof(ID3D11DeviceContext1), (void **)&g.ctx1);
    ctx->Release();
    if (FAILED(hr)) { logf("no ID3D11DeviceContext1 (hr=%08lx)", hr); return false; }
    ID3D11Device1 *dev1 = nullptr;
    if (FAILED(g.dev->QueryInterface(__uuidof(ID3D11Device1), (void **)&dev1))) { logf("no ID3D11Device1"); return false; }
    // 画之前切到一份独立的管线状态，画完切回去，游戏的渲染状态一点不动
    UINT sf = (cf & D3D11_CREATE_DEVICE_SINGLETHREADED) ? D3D11_1_CREATE_DEVICE_CONTEXT_STATE_SINGLETHREADED : 0;
    hr = dev1->CreateDeviceContextState(sf, &fl, 1, D3D11_SDK_VERSION, __uuidof(ID3D11Device1), nullptr, &g.state);
    dev1->Release();
    if (FAILED(hr)) { logf("CreateDeviceContextState failed (hr=%08lx)", hr); return false; }
    return initD2D(g.dev);
}

// 合成用的着色器：全屏三角形，按像素取贴图（预乘 alpha）
static const char kShader[] =
    "Texture2D tex : register(t0);\n"
    "float4 vs(uint id : SV_VertexID) : SV_Position {\n"
    "  float2 uv = float2((id << 1) & 2, id & 2);\n"
    "  return float4(uv * float2(2, -2) + float2(-1, 1), 0, 1);\n"
    "}\n"
    "float4 ps(float4 pos : SV_Position) : SV_Target { return tex.Load(int3(pos.xy, 0)); }\n";

typedef HRESULT(WINAPI *D3DCompileFn)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO *, ID3DInclude *, LPCSTR,
                                      LPCSTR, UINT, UINT, ID3DBlob **, ID3DBlob **);

static bool initComposite() {
    HMODULE m = LoadLibraryW(L"d3dcompiler_47.dll");
    auto compile = m ? (D3DCompileFn)GetProcAddress(m, "D3DCompile") : nullptr;
    if (!compile) { logf("d3dcompiler_47.dll not available"); return false; }
    ID3DBlob *vsb = nullptr, *psb = nullptr, *err = nullptr;
    HRESULT hr = compile(kShader, sizeof(kShader) - 1, "etb", nullptr, nullptr, "vs", "vs_4_0", 0, 0, &vsb, &err);
    if (err) { logf("vs: %s", (const char *)err->GetBufferPointer()); etb_release(err); }
    if (SUCCEEDED(hr)) hr = compile(kShader, sizeof(kShader) - 1, "etb", nullptr, nullptr, "ps", "ps_4_0", 0, 0, &psb, &err);
    if (err) { logf("ps: %s", (const char *)err->GetBufferPointer()); etb_release(err); }
    if (SUCCEEDED(hr)) hr = g.d11->CreateVertexShader(vsb->GetBufferPointer(), vsb->GetBufferSize(), nullptr, &g.vs);
    if (SUCCEEDED(hr)) hr = g.d11->CreatePixelShader(psb->GetBufferPointer(), psb->GetBufferSize(), nullptr, &g.ps);
    etb_release(vsb);
    etb_release(psb);
    if (FAILED(hr)) { logf("shader creation failed (hr=%08lx)", hr); return false; }
    D3D11_BLEND_DESC bd = {};
    bd.RenderTarget[0].BlendEnable = TRUE;
    bd.RenderTarget[0].SrcBlend = D3D11_BLEND_ONE;              // 预乘 alpha
    bd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
    bd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ZERO;
    bd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_ONE;
    bd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
    bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
    hr = g.d11->CreateBlendState(&bd, &g.blend);
    if (FAILED(hr)) { logf("CreateBlendState failed (hr=%08lx)", hr); return false; }
    return true;
}

static bool init12() {
    ID3D12CommandQueue *q = g_queue;
    D3D_FEATURE_LEVEL fls[] = {D3D_FEATURE_LEVEL_12_1, D3D_FEATURE_LEVEL_12_0, D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
    HRESULT hr = D3D11On12CreateDevice(g.dev12, D3D11_CREATE_DEVICE_BGRA_SUPPORT, fls, 4, (IUnknown **)&q, 1, 0,
                                       &g.d11, &g.ctx11, nullptr);
    if (FAILED(hr)) { logf("D3D11On12CreateDevice failed (hr=%08lx)", hr); return false; }
    if (FAILED(g.d11->QueryInterface(__uuidof(ID3D11On12Device), (void **)&g.on12))) { logf("no ID3D11On12Device"); return false; }
    logf("D3D12 device wrapped with D3D11On12");
    return initComposite() && initD2D(g.d11);
}

// 1 = 成功，0 = 还没拿到命令队列（下一帧再试），-1 = 不支持
static int initDevice(IDXGISwapChain *sc) {
    if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D11Device), (void **)&g.dev))) {
        g.api = 11;
        return init11(sc) ? 1 : -1;
    }
    HRESULT hr = sc->GetDevice(__uuidof(ID3D12Device), (void **)&g.dev12);
    if (FAILED(hr)) { logf("swapchain device is neither D3D11 nor D3D12 (hr=%08lx)", hr); return -1; }
    if (!g_qvtbl) { logf("D3D12 swapchain but command queue hook missing"); return -1; }
    if (!g_queue) return 0;
    g.api = 12;
    return init12() ? 1 : -1;
}

static bool ensureTarget11(IDXGISwapChain *sc) {
    if (g.target) return true;
    IDXGISurface *surf = nullptr;
    if (FAILED(sc->GetBuffer(0, __uuidof(IDXGISurface), (void **)&surf))) { logf("GetBuffer failed"); return false; }
    DXGI_SURFACE_DESC sd;
    surf->GetDesc(&sd);
    D2D1_BITMAP_PROPERTIES1 bp = D2D1::BitmapProperties1(
        D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
        D2D1::PixelFormat(sd.Format, D2D1_ALPHA_MODE_IGNORE), 96, 96);
    HRESULT hr = g.dc->CreateBitmapFromDxgiSurface(surf, &bp, &g.target);
    surf->Release();
    if (FAILED(hr)) { logf("backbuffer format %d not drawable by Direct2D (hr=%08lx)", sd.Format, hr); return false; }
    g.bbW = sd.Width;
    g.bbH = sd.Height;
    logf("D3D11 backbuffer %ux%u format %d", sd.Width, sd.Height, sd.Format);
    return true;
}

static bool ensureTargets12(IDXGISwapChain *sc) {
    if (g.ovBitmap) return true;
    DXGI_SWAP_CHAIN_DESC d;
    if (FAILED(sc->GetDesc(&d))) return false;
    for (UINT i = 0; i < d.BufferCount; i++) {
        ID3D12Resource *res = nullptr;
        if (FAILED(sc->GetBuffer(i, __uuidof(ID3D12Resource), (void **)&res))) { logf("GetBuffer(%u) failed", i); return false; }
        D3D11_RESOURCE_FLAGS f = {D3D11_BIND_RENDER_TARGET, 0, 0, 0};
        ID3D11Resource *w = nullptr;
        HRESULT hr = g.on12->CreateWrappedResource(res, &f, D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_PRESENT,
                                                  __uuidof(ID3D11Resource), (void **)&w);
        res->Release();
        if (FAILED(hr)) { logf("CreateWrappedResource failed (hr=%08lx)", hr); return false; }
        g.wrapped.push_back(w);
        ID3D11RenderTargetView *rtv = nullptr;
        hr = g.d11->CreateRenderTargetView(w, nullptr, &rtv);
        if (FAILED(hr)) { logf("CreateRenderTargetView failed (hr=%08lx)", hr); return false; }
        g.rtvs.push_back(rtv);
    }
    g.bbW = d.BufferDesc.Width;
    g.bbH = d.BufferDesc.Height;

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = g.bbW;
    td.Height = g.bbH;
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = g.d11->CreateTexture2D(&td, nullptr, &g.ovTex);
    if (SUCCEEDED(hr)) hr = g.d11->CreateShaderResourceView(g.ovTex, nullptr, &g.ovSrv);
    IDXGISurface *surf = nullptr;
    if (SUCCEEDED(hr)) hr = g.ovTex->QueryInterface(__uuidof(IDXGISurface), (void **)&surf);
    if (SUCCEEDED(hr)) {
        D2D1_BITMAP_PROPERTIES1 bp = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
        hr = g.dc->CreateBitmapFromDxgiSurface(surf, &bp, &g.ovBitmap);
    }
    if (surf) surf->Release();
    if (FAILED(hr)) { logf("overlay texture creation failed (hr=%08lx)", hr); return false; }
    logf("D3D12 backbuffers %u x %ux%u format %d", d.BufferCount, g.bbW, g.bbH, d.BufferDesc.Format);
    return true;
}

static void paint(EtbHeader *hdr, uint32_t used, bool clear) {
    g.dc->BeginDraw();
    if (clear) g.dc->Clear(D2D1::ColorF(0, 0, 0, 0));
    g.dc->SetTransform(D2D1::Matrix3x2F::Scale((float)g.bbW / hdr->w, (float)g.bbH / hdr->h));
    g.painter.beginFrame((float)hdr->w, (float)hdr->h, hdr->delay);
    g.painter.draw(g.local.data(), used);
    HRESULT hr = g.dc->EndDraw();
    g.painter.endFrame();
    if (hr == (HRESULT)D2DERR_RECREATE_TARGET) {
        logf("D2D target lost, recreating");
        g.ready = false;              // 下一帧在 onPresent 里整体重建
    }
}

static void fail(EtbHeader *hdr) {
    releaseDevice();
    g.unsupported = true;
    InterlockedExchange(&hdr->loaded, 2);
}

static void onPresent(IDXGISwapChain *sc) {
    if (g_unloading || !openShared()) return;
    EtbHeader *hdr = g.hdr;
    if (hdr->quit) { beginUnload(); return; }
    if (g.unsupported) { InterlockedExchange(&hdr->loaded, 2); return; }
    if (g.api && (sc != g.sc || !g.ready)) {   // 游戏重建了交换链，或者 D2D 要求重建
        logf("recreating device resources");
        releaseDevice();
    }
    if (!g.ready) {
        g.sc = sc;
        int r = initDevice(sc);
        if (r == 0) { releaseDevice(); return; }
        if (r < 0) { fail(hdr); return; }
        g.ready = true;
    }
    if (!(g.api == 11 ? ensureTarget11(sc) : ensureTargets12(sc))) { fail(hdr); return; }
    InterlockedExchange(&hdr->loaded, 1);

    if (!hdr->visible || hdr->w <= 0 || hdr->h <= 0) return;
    if (GetTickCount() - hdr->heartbeat > 2000) return;     // Python 端没了：不画
    uint32_t act = hdr->active & 1;
    uint32_t used = hdr->used[act];
    if (!used || used > ETB_BUF_SIZE) return;
    memcpy(g.local.data(), g.base + sizeof(EtbHeader) + act * ETB_BUF_SIZE, used);

    if (g.api == 11) {
        ID3DDeviceContextState *prev = nullptr;
        g.ctx1->SwapDeviceContextState(g.state, &prev);
        g.dc->SetTarget(g.target);
        paint(hdr, used, false);
        g.dc->SetTarget(nullptr);
        g.ctx1->SwapDeviceContextState(prev, nullptr);
        if (prev) prev->Release();
    } else {
        IDXGISwapChain3 *sc3 = nullptr;
        if (FAILED(sc->QueryInterface(__uuidof(IDXGISwapChain3), (void **)&sc3))) return;
        UINT idx = sc3->GetCurrentBackBufferIndex();
        sc3->Release();
        if (idx >= g.rtvs.size()) return;
        g.dc->SetTarget(g.ovBitmap);
        paint(hdr, used, true);
        g.dc->SetTarget(nullptr);
        if (!g.ready) return;

        // 把覆盖层贴图混合到这一帧的后台缓冲上
        g.on12->AcquireWrappedResources(&g.wrapped[idx], 1);
        ID3D11DeviceContext *c = g.ctx11;
        c->OMSetRenderTargets(1, &g.rtvs[idx], nullptr);
        D3D11_VIEWPORT vp = {0, 0, (float)g.bbW, (float)g.bbH, 0, 1};
        c->RSSetViewports(1, &vp);
        c->IASetInputLayout(nullptr);
        c->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        c->VSSetShader(g.vs, nullptr, 0);
        c->PSSetShader(g.ps, nullptr, 0);
        c->PSSetShaderResources(0, 1, &g.ovSrv);
        float bf[4] = {0, 0, 0, 0};
        c->OMSetBlendState(g.blend, bf, 0xFFFFFFFF);
        c->Draw(3, 0);
        ID3D11ShaderResourceView *nullSrv = nullptr;
        c->PSSetShaderResources(0, 1, &nullSrv);
        c->OMSetRenderTargets(0, nullptr, nullptr);
        g.on12->ReleaseWrappedResources(&g.wrapped[idx], 1);
        g.ctx11->Flush();              // 提交到游戏的命令队列，排在 Present 前面
    }
}

static HRESULT STDMETHODCALLTYPE hkPresent(IDXGISwapChain *sc, UINT sync, UINT flags) {
    if (!(flags & DXGI_PRESENT_TEST)) onPresent(sc);
    return oPresent(sc, sync, flags);
}

static HRESULT STDMETHODCALLTYPE hkPresent1(IDXGISwapChain1 *sc, UINT sync, UINT flags,
                                           const DXGI_PRESENT_PARAMETERS *pp) {
    if (!(flags & DXGI_PRESENT_TEST)) onPresent(sc);
    return oPresent1(sc, sync, flags, pp);
}

static HRESULT STDMETHODCALLTYPE hkResizeBuffers(IDXGISwapChain *sc, UINT n, UINT w, UINT h, DXGI_FORMAT f, UINT fl) {
    if (!g_unloading) releaseTarget();     // 后台缓冲还被引用着的话 ResizeBuffers 会失败
    return oResize(sc, n, w, h, f, fl);
}

static HRESULT STDMETHODCALLTYPE hkResizeBuffers1(IDXGISwapChain3 *sc, UINT n, UINT w, UINT h, DXGI_FORMAT f,
                                                 UINT fl, const UINT *mask, IUnknown *const *queues) {
    if (!g_unloading) releaseTarget();
    return oResize1(sc, n, w, h, f, fl, mask, queues);
}

// 记下游戏提交图形命令用的直接队列（D3D11On12 必须用它）
static void STDMETHODCALLTYPE hkExecute(ID3D12CommandQueue *q, UINT n, ID3D12CommandList *const *lists) {
    if (!g_queue && !g_unloading && n && lists && lists[0] &&
        lists[0]->GetType() == D3D12_COMMAND_LIST_TYPE_DIRECT) {
        q->AddRef();
        if (InterlockedCompareExchangePointer((void *volatile *)&g_queue, q, nullptr) != nullptr)
            q->Release();
        else
            logf("captured direct command queue");
    }
    oExecute(q, n, lists);
}

// ---------------------------------------------------------------- 安装

static void hookQueue() {
    HMODULE m = GetModuleHandleW(L"d3d12.dll");
    if (!m) { logf("d3d12.dll not loaded, D3D12 path disabled"); return; }
    auto create = (PFN_D3D12_CREATE_DEVICE)GetProcAddress(m, "D3D12CreateDevice");
    ID3D12Device *dev = nullptr;
    if (!create || FAILED(create(nullptr, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), (void **)&dev))) {
        logf("dummy D3D12 device failed");
        return;
    }
    D3D12_COMMAND_QUEUE_DESC qd = {};
    qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue *q = nullptr;
    if (SUCCEEDED(dev->CreateCommandQueue(&qd, __uuidof(ID3D12CommandQueue), (void **)&q))) {
        g_qvtbl = *(void ***)q;
        oExecute = (ExecuteFn)g_qvtbl[10];
        q->Release();
        setVtbl(g_qvtbl, 10, (void *)hkExecute);
    }
    dev->Release();
}

static DWORD WINAPI initThread(LPVOID) {
    WNDCLASSW wc = {};
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = g_self;
    wc.lpszClassName = L"ETBHookDummy";
    RegisterClassW(&wc);
    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, L"", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64,
                                nullptr, nullptr, g_self, nullptr);
    DXGI_SWAP_CHAIN_DESC sd = {};
    sd.BufferCount = 1;
    sd.BufferDesc.Width = 64;
    sd.BufferDesc.Height = 64;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hwnd;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain *sc = nullptr;
    ID3D11Device *dev = nullptr;
    ID3D11DeviceContext *ctx = nullptr;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0,
                                               D3D11_SDK_VERSION, &sd, &sc, &dev, nullptr, &ctx);
    if (FAILED(hr)) {
        logf("dummy swapchain failed (hr=%08lx)", hr);
        DestroyWindow(hwnd);
        return 0;
    }
    // 所有 DXGI 交换链共用 dxgi.dll 里的同一张虚表，改这里就能截到游戏的 Present
    g_vtbl = *(void ***)sc;
    IDXGISwapChain1 *sc1 = nullptr;
    if (SUCCEEDED(sc->QueryInterface(__uuidof(IDXGISwapChain1), (void **)&sc1))) {
        g_hasPresent1 = *(void ***)sc1 == g_vtbl;
        sc1->Release();
    }
    IDXGISwapChain3 *sc3 = nullptr;
    if (SUCCEEDED(sc->QueryInterface(__uuidof(IDXGISwapChain3), (void **)&sc3))) {
        g_hasResize1 = *(void ***)sc3 == g_vtbl;
        sc3->Release();
    }
    oPresent = (PresentFn)g_vtbl[8];
    oResize = (ResizeBuffersFn)g_vtbl[13];
    if (g_hasPresent1) oPresent1 = (Present1Fn)g_vtbl[22];
    if (g_hasResize1) oResize1 = (ResizeBuffers1Fn)g_vtbl[39];
    sc->Release();
    ctx->Release();
    dev->Release();
    DestroyWindow(hwnd);
    UnregisterClassW(wc.lpszClassName, g_self);

    hookQueue();                       // 先装队列钩子，Present 第一次进来时多半已经拿到队列
    setVtbl(g_vtbl, 8, (void *)hkPresent);
    setVtbl(g_vtbl, 13, (void *)hkResizeBuffers);
    if (g_hasPresent1) setVtbl(g_vtbl, 22, (void *)hkPresent1);
    if (g_hasResize1) setVtbl(g_vtbl, 39, (void *)hkResizeBuffers1);
    logf("hooks installed (Present1=%d ResizeBuffers1=%d queue=%d)", g_hasPresent1, g_hasResize1, g_qvtbl != nullptr);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = inst;
        DisableThreadLibraryCalls(inst);
        CloseHandle(CreateThread(nullptr, 0, initThread, nullptr, 0, nullptr));   // 不在加载器锁里建设备
    }
    return TRUE;
}
