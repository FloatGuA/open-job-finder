// \u7b80\u5386 HTML \u6e32\u67d3\uff08\u7eaf\u51fd\u6570\uff09\u2014\u2014\u9884\u89c8 iframe \u4e0e\u5bfc\u51fa PDF \u540c\u6e90\uff0c\u62bd\u5230\u8fd9\u91cc\u4ee5\u4fbf\u5355\u6d4b\u3002
import { type ResumeBlocks } from '@/api'

export const escHtml = (s: string) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export function buildResumeHtml(doc: ResumeBlocks): string {
  const bi = doc.basic_info
  const contact = [bi.email, bi.phone, bi.city].filter(Boolean).map(escHtml).join('<span class="sep">\u00b7</span>')
  const secs = (doc.sections || []).map((sec) => {
    const list = (sec.blocks || []).filter((b) => b.title || b.bullets.some((x) => x.trim()))
    // 只要分区有名字就渲染标题：所见即所得，新建分区/清空条目后预览要立刻有反馈；
    // 不想要的空分区删掉即可。名字与内容都空才整块跳过。
    if (!sec.name.trim() && !list.length) return ''
    const entries = list.map((b) => {
      const bullets = b.bullets.filter((x) => x.trim()).map((x) => `<li>${escHtml(x)}</li>`).join('')
      const head = `<div class="e-head"><span class="e-title">${escHtml(b.title)}</span>${b.time ? `<span class="e-date">${escHtml(b.time)}</span>` : ''}</div>`
      return `<div class="entry">${head}${bullets ? `<ul>${bullets}</ul>` : ''}</div>`
    }).join('')
    return `<div class="section"><div class="s-title">${escHtml(sec.name)}</div>${entries}</div>`
  }).join('')
  return `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size:A4; margin:0; }
* { box-sizing:border-box; }
html,body { margin:0; padding:0; }
body { width:794px; min-height:1123px; padding:46px 56px; background:#fff; color:#1a1a1a;
  font-family: Georgia, "Times New Roman", "Microsoft YaHei", "PingFang SC", serif; font-size:14px; line-height:1.52; }
.name { text-align:center; font-size:31px; font-weight:700; letter-spacing:2px; margin:0 0 10px; }
.contact { text-align:center; font-size:12.5px; color:#333; margin-bottom:4px; }
.contact .sep { margin:0 10px; color:#c2c2c2; }
.subtitle { text-align:center; font-size:12.5px; color:#555; margin-bottom:4px; }
.section { margin-top:17px; }
.s-title { font-size:15px; font-weight:700; letter-spacing:1px; padding-bottom:4px; margin-bottom:8px; border-bottom:1px solid #1a1a1a; }
.entry { margin-bottom:10px; }
.e-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; }
.e-title { font-weight:700; font-size:14px; }
.e-date { color:#777; font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; }
ul { margin:4px 0 0; padding-left:17px; }
li { margin-bottom:2px; }
</style></head><body>
<div class="name">${escHtml(bi.name)}</div>
${contact ? `<div class="contact">${contact}</div>` : ''}
${bi.target_title ? `<div class="subtitle">${escHtml(bi.target_title)}</div>` : ''}
${secs}
</body></html>`
}
