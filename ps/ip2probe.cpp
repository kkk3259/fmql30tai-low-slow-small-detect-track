// ip2probe.cpp —— 只用 icraft-xrt 原生 API，验证我们的检测器在三域平台里工作
#include <icraft-xrt/core/session.h>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <vector>
#include <chrono>
#include <thread>

using namespace icraft::xrt;

static const uint64_t REG = 0x400C0000ULL;
static const int W = 640, H = 360;

static void put_rect(std::vector<uint8_t>& img, int cx, int cy, int sz, uint8_t v) {
    int x0 = cx - sz / 2, y0 = cy - sz / 2;
    for (int y = y0; y < y0 + sz; ++y)
        for (int x = x0; x < x0 + sz; ++x)
            if (x >= 0 && x < W && y >= 0 && y < H)
                img[y * W + x] = v;
}

int main() {
    auto device = Device::Open("zg330://0");
    const auto& reg = device.defaultRegRegion();
    const auto& mem = device.defaultMemRegion();

    printf("[1] VERSION = 0x%08x\n", reg.read(REG + 0x14));

    std::vector<uint8_t> img(W * H, 0);
    put_rect(img, 100, 80, 6, 255);
    put_rect(img, 250, 100, 10, 255);
    put_rect(img, 400, 120, 14, 255);
    put_rect(img, 150, 250, 18, 255);
    put_rect(img, 480, 260, 20, 255);

    auto chunk = mem.malloc(W * H, false, 64);
    chunk.write(0, reinterpret_cast<char*>(img.data()), img.size());
    uint64_t base = chunk.getMemPtr().addr();
    printf("[2] frame base = 0x%llx\n", (unsigned long long)base);

    reg.write(REG + 0x04, (uint32_t)base);
    reg.write(REG + 0x08, (uint32_t)base);
    reg.write(REG + 0x00, 0);
    reg.write(REG + 0x00, 1);

    auto t0 = std::chrono::steady_clock::now();
    int done = 0;
    for (int i = 0; i < 4000; ++i) {
        if (reg.read(REG + 0x80) & 1) { done = 1; break; }
        std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
    auto t1 = std::chrono::steady_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    printf("[3] done=%d  elapsed=%.2f ms  STATUS=0x%08x\n", done, ms, reg.read(REG + 0x0C));
    if (!done) return 1;

    int nw = (1 + 16 * 7 + 3) / 4;
    std::vector<uint32_t> tab(nw, 0);
    for (int i = 0; i < nw; ++i) {
        reg.write(REG + 0x10, i);
        tab[i] = reg.read(REG + 0x10);
    }
    auto* b = reinterpret_cast<uint8_t*>(tab.data());
    int n = b[0];
    printf("[4] n_cand = %d\n", n);
    for (int i = 0; i < n && i < 16; ++i) {
        uint8_t* c = b + 1 + i * 7;
        int x = (c[0] << 8) | c[1];
        int y = (c[2] << 8) | c[3];
        int a = (c[4] << 8) | c[5];
        printf("    #%d  (%d,%d)  area=%d  peak=%d\n", i, x, y, a, c[6]);
    }
    return 0;
}
