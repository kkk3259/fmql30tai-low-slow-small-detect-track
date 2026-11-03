# -*- coding: utf-8 -*-
"""Pl2 流式模块回归：编译 iverilog + 跑 vvp + 比对 ref.hex。

用法：python run_sim.py [job ...]
    job 省略 = 全部跑
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

IVERILOG = r'C:\iverilog\bin\iverilog.exe'
VVP = r'C:\iverilog\bin\vvp.exe'
SIM = r'D:\firstharness\repo\pl\sim'
TB = r'D:\firstharness\repo\pl\tb'
RTL = r'D:\firstharness\repo\pl\rtl'

ALL_RTL = ['minmax_tree.v', 'win5.v', 'tophat_5x5_stream.v',
           'cfar_threshold_stream.v',
           'candidate_extract_stream.v', 'ip2_top_stream.v']

JOBS = {
    'tophat':   dict(tb='tb_tophat_stream.v',    rtl=['minmax_tree.v', 'tophat_5x5_stream.v', 'win5.v'],
                     out='output_tophat_stream.hex',  ref='ref_tophat.hex'),
    'cfar64':   dict(tb='tb_cfar_stream.v',      rtl=['cfar_threshold_stream.v'],
                     out='output_cfar_stream.hex',    ref='ref_cfar.hex'),
    'cfar128':  dict(tb='tb_cfar_stream_128.v',  rtl=['cfar_threshold_stream.v'],
                     out='output_cfar_128_stream.hex', ref='ref_cfar_128.hex'),
    'ccl':      dict(tb='tb_ccl_stream.v',       rtl=['candidate_extract_stream.v'],
                     out='output_ccl_stream.hex',     ref='ref_ccl.hex'),
    'chain':    dict(tb='tb_ip2_stream.v',       rtl=ALL_RTL,
                     out='output_integration_stream.hex', ref='ref_integration.hex'),
}


def run(job):
    cfg = JOBS[job]
    srcs = [os.path.join(RTL, f) for f in cfg['rtl']] + [os.path.join(TB, cfg['tb'])]
    vvp = os.path.join(SIM, 'sim_%s.vvp' % job)
    cmd = [IVERILOG, '-o', vvp] + srcs
    def dec(b):
        return (b or b'').decode('gbk', errors='replace')

    r = subprocess.run(cmd, cwd=SIM, capture_output=True)
    if r.returncode != 0:
        print('[%s] 编译失败\n%s' % (job, dec(r.stdout) + dec(r.stderr)))
        return False
    r = subprocess.run([VVP, vvp], cwd=SIM, capture_output=True)
    out = dec(r.stdout) + dec(r.stderr)
    if r.returncode != 0:
        print('[%s] 仿真失败\n%s' % (job, out[-3000:]))
        return False

    tool = [l for l in out.splitlines() if 'WATCHDOG' in l or '收集' in l]
    for l in tool:
        print('   ' + l.strip())

    op = os.path.join(SIM, cfg['out'])
    rp = os.path.join(SIM, cfg['ref'])
    if not os.path.exists(op):
        print('[%s] 缺输出文件 %s' % (job, cfg['out']))
        return False
    got = [int(x, 16) for x in open(op).read().split()]
    exp = [int(x, 16) for x in open(rp).read().split()]
    if len(got) != len(exp):
        print('[%s] 长度不一致 %d vs %d' % (job, len(got), len(exp)))
        return False
    bad = [(i, got[i], exp[i]) for i in range(len(exp)) if got[i] != exp[i]]
    print('[%s] 像素 %d，差异 %d 个' % (job, len(exp), len(bad)))
    if bad:
        print('   前 12 处 (idx, got, exp):', bad[:12])
    return not bad


if __name__ == '__main__':
    jobs = sys.argv[1:] or list(JOBS)
    ok = True
    for j in jobs:
        print('==== %s ====' % j)
        try:
            ok = run(j) and ok
        except Exception as e:
            print('[%s] 异常 %r' % (j, e))
            ok = False
    print('\n总结:', 'ALL PASS' if ok else 'HAS DIFF')
