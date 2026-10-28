# append_doc13c.py —— 追加「10.6 板上自加载位流 + 开机自启」一节
import io, os

d = r"D:\firstharness\repo\docs"
name = [f for f in os.listdir(d) if f.startswith("13-") and f.endswith(".md")][0]
p = os.path.join(d, name)

sec = """
### 10.6 板上自己加载位流（不再需要 Vivado/xsct）

**结论：`fpga_manager` 能用，但要“字节交换”的 .bin。**

```bash
# PC 侧：从 impl_1 直接出 .bin，再按 32 位字做字节交换
#   write_bitstream -force -bin_file ip2_bd_wrapper     （在 open_run impl_1 之后）
python tools/mk_swap_bin.py ip2_bd_wrapper.bin          # 产出 ip2_bd_wrapper_swap.bin

# 板上：
scp ip2_bd_wrapper_swap.bin root@<板子IP>:/lib/firmware/ip2_bd_wrapper.bin
echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware
cat /sys/class/fpga_manager/fpga0/state        # 期望 operating
```

踩坑记录（都实测过）：
| 喂进去的文件 | 结果 |
|---|---|
| `ip2_bd_wrapper.bit`（Vivado 原始位流，带头） | `Invalid bitstream, could not find a sync word` |
| `ip2_bd_wrapper.bin`（`-bin_file` 出的，头部 `FFFFFFFF…000000BB 11220044…AA995566`） | 同样报 sync word 错 |
| **每 4 字节倒序后的 .bin**（`FFFFFFFF…BB000000 44002211…665599AA`） | **成功，state=operating**，`read_cand.py` 仍然 `VERDICT REG-OK` |

**开机自启**：`/etc/init.d/ip2demo`（源文件在仓库 `pl/ps` 同级的 `ps/ip2demo.initd`）做两件事——先 `echo ip2_bd_wrapper.bin > fpga_manager/firmware` 配 PL，再 `setsid nohup python3 -u cam_demo.py --port 8080` 起预览服务，日志写 `/var/log/ip2demo.log`。

```bash
update-rc.d ip2demo defaults        # 注册开机自启（已执行）
/etc/init.d/ip2demo start           # 手动起一次
/etc/init.d/ip2demo stop|restart|status
```

于是“上电 → 浏览器打开 `http://169.254.67.100:8080/` → 看到实时框”整条链不再依赖 PC 侧任何工具。
"""

s = io.open(p, encoding="utf-8").read()
if "板上自己加载位流" in s:
    print("already")
else:
    io.open(p, "a", encoding="utf-8").write(sec)
    print("appended", len(sec))
