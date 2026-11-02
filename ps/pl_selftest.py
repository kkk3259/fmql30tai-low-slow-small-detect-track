# -*- coding: utf-8 -*-
"""
上板自检（pl_selftest.py）—— 位流加载后第一件事：确认 AXI4-Lite 寄存器通路是通的。

不需要相机、不需要 udmabuf、不动图像数据，只做三件事：
  1) 打开 /dev/mem，mmap 0x43C00000，读 VERSION（应为 0x00010000）
  2) 读 STATUS，看 busy/done/error/n_cand/帧计数
  3) 可选：写一次 FRAME_ADDR/RESULT_ADDR + CTRL=1，短轮询看 done 是否置起
     （不打帧也能验证"寄存器能写、状态能回"，但这帧数据是随机的，会报 error 或乱候选）

用法（板上，需要 root）：
    sudo python3 pl_selftest.py
    sudo python3 pl_selftest.py --trigger     # 额外做一次空触发

判读：
    VERSION = 0x00010000  → 位流已加载 + 地址映射对 + BD 挂对了
    VERSION = 0xFFFFFFFF / 0x00000000 → 依次检查：位流没加载？BD 没挂 GP0？地址段被占？
"""

import argparse
import mmap
import os
import struct
import sys
import time

# 【2026-10-27 改】寄存器基址 0x43C00000（BD 挂在 M_AXI_GP0 上，官方 FSBL 已使能 GP0）
REG_BASE = 0x43C00000
REG_WINDOW = 0x1000

REG_CTRL = 0x00
REG_FRAME_ADDR = 0x04
REG_RESULT_ADDR = 0x08
REG_STATUS = 0x0C
REG_FRAME_ID = 0x10
REG_VERSION = 0x14

VERSION_EXPECT = 0x00010000

UDMABUF_DEV = "/dev/udmabuf0"
UDMABUF_SYS = "/sys/class/u-dma-buf/udmabuf0"
RESULT_BASE = 0x31000000
STATUS_OFFSET = 0x40


def hx(v):
    return "0x%08X" % (v & 0xFFFFFFFF)


def check_devmem():
    print("[1] /dev/mem 权限")
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    except PermissionError:
        print("     打不开 /dev/mem —— 需要 sudo 运行")
        return None
    except FileNotFoundError:
        print("     没有 /dev/mem —— 内核配置异常")
        return None
    print("     可打开")
    try:
        buf = mmap.mmap(fd, REG_WINDOW, mmap.MAP_SHARED,
                        mmap.PROT_READ | mmap.PROT_WRITE, offset=REG_BASE)
    except OSError as e:
        print("     mmap %s 失败: %s" % (hx(REG_BASE), e))
        print("      可能是内核开了 CONFIG_STRICT_DEVMEM，或该地址段被别的驱动占用")
        os.close(fd)
        return None
    print("     已映射 %s (%d KiB)" % (hx(REG_BASE), REG_WINDOW // 1024))
    return fd, buf


def check_udmabuf():
    print("[2] udmabuf（PS 与 PL 共享的大块内存）")
    if not os.path.exists(UDMABUF_DEV):
        print("     没有 %s —— 内核模块 u-dma-buf 没加载，或设备树没配" % UDMABUF_DEV)
        return False
    try:
        with open(os.path.join(UDMABUF_SYS, "phys_addr")) as f:
            phys = int(f.read().strip(), 0)
        with open(os.path.join(UDMABUF_SYS, "size")) as f:
            size = int(f.read().strip(), 0)
    except OSError as e:
        print("    [WARN] 读 sysfs 失败: %s" % e)
        phys, size = -1, -1
    print("    phys_addr = %s   size = %d (%.1f MiB)" % (hx(phys), size, size / 1048576.0))
    ok = True
    if phys != 0x30100000:
        print("    [WARN] 期望 phys_addr = 0x30100000（docs/14 约定）")
        ok = False
    if size < 0x1000000:
        print("    [WARN] size 期望 ≥ 16 MiB（至少要装下帧区）")
        ok = False
    if ok:
        print("     帧区 0x30100000、结果区 0x31000000 都落在里面")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigger", action="store_true", help="额外做一次空触发（不写帧）")
    args = ap.parse_args()

    print("=" * 60)
    print("PL 上板自检")
    print("=" * 60)

    r = check_devmem()
    if r is None:
        print("\n结论：寄存器通路不通，先把 /dev/mem 或地址映射问题解决。")
        return 1
    fd, buf = r

    def rd(off):
        return struct.unpack_from("<I", buf, off)[0]

    def wr(off, val):
        buf[off:off + 4] = struct.pack("<I", val & 0xFFFFFFFF)

    print("[3] 读寄存器")
    ver = rd(REG_VERSION)
    st = rd(REG_STATUS)
    print("    VERSION = %s" % hx(ver))
    print("    STATUS  = %s   busy=%d done=%d error=%d n_cand=%d 帧计数=%d"
          % (hx(st), st & 1, (st >> 1) & 1, (st >> 2) & 1, (st >> 8) & 0xFF, (st >> 16) & 0xFF))

    ok = True
    if ver == VERSION_EXPECT:
        print("     VERSION 正确 —— 位流已加载、地址映射对、BD 挂对了")
    else:
        ok = False
        print("     VERSION 不对（期望 %s）" % hx(VERSION_EXPECT))
        print("      依次排查：① 位流真加载了吗（fpga_manager state / FSBL 日志）")
        print("                ② BD 里寄存器段是不是 0x43C00000、挂在 M_AXI_GP0")
        print("                ③ 这段地址在 /proc/iomem 里有没有被别的驱动先占")

    udma_ok = check_udmabuf()

    if args.trigger:
        print("[4] 空触发（不打帧，只验证写寄存器 + 状态回读）")
        wr(REG_FRAME_ADDR, 0x30100000)
        wr(REG_RESULT_ADDR, 0x31000000)
        wr(REG_FRAME_ID, 1)
        t0 = time.time()
        wr(REG_CTRL, 1)
        got_done = got_busy = False
        deadline = t0 + 0.2
        while time.time() < deadline:
            s = rd(REG_STATUS)
            got_busy |= bool(s & 1)
            if (s >> 1) & 1:
                got_done = True
                print("     done 置起，用时 %.1f ms，n_cand=%d" % ((time.time() - t0) * 1000, (s >> 8) & 0xFF))
                break
            time.sleep(0.0002)
        if not got_done:
            print("     200 ms 内没等到 done（busy 见过=%s）" % got_busy)
            print("      说明 CTRL 写进去了但流水线没跑完：检查帧地址/结果地址是否在 udmabuf 内、")
            print("      以及 m_axi 读写是否被 HP0 接住（看 bit 2 error）")
    else:
        print("[4] 跳过空触发（加 --trigger 可测）")

    buf.close()
    os.close(fd)

    print("\n" + "=" * 60)
    if ok and udma_ok:
        print("结论：通路全通，可以跑 pl_cam_demo.py 了。")
        return 0
    print("结论：还有项没过，按上面的提示逐条排查。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
