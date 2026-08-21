"""简历库：一个文件夹，装所有能往外发的简历 PDF。

用户 2026-08-16 提、2026-08-21 明确：「我可以自己把导出的简历、自己在其他地方做的
简历放在系统里同一个文件夹下，这样方便管理。系统里所有需要用到简历的地方都可以
选择用这里的哪些简历。」

**模型变了**：旧的是「PDF 是某份可编辑简历的派生物」——文件名里带 slug，
`latest_export_for_slug` 靠 `_{slug}_` 找，所以**外来 PDF 结构上永远选不中**。
新的是「**PDF 就是简历本身，来源不限**」。可编辑简历（`data/resumes/{slug}.yaml`）
仍然存在，但它退居为**生成器**：导出一次 = 往库里加一份成品。

**为什么另起一个文件夹、不复用 `data/resume_pdfs/exports/`**：那里有
`_prune_exports()`，只留最近 20 个、多的直接 `os.remove`——用户自己放进去的文件
会被系统悄悄吃掉。

**文件夹是"存在与否"的唯一真相，`library.yaml` 只是覆盖层。** 反面教材就在同一天：
`resumes/index.yaml` 里列着两份简历、文件却不在了，列表照样显示，点开是空的。
存在性和元数据分处两地、还以元数据为准，就会出现这种状态。所以这里
**列表 = 扫文件夹**，元数据按文件名 join，孤儿元数据在保存时剪掉。
"""
import os
import re
import time
from typing import Optional

import yaml

# 挑简历的打分权重：跟 `resume_matcher` 同一套规则（标题命中是强信号，JD 是弱信号）。
# **刻意不 import 那个模块**：它按「可编辑简历条目」取字段（items[].target/slug），
# 这里按「库里的文件」取，两边的输入形状不同。共用的是**规则**，不是函数签名——
# 硬套一个函数会逼出一层适配，反而更难读。规则一旦要改，两处一起改。
TITLE_WEIGHT = 3
JD_WEIGHT = 1

_SPLIT = re.compile(r"[\s,，、/|｜;；]+")
_TS = re.compile(r"^(\d{8})_(\d{6})_")


