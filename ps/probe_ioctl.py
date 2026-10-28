#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# probe_ioctl.py —— 探测 u-dma-buf 3.2.5 支持哪个 sync ioctl
import os, fcntl, ctypes, struct

fd = os.open("/dev/udmabuf0", os.O_RDWR)

CAND = [
    ("UDMABUF_IOCTL_SYNC (24B, nr0)", 0x40187500, 24),
    ("DMA_BUF_IOCTL_SYNC (8B, nr0)", 0x40086200, 8),
    ("DMA_BUF_IOCTL_SYNC (8B, nr2)", 0x40086202, 8),
    ("IOC 8B type 'u' nr0", 0x40087500, 8),
    ("IOC 8B type 'u' nr1", 0x40087501, 8),
    ("IOC 8B type 'u' nr2", 0x40087502, 8),
    ("IOC 8B type 'u' nr3", 0x40087503, 8),
    ("IOC 24B type 'u' nr1", 0x40187501, 24),
    ("IOC 24B type 'u' nr2", 0x40187502, 24),
]

for name, cmd, size in CAND:
    if size == 24:
        payload = struct.pack("<QQQ", 1 | (1 << 2), 0, 640 * 360)
    else:
        payload = struct.pack("<Q", 1)      # START|WRITE
    buf = ctypes.create_string_buffer(payload, size)
    try:
        fcntl.ioctl(fd, cmd, buf)
        print("OK    %s  cmd=0x%08X" % (name, cmd))
    except OSError as e:
        print("fail  %-34s cmd=0x%08X  errno=%d %s" % (name, cmd, e.errno, e.strerror))

os.close(fd)
