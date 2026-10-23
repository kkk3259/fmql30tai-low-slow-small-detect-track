# U19 (PL_JTAG) 引脚定义与下载器接线

## 来源（权威）
《悟净开发板Lite（轻量版）硬件使用手册V1.0》第 16 页，"4.7 JTAG 接口"原理图
（U19 = PL_JTAG，U18 = PS_JTAG），从该 PDF 内嵌图像导出：
`D:\firstharness\dl\mimg\p16_IM196.jpg`，放大版 `D:\firstharness\dl\mimg\u19_zoom.png`。

## U19 = PL_JTAG（2×10，20 针）引脚定义

| 引脚 | 信号 | 说明 |
|---|---|---|
| 1 | VTref / 3.3V | 板上直接接 VCC3V3，给下载器做参考电压 |
| 3 | NC1 | 空脚（原理图标 ×） |
| 5 | TDI | JTAG 数据输入 |
| 7 | TMS | JTAG 模式选择 |
| 9 | TCK | JTAG 时钟 |
| 11 | NC | 空脚 |
| 13 | TDO | JTAG 数据输出 |
| 15 | RESET | PL 复位（nSRST） |
| 17 | NC2 | 空脚 |
| 19 | NC3 | 空脚 |
| 2 | NC4 | 空脚 |
| 4,6,8,10,12,14,16,18,20 | GND | 全部接地（9 个脚并联到板地） |

奇数列（丝印 "1" 那一列，从 1 那一端往下）：1,3,5,7,9,11,13,15,17,19
偶数列（丝印 "2" 那一列，同端往下）：2,4,6,8,10,12,14,16,18,20

## Xilinx Platform Cable USB II (DLC10) 飞线接法

DLC10 8 孔 2.5mm 连接器（JTAG 模式：孔 8 = HALT，JTAG 不用）：
孔 1 = VREF、孔 2 = TMS、孔 3 = TCK、孔 4 = TDO、孔 5 = TDI、孔 6 = GND、孔 7 = GND。

| DLC10 | U19 引脚 |
|---|---|
| VREF | 1 |
| TDI | 5 |
| TMS | 7 |
| TCK | 9 |
| TDO | 13 |
| GND | 4（或任一 GND 脚） |
| GND | 6（或任一 GND 脚） |
| RESET（可不接） | 15 |

## 注意事项
1. **绝不能**接到 2、3、11、17、19（NC，原理图上是悬空脚）。
2. 板上必须**先上电**（12V → J37 → SW8 拨 ON，电源灯亮），U19 的 1 脚才会有 3.3V 参考电压；断电时下载器识别不到目标。
3. 不要在通电状态下插拔杜邦线。
4. 上电顺序：先接线 → 再给板上电 → 再插 USB 到电脑 → Procise 里 Connect to board。
5. RESET（15 脚）先不接，只接 7 根（VREF/TDI/TMS/TCK/TDO/GND/GND）即可下载。
