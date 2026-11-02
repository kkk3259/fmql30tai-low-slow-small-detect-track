# -*- coding: utf-8 -*-
"""三域版网页模板 —— 直接取自独立版 cam_pipe.py 的 PAGE，保证两套界面一致。

独立成文件的目的：cam3d_pipe.py 常被多人同时改，PAGE 单独放这里可以避免合并冲突。
本文件不含任何逻辑，只有一个字符串常量。
"""

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>低小慢目标检测 · 三域 PL+NPU</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b1119;color:#cfe0f0;font:13px/1.55 -apple-system,"Segoe UI",Consolas,monospace}
.top{display:flex;align-items:center;gap:12px;padding:9px 16px;background:#101a26;border-bottom:1px solid #1e2c3d}
.top h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.3px}
.badge{padding:2px 9px;border-radius:10px;font-size:11px;background:#12352a;color:#4ade80;border:1px solid #1c5c43}
.badge.b2{background:#1a2433;color:#7fb3d5;border-color:#2a3d52}
.wrap{display:flex;height:calc(100vh - 46px)}
.video{flex:1;position:relative;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:14px}
.vbox{position:relative;width:100%;max-width:100%;aspect-ratio:16/9;margin:auto}
.vbox img{display:block;width:100%;height:100%;object-fit:fill}
.vbox canvas{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
.panel{width:360px;flex:none;background:#0e1723;border-left:1px solid #1e2c3d;overflow-y:auto;padding:12px}
.card{background:#111c29;border:1px solid #1e2c3d;border-radius:7px;padding:11px;margin-bottom:11px}
.card h2{font-size:11px;margin:0 0 9px;color:#6d879e;font-weight:600;letter-spacing:.6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.m label{display:block;font-size:10px;color:#6d879e;margin-bottom:2px}
.m b{font-size:17px;font-family:Consolas,monospace;color:#4ade80;font-weight:600}
.m.b b{color:#60a5fa}
.ctl{margin-bottom:11px}
.ctl label{display:flex;justify-content:space-between;font-size:11px;color:#8ea6bd;margin-bottom:5px}
.ctl b{color:#facc15;font-family:Consolas,monospace}
input[type=range]{width:100%;height:4px;-webkit-appearance:none;background:#22303f;border-radius:2px;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:13px;height:13px;border-radius:50%;background:#38bdf8;cursor:pointer}
.sw{display:flex;align-items:center;gap:6px;font-size:11.5px;color:#8ea6bd;margin-bottom:6px;cursor:pointer}
.btnrow{display:flex;gap:7px;margin-top:9px}
button{flex:1;padding:7px;background:#1a2836;color:#cfe0f0;border:1px solid #2a3d52;border-radius:5px;cursor:pointer;font-size:11.5px}
button:hover{background:#22344a}
button.rec{background:#3a1520;border-color:#6b2130;color:#f87171}
table{width:100%;border-collapse:collapse;font-size:11px;font-family:Consolas,monospace}
th{color:#5f7891;text-align:left;font-weight:500;padding:3px 4px;border-bottom:1px solid #1e2c3d;font-size:10px}
td{padding:2.5px 4px;border-bottom:1px solid #16212e;color:#9fb6cb}
td.hi{color:#4ade80}
canvas.chart{width:100%;height:74px;display:block}
</style></head><body>
<div class="top">
  <h1>低小慢目标智能检测 · 三域（PL + NPU）</h1>
  <span class="badge" id="st">运行中</span>
  <span class="badge b2" id="bk">pl · 0x43C00000</span>
</div>
<div class="wrap">
  <div class="video"><div class="vbox" id="vbox">
    <img id="vs" src="/stream">
    <canvas id="ov" width="640" height="360"></canvas>
  </div></div>
  <div class="panel">
    <div class="card">
      <h2>实时指标</h2>
      <div class="grid2">
        <div class="m"><label>端到端帧率</label><b id="m_fps">--</b></div>
        <div class="m b"><label>PL 单帧</label><b id="m_pl">--</b></div>
        <div class="m"><label>采集耗时</label><b id="m_cap">--</b></div>
        <div class="m b"><label>编码耗时</label><b id="m_enc">--</b></div>
        <div class="m"><label>候选 / 稳定</label><b id="m_cand">--</b></div>
        <div class="m b"><label>端到端时延</label><b id="m_lat">--</b></div>
      </div>
    </div>
    <div class="card">
      <h2>检测参数（三档）</h2>
      <div class="ctl"><label>灵敏度 <b id="l_sens">中</b></label>
        <input type="range" id="s_sens" min="0" max="2" step="1" value="1"></div>
      
      <div class="ctl"><label>场景 <b id="l_scene">室内亮目标</b></label>
        <input type="range" id="s_scene" min="0" max="2" step="1" value="1"></div>
      <div class="btnrow"><button id="b_snap">截图保存</button></div>
      <div class="ctl" style="margin-top:8px">
        <label><input type="checkbox" id="c_pl" checked> 显示 PL 疑似目标（灰细框）</label></div>
      <div style="font-size:10.5px;color:#5a6f85;margin-top:8px;line-height:1.5">
        <b>绿框</b> = 已确认目标（连续 ≥2 帧都出现，稳定）　<b>红框</b> = 疑似目标（只出现 1 帧，可能是噪声，会自己消失）<br>滑条只影响网页显示，不改变板子里的 CFAR 门限。</div>
    </div>
    <div class="card">
      <h2>耗时曲线（近 60 帧）</h2>
      <canvas class="chart" id="chart" width="660" height="148"></canvas>
    </div>
    <div class="card">
      <h2>目标列表</h2>
      <table><thead><tr><th>ID</th><th>X</th><th>Y</th><th>面积</th><th>峰值</th><th>速度</th><th>判为无人机</th></tr></thead>
      <tbody id="tb"><tr><td colspan="7" style="color:#5a6f85">等待数据…</td></tr></tbody></table>
    </div>
  </div>
</div>
<script>
var PK=0, MAXN=64, MINH=0, ALL=false, TRAIL=true, PLBOX=true;
var hist=[];
function $(id){var e=document.getElementById(id);if(e)return e;return {value:'0',checked:false,textContent:'',innerHTML:'',style:{},addEventListener:function(){},appendChild:function(){}};}
['s_pk','s_n','s_h'].forEach(function(id){
  $(id).addEventListener('input',function(){
    PK=+0; MAXN=+64; MINH=+0;
          draw();
  });
});
$('c_all').addEventListener('change',function(){ALL=this.checked;draw()});
$('c_pl').addEventListener('change',function(){PLBOX=this.checked;draw()});
$('c_tr').addEventListener('change',function(){TRAIL=this.checked;draw()});
$('c_inv').addEventListener('change',function(){
  fetch('/set?invert='+(this.checked?1:0)).catch(function(){});
});
$('b_snap').addEventListener('click',function(){
  var a=document.createElement('a'); a.href='/snap?q=95';
  a.download='snap_'+Date.now()+'.jpg'; a.click();
});
var last=[];
function filt(cs){
  if(!PLBOX) cs=cs.filter(function(c){ return !c.pl; });
  var out=cs.filter(function(c){ return ALL || (c.peak||0)>=PK; });
  out=out.filter(function(c){ return (c.hits||0)>=MINH; });
  // 同一目标多条航迹：按 p 降序，中心距过近的只留最强的那条
  out.sort(function(a,b){return (b.p||0)-(a.p||0)});
  var uni=[];
  out.forEach(function(c){
    var r=Math.max(26, 2.2*Math.sqrt(Math.max(c.area||4,4)));
    var dup=uni.some(function(q){
      var dx=c.x-q.x, dy=c.y-q.y;
      return Math.sqrt(dx*dx+dy*dy) < r;
    });
    if(!dup) uni.push(c);
  });
  uni.sort(function(a,b){return (b.peak||0)-(a.peak||0)});
  return uni.slice(0,MAXN);
}
var LASTJ=null;
function draw(){
  var cv=$('ov'), g=cv.getContext('2d');
  g.clearRect(0,0,cv.width,cv.height);
  var sel=filt(last);
  // HUD drawn by canvas (vector text, stays sharp at any zoom)
  if(LASTJ){
    g.save(); g.fillStyle='#ffe066'; g.font='bold 13px Consolas'; g.textBaseline='top';
    var pl=(Number(LASTJ.PL_ms)||0).toFixed(1);
    var np=(Number(LASTJ.npu_ms)||0).toFixed(1);
    var _f=Number(LASTJ.fps||0); var _fs=(_f>=2)?Math.round(_f):'--';
  var hud='PL '+pl+'ms   npu '+np+'ms   cand '+(LASTJ.n||0)+'   '+_fs+' fps';
    g.fillText(hud, 6, 5);
    g.restore();
  }
  g.lineWidth=2; g.font='bold 12px Consolas'; g.textBaseline='bottom';
  sel.forEach(function(c){
    var a=Math.max(c.area||4,1), d=Math.max(3,Math.round(2*Math.sqrt(a/Math.PI))*2);
    if(d>140) return;                       // huge box = edge ring of a big object, skip
    var x=c.x-d/2, y=c.y-d/2;
    var isTrk=(c.hits||0)>=2;               // seen >=2 frames
    var p=(c.p===null||c.p===undefined)?null:Number(c.p);
    if(c.pl||!c.p){                           // PL 候选（NPU 未判）：淡灰细线，不写字
      g.lineWidth=1; g.strokeStyle='rgba(200,200,200,0.55)';
      g.strokeRect(x,y,d,d);
      return;
    }
    g.lineWidth=2;
    var col=(p>=0.5)?'#22e06a':(isTrk?'#ff9a2e':'#ff5a4d');
    g.strokeStyle=col;                      // green=drone, orange=track not drone, red=1-frame
    g.strokeRect(x,y,d,d);
    if(isTrk){
      g.fillStyle=col;
      var tag=Math.round(d)+'px';
      if(p!==null) tag+=' '+(p*100).toFixed(0)+'%';
      g.fillText(tag, x, y-2);
    }
  });
  return sel;
}
function chart(){
  var cv=$('chart'), g=cv.getContext('2d');
  var w=cv.width,h=cv.height; g.clearRect(0,0,w,h);
  if(hist.length<2) return;
  var mx=Math.max.apply(null,hist)*1.15||1;
  g.strokeStyle='#38bdf8'; g.lineWidth=1.5; g.beginPath();
  hist.forEach(function(v,i){
    var x=i/(hist.length-1)*w, y=h-4-(v/mx)*(h-12);
    i?g.lineTo(x,y):g.moveTo(x,y);
  });
  g.stroke();
  g.fillStyle='#5f7891'; g.font='10px Consolas';
  g.fillText(mx.toFixed(1)+' ms', 4, 11);
}
try{ $('vs').style.imageRendering='pixelated'; }catch(e){}
try{ $('ov').style.imageRendering='pixelated'; }catch(e){}   // overlay canvas 同样不做插值，框线不糊
setInterval(function(){
  fetch('/info').then(function(r){return r.json()}).then(function(j){
    LASTJ=j; var cs=j.cands||[];
    last=cs;
    $('m_fps').textContent=(j.fps||0).toFixed(1);
    $('m_pl').textContent=(j.PL_ms||0).toFixed(2)+' ms';
    $('m_cap').textContent=(j.cap_ms||0).toFixed(1)+' ms';
    $('m_enc').textContent=(j.enc_ms||0).toFixed(1)+' ms';
    $('m_cand').textContent=(j.raw||cs.length)+' / '+(j.stable||cs.length);
    $('m_lat').textContent=(j.lat_ms||0).toFixed(0)+' ms';
    var sel=draw();
    hist.push(j.PL_ms||0); if(hist.length>60) hist.shift();
    chart();
    var tb=$('tb');
    if(!sel.length){ tb.innerHTML='<tr><td colspan="7" style="color:#5a6f85">无候选通过当前筛选</td></tr>'; return; }
    tb.innerHTML=sel.map(function(c){
      var d=Math.max(3,Math.round(2*Math.sqrt(Math.max(c.area||4,1)/Math.PI))*2);
      var p=c.p, vt='—', vs='color:#5a6f85';
      if(p!==null&&p!==undefined&&p>=0){ vt=(p*100).toFixed(0)+'%'; vs=(p>=0.5?'color:#3ddc84;font-weight:600':'color:#ffa726'); }
      return '<tr><td class="hi">'+c.id+'</td><td>'+c.x+'</td><td>'+c.y+'</td><td>'
        +d+'px</td><td>'+(c.peak||0)+'</td><td>'+(c.spd||0).toFixed(0)+'</td><td style="'+vs+'">'+vt+'</td></tr>';
    }).join('');
  }).catch(function(){ $('st').textContent='连接中断'; });
}, 400);
</script>

<script>
(function(){
  var N1=["保守","中","激进"], N2=["只看小目标","自动","兼顾大目标"], N3=["室内亮目标","逆光暗目标","混合(拉伸)"];
  var a=document.getElementById('s_sens'), b=document.getElementById('s_size'), c=document.getElementById('s_scene');
  function lab(){ document.getElementById('l_sens').textContent=N1[+a.value];
                                      document.getElementById('l_scene').textContent=N3[+c.value]; }
  function push(){ lab(); var u='/set?sens='+a.value+'&scene='+c.value; if(b){u+='&size='+b.value;} fetch(u).catch(function(){}); }
  [a,b,c].forEach(function(e){ if(!e){return;} e.addEventListener('input',lab); e.addEventListener('change',push); });
  lab();
})();
</script>
</body></html>"""
