#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import icraft.xrt as xrt

REG = 0x400C0000
W, H = 640, 360

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "zg330://0"
    dev = xrt.Device.Open(url)
    print("[0] device opened, type =", type(dev).__name__)

    reg = dev.defaultRegRegion()
    try:
        v = reg.read(REG + 0x14)
    except Exception as e:
        print("readReg fail:", e)
        return 1
    print("[1] VERSION = 0x%08x" % (v & 0xffffffff))

    mem = dev.defaultMemRegion()
    print("[2] memregion =", type(mem).__name__)
    try:
        chunk = mem.malloc(W * H, False, 64)
    except TypeError:
        chunk = mem.malloc(W * H)
    print("[3] chunk =", type(chunk).__name__)
    for name in ("getMemPtr", "memPtr", "ptr"):
        if hasattr(chunk, name):
            p = getattr(chunk, name)
            p = p() if callable(p) else p
            try:
                base = p.addr()
            except Exception:
                base = None
            print("    %s -> %s addr=0x%x" % (name, type(p).__name__, base or 0))
            if base:
                break
    return 0

if __name__ == "__main__":
    sys.exit(main())
