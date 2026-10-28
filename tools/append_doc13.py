# append_doc13.py —— 给 docs/13 追加「十、相机闭环打通」一节
import io, os

p = r"D:\firstharness\repo\docs\13-PL上板进度.md"
if not os.path.exists(p):
    cands = [f for f in os.listdir(r"D:\firstharness\repo\docs") if f.startswith("13")]
    print("找不到，候选:", cands)
    raise SystemExit(1)

sec = """
## 十、2026-10-28 晚：相机 → PL → 候选表 全流程打通

### 10.1 结论（可写进文章/答辩）
- **端到端闭环成立**：USB 相机 640x480(MJPG) → 裁剪 640x360 → DDR 帧缓冲 → PL(IP2) → AXI-Lite 候选表 → 浏览器实时叠加框。
- **实测指标**：PL 单帧 **11.7 ms**（AXI 4 态流程 + 32x64 位突发读 + 5x5/31x31 三级流水 + 4 次 256B 突发回写/寄存器镜像）；整环 **14.9 fps**（瓶颈是 PS 侧 cv2 取图+解码 27 ms，不是 PL）。
- **坐标正确**：寄存器镜像版在板上四组用例全部命中期望坐标（`(100,120)`、`(320,180)`、`(60,300)/(500,60)/(580,340)`、`(100,120)/(400,200)`），此前的 +120 像素整体平移已随帧缓冲 `clr` 修复消失。

### 10.2 本轮修掉的两个真问题
1. **帧缓冲跨帧残留 120 字节**（`ip2_pix_fifo` 无清空口）：导致整帧像素流平移 120，候选 x 全体 +120。修法：给 FIFO 加 `clr` 端口，`F_RST` 前 16 拍清空；`n_bytes` 改 `NPIX+512` 防止最后一包悬空。
2. **候选表用 DDR 传递读不到**：PL 侧 `m_awready/BRESP` 行为与 PS 侧 `mmap` 语义不一致，`/dev/mem` 读 `0x31000000` 恒为 0（写进去的 0xAA 也读不回）。改为 **AXI-Lite 寄存器镜像 36 字节候选表（0x18~0x3C）**，绕开共享内存一致性，实测稳定。

### 10.3 环境坑（都已绕开）
- `udmabuf` 的 `sync_for_device` 默认按 **128 MiB 整块清 cache**，每帧白吃 ~20 ms；把 `sync_offset/sync_size` 收到 `0/230400` 后 PL 侧从 23.5 ms 降到 11.7 ms。
- 板上无 `devmem`、无内核头文件（`/lib/modules/$(uname -r)/build` 不存在），统一用 `/dev/mem` + `mmap` 读写寄存器；`/dev/mem` 映射 `0x30100000` 会 EPERM（STRICT_DEVMEM），只能用 `/dev/udmabuf0` 访问帧缓冲。
- Procise/Vivado 批处理 **不能** `create_bd_cell`（`[filemgmt 56-189] Failed to resolve reference`），必须以 `-mode gui` 跑 `build_bd.tcl`；`open_hw_manager` 在 Vivado 2018.2 batch 里同样不存在，烧板一律走 `xsct`（`D:\\Xilinx\\SDK\\2018.2\\bin\\xsct.bat prog_xsdb.tcl`）。
- 杀板上进程别用 `pkill -f cam_demo.py`：ssh 那条命令自带的命令行里含同样的字面量，会把自己杀掉；用 `pkill -f 'cam_demo[.]py'`。

### 10.4 复现命令
```bash
# 板上
cd /tmp && python3 -u cam_demo.py --port 8080        # 浏览器打开 http://169.254.67.100:8080/
python3 -u read_cand.py                              # 四组坐标自检，期望 VERDICT REG-OK
# PC 侧烧板
D:\\Xilinx\\SDK\\2018.2\\bin\\xsct.bat D:\\firstharness\\synth\\vivado\\prog_xsdb.tcl
```

### 10.5 下一步
- 场景换成**暗背景 + 小亮点**（当前对着白墙/窗帘，检出的都是边缘纹理）；改 IP1 的灰度/阈值参数适配真实道路/远景。
- 相机取图换成 `v4l2 + 零拷贝`（或直接在 PL 侧接 DVP/MIPI），把 27 ms 的 PS 开销压下去。
- `MAX_CAND` 从 5 扩到 64、输出 449 字节（为后级 ROI 468 裁剪用）。
"""

s = io.open(p, encoding="utf-8").read()
if "相机 → PL → 候选表 全流程打通" in s:
    print("已存在，跳过")
else:
    io.open(p, "a", encoding="utf-8").write(sec)
    print("已追加", len(sec), "字符")
