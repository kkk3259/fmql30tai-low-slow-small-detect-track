import sys
from icraft.xrt import Device

d = Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
r = d.defaultRegRegion()
v = r.read(0x400C0014) & 0xFFFFFFFF
print("VER 0x%08X" % v)
sys.exit(0 if v == 0x00010000 else 1)
