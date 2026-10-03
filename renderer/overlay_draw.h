// 覆盖层的公共部分：共享内存布局 + 用 Direct2D/DirectWrite 执行绘制命令。
// etb_render.exe（独立透明窗口）和 etb_hook.dll（注入游戏、在 Present 里画）共用。
//
// 共享内存布局（小端）：
//   Header（64 字节）+ 2 个命令缓冲区（双缓冲，各 ETB_BUF_SIZE 字节）
//   Python 写完一个缓冲区后设置 active、再把 seq 加 1；绘制端发现 seq 变了就复制 active 缓冲区来画。
// 命令（每条以 1 字节类型开头）：
//   1 文字   f32 x, f32 y, u32 argb, f32 字号(px), u8 粗体, u8 锚点(0~8), u16 字符数, wchar[字符数]
//   2 椭圆   f32 cx, f32 cy, f32 rx, f32 ry, u32 填充argb(0=不填), u32 描边argb(0=不描), f32 线宽
//   3 线段   f32 x1, f32 y1, f32 x2, f32 y2, u32 argb, f32 线宽
//   4 多边形 u16 点数, u32 填充argb, u32 描边argb, f32 线宽, 点数×(f32 x, f32 y)
//   5、6 是世界坐标标记和相机参数，只有 etb_hook.dll 处理（见那边的说明）
#pragma once
#include <windows.h>
#include <d2d1_1.h>
#include <dwrite.h>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <unordered_map>

static const uint32_t ETB_MAGIC = 0x4F425445;   // "ETBO"
static const uint32_t ETB_VERSION = 1;
static const uint32_t ETB_BUF_SIZE = 1 << 20;

#pragma pack(push, 1)
struct EtbHeader {
    uint32_t magic;
    uint32_t version;
    volatile LONG seq;
    uint32_t active;
    int32_t x, y, w, h;     // 游戏客户区（屏幕坐标），绘制命令都按这个尺寸给出
    uint32_t visible;
    uint32_t quit;
    uint32_t used[2];
    uint32_t delay;         // 注入版：相机采样晚几帧（对齐补偿）
    uint32_t heartbeat;     // 注入版：Python 每帧写 GetTickCount()，太久没更新就不画
    volatile LONG loaded;   // 注入版：DLL 写 1 = 正常工作，2 = 不支持（Python 退回独立窗口），0 = 已卸载
    uint32_t reserved;
};
#pragma pack(pop)
static_assert(sizeof(EtbHeader) == 64, "header must be 64 bytes");

template <class T> static void etb_release(T *&p) {
    if (p) { p->Release(); p = nullptr; }
}

struct Painter {
    ID2D1Factory1 *factory = nullptr;
    ID2D1DeviceContext *dc = nullptr;
    ID2D1SolidColorBrush *brush = nullptr;
    IDWriteFactory *dw = nullptr;
    std::map<std::pair<int, bool>, IDWriteTextFormat *> formats;

    // 文字排版缓存：同样的字符串/字号/粗细直接复用排版结果，长时间没用到的定期清掉
    struct CachedText {
        IDWriteTextLayout *layout;
        DWRITE_TEXT_METRICS m;
        uint32_t used;
    };
    std::unordered_map<std::wstring, CachedText> texts;
    uint32_t frameNo = 0;

    virtual ~Painter() {}

