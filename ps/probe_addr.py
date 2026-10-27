import mmap, os, struct, sys
addr = int(sys.argv[1], 16)
base = addr & ~0xFFF          # 页对齐
off  = addr - base
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
try:
    m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
    val = struct.unpack("<I", m[off:off+4])[0]
    print("0x%08X = 0x%08X" % (addr, val))
    m.close()
finally:
    os.close(fd)
