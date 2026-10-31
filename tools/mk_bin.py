#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Vivado 的 .bit 转成 FMSH fpga_manager 能吃的 .bin（去头 + 每 32 位字内反序）。

背景：悟净 Lite 的 fpga_manager 只接受 FMSH 特有的“字内反序”bin，且
Vivado 每次生成的 .bit 头部长度不一样（实测遇到过 110/111/115/159 字节），
所以不能写死，必须**按同步字 0xAA995566 定位**，并用“结果字节数 = 已知可用 bin 长度”校验。

用法：
    python mk_bin.py <in.bit> <out.bin> [期望字节数=5979916]
"""
import struct
import sys

SYNC = 0xAA995566
EXPECT = 5979916


def find_sync(data):
    """返回同步字所在的字节偏移（可能多处，全部返回）。"""
    hits = []
    for i in range(0, len(data) - 4):
        if struct.unpack_from(">I", data, i)[0] == SYNC:
            hits.append(i)
    return hits


def swap_words(buf):
    """每 4 字节整体反转（FMSH 的要求）。"""
    n = len(buf) // 4
    out = bytearray(n * 4)
    for i in range(n):
        w = buf[i * 4: i * 4 + 4]
        out[i * 4: i * 4 + 4] = w[::-1]
    return bytes(out)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    expect = int(sys.argv[3]) if len(sys.argv) > 3 else EXPECT
    data = open(src, "rb").read()
    print("in  = %s  %d B" % (src, len(data)))
    hits = find_sync(data)
    print("sync word 出现位置: %s" % hits[:6])
    if not hits:
        raise SystemExit("没找到同步字，无法定位头部")
    ok = 0
    for h in hits:
        body = data[h:]
        if len(body) % 4:
            body = body[: len(body) // 4 * 4]
        if len(body) != expect:
            continue
        bin_data = swap_words(body)
        if bin_data[:4] != b"\xff\xff\xff\xff":
            print("  偏移 %d：长度对但头不是 FF（%s），跳过" % (h, bin_data[:4].hex()))
            continue
        open(dst, "wb").write(bin_data)
        print("OK  头部长度 = %d B，输出 %s  %d B  头=%s"
              % (h, dst, len(bin_data), bin_data[:8].hex()))
        ok = 1
        break
    if not ok:
        # 退而求其次：按 长度差 推算头部
        hdr = len(data) - expect
        if 0 < hdr < 512:
            body = data[hdr: hdr + expect]
            bin_data = swap_words(body)
            open(dst, "wb").write(bin_data)
            print("FALLBACK 头部按长度差推算 = %d B，头=%s" % (hdr, bin_data[:8].hex()))
        else:
            raise SystemExit("无法确定头部长度（bit=%d, 期望=%d）" % (len(data), expect))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
