//====================================================================
// IP2 三域平台测试程序
//   流程：ICraft 分配 PL DDR -> 写测试帧 -> 写寄存器启动检测器
//         -> 轮询 done -> 读候选表 -> 打印
//
// 平台寄存器（字节地址，基址 0x400C0000）：
//   0x00 CTRL(start)      写 1 启动
//   0x04 FRAME_ADDR       帧在 PL DDR 的地址
//   0x08 RESULT_ADDR      保留
//   0x0C STATUS           {frm_cnt[23:16], n_cand[15:8], err[2], done[1], busy[0]}
//   0x14 VERSION          0x00010000
//   0x10 窗口             写=字索引 0..112，读=该字数据（候选表 1+64*7 字节）
//   0x80 DONE             适配层把 STATUS.done 映射到这里，读回 0/1
//
// 编译（板上）：
//   g++ -O2 -std=c++17 ip2_demo.cpp -o ip2_demo \
//       -I/root/fpai_app/deps/modelzoo_utils/include \
//       -I/root/fpai_app/deps/thirdparty/include \
//       -licraft-xrt -licraft-xir
//====================================================================
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <chrono>
#include <thread>

#include "et_device.hpp"
#include <icraft-xrt/core/session.h>

using namespace icraft::xrt;
using namespace fpai;

static const int W = 640;
static const int H = 360;
static const uint32_t REG_BASE = 0x400C0000;

static void fill_square(std::vector<uint8_t> &img, int cx, int cy, int s, uint8_t v)
{
    for (int y = cy - s / 2; y <= cy + s / 2; ++y)
        for (int x = cx - s / 2; x <= cx + s / 2; ++x)
            if (x >= 0 && x < W && y >= 0 && y < H)
                img[(size_t)y * W + x] = v;
}

int main(int argc, char *argv[])
{
    //----------------------------------------------------------------
    // 1. 打开设备
    //----------------------------------------------------------------
    auto device = Device::Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000");
    auto fpai = device.cast<FPAIDevice>();

    uint32_t ver = (uint32_t)fpai.defaultRegRegion().read(REG_BASE + 0x14, false);
    printf("IP2 VERSION = 0x%08x\n", ver);
    if ((ver & 0xFFFF0000u) != 0x00010000u)
        printf("WARN: VERSION 不符，可能加载的不是我们的位流\n");

    //----------------------------------------------------------------
    // 2. 分配 PL DDR 并写入测试帧
    //----------------------------------------------------------------
    size_t nbytes = (size_t)W * H;
    auto mem = fpai.defaultMemRegion().malloc(nbytes + 4096, 0, 64);
    uint32_t base = (uint32_t)mem->begin.addr();
    printf("PL-DDR frame base = 0x%08x (%u bytes)\n", base, (unsigned)nbytes);

    std::vector<uint8_t> img(nbytes, 0);
    // 五个已知方块：尺寸 6/10/14/18/20，中心见 P1..P5
    const int sz[5] = {6, 10, 14, 18, 20};
    const int cx[5] = {100, 250, 400, 150, 480};
    const int cy[5] = {80, 100, 120, 250, 260};
    for (int i = 0; i < 5; ++i)
        fill_square(img, cx[i], cy[i], sz[i], 255);

    mem->write(0, (char *)img.data(), nbytes);
    printf("frame written\n");

    //----------------------------------------------------------------
    // 3. 配置并启动
    //----------------------------------------------------------------
    fpai.defaultRegRegion().write(REG_BASE + 0x04, base, false);           // FRAME_ADDR
    fpai.defaultRegRegion().write(REG_BASE + 0x08, base + nbytes, false);  // RESULT_ADDR（暂不用）
    fpai.defaultRegRegion().write(REG_BASE + 0x00, 1, false);              // START

    auto t0 = std::chrono::steady_clock::now();
    int done = 0;
    while (!done) {
        done = (int)(fpai.defaultRegRegion().read(REG_BASE + 0x80, false) & 1);
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                      std::chrono::steady_clock::now() - t0).count();
        if (ms > 10000) {
            printf("ERROR: timeout waiting done (10 s)\n");
            return -1;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                  std::chrono::steady_clock::now() - t0).count();
    printf("done in %lld ms\n", (long long)ms);

    uint32_t status = (uint32_t)fpai.defaultRegRegion().read(REG_BASE + 0x0C, false);
    int n_stat = (status >> 8) & 0xFF;
    int err = (status >> 2) & 1;
    printf("STATUS = 0x%08x  n_cand=%d  err=%d\n", status, n_stat, err);

    //----------------------------------------------------------------
    // 4. 读候选表（113 个字 = 452 字节）
    //----------------------------------------------------------------
    std::vector<uint32_t> words(113, 0);
    for (int i = 0; i < 113; ++i) {
        fpai.defaultRegRegion().write(REG_BASE + 0x10, (uint32_t)i, false);
        words[i] = (uint32_t)fpai.defaultRegRegion().read(REG_BASE + 0x10, false);
    }
    const uint8_t *b = (const uint8_t *)words.data();
    int nc = b[0];
    printf("TABLE n_cand = %d\n", nc);
    for (int i = 0; i < nc && i < 16; ++i) {
        const uint8_t *c = b + 1 + i * 7;
        int x = (c[0] << 8) | c[1];
        int y = (c[2] << 8) | c[3];
        int a = (c[4] << 8) | c[5];
        int pk = c[6];
        printf("  cand%-2d x=%-3d y=%-3d area=%-4d peak=%d\n", i, x, y, a, pk);
    }

    Device::Close(device);
    return 0;
}
