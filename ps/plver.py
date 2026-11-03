import mmap, os, sys
try:
    f = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=0x400C0000)
    print("%08X" % int.from_bytes(m[0x14:0x18], 'little'))
except Exception:
    print("00000000")
