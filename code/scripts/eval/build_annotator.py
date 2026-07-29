# -*- coding: utf-8 -*-
"""把意图金标 JSONL 渲染成一个本地网页标注器（聊天气泡 + 点选 + 导出）。

痛点：手改 JSONL 读嵌套 messages 太累。本脚本生成一个自包含 HTML，把每条会话渲染成
聊天气泡，点按钮选意图，标完「导出」下载回 intent_golden.jsonl。

⚠️ PII：生成的 HTML 内联真实会话内容 → 落在 gitignore 的 data/eval/，**本地浏览器打开、
勿上传/分享/用 Artifact 发布**。

用法：
    cd code && python scripts/eval/build_annotator.py
    # 然后本地浏览器打开 data/eval/annotate_intents.html（双击即可 / file://）
    # 标完点「导出 JSONL」，把下载的文件覆盖 data/eval/intent_golden.jsonl
    # 再跑 python scripts/eval/run_intent_eval.py
"""
import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent
GOLDEN = CODE_DIR / "data" / "eval" / "intent_golden.jsonl"
OUT = CODE_DIR / "data" / "eval" / "annotate_intents.html"

HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>意图标注</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #0d0d0f; color: #e6e6e8; }
  header { position: sticky; top: 0; z-index: 10; background: #161619;
           border-bottom: 1px solid #2a2a2e; padding: 12px 20px; }
  .bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .prog { font-weight: 600; }
  .prog b { color: #4a9eff; }
  .tabs { display: flex; gap: 6px; }
  .tab { padding: 4px 12px; border-radius: 999px; border: 1px solid #333; cursor: pointer;
         background: #1e1e22; color: #bbb; font-size: 13px; }
  .tab.on { background: #4a9eff; color: #fff; border-color: #4a9eff; }
  .btn { padding: 6px 14px; border-radius: 8px; border: 1px solid #333; cursor: pointer;
         background: #1e1e22; color: #e6e6e8; font-size: 14px; }
  .btn:hover { border-color: #4a9eff; }
  .btn.primary { background: #4a9eff; color: #fff; border-color: #4a9eff; }
  main { max-width: 860px; margin: 0 auto; padding: 20px; }
  .card { background: #161619; border: 1px solid #2a2a2e; border-radius: 14px;
          margin-bottom: 20px; overflow: hidden; }
  .card.unlabeled { border-left: 3px solid #f5a623; }
  .card.done { opacity: 0.62; }
  .chead { display: flex; justify-content: space-between; align-items: baseline;
           padding: 12px 16px; background: #1b1b1f; border-bottom: 1px solid #2a2a2e; font-size: 13px; }
  .chead .co { font-weight: 600; color: #ddd; }
  .chead .sug { color: #888; }
  .thread { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
  .msg { max-width: 76%; padding: 8px 12px; border-radius: 12px; white-space: pre-wrap;
         word-break: break-word; font-size: 14px; }
  .hr { align-self: flex-start; background: #26262b; border-top-left-radius: 3px; }
  .me { align-self: flex-end; background: #234a75; border-top-right-radius: 3px; }
  .sys { align-self: center; background: transparent; color: #7a7a80; font-size: 12px;
         max-width: 90%; text-align: center; }
  .who { font-size: 11px; color: #888; margin-bottom: 2px; }
  .me .who { text-align: right; }
  .choices { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px;
             border-top: 1px solid #2a2a2e; background: #131316; }
  .choice { padding: 6px 14px; border-radius: 999px; border: 1px solid #3a3a40;
            cursor: pointer; background: #1e1e22; color: #ccc; font-size: 13px; user-select: none; }
  .choice:hover { border-color: #4a9eff; }
  .choice.sel { background: #2e7d32; border-color: #2e7d32; color: #fff; font-weight: 600; }
  .choice .en { color: #9aa; font-size: 11px; margin-left: 4px; }
  .choice.sel .en { color: #cfe; }
  footer { position: sticky; bottom: 0; background: #161619; border-top: 1px solid #2a2a2e;
           padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
  .hint { color: #888; font-size: 13px; }
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="prog">已标 <b id="done">0</b> / <span id="total">0</span></span>
    <div class="tabs">
      <span class="tab on" data-f="all">全部</span>
      <span class="tab" data-f="todo">未标注</span>
      <span class="tab" data-f="done">已标注</span>
    </div>
    <span class="hint">点气泡下方的意图即可标注，自动本地暂存</span>
  </div>
</header>
<main id="list"></main>
<footer>
  <button class="btn primary" id="export">导出 intent_golden.jsonl</button>
  <button class="btn" id="copy">复制 JSONL</button>
  <span class="hint" id="status"></span>
  <span class="hint">导出后覆盖 data/eval/intent_golden.jsonl，再跑 run_intent_eval.py</span>
</footer>
<script>
const ROWS = __DATA__;
const INTENTS = [
  ["interview_invite", "面试邀请"],
  ["offer", "录用/谈薪"],
  ["rejection", "委婉拒绝"],
  ["resume_request", "索要简历"],
  ["general_inquiry", "一般询问·需回"],
  ["general_notice", "一般通知·不回"],
  ["unknown", "无法确定"],
];
const LS_KEY = "intent_labels_v1";
const saved = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
// 初始标签：localStorage 优先，其次金标里已填的 human_intent
ROWS.forEach(r => { if (!(r.conv_id in saved) && r.human_intent) saved[r.conv_id] = r.human_intent; });
let filter = "all";

function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function whoLabel(s){ return s === "hr" ? "HR" : s === "me" ? "我" : "系统"; }

function render(){
  const list = document.getElementById("list");
  list.innerHTML = "";
  let doneCount = 0;
  ROWS.forEach(r => {
    const lab = saved[r.conv_id] || "";
    if (lab) doneCount++;
    if (filter === "todo" && lab) return;
    if (filter === "done" && !lab) return;
    const card = document.createElement("div");
    card.className = "card " + (lab ? "done" : "unlabeled");
    const thread = r.messages.map(m => {
      const cls = m.sender === "hr" ? "hr" : m.sender === "me" ? "me" : "sys";
      if (cls === "sys") return `<div class="msg sys">${esc(m.text)}</div>`;
      return `<div class="msg ${cls}"><div class="who">${whoLabel(m.sender)}</div>${esc(m.text)}</div>`;
    }).join("");
    const choices = INTENTS.map(([v, zh]) =>
      `<span class="choice ${lab===v?"sel":""}" data-id="${esc(r.conv_id)}" data-v="${v}">${zh}<span class="en">${v}</span></span>`
    ).join("");
    card.innerHTML =
      `<div class="chead"><span class="co">${esc(r.company) || "（公司未知）"}</span>` +
      `<span class="sug">模型建议: ${esc(r.model_intent)}</span></div>` +
      `<div class="thread">${thread}</div>` +
      `<div class="choices">${choices}</div>`;
    list.appendChild(card);
  });
  document.getElementById("done").textContent = doneCount;
  document.getElementById("total").textContent = ROWS.length;
}

document.getElementById("list").addEventListener("click", e => {
  const c = e.target.closest(".choice");
  if (!c) return;
  const id = c.getAttribute("data-id"), v = c.getAttribute("data-v");
  saved[id] = (saved[id] === v) ? "" : v;   // 再点一次取消
  if (!saved[id]) delete saved[id];
  localStorage.setItem(LS_KEY, JSON.stringify(saved));
  render();
});

document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("on"));
  t.classList.add("on");
  filter = t.getAttribute("data-f");
  render();
}));

function buildJSONL(){
  return ROWS.map(r => {
    const out = Object.assign({}, r, { human_intent: saved[r.conv_id] || "" });
    return JSON.stringify(out);
  }).join("\n") + "\n";
}
document.getElementById("export").addEventListener("click", () => {
  const blob = new Blob([buildJSONL()], { type: "application/x-ndjson" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "intent_golden.jsonl";
  a.click();
  document.getElementById("status").textContent = "已导出 ✓";
});
document.getElementById("copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(buildJSONL());
  document.getElementById("status").textContent = "已复制到剪贴板 ✓";
});

render();
</script>
</body>
</html>
"""


def main() -> int:
    if not GOLDEN.exists():
        print(f"[错误] 金标不存在：{GOLDEN}\n先跑 export_intent_golden.py")
        return 2
    rows = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    data = json.dumps(rows, ensure_ascii=False)
    html = HTML.replace("__DATA__", data)
    OUT.write_text(html, encoding="utf-8")
    print(f"[生成] {OUT}（{len(rows)} 条，{len(html)//1024} KB）")
    print("[打开] 本地浏览器双击打开该 HTML（file://），点选意图即自动本地暂存")
    print("[回填] 标完点「导出 intent_golden.jsonl」→ 覆盖 data/eval/intent_golden.jsonl → 跑 run_intent_eval.py")
    print("[⚠️PII] 该 HTML 含真实会话内容，仅本地打开，勿上传/分享")
    return 0


if __name__ == "__main__":
    sys.exit(main())
