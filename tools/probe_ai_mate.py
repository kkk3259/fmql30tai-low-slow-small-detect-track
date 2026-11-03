#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_ai_mate.py —— 板上 NPU（AI_Mate / ZG330）硬件通路自检

用途
    在 FMQL30TAI 开发板（悟净 Lite）上确认 PL 位流里的 AI_Mate 是否可访问。
    纯只读，不写任何寄存器，不做任何破坏性操作。

背景（详见 `docs/33-NPU级联实测记录.md`）
    2026-10-22 曾误判「位流不含 ZG330 AXI 从设备」，原因是扫错了地址：
        · AI_Mate 寄存器窗口   -> 0x40000000 ~ 0x400000E3（约 224 字节）
        · custom op 寄存器空间 -> 0x400C0000 ~ 0x400FFFFF（当前位流未挂）
    AI_Mate 在 +0x1C 处给出 32 位版本号，官方 README 标注为 25122301。

用法
    python3 probe_ai_mate.py            # 默认扫描
    python3 probe_ai_mate.py --json     # 输出 JSON（便于流水线采集）

判据
    +0x01C == 0x25122301             -> AI_Mate 在位且可访问，硬件通路 OK
    +0x01C 可读但值不同               -> 在位，但位流/固件版本不同（记录该值）
    +0x0E4 起全为 0xFFFFFFFF          -> 正常（超出寄存器窗口，DECERR）
    0x400C0000 全为 0xFFFFFFFF        -> 正常（当前位流未挂 custom op）

注意
    · 需要 root 权限（读 /dev/mem）
    · 只读映射（mmap.PROT_READ），不会修改 PL 侧状态
