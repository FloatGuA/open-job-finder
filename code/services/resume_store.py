"""多份简历管理 + 导出 PDF 存档（简历制作台 v2.15）。

存储模型（用户定：每份独立完整，FlowCV 式）：
- data/resumes/index.yaml  → {active: slug, items: [{slug, name, target, updated_at}]}

**导出的 PDF 不在这里**：2026-08-21 起归 `services/resume_library.py`（`data/resumes/library/`）——
一个文件夹装所有能往外发的 PDF，系统导出的和用户自己放进去的平起平坐。
本模块只管**可编辑简历**（块结构），它现在是库的“生成器”。
- data/resumes/{slug}.yaml → 该简历的完整块集

历史：v2.15 之前只有一份简历，存在 data/resume_blocks.yaml。改成多份之后那个文件
被留成「兼容位」，每次保存**双写**一遍（既有消费方只认老文件名）。2026-08-15 删掉了
——它没有任何独占信息（内容按定义等于 {active}.yaml），而"同一份数据两个写入口"
是这个项目已经栽过五次的形状。要"当前激活简历的内容"一律走 `load_active()`。

导出存档：data/resume_pdfs/exports/{ts}_{name}.pdf，按时间倒序列出，滚动上限修剪。
"""
import os
import re
import time
import uuid

import yaml

from services import resume_blocks as rb

EXPORT_KEEP = 20  # 导出存档滚动上限


class ResumeStore:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.resumes_dir = os.path.join(data_dir, "resumes")
        self.index_path = os.path.join(self.resumes_dir, "index.yaml")

    # ── index ────────────────────────────────────────────────────────────────
    def _load_index(self) -> dict:
        if not os.path.exists(self.index_path):
            return self._migrate_initial()
        with open(self.index_path, "r", encoding="utf-8") as f:
            idx = yaml.safe_load(f) or {}
        items = [it for it in (idx.get("items") or []) if isinstance(it, dict) and it.get("slug")]
        active = idx.get("active") or (items[0]["slug"] if items else "")
        return {"active": active, "items": items}

    def _save_index(self, idx: dict) -> None:
        os.makedirs(self.resumes_dir, exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(idx, f, allow_unicode=True, sort_keys=False)

    def _migrate_initial(self) -> dict:
        """还没有 index.yaml 时建一份空的「默认简历」。

        这里原本会去收编 data/resume_blocks.yaml（v2.15 之前那唯一一份简历）。
        那个一次性迁移早就跑完了，文件也已删除，所以现在只建空结构。
        """
        slug = uuid.uuid4().hex[:8]
        item = {"slug": slug, "name": "默认简历", "target": "", "updated_at": _now()}
        rb.save_blocks(rb.empty_blocks(), self._blocks_path(slug))
        idx = {"active": slug, "items": [item]}
        self._save_index(idx)
        return idx

    def _blocks_path(self, slug: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{8}", slug):
            raise ValueError(f"非法 slug: {slug}")  # slug 只来自本模块生成，防路径穿越
        return os.path.join(self.resumes_dir, f"{slug}.yaml")

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def list(self) -> dict:
        return self._load_index()

    def load_active(self) -> dict:
        """当前激活简历的内容。**"激活份内容"的唯一读取入口**——原先各处直接读
        兼容位文件 data/resume_blocks.yaml，那是同一份数据的第二个副本。"""
        idx = self._load_index()
        if not idx["active"]:
            return rb.empty_blocks()
        return rb.load_blocks(self._blocks_path(idx["active"]))

    def get_blocks(self, slug: str) -> dict:
        """读某一份简历的内容（不改变激活份）——「已保存简历」预览用。"""
        idx = self._load_index()
        if not any(it["slug"] == slug for it in idx["items"]):
            raise KeyError(slug)
        return rb.load_blocks(self._blocks_path(slug))

    def create(self, name: str, target: str = "", copy_from_active: bool = True, blocks: dict = None) -> dict:
        """新建一份简历。blocks 给定则用它（AI 组合落地）；否则复制激活份/空结构。"""
        idx = self._load_index()
        slug = uuid.uuid4().hex[:8]
        if blocks is None:
            blocks = self.load_active() if copy_from_active else rb.empty_blocks()
        rb.save_blocks(blocks, self._blocks_path(slug))
        item = {"slug": slug, "name": name or "未命名简历", "target": target, "updated_at": _now()}
        idx["items"].append(item)
        self._save_index(idx)
        return item

    def update_meta(self, slug: str, name: str = None, target: str = None) -> dict:
        idx = self._load_index()
        for it in idx["items"]:
            if it["slug"] == slug:
                if name is not None:
                    it["name"] = name
                if target is not None:
                    it["target"] = target
                it["updated_at"] = _now()
                self._save_index(idx)
                return it
        raise KeyError(slug)

    def delete(self, slug: str) -> None:
        idx = self._load_index()
        if len(idx["items"]) <= 1:
            raise ValueError("至少保留一份简历")
        idx["items"] = [it for it in idx["items"] if it["slug"] != slug]
        if idx["active"] == slug:
            idx["active"] = idx["items"][0]["slug"]
        self._save_index(idx)
        try:
            os.remove(self._blocks_path(slug))
        except OSError:
            pass

    def activate(self, slug: str) -> dict:
        """切换激活简历。只改 index 里的指针——内容一直在各自的 {slug}.yaml 里，
        不需要再往别处拷一份。"""
        idx = self._load_index()
        if not any(it["slug"] == slug for it in idx["items"]):
            raise KeyError(slug)
        idx["active"] = slug
        self._save_index(idx)
        return idx

    def save_active_blocks(self, blocks: dict) -> None:
        """保存当前激活简历。**只写 {slug}.yaml 一处**（原先还双写一份兼容位）。"""
        idx = self._load_index()
        if idx["active"]:
            rb.save_blocks(blocks, self._blocks_path(idx["active"]))
            self.update_meta(idx["active"])  # 刷 updated_at

    # ── 导出存档 ─────────────────────────────────────────────────────────────


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
