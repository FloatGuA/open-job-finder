"""岗位特化生成（功能二）。

职责：
- 预制模板：`data/resume_templates.yaml`，每个 = {name, keywords[], blocks[{cat,idx}], greeting_style}。
  关键词命中岗位标题/JD → 用该模板的块组合为起点；命中多个取命中词最多的；都不中 → LLM 自动组合。
- 按 JD 生成「组合方案」：从积木库挑选/排序/微调块（不杜撰），产出结构化简历内容。存 `data/resume_plans.yaml`（按 job_id）。
- 招呼语：单独的 LLM 调用生成。
- 渲染：组合方案 → HTML → Chromium CDP `Page.printToPDF` → PDF（不依赖 WeasyPrint/GTK）。

简历与招呼语「分开按需生成」：各自独立的端点/函数，结果都挂在该 job 的 plan 上。
"""
import json
import os
import re
import time
from typing import Optional

import yaml

from services import resume_blocks as rb

TEMPLATES_PATH = "data/resume_templates.yaml"
PLANS_PATH = "data/resume_plans.yaml"


# ── 预制模板 ────────────────────────────────────────────────────────────────
def load_templates(path: str = TEMPLATES_PATH) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data if isinstance(data, list) else []


def save_templates(templates: list, path: str = TEMPLATES_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(templates, f, allow_unicode=True, sort_keys=False)


def match_template(templates: list, job_title: str, jd_text: str = "") -> Optional[dict]:
    """关键词匹配：命中词最多的模板胜出；无命中返回 None。code decides（确定性匹配）。"""
    hay = f"{job_title or ''} {jd_text or ''}".lower()
    best, best_hits = None, 0
    for t in templates:
        kws = t.get("keywords") or []
        hits = sum(1 for kw in kws if str(kw).strip() and str(kw).lower() in hay)
        if hits > best_hits:
            best, best_hits = t, hits
    return best


# ── 组合方案存储（按 job_id）────────────────────────────────────────────────
def load_plans(path: str = PLANS_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_plans(plans: dict, path: str = PLANS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(plans, f, allow_unicode=True, sort_keys=False)


def get_plan(job_id: str, path: str = PLANS_PATH) -> dict:
    return load_plans(path).get(job_id, {})


def _set_plan_part(job_id: str, part_key: str, value, *, job_title: str, company: str, path: str = PLANS_PATH) -> dict:
    plans = load_plans(path)
    plan = plans.get(job_id) or {"job_id": job_id}
    plan["job_title"] = job_title or plan.get("job_title", "")
    plan["company"] = company or plan.get("company", "")
    plan[part_key] = value
    plans[job_id] = plan
    save_plans(plans, path)
    return plan


# ── LLM 生成 ────────────────────────────────────────────────────────────────
def _blocks_digest(doc: dict) -> str:
    """把信息池压成「s{分区}#{块}: [分区名] 标题 | 概括」清单，喂给 LLM 挑块
    （省 token，仍可精确定位到块；v2.16 起吃动态 sections 形状）。"""
    lines = []
    for si, sec in enumerate(doc.get("sections") or []):
        for bi, b in enumerate(sec.get("blocks") or []):
            label = b.get("summary") or b.get("title") or ""
            lines.append(f"s{si}#{bi}: [{sec.get('name','')}] {b.get('title','')} | {label}")
    return "\n".join(lines) or "（信息池为空）"


def generate_composed_sections(pool: dict, job: dict, model_router, prompt_manager) -> list:
    """Agent 组合（v2.16 核心）：按岗位 JD 从信息池挑块+排序，产出简历 sections。

    LLM 只输出「分区名 + 挑中的块 id 列表」（judge），块内容由 code 从池里**复制**
    （不杜撰、不改写）；非法 id 丢弃，空分区丢弃。
    """
    from services.llm_parser import safe_parse_json

    prompt = prompt_manager.render("resume_compose", {
        "job": _job_str(job), "digest": _blocks_digest(pool),
    })
    text, _p = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"sections": list})
    pool_secs = pool.get("sections") or []
    out = []
    for sec in parsed.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        blocks = []
        for pick in sec.get("picks") or []:
            m = re.fullmatch(r"s(\d+)#(\d+)", str(pick).strip())
            if not m:
                continue
            si, bi = int(m.group(1)), int(m.group(2))
            if si < len(pool_secs) and bi < len(pool_secs[si].get("blocks") or []):
                blocks.append(dict(pool_secs[si]["blocks"][bi]))
        if blocks:
            name = str(sec.get("name", "")).strip() or "经历"
            out.append({"name": name, "blocks": blocks})
    return out


# 简历 / 招呼语生成 prompt 已迁入 prompts/resume_tailor.md、resume_greeting.md
# （走 PromptManager，可在前端编辑；替代原内联字符串——原 .format 会被 JSON schema 的裸花括号打断）。


def _job_str(job: dict) -> str:
    parts = [job.get("title", ""), job.get("company", "")]
    jd = (job.get("jd_text") or "").strip()
    s = " / ".join([p for p in parts if p])
    if jd:
        s += f"\nJD: {jd[:1200]}"
    return s or "（未知岗位）"


def generate_resume_sections(blocks: dict, job: dict, template: Optional[dict], model_router, prompt_manager) -> dict:
    """生成简历组合方案（sections）。template 命中则作为起点提示，LLM 再按 JD 微调。"""
    from services.llm_parser import safe_parse_json

    hint = ""
    if template:
        hint = (
            f"已匹配预制模板「{template.get('name','')}」，其建议块组合为 "
            f"{template.get('blocks')}；请以此为起点，再按岗位微调。\n"
        )
    prompt = prompt_manager.render("resume_tailor", {
        "template_hint": hint, "job": _job_str(job), "digest": _blocks_digest(blocks),
    })
    text, _p = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"sections": list})
    sections = []
    for s in parsed.get("sections") or []:
        if not isinstance(s, dict):
            continue
        sections.append({
            "category": str(s.get("category", "")),
            "title": str(s.get("title", "")),
            "time": str(s.get("time", "")),
            "bullets": [str(b) for b in (s.get("bullets") or []) if str(b).strip()],
        })
    return {
        "template_used": (template or {}).get("name", ""),
        "sections": sections,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def generate_greeting(blocks: dict, job: dict, template: Optional[dict], model_router, prompt_manager) -> dict:
    hint = ""
    if template and template.get("greeting_style"):
        hint = f"招呼语风格参考：{template['greeting_style']}\n"
    prompt = prompt_manager.render("resume_greeting", {
        "template_hint": hint, "job": _job_str(job), "digest": _blocks_digest(blocks),
    })
    text, _p = model_router.complete(prompt=prompt, capability="balanced")
    return {"text": (text or "").strip(), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ── 渲染：组合方案 → HTML → PDF（Chromium CDP）──────────────────────────────
def render_resume_html(basic_info: dict, sections: list) -> str:
    """把组合方案拼成一份简洁的简历 HTML（自包含样式，便于 Chromium 打印）。"""
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    bi = basic_info or {}
    contact = " · ".join([esc(bi.get(k, "")) for k in ("phone", "email", "city") if bi.get(k)])
    head_line2 = " · ".join([esc(bi.get(k, "")) for k in ("degree", "target_title") if bi.get(k)])
    secs_html = []
    for s in sections or []:
        bullets = "".join(f"<li>{esc(b)}</li>" for b in (s.get("bullets") or []))
        title = esc(s.get("title", ""))
        tm = esc(s.get("time", ""))
        secs_html.append(
            f'<div class="entry"><div class="entry-head"><span class="etitle">{title}</span>'
            f'<span class="etime">{tm}</span></div><ul>{bullets}</ul></div>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; color: #1a1a1a; font-size: 12px; line-height: 1.5; }}
h1 {{ font-size: 22px; margin: 0 0 2px; }}
.contact {{ color: #555; font-size: 11px; margin-bottom: 14px; }}
.entry {{ margin-bottom: 12px; }}
.entry-head {{ display: flex; justify-content: space-between; font-weight: 600; }}
.etime {{ color: #777; font-weight: 400; }}
ul {{ margin: 4px 0 0; padding-left: 18px; }}
li {{ margin-bottom: 2px; }}
</style></head><body>
<h1>{esc(bi.get('name',''))}</h1>
<div class="contact">{contact}{(' · ' + head_line2) if (contact and head_line2) else head_line2}</div>
{''.join(secs_html)}
</body></html>"""


def render_html_to_pdf(html: str, out_path: str, port: int = 9920) -> str:
    """用一次性无头 Chromium 把 HTML 渲染成 PDF（CDP Page.printToPDF）。

    复用项目已有的 DrissionPage/Chromium，避开 WeasyPrint 的 GTK 系统依赖。
    用独立调试端口 + 临时 profile，绝不碰 Boss 登录浏览器。
    """
    import base64

    from DrissionPage import ChromiumPage, ChromiumOptions

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    html_path = os.path.abspath(out_path + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    co = ChromiumOptions().headless(True)
    co.set_local_port(port)
    co.set_argument("--hide-scrollbars")
    page = ChromiumPage(co)
    try:
        page.get("file:///" + html_path.replace("\\", "/"))
        time.sleep(1.0)
        res = page.run_cdp("Page.printToPDF", printBackground=True)
        data = base64.b64decode(res["data"])
        with open(out_path, "wb") as f:
            f.write(data)
    finally:
        try:
            page.quit()
        except Exception:
            pass
        try:
            os.remove(html_path)
        except Exception:
            pass
    return os.path.abspath(out_path)
