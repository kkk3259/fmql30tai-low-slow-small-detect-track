# BOOT.bin 生成与上板步骤（P 自己动手版）

> 目标：把「我们的位流 + 我们的 PS 配置（GP1 已开）」打成 BOOT.bin，让板子启动后 PS 能读写 PL 寄存器（`0x83C00000`）。
> 结论先说：**不需要 S**。需要的五件东西本地都有，只差 FSBL —— FSBL 自己用 SDK 生成。

## 五件东西在哪

| 东西 | 路径 | 备注 |
|---|---|---|
| **我们的 FSBL.elf** | `D:/firstharness/synth/sdk_ws/ip2_fsbl/Debug/ip2_fsbl.elf` | ⚠️ 需自己生成（见第 2 步）|
| **我们的位流** | `D:/firstharness/repo/handoff/ip2_bd_wrapper.bit`（5,980,026 B）| 已从 hdf 解出 |
| 官方 `bl31.elf` | `D:/firstharness/dl/bootgen/x/BOOT_Gen/bl31.elf` | 官方原件 |
| 官方 `u-boot` | `D:/firstharness/dl/bootgen/x/BOOT_Gen/u-boot` | ELF 头 7F 45 4C 46 |
| 官方 `FSBL...out`、官方位流 | 同目录 | 只用于「阶段①」基线验证 |

三个 bif 已写好（`repo/handoff/bif/`）：

| bif | 内容 | 目的 |
|---|---|---|
| `stage1_official.bif` | 官方 FSBL + 官方 bit | 验证**打包工具链**（不改任何东西，5 分钟）|
| `stage2_ourfsbl_officialbit.bif` | 我们的 FSBL + 官方 bit | 验证**新 FSBL 能不能启动** |
| `stage3_final.bif` | 我们的 FSBL + 我们的 bit | **最终版**，PS 可访问 `0x83C00000` |

> 为什么分三段：谁都没做过，一段一个变量，出错能立刻定位。

## 第 0 步：备份 SD 卡（5 分钟，必须先做）

1. 断电，拔 SD 卡，插读卡器
2. 把**整个卡**复制到 `D:\firstharness\dl\sdcard_backup\`（含 `BOOT.bin`、`Image`、`uEnv.txt`、dtb、分区等）
3. 顺手把卡里原有 `BOOT.bin` 改名成 `BOOT_official.bin` 留一份**在卡上**（不删）
4. 记下卡里文件清单（截图）

出事就恢复：把 `BOOT_official.bin` 改回 `BOOT.bin` 即可。

## 第 1 步：先用阶段①验证打包工具（10 分钟）

这一步不改动任何新东西，只用官方原件打包，确认「打包工具怎么用」。

1. 打开 Procise（GUI，不是 Shell）：开始菜单 → `Start Procise`
2. 在菜单栏找 Create Image（教程原文：「打开 Procise，按下图依次点击 → 单击 Create Image」）
   - 优先看 **Tools** 菜单
   - 也看 File / Project 菜单
3. 选中 `D:\firstharness\repo\handoff\bif\stage1_official.bif`
4. 输出目录填 `D:\firstharness\dl\bootgen\out1`，生成物应是 `BOOT.bin`（约 7 MB）
5. 把这个 `BOOT.bin` 拷到 SD 卡 FAT 分区（覆盖原 BOOT.bin）→ 插卡上电 → 看能不能正常启动

**判断成功**：能 ping 通 / 能 SSH 进去 / 串口有内核日志 → 打包工具用法正确 ✅

如果 Procise 里找不到 Create Image（备选，我们已确认 bootstrap 支持 zynq 架构）：

```powershell
cd D:\firstharness\repo\handoff\bif
& "D:\Xilinx\SDK\2018.2\bin\unwrapped\win64.o\bootgen.exe" `
    -image stage1_official.bif -arch zynq -o D:\firstharness\dl\bootgen\out1\BOOT.bin -w on
```

`-arch zynq` 会覆盖 bif 里的 `arch = fmql`（FMQL30 是 Zynq 同源器件，BOOT.bin 格式一致）。
这一步必须先用阶段①验证：官方原件能启动，才说明这个打包方式被 boot ROM 接受。

## 第 2 步：SDK 生成我们的 FSBL（30 分钟）

1. 双击 `D:\Xilinx\SDK\2018.2\bin\xsdk.bat`
2. Workspace：`D:\firstharness\synth\sdk_ws` → OK（首次会问，新建即可）
3. 菜单 `File → New → Application Project`
4. 填：
   - Project name: `ip2_fsbl`
   - OS Platform: `standalone`
   - Language: `C`
   - Target Hardware: 勾 Create new → Browse 选 `D:\firstharness\repo\handoff\ip2_bd_wrapper.hdf`
   - Processor: `ps7_cortexa9_0`
5. Next → 模板列表里选 `Zynq FSBL` → Finish（自动编译 1~2 分钟）
6. 确认产物存在：`D:\firstharness\synth\sdk_ws\ip2_fsbl\Debug\ip2_fsbl.elf`

**判断成功**：Console 出现 `Build Finished (took ...)` 且 `.elf` 文件存在 ✅
（如果报错说找不到 BSP，勾上 "Use existing platform" 或让它自动建 BSP）

## 第 3 步：打包阶段②、③

按第 1 步同样的方式（Procise Create Image 或 bootgen），依次做：

| 顺序 | bif | 输出 | 上板验证什么 |
|---|---|---|---|
| 2 | `stage2_ourfsbl_officialbit.bif` | `out2\BOOT.bin` | 能启动 → 新 FSBL 没问题 |
| 3 | `stage3_final.bif` | `out3\BOOT.bin` | 能启动 + 能读寄存器 → 成了 |

## 第 4 步：上板验证阶段③

1. 卡里 `BOOT.bin` 换成 `out3\BOOT.bin`
2. 上电，串口（MINI-USB，115200 8N1）看内核启动
3. 进系统后逐条查：

```bash
# ① 位流加载了吗
cat /sys/class/fpga_manager/fpga0/state        # 期望 operating

# ② GP1 通了吗（读 VERSION，偏移 0x14）
sudo devmem 0x83C00014 32                       # 期望 0x00010000

# ③ 正式自检
cd /root  # 或你放脚本的目录
sudo python3 pl_selftest.py
```

三个都过 = AXI 通路打通，接下来就能接相机做闭环。

## 常见问题对照

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 板子完全不启动（串口无输出）| FSBL 不对 / bif 顺序错 | 恢复 `BOOT_official.bin`，用阶段②重试 |
| 能启动，但 `devmem 0x83C00014` 报 Bus error | GP1 没开（FSBL 还是旧的）| 确认 bif 里 bootloader 是**我们的** `ip2_fsbl.elf` |
| 能启动、`state=operating`，但读出来是 0 | 地址错 / BD 没接 | 确认基址 `0x83C00000`（不是 0xA0000000）|
| bootgen 报 unknown arch | bif 头是 `arch = fmql` | 用 `-arch zynq` 覆盖，或改用 Procise Create Image |
| Procise 打包报找不到文件 | bif 里路径分隔符 | 全部用正斜杠 `/`，别用 `\` |

## 一句话总结

阶段① 验证工具→ 阶段② 验证 FSBL → 阶段③ 交付。每步都能单独判断，出问题只回退一步。
