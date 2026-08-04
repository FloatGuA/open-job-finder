// \u7b80\u5386 HTML \u6e32\u67d3\uff08\u7eaf\u51fd\u6570\uff09\u2014\u2014\u9884\u89c8 iframe \u4e0e\u5bfc\u51fa PDF \u540c\u6e90\uff0c\u62bd\u5230\u8fd9\u91cc\u4ee5\u4fbf\u5355\u6d4b\u3002
import { type ResumeBlocks } from '@/api'

// \u5b57\u6bb5\u7ea7\u5bcc\u6587\u672c\uff1a\u53ea\u5728\u7528\u6237\u663e\u5f0f\u6253\u5f00\u65f6\u624d\u8f93\u51fa inline style\uff0c\u5426\u5219\u4ec0\u4e48\u90fd\u4e0d\u5199\uff0c
// \u6a21\u677f\u9884\u8bbe\uff08CSS \u91cc\u7684\u7c97\u4f53/\u7070\u8272\u7b49\uff09\u7ee7\u7eed\u751f\u6548\u2014\u2014\u8001\u6570\u636e\u4e0e AI \u751f\u6210\u7684\u90fd\u8d70\u9884\u8bbe\u3002
export function styleAttr(marks?: { bold?: boolean; italic?: boolean; underline?: boolean }): string {
  if (!marks) return ''
  const css: string[] = []
  if (marks.bold) css.push('font-weight:700')
  if (marks.italic) css.push('font-style:italic')
  if (marks.underline) css.push('text-decoration:underline')
  return css.length ? ` style="${css.join(';')}"` : ''
}

export const escHtml = (s: string) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export function buildResumeHtml(doc: ResumeBlocks): string {
  const bi = doc.basic_info
  const contact = [bi.email, bi.phone, bi.city].filter(Boolean).map(escHtml).join('<span class="sep">\u00b7</span>')
  const secs = (doc.sections || []).map((sec) => {
    const list = (sec.blocks || []).filter((b) => b.title || b.bullets.some((x) => x.trim()))
    // \u53ea\u8981\u5206\u533a\u6709\u540d\u5b57\u5c31\u6e32\u67d3\u6807\u9898\uff1a\u6240\u89c1\u5373\u6240\u5f97\uff0c\u65b0\u5efa\u5206\u533a/\u6e05\u7a7a\u6761\u76ee\u540e\u9884\u89c8\u8981\u7acb\u523b\u6709\u53cd\u9988\uff1b
    // \u4e0d\u60f3\u8981\u7684\u7a7a\u5206\u533a\u5220\u6389\u5373\u53ef\u3002\u540d\u5b57\u4e0e\u5185\u5bb9\u90fd\u7a7a\u624d\u6574\u5757\u8df3\u8fc7\u3002
    if (!sec.name.trim() && !list.length) return ''
    const entries = list.map((b) => {
      const st = (f: 'title' | 'time' | 'bullets') => styleAttr(b.style?.[f])
      const bullets = b.bullets.filter((x) => x.trim())
        .map((x) => `<li${st('bullets')}>${escHtml(x)}</li>`).join('')
      const head = `<div class="e-head"><span class="e-title"${st('title')}>${escHtml(b.title)}</span>${b.time ? `<span class="e-date"${st('time')}>${escHtml(b.time)}</span>` : ''}</div>`
      return `<div class="entry">${head}${bullets ? `<ul>${bullets}</ul>` : ''}</div>`
    }).join('')
    return `<div class="section"><div class="s-title">${escHtml(sec.name)}</div>${entries}</div>`
  }).join('')
  return `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size:A4; margin:0; }
* { box-sizing:border-box; }
html,body { margin:0; padding:0; }
body { width:794px; min-height:1123px; padding:46px 56px; background:#fff; color:#1a1a1a;
  font-family: "Microsoft YaHei", "\u5fae\u8f6f\u96c5\u9ed1", "PingFang SC", sans-serif; font-size:14px; line-height:1.52; }
/* \u6807\u9898\u7c7b\u7edf\u4e00\u9ed1\u4f53\u3001\u6b63\u6587\u5fae\u8f6f\u96c5\u9ed1\uff08\u7528\u6237 2026-08-04 \u5b9a\uff09 */
.name, .s-title, .e-title { font-family: SimHei, "\u9ed1\u4f53", "Microsoft YaHei", sans-serif; }
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