def _keywords(target: str) -> list:
    return [w.strip().lower() for w in _SPLIT.split(target or "") if len(w.strip()) >= 2]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class ResumeLibrary:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.library_dir = os.path.join(data_dir, "resumes", "library")
        self.meta_path = os.path.join(data_dir, "resumes", "library.yaml")

    # ── 存取 ────────────────────────────────────────────────────────────────
    def _load_meta(self) -> dict:
        if not os.path.exists(self.meta_path):
            return {"fallback": "", "items": {}}
        with open(self.meta_path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        items = d.get("items")
        return {"fallback": d.get("fallback") or "",
                "items": items if isinstance(items, dict) else {}}

    def _save_meta(self, meta: dict) -> None:
        os.makedirs(os.path.dirname(self.meta_path), exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)

    def _files(self) -> list:
        if not os.path.isdir(self.library_dir):
            return []
        return sorted(f for f in os.listdir(self.library_dir) if f.lower().endswith(".pdf"))

    def path_of(self, file: str) -> str:
        """库里某个文件的绝对路径。**文件名来自用户和文件夹，不能直接拼路径就用。**"""
        if not file or "/" in file or "\\" in file or ".." in file:
            raise ValueError(f"非法文件名: {file}")
        return os.path.join(self.library_dir, file)

    # ── 列表 ────────────────────────────────────────────────────────────────
    def list(self) -> list:
        """库里所有简历。**以文件夹为准**：文件在就列出来，元数据只是覆盖层。

        没登记过的文件（你直接扔进来的）自动出现，且是最保守的初始状态：
        没有目标岗位（不参与自动匹配）、没勾允许发送（不会被自动发出去）。
        """
        meta = self._load_meta()
        out = []
        for file in self._files():
            m = meta["items"].get(file) or {}
            out.append({
                "file": file,
                "name": m.get("name") or os.path.splitext(file)[0],
                "target": m.get("target") or "",
                "allow_send": bool(m.get("allow_send")),
                "source": m.get("source") or "dropped",
                "slug": m.get("slug") or "",
                "size": os.path.getsize(os.path.join(self.library_dir, file)),
                "added_at": m.get("added_at") or "",
            })
        return out

    def fallback(self) -> str:
        return self._load_meta()["fallback"]

    def set_fallback(self, file: str) -> None:
        meta = self._load_meta()
        meta["fallback"] = file or ""
        self._save_meta(meta)

    def update_meta(self, file: str, name: str = None, target: str = None,
                    allow_send: bool = None, source: str = None,
                    slug: str = None) -> dict:
        if file not in self._files():
            raise KeyError(file)
        meta = self._load_meta()
        it = dict(meta["items"].get(file) or {})
        if name is not None:
            it["name"] = name
        if target is not None:
            it["target"] = target
        if allow_send is not None:
            it["allow_send"] = bool(allow_send)
        if source is not None:
            it["source"] = source
        if slug is not None:
            it["slug"] = slug
        it.setdefault("added_at", _now())
        meta["items"][file] = it
        # 文件没了的元数据顺手剪掉——留着只会让下次"这个名字又出现"时继承一份
        # 来路不明的授权状态（`allow_send` 尤其危险）。
        live = set(self._files())
        meta["items"] = {k: v for k, v in meta["items"].items() if k in live}
        if meta["fallback"] not in live:
            meta["fallback"] = ""
        self._save_meta(meta)
        return it

    def delete(self, file: str) -> None:
        os.remove(self.path_of(file))
        meta = self._load_meta()
        meta["items"].pop(file, None)
        if meta["fallback"] == file:
            meta["fallback"] = ""
        self._save_meta(meta)

    # ── 导出 ────────────────────────────────────────────────────────────────
    def new_export_path(self, name: str, target: str = "", slug: str = "") -> str:
        """给一次导出分配库内路径，并登记元数据。**导出＝往库里加一份成品。**

        文件名带时间戳和 slug：两份同名简历（真实数据里出现过两份「游戏岗版」）
        都导出之后，只靠名字再也分不清谁是谁——而分不清的后果是给 A 岗位发了 B 的简历。

        **仍然默认不允许发送**（用户 2026-08-21 定）：导出是你亲手做的，
        但"准不准自动发出去"是另一次点头。
        """
        os.makedirs(self.library_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name or "resume").strip("_") or "resume"
        parts = [time.strftime("%Y%m%d_%H%M%S")]
        if slug:
            parts.append(slug)
        parts.append(safe)
        file = "_".join(parts) + ".pdf"

        meta = self._load_meta()
        meta["items"][file] = {"name": name or safe, "target": target or "",
                               "allow_send": False, "source": "exported",
                               "slug": slug or "", "added_at": _now()}
        self._save_meta(meta)
        return os.path.join(self.library_dir, file)

    # ── 挑一份发出去 ────────────────────────────────────────────────────────
    def pick(self, job_title: str = "", jd_text: str = "") -> dict:
        """给这个岗位挑一份能发的简历。返回 `{file, name, matched, reason, ...}`。

        **只在勾了「允许发送」的里面挑。** 没勾的连"最匹配的那份"都不该是它——
        否则等于绕过授权，而授权正是用户要的那一层。

        挑不中就用指定的兜底那份；**没指定兜底就返回空**，让调用方拒发。
        宁可不发也不乱发——往企业系统里传错简历是不可撤销的。
        """
        title_l = (job_title or "").lower()
        jd_l = (jd_text or "")[:2000].lower()
        allowed = [i for i in self.list() if i["allow_send"]]

        best = None
        for it in allowed:
            kws = _keywords(it["target"])
            if not kws:
                continue
            hits, score = [], 0
            for kw in kws:
                if kw in title_l:
                    score += TITLE_WEIGHT
                    hits.append(kw)
                elif kw in jd_l:
                    score += JD_WEIGHT
                    hits.append(kw)
            if score <= 0:
                continue
            key = (score, it["added_at"])
            if best is None or key > best[0]:
                best = (key, it, hits)

        if best is not None:
            _, it, hits = best
            return {**it, "matched": True, "score": best[0][0],
                    "reason": f"目标岗位命中 {'/'.join(hits)}"}

        fb = self.fallback()
        fb_item = next((i for i in allowed if i["file"] == fb), None)
        if fb_item is not None:
            return {**fb_item, "matched": False, "score": 0,
                    "reason": "没有简历的目标岗位与之匹配，用指定的兜底那份"}

        return {"file": "", "name": "", "target": "", "allow_send": False,
                "source": "", "slug": "", "size": 0, "added_at": "",
                "matched": False, "score": 0,
                "reason": ("没有匹配的简历，也没有指定兜底的那份——"
                           "去简历库勾一份「允许发送」并设为兜底，或给某一份填上目标岗位")}

    def path_for_name(self, name: str) -> str:
        """按显示名回查 PDF 路径；找不到、没勾允许发送、或**重名**都返回 ""。

        W2 那条链存的是简历名字（`hr_conversations.matched_resume`，聊天页显示
        「建议发 X 版」），发送时按名字回查。

        **重名时拒绝，不猜。** 真实数据里出现过两份都叫「游戏岗版」的——猜错的
        后果是给这个 HR 发了另一份简历。沿用旧 `latest_export_for_slug` 的立场：
        宁可报"没有"让人去确认，也不要赌一把。
        """
        hits = [i for i in self.list() if i["allow_send"] and i["name"] == name]
        return self.path_of(hits[0]["file"]) if len(hits) == 1 else ""

    # ── 新鲜度 ──────────────────────────────────────────────────────────────
    def staleness(self, resume_updated_at: dict) -> dict:
        """每个文件是不是「旧内容」。返回 `{file: 'ready'|'stale'}`。

        `resume_updated_at`: `{slug: updated_at}`，来自可编辑简历的索引。

        **导出的那份，源简历改过之后就是旧内容**——2026-08-16 真机连投三个岗位，
        用的都是比简历最后修改还早 10 分钟的 PDF，而界面上没有任何地方显示这件事。
        换了模型不能把这条判断丢掉。

        **自己放进来的文件没有"源简历"**，无从判断新旧，一律 `ready`——
        它的内容是你自己维护的，系统不该假装知道它过没过时。
        """
        out = {}
        for it in self.list():
            slug = it["slug"]
            exported_at = _ts_from_name(it["file"])
            src = resume_updated_at.get(slug, "") if slug else ""
            out[it["file"]] = ("stale" if (src and exported_at and exported_at < src)
                               else "ready")
        return out


def _ts_from_name(fname: str) -> str:
    """从 `{YYYYMMDD}_{HHMMSS}_...pdf` 取出 `YYYY-MM-DDTHH:MM:SS`，好跟 updated_at 直接比。

    不是这个格式（用户自己放的文件）返回空串——比不了就别比，别猜一个时间出来。
    """
    m = _TS.match(fname)
    if not m:
        return ""
    d, t = m.group(1), m.group(2)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}"