"""

import argparse
import json
import mmap
import os
import struct
import sys

AI_MATE_BASE = 0x40000000
VERSION_OFFSET = 0x01C
EXPECTED_VERSION = 0x25122301

CUSTOM_OP_BASE = 0x400C0000
DMA_BASE = 0x80000000

# 寄存器窗口内已知有值的偏移（用于快照，不含猜测含义）
SNAPSHOT_OFFSETS = (0x01C, 0x030, 0x040, 0x048, 0x0E0)


class MemReader:
    """只读 /dev/mem 映射器，按 4KB 页缓存，减少 mmap 次数。"""

    PAGE = 0x1000

    def __init__(self, path="/dev/mem"):
        # O_SYNC 在 Windows 上不存在（脚本本身只在 Linux 板端运行，这里保证跨平台可 import）
        flags = os.O_RDONLY | getattr(os, "O_SYNC", 0)
        try:
            self.fd = os.open(path, flags)
        except PermissionError:
            sys.exit("需要 root 权限读取 /dev/mem（请用 sudo 运行）")
        except OSError as exc:
            sys.exit("无法打开 %s（%s）；该平台可能未提供该接口，或不在 Linux 板端运行"
                     % (path, exc))
        self._pages = {}

    def _page(self, page_addr):
        m = self._pages.get(page_addr)
        if m is None:
            m = mmap.mmap(
                self.fd, self.PAGE, mmap.MAP_SHARED,
                mmap.PROT_READ, offset=page_addr,
            )
            self._pages[page_addr] = m
        return m

    def read32(self, addr):
        """读 32 位；地址非法时返回异常类型名。"""
        page_addr = addr & ~(self.PAGE - 1)
        off = addr - page_addr
        try:
            m = self._page(page_addr)
            return struct.unpack("<I", m[off:off + 4])[0]
        except Exception as exc:  # noqa: BLE001 - 需要把失败原因报出来
            return type(exc).__name__

    def close(self):
        for m in self._pages.values():
            m.close()
        self._pages.clear()
        os.close(self.fd)


def scan_window(reader, base, size, label):
    """逐 4 字节扫描，返回 (非零列表, 首个 0xFFFFFFFF 的偏移)。"""
    nonzero = []
    first_ff = None
    for off in range(0, size, 4):
        v = reader.read32(base + off)
        if isinstance(v, str):
            if first_ff is None:
                first_ff = (off, v)
            continue
        if v != 0:
            nonzero.append((off, v))
        if v == 0xFFFFFFFF and first_ff is None:
            first_ff = (off, "0xFFFFFFFF")
    return nonzero, first_ff


def main():
    ap = argparse.ArgumentParser(description="AI_Mate (ZG330) 硬件通路自检")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--window", type=lambda s: int(s, 0), default=0x100,
                    help="扫描窗口字节数，默认 0x100（覆盖 0x40000000~0x400000FF）")
    args = ap.parse_args()

    reader = MemReader()
    result = {"ai_mate": {}, "custom_op": {}, "dma": {}, "verdict": ""}

    try:
        # 1) AI_Mate 寄存器窗口
        win = max(args.window, VERSION_OFFSET + 4)
        nonzero, first_ff = scan_window(reader, AI_MATE_BASE, win, "AI_Mate")
        snapshot = {}
        for off in SNAPSHOT_OFFSETS:
            snapshot["0x%03X" % off] = reader.read32(AI_MATE_BASE + off)

        version = reader.read32(AI_MATE_BASE + VERSION_OFFSET)
        result["ai_mate"] = {
            "base": "0x%08X" % AI_MATE_BASE,
            "window_scanned": win,
            "version_offset": "0x%03X" % VERSION_OFFSET,
            "version_raw": version if not isinstance(version, str) else version,
            "version_hex": ("0x%08X" % version) if isinstance(version, int) else None,
            "expected": "0x%08X" % EXPECTED_VERSION,
            "snapshot": snapshot,
            "nonzero_count": len(nonzero),
            "first_ff": None if first_ff is None else
                         {"offset": "0x%03X" % first_ff[0], "reason": first_ff[1]},
        }

        # 2) custom op 空间（仅取首字，确认是否挂载）
        result["custom_op"] = {
            "base": "0x%08X" % CUSTOM_OP_BASE,
            "read32": _fmt(reader.read32(CUSTOM_OP_BASE)),
        }

        # 3) DMA 窗口（PS 侧直接读通常无意义，仅记录）
        result["dma"] = {
            "base": "0x%08X" % DMA_BASE,
            "read32": _fmt(reader.read32(DMA_BASE)),
        }

        # 4) 判定
        if isinstance(version, int) and version == EXPECTED_VERSION:
            result["verdict"] = "OK: AI_Mate 在位且可访问（版本 0x%08X）" % version
        elif isinstance(version, int):
            result["verdict"] = ("WARN: AI_Mate 可访问但版本为 0x%08X（期望 0x%08X），"
                                 "位流/固件版本可能不同" % (version, EXPECTED_VERSION))
        else:
            result["verdict"] = ("FAIL: 无法读取 AI_Mate 版本寄存器（%s）。"
                                 "位流可能不含 AI_Mate，或 PL 未配置成功" % version)
    finally:
        reader.close()

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["verdict"].startswith("OK") else 1

    # 人类可读输出
    am = result["ai_mate"]
    print("=" * 62)
    print(" AI_Mate (ZG330) 硬件通路自检")
    print("=" * 62)
    print(" 寄存器窗口   : %s（扫描 %d 字节）" % (am["base"], am["window_scanned"]))
    print(" 版本寄存器   : +%s = %s" % (am["version_offset"],
                                       am["version_hex"] or am["version_raw"]))
    print(" 期望版本     : %s" % am["expected"])
    print()
    print(" 寄存器快照：")
    for k in sorted(am["snapshot"]):
        v = am["snapshot"][k]
        print("   %s -> %s" % (k, ("0x%08X" % v) if isinstance(v, int) else v))
    print()
    if am["first_ff"]:
        print(" 寄存器窗口结束于 +%s（之后为 %s，属正常 DECERR）"
              % (am["first_ff"]["offset"], am["first_ff"]["reason"]))
    print(" non-zero 单元数: %d" % am["nonzero_count"])
    print()
    print(" custom op 区 : %s -> %s（当前位流通常未挂）"
          % (result["custom_op"]["base"], result["custom_op"]["read32"]))
    print(" DMA 窗口     : %s -> %s（由 libicraft 内部管理）"
          % (result["dma"]["base"], result["dma"]["read32"]))
    print()
    print("-" * 62)
    print(" 结论: %s" % result["verdict"])
    print("-" * 62)
    print()
    print(" 提示：若判定 OK 但上层仍报错，检查 Icraft 版本配套（见 docs/12 第九章）。")
    print("       官方 demo 由 3.33.1 编译、随包模型由 3.36.0 导出，二者不兼容。")
    return 0 if result["verdict"].startswith("OK") else 1


def _fmt(v):
    return ("0x%08X" % v) if isinstance(v, int) else v


if __name__ == "__main__":
    sys.exit(main())
