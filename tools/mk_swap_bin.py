# mk_swap_bin.py —— 把 Vivado 位流变成复旦微 fpga_manager 认识的“字节交换”版本
#
# 背景（2026-10-28 实测）：
#   `echo xxx.bit > /sys/class/fpga_manager/fpga0/firmware` 会报
#     "Invalid bitstream, could not find a sync word. Bitstream must be a byte swapped .bin file"
#   Vivado `write_bitstream -bin_file` 出的 .bin 载荷是
#     FFFFFFFF... 000000BB 11220044 FFFFFFFF... AA995566 ...
#   把**每个 32 位字的 4 个字节顺序颠倒**后（FFFFFFFF... BB000000 44002211 ... 665599AA），
#   同一个驱动就能正常加载，`state` 变成 operating。
#
# 【重要】直接喂 .bit 是不行的：.bit 前面有 ~64 字节文本头
#   （`00 09 0f f0 ... 00 61 00 "ip2_bd_wrapper;UserID=...;Version=2018.2" 00`），
#   必须先把头部剥掉只保留二进制载荷再交换。本脚本会自动识别并剥离。
#
# 用法：
#   python mk_swap_bin.py <in.bit|in.bin> [out.bin]
import os
import sys


def strip_bit_header(data: bytes) -> bytes:
    """如果是 .bit（以 00 09 0f f0 开头），剥掉到第一个 0x00 结尾的文本头。"""
    if not (len(data) > 16 and data[0] == 0x00 and data[1] == 0x09 and data[2] == 0x0F and data[3] == 0xF0):
        return data                      # 已经是原始 .bin
    i = 16
    while i < len(data) and 32 <= data[i] < 127:
        i += 1
    if i < len(data) and data[i] == 0:
        i += 1
    return data[i:]


def swap_words(data: bytes) -> bytes:
    n = len(data) & ~3
    out = bytearray(n)
    for i in range(0, n, 4):
        out[i] = data[i + 3]
        out[i + 1] = data[i + 2]
        out[i + 2] = data[i + 1]
        out[i + 3] = data[i]
    return bytes(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_swap.bin"
    data = open(src, "rb").read()
    pay = strip_bit_header(data)
    if len(data) != len(pay):
        print("检测到 .bit 头：%d B → 载荷 %d B" % (len(data) - len(pay), len(pay)))
    out = swap_words(pay)
    head = " ".join("%02x" % b for b in out[:16])
    open(dst, "wb").write(out)
    print("输入 %s (%d B)" % (src, len(data)))
    print("输出 %s (%d B)" % (dst, len(out)))
    print("交换后前 16 字节：%s" % head)
    if out[:4] != b"\xff\xff\xff\xff":
        print("警告：前 4 字节不是 FF FF FF FF，可能不是合法位流载荷")
    print("拷贝：scp %s root@<板子IP>:/lib/firmware/ip2_bd_wrapper.bin" % os.path.basename(dst))
    print("加载：echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main())
