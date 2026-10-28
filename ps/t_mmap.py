import os, mmap
fd = os.open('/dev/udmabuf0', os.O_RDWR)
m = mmap.mmap(fd, 4096)
m[0:16] = b'\x01' * 16
print('4K write ok', bytes(m[0:4]).hex())
m2 = mmap.mmap(fd, 134217728)
m2[0:16] = b'\x02' * 16
print('128M write ok', bytes(m2[0:4]).hex())
m2[230400 - 16:230400] = b'\x03' * 16
print('offset 230400 write ok')
m3 = mmap.mmap(fd, 0x200000, offset=0)
m3[0x140000:0x140010] = b'\x04' * 16
print('result区 write ok')
