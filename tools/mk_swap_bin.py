# mk_swap_bin.py —— 把 Vivado 的 .bin 变成复旦微 fpga_manager 认识的“字节交换”版本
#
# 背景（2026-10-28 实测）：
#   `echo xxx.bit > /sys/class/fpga_manager/fpga0/firmware` 会报
#     "Invalid bitstream, could not find a sync word. Bitstream must be a byte swapped .bin file"
#   Vivado `write_bitstream -bin_file` 出的 .bin 头部是
#     FFFFFFFF... 000000BB 11220044 FFFFFFFF... AA995566 ...
#   把**每个 32 位字的 4 个字节顺序颠倒**后（FFFFFFFF... BB000000 44002211 ... 665599AA），
#   同一个驱动就能正常加载，`state` 变成 operating。
#
# 用法：
#   python mk_swap_bin.py <in.bin> [out.bin]
#   默认输出 <in 同目录>/<in 名去掉 .bin>_swap.bin
import os
import sys


def swap_words(data: bytes) -> bytes:
    out = bytearray(len(data) & ~3)
    for i in range(0, len(out), 4):
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
    if len(data) % 4:
        print("警告：文件长度不是 4 的倍数（%d），尾部会丢弃" % len(data))
    out = swap_words(data)
    open(dst, "wb").write(out)
    print("输入 %s (%d B)" % (src, len(data)))
    print("输出 %s (%d B)" % (dst, len(out)))
    print("拷贝到板子：scp %s root@<板子IP>:/lib/firmware/ip2_bd_wrapper.bin" % os.path.basename(dst))
    print("加载：echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main())
