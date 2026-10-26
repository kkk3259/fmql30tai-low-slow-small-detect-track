# -*- coding: utf-8 -*-
"""
PS ↔ PL 通信模块（pl_link.py）

作用：把 PS 侧算好的 640×360 灰度帧送进 PL、触发处理、取回 36 字节候选表。
      是 docs/14-PS-PL接口约定.md 的 PS 侧实现。

数据通路（实测确认）：
    /dev/udmabuf0        物理基址 0x30100000，128 MiB
    sync_mode = 1        可按 offset/size 局部同步
    dma_coherent = 0     ★ 必须手动 sync，否则"随机帧结果错"，极难定位

内存分区（docs/14 §1.1）：
    0x30100000 ~ 0x30FFFFFF   16 MiB  输入帧区（72 帧 × 230400 B）
    0x31000000 ~ 0x310FFFFF    1 MiB  输出区（候选表 + 状态字）
    0x31100000 ~ 0x380FFFFF  111 MiB  备用

✅ P 已确认（2026-10-26）：寄存器基址 = 0xA0000000（挂 PS 的 M_AXI_GP1），
   访问方式 = /dev/mem + mmap；`trigger()` 会写 CTRL.bit0=1 启动一帧，
   `version()` / `status()` 可用于上板首测。其余按 docs/14 v0.2 实现。

用法：
    from pl_link import PlLink
    pl = PlLink(reg_base=REG_BASE)          # 0xA0000000，挂 PS 的 M_AXI_GP1（P 已确认）
    pl.put_frame(0, gray640x360)
    pl.trigger(frame_id=0, frame_addr=0x30100000, result_addr=0x31000000)
    cands = pl.wait_done()
"""

import mmap
import os
import struct
import time

# ---------------------------------------------------------------- 常量（docs/14）
UDMABUF_DEV = "/dev/udmabuf0"
UDMABUF_SYS = "/sys/class/u-dma-buf/udmabuf0"

FRAME_BASE = 0x30100000          # 输入帧区物理基址
FRAME_SIZE = 640 * 360           # 230400 B，8 bit 灰度
N_FRAMES = 72                    # 16 MiB / 230400 = 72.8

RESULT_BASE = 0x31000000         # 输出区物理基址
CAND_OFFSET = 0x00               # 候选表 36 B
STATUS_OFFSET = 0x40             # 状态字 4 B
MAILBOX_OFFSET = 0x44            # 邮箱（docs/14 旧方案，P 改为寄存器接口后备用）

N_CAND_MAX = 5
CAND_STRIDE = 7                  # x(2) + y(2) + 保留(1) + area(1) + peak(1)
STATUS_DONE = 0x80000000         # bit31
STATUS_ERROR = 0x40000000        # bit30

# ---------------------------------------------------------------- 寄存器基址
# P 已确认（2026-10-26）：寄存器组基址 = 0xA0000000，由 Vivado BD 挂在 **M_AXI_GP1** 上。
#   原因：Zynq-7000 的 PS 主口地址窗口是硬件固定的——
#         M_AXI_GP0 -> 0x4000_0000 ~ 0x7FFF_FFFF（0x40000000 正是 AI_Mate 的寄存器窗口）
#         M_AXI_GP1 -> 0x8000_0000 ~ 0xBFFF_FFFF（0xA0000000 落在这段）
#   我们自己的位流里没有 AI_Mate，所以 0x80000000（AI_Mate DMA 窗口）与
#   0xA0000000（我们的寄存器）都在 GP1 段内、互不重叠。
#   不要把基址改回 0x40000000 或 0x80000000。
REG_BASE = 0xA0000000
REG_WINDOW = 0x1000              # mmap 4 KiB（寄存器只用到 0x00~0x17）

# 以下是 P 在 pl/rtl/ip2_axi_top.v 里实现的**偏移**（注释原文摘录）：
REG_CTRL = 0x00                  # W  bit0 = start（写 1 启动一帧，自清）
REG_STATUS = 0x0C                # R  bit0 busy / bit1 done / bit2 error /
                                 #    [15:8] n_cand / [23:16] 已完成帧计数
REG_VERSION = 0x14               # R  0x0001_0000
REG_FRAME_ADDR = 0x04            # W  输入帧物理地址（默认 0x30100000）
REG_RESULT_ADDR = 0x08           # W  输出区物理地址（默认 0x31000000）
REG_FRAME_ID = 0x10              # W  帧号（低 16 位）