    // factory / dc 由调用方创建好再交进来
    bool setup(ID2D1Factory1 *f, ID2D1DeviceContext *c) {
        factory = f;
        dc = c;
        dc->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);   // 透明背景上只能用灰度抗锯齿
        if (FAILED(dc->CreateSolidColorBrush(D2D1::ColorF(1, 1, 1, 1), &brush))) return false;
        return SUCCEEDED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                                             (IUnknown **)&dw));
    }

    void releaseAll() {
        for (auto &kv : texts) kv.second.layout->Release();
        texts.clear();
        for (auto &kv : formats)
            if (kv.second) kv.second->Release();
        formats.clear();
        etb_release(brush);
        etb_release(dw);
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
        int px = (int)(size + 0.5f);
        std::wstring key(s, n);
        key.push_back((wchar_t)(px * 2 + (bold ? 1 : 0)));
        auto it = texts.find(key);
        if (it == texts.end()) {
            IDWriteTextFormat *f = format(px, bold);
            if (!f) return;
            CachedText c = {};
            if (FAILED(dw->CreateTextLayout(s, n, f, 4096.f, 512.f, &c.layout))) return;
            c.layout->GetMetrics(&c.m);
            it = texts.emplace(std::move(key), c).first;
        }
        it->second.used = frameNo;
        const DWRITE_TEXT_METRICS &m = it->second.m;
        // 锚点：0 nw 1 n 2 ne 3 w 4 center 5 e 6 sw 7 s 8 se（和 tkinter 一致）
        float ax = (anchor % 3 == 0) ? 0.f : (anchor % 3 == 1 ? m.width / 2 : m.width);
        float ay = (anchor / 3 == 0) ? 0.f : (anchor / 3 == 1 ? m.height / 2 : m.height);
        color(argb);
        dc->DrawTextLayout(D2D1::Point2F(x - ax - m.left, y - ay), it->second.layout, brush);
    }

    // 带一层黑色阴影的文字（和 Python 端 Overlay.text 一样）
    void shadowText(float x, float y, uint32_t argb, float size, bool bold, int anchor, const wchar_t *s, int n) {
        text(x + 1, y + 1, 0xFF000000, size, bold, anchor, s, n);
        text(x, y, argb, size, bold, anchor, s, n);
    }

    void ellipse(float cx, float cy, float rx, float ry, uint32_t fill, uint32_t outline, float width) {
        D2D1_ELLIPSE e = D2D1::Ellipse(D2D1::Point2F(cx, cy), rx, ry);
        if (fill) { color(fill); dc->FillEllipse(e, brush); }
        if (outline) { color(outline); dc->DrawEllipse(e, brush, width); }
    }

    void line(float x1, float y1, float x2, float y2, uint32_t c, float width) {
        color(c);
        dc->DrawLine(D2D1::Point2F(x1, y1), D2D1::Point2F(x2, y2), brush, width);
    }

    void polygon(const float *pts, int count, uint32_t fill, uint32_t outline, float width) {
        if (count < 2) return;
        ID2D1PathGeometry *geo = nullptr;
        ID2D1GeometrySink *sink = nullptr;
        if (FAILED(factory->CreatePathGeometry(&geo))) return;
        if (FAILED(geo->Open(&sink))) { geo->Release(); return; }
        sink->BeginFigure(D2D1::Point2F(pts[0], pts[1]), D2D1_FIGURE_BEGIN_FILLED);
        for (int i = 1; i < count; i++) sink->AddLine(D2D1::Point2F(pts[i * 2], pts[i * 2 + 1]));
        sink->EndFigure(D2D1_FIGURE_END_CLOSED);
        sink->Close();
        if (fill) { color(fill); dc->FillGeometry(geo, brush); }
        if (outline) { color(outline); dc->DrawGeometry(geo, brush, width); }
        sink->Release();
        geo->Release();
    }

    // 处理 1~4 以外的命令；返回下一条命令的位置，nullptr 表示不认识（丢弃这一帧剩下的部分）
    virtual const uint8_t *ext(uint8_t type, const uint8_t *p, const uint8_t *end) { return nullptr; }

    static float rf32(const uint8_t *&q) { float v; memcpy(&v, q, 4); q += 4; return v; }
    static uint32_t ru32(const uint8_t *&q) { uint32_t v; memcpy(&v, q, 4); q += 4; return v; }
    static uint16_t ru16(const uint8_t *&q) { uint16_t v; memcpy(&v, q, 2); q += 2; return v; }
    static uint64_t ru64(const uint8_t *&q) { uint64_t v; memcpy(&v, q, 8); q += 8; return v; }

    void draw(const uint8_t *p, uint32_t n) {
        const uint8_t *end = p + n;
        while (p < end) {
            uint8_t type = *p++;
            if (type == 1) {
                if (p + 20 > end) return;
                float x = rf32(p), y = rf32(p);
                uint32_t c = ru32(p);
                float size = rf32(p);
                bool bold = *p++;
                int anchor = *p++;
                uint16_t len = ru16(p);
                if (p + len * 2 > end) return;
                std::wstring s((const wchar_t *)p, len);
                p += len * 2;
                text(x, y, c, size, bold, anchor, s.c_str(), len);
            } else if (type == 2) {
                if (p + 28 > end) return;
                float cx = rf32(p), cy = rf32(p), rx = rf32(p), ry = rf32(p);
                uint32_t fill = ru32(p), outline = ru32(p);
                float width = rf32(p);
                ellipse(cx, cy, rx, ry, fill, outline, width);
            } else if (type == 3) {
                if (p + 24 > end) return;
                float x1 = rf32(p), y1 = rf32(p), x2 = rf32(p), y2 = rf32(p);
                uint32_t c = ru32(p);
                float width = rf32(p);
                line(x1, y1, x2, y2, c, width);
            } else if (type == 4) {
                if (p + 14 > end) return;
                uint16_t count = ru16(p);
                uint32_t fill = ru32(p), outline = ru32(p);
                float width = rf32(p);
                if (p + count * 8 > end) return;
                float pts[2 * 64];
                int k = count > 64 ? 64 : count;
                memcpy(pts, p, k * 8);
                polygon(pts, k, fill, outline, width);
                p += count * 8;
            } else {
                p = ext(type, p, end);
                if (!p) return;
            }
        }
    }

    // 每帧画完调用：清理长时间没用到的文字排版
    void endFrame() {
        if (++frameNo % 120 != 0) return;
        for (auto it = texts.begin(); it != texts.end();) {
            if (frameNo - it->second.used > 120) {
                it->second.layout->Release();
                it = texts.erase(it);
            } else {
                ++it;
            }
        }
    }
};
