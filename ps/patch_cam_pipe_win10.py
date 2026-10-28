# patch_cam_pipe_win10.py —— cam_pipe 候选表窗口改到 0x10（写索引 / 读数据）
import io
p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace("R_CIDX = 0x40             # 写：候选表字索引（0..112）",
              "R_CIDX = 0x10             # 写：候选表字索引（0..112）；读同一地址返回该字")
s = s.replace("R_CDAT = 0x44             # 读：该字", "R_CDAT = 0x10             # 读：该字（与索引同地址）")
s = s.replace("R_HAND = 0x20             # 读：{thv[17:8], cfv[17:8], 2'b10} 握手探针",
              "R_HAND = 0x3C             # 读：状态字镜像（原握手探针槽位已改）")
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("cam_pipe patched to window 0x10")