class PlLink:
    """PS 侧 PL 通信封装。只负责搬运与同步，不涉及算法。"""

    def __init__(self, reg_base=REG_BASE):
        """
        参数：
            reg_base: AXI4-Lite 寄存器组物理基地址，默认 0xA0000000（P 已确认）
        """
        self.reg_base = reg_base
        self._fd = None
        self._buf = None
        self._mem = None
        self._reg_fd = None
        self._reg_buf = None
        self.last_trigger_id = None

    # ------------------------------------------------------------ 生命周期
    def open(self):
        """打开 udmabuf（映射 128 MiB）+ 映射寄存器窗口（4 KiB，/dev/mem）。"""
        self._fd = os.open(UDMABUF_DEV, os.O_RDWR | os.O_SYNC)
        self._buf = mmap.mmap(self._fd, 0)

        # 寄存器窗口：PL 的 AXI 从口不是 RAM，/dev/mem 直接映射即可
        # （若内核开了 CONFIG_STRICT_DEVMEM，非 RAM 区域仍允许访问；真被拦时
        #   open 会 EPERM，此时改用 /dev/uioN，见文档 §7 风险表）
        if self.reg_base:
            self._reg_fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            self._reg_buf = mmap.mmap(self._reg_fd, REG_WINDOW,
                                      mmap.MAP_SHARED,
                                      mmap.PROT_READ | mmap.PROT_WRITE,
                                      offset=self.reg_base)
        return self

    def close(self):
        if self._reg_buf is not None:
            self._reg_buf.close()
            self._reg_buf = None
        if self._reg_fd is not None:
            os.close(self._reg_fd)
            self._reg_fd = None
        if self._buf is not None:
            self._buf.close()
            self._buf = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ cache 同步
    def _sync(self, offset, size, for_device):
        """
        dma_coherent = 0，必须手动同步。
        for_device=True  : PS 写完之后，交权给 PL（sync_for_device）
        for_device=False : PS 读之前，把 PL 写的内容拉回 CPU cache（sync_for_cpu）
        """
        base = UDMABUF_SYS
        with open(os.path.join(base, "sync_offset"), "w") as f:
            f.write(str(offset))
        with open(os.path.join(base, "sync_size"), "w") as f:
            f.write(str(size))
        flag = "sync_for_device" if for_device else "sync_for_cpu"
        with open(os.path.join(base, flag), "w") as f:
            f.write("1")

    # ------------------------------------------------------------ 写帧
    def put_frame(self, k, gray):
        """
        把第 k 帧灰度图写入 udmabuf，并完成 sync_for_device。

        参数：
            k    : 帧序号（自动对 N_FRAMES 取模）
            gray : numpy uint8 数组，必须是 640×360 = 230400 字节（已 contiguous）

        返回：
            该帧在 udmabuf 里的**相对偏移**（字节）
        """
        if gray.size != FRAME_SIZE:
            raise ValueError("帧大小应为 %d 字节（640×360），实际 %d"
                             % (FRAME_SIZE, gray.size))
        if not gray.flags["C_CONTIGUOUS"]:
            gray = gray.copy(order="C")

        off = (k % N_FRAMES) * FRAME_SIZE
        self._buf[off:off + FRAME_SIZE] = gray.tobytes()
        self._sync(off, FRAME_SIZE, for_device=True)      # ★ 不可省
        return off

    # ------------------------------------------------------------ 触发
    def trigger(self, frame_id, frame_addr=None, result_addr=None):
        """
        通过 AXI4-Lite 寄存器通知 PL 处理第 frame_id 帧。

        ⚠️ PL 侧判据是"寄存器值发生变化"，因此**不要重复写同一个 frame_id**
           （否则 PL 不触发）。需要重复处理同一帧时，用 frame_id + 0x10000
           翻转 bit16 即可（P 在 docs/14 §3 的约定）。

        参数：
            frame_id    : 帧号（写入低 16 位）
            frame_addr  : 帧物理地址，None 用默认 FRAME_BASE
            result_addr : 输出区物理地址，None 用默认 RESULT_BASE
        """
        if frame_addr is None:
            frame_addr = FRAME_BASE
        if result_addr is None:
            result_addr = RESULT_BASE

        self._reg_write(REG_FRAME_ADDR, frame_addr)
        self._reg_write(REG_RESULT_ADDR, result_addr)
        self._reg_write(REG_FRAME_ID, frame_id & 0xFFFFFFFF)
        # docs/14 v0.2：写 CTRL.bit0 = 1 启动一帧（PL 侧自清）
        self._reg_write(REG_CTRL, 1)
        self.last_trigger_id = frame_id

    # ------------------------------------------------------------ 等结果
    def wait_done(self, timeout_s=0.1):
        """
        轮询状态字 bit31(done)。超时返回 None。

        返回：
            [{"x":int, "y":int, "area":int, "peak":int}, ...]，最多 5 个
            坐标为**质心**（详见 docs/13 的更正说明）
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self._sync(CAND_OFFSET, STATUS_OFFSET + 4, for_device=False)   # ★ 读前必同步
            status = struct.unpack_from("<I", self._buf, STATUS_OFFSET)[0]
            if status & STATUS_DONE:
                if status & STATUS_ERROR:
                    raise RuntimeError("PL 报告 AXI 读超时/异常（status=0x%08X）" % status)
                n = self._buf[CAND_OFFSET]
                return self._parse_candidates(n)
            time.sleep(0.0002)          # 200 µs，比 PL 的 5 ms 处理时间细得多
        return None

    def _parse_candidates(self, n):
        """解析 36 字节候选表。大端 16 bit 的 x/y（docs/14 §2.1）。"""
        n = min(int(n), N_CAND_MAX)
        out = []
        for i in range(n):
            o = CAND_OFFSET + 1 + i * CAND_STRIDE
            x, y = struct.unpack_from(">HH", self._buf, o)
            area = self._buf[o + 5]
            peak = self._buf[o + 6]
            if x == 0 and y == 0 and area == 0 and peak == 0:
                continue                      # 空槽位
            out.append({"x": x, "y": y, "area": area, "peak": peak})
        return out

    # ------------------------------------------------------------ 寄存器访问
    def _reg_write(self, offset, value):
        """
        写 AXI4-Lite 寄存器（/dev/mem + mmap，P 已确认走这条路）。

        基地址 0xA0000000 由 Vivado BD 挂在 PS 的 M_AXI_GP1 上；
        PL 的 AXI 从口不是 RAM 区，/dev/mem 可以直接映射。
        """
        if self._reg_buf is None:
            raise RuntimeError("寄存器窗口未映射：请先 open()（或检查 /dev/mem 权限）")
        self._reg_buf[offset:offset + 4] = struct.pack("<I", value & 0xFFFFFFFF)

    def _reg_read(self, offset):
        """读 AXI4-Lite 寄存器。"""
        if self._reg_buf is None:
            raise RuntimeError("寄存器窗口未映射：请先 open()（或检查 /dev/mem 权限）")
        return struct.unpack_from("<I", self._reg_buf, offset)[0]

    def version(self):
        """读 VERSION 寄存器，正常应为 0x00010000（用于确认 PL 已加载、地址通）。"""
        return self._reg_read(REG_VERSION)

    def status(self):
        """读 STATUS 寄存器：bit0 busy / bit1 done / bit2 error / [15:8] n_cand。"""
        return self._reg_read(REG_STATUS)


# ---------------------------------------------------------------- 自检
def _self_test():
    """
    不需要 PL、不需要板子，只在有 /dev/udmabuf0 的板端跑。
    验证：写入 → sync → 读回是否一致。
    """
    import numpy as np

    print("=== PlLink 自检（不触发 PL）===")
    with PlLink(reg_base=0) as pl:
        frame = np.random.randint(0, 256, FRAME_SIZE, dtype=np.uint8)
        off = pl.put_frame(0, frame)
        print("  写入第 0 帧，偏移 0x%06X，%d 字节" % (off, FRAME_SIZE))

        # 直接比较（同进程写读，不涉及 PL，主要验证 mmap 与 sync 调用链路通）
        got = np.frombuffer(pl._buf[off:off + FRAME_SIZE], dtype=np.uint8)
        same = bool(np.array_equal(frame, got))
        print("  读回一致: %s" % same)
        if not same:
            diff = int((frame != got).sum())
            print("  ⚠️ 差异 %d 字节 / %d" % (diff, FRAME_SIZE))

        # 验证候选表解析（手工造一条，确认字节序与字段偏移）
        pl._buf[CAND_OFFSET] = 1
        struct.pack_into(">HH", pl._buf, CAND_OFFSET + 1, 320, 180)
        pl._buf[CAND_OFFSET + 6] = 42          # area
        pl._buf[CAND_OFFSET + 7] = 200         # peak
        cands = pl._parse_candidates(1)
        print("  候选表解析: %s" % cands)
        assert cands[0]["x"] == 320 and cands[0]["y"] == 180
        assert cands[0]["area"] == 42 and cands[0]["peak"] == 200

        # 恢复
        pl._buf[CAND_OFFSET] = 0
        pl._buf[CAND_OFFSET: CAND_OFFSET + 1 + CAND_STRIDE] = b"\x00" * (1 + CAND_STRIDE)

    print("=== 自检通过 ===")


if __name__ == "__main__":
    _self_test()
