
import sys, time
sys.path.insert(0, "/root/ip2")
from icraft.xrt import Device
dev = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
reg = dev.defaultRegRegion()
mem = dev.defaultMemRegion()
REG = 0x400C0000
print("VER", hex(reg.read(REG + 0x14)))
ch = mem.malloc(263168)
import numpy as np
img = np.zeros((360, 640), np.uint8)
for cy, cx, s in ((80,100,6),(100,250,10),(120,400,14),(250,150,18),(260,480,20)):
    pass
ch.write(0, img.tobytes(), img.size)
base = ch.begin.addr()
print("base", hex(base))
reg.write(REG + 0x04, base)
reg.write(REG + 0x08, base)
reg.write(REG + 0x00, 0)
reg.write(REG + 0x00, 1)
for i in range(12):
    st = reg.read(REG + 0x0C) & 0xffffffff
    d  = reg.read(REG + 0x80) & 0xffffffff
    print("t=%2d ms  STATUS=0x%08x done=%d" % (i*10, st, d & 1))
    time.sleep(0.01)
