# patch_cam_demo4.py —— 给预览服务加一个自动刷新的 HTML 页面（/ 返回网页，/live 返回当前帧）
import io

p = r"D:\firstharness\repo\ps\cam_demo.py"
s = io.open(p, encoding="utf-8").read()

PAGE_CONST = '''
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>IP2 实时检测</title>
<style>
body{margin:0;background:#0d0d0d;color:#7CFC00;font:14px/1.5 Consolas,monospace}
#hud{padding:8px 12px;border-bottom:1px solid #24451f;white-space:pre}
img{width:100%;max-width:1280px;display:block;margin:0 auto}
</style></head><body>
<div id="hud">连接中…</div>
<img id="v" src="/live">
<script>
const v = document.getElementById('v'), hud = document.getElementById('hud');
setInterval(function(){ v.src = '/live?t=' + Date.now(); }, 150);
setInterval(function(){
  fetch('/info').then(r=>r.json()).then(function(j){
    var n = (j.cands||[]).length;
    hud.textContent = 'PL 帧率 ' + j.fps + ' fps   |   PL 耗时 ' + j.PL_ms +
                      ' ms   |   候选 ' + n + (n ? '\\n' + JSON.stringify(j.cands) : '');
  }).catch(function(){});
}, 600);
</script></body></html>"""

'''

anchor = "class Handler(BaseHTTPRequestHandler):"
assert anchor in s
s = s.replace(anchor, PAGE_CONST.lstrip("\n") + anchor, 1)

old_get = '''    def do_GET(self):
        if self.path.startswith("/info"):'''
new_get = '''    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/info"):'''
assert old_get in s
s = s.replace(old_get, new_get, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("patched4 OK")
