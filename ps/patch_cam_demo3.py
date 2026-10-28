# patch_cam_demo3.py —— 把 udmabuf 的同步范围收窄到实际用到的 NPIX 字节
#   原因：sync_for_device 默认按 128 MiB 整块清 cache，实测每帧吃掉 ~20 ms。
#   把 sync_offset/sync_size 一次性设成 0 / 230400，每帧只清 225 KB。
import io

p = r"D:\firstharness\repo\ps\cam_demo.py"
s = io.open(p, encoding="utf-8").read()

old = """        self.reg = MM.mmap(self.rfd, 0x1000, MM.MAP_SHARED, offset=REG)"""
new = """        self.reg = MM.mmap(self.rfd, 0x1000, MM.MAP_SHARED, offset=REG)
        # 只同步真正用到的 640x360 字节，避免每帧清 128 MiB cache（实测可省 ~20 ms）
        try:
            sysfs("sync_offset", 0)
            sysfs("sync_size", NPIX)
        except Exception as e:
            print("WARN: 设置 sync_size 失败: %s" % e)"""
assert old in s
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("patched3 OK")
