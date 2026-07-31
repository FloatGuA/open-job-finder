"""多份简历管理 + 导出 PDF 存档（简历制作台 v2.15）。

存储模型（用户定：每份独立完整，FlowCV 式）：
- data/resumes/index.yaml  → {active: slug, items: [{slug, name, target, updated_at}]}
- data/resumes/{slug}.yaml → 该简历的完整块集（结构同 resume_blocks.yaml）
- data/resume_blocks.yaml  → 始终是**当前激活简历**的内容（兼容位：JD 定制/
  onboarding/上传解析等既有消费方只认这个文件，切换简历=把选中份拷入此文件；
  保存激活简历=同时写 {slug}.yaml 与此文件）。

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
        self.active_blocks_path = os.path.join(data_dir, "resume_blocks.yaml")
        self.exports_dir = os.path.join(data_dir, "resume_pdfs", "exports")

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
        """首次使用：若已有 resume_blocks.yaml，把它收编为第一份简历「默认简历」。"""
        slug = uuid.uuid4().hex[:8]
        item = {"slug": slug, "name": "默认简历", "target": "", "updated_at": _now()}
        blocks = rb.load_blocks(self.active_blocks_path)
        rb.save_blocks(blocks, self._blocks_path(slug))
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

    def create(self, name: str, target: str = "", copy_from_active: bool = True) -> dict:
        idx = self._load_index()
        slug = uuid.uuid4().hex[:8]
        blocks = rb.load_blocks(self.active_blocks_path) if copy_from_active else rb.empty_blocks()
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
            rb.save_blocks(rb.load_blocks(self._blocks_path(idx["active"])), self.active_blocks_path)
        self._save_index(idx)
        try:
            os.remove(self._blocks_path(slug))
        except OSError:
            pass

    def activate(self, slug: str) -> dict:
        """切换激活简历：把该份内容拷入兼容位 resume_blocks.yaml。"""
        idx = self._load_index()
        if not any(it["slug"] == slug for it in idx["items"]):
            raise KeyError(slug)
        rb.save_blocks(rb.load_blocks(self._blocks_path(slug)), self.active_blocks_path)
        idx["active"] = slug
        self._save_index(idx)
        return idx

    def save_active_blocks(self, blocks: dict) -> None:
        """保存当前激活简历：双写 {slug}.yaml + 兼容位。"""
        idx = self._load_index()
        rb.save_blocks(blocks, self.active_blocks_path)
        if idx["active"]:
            rb.save_blocks(blocks, self._blocks_path(idx["active"]))
            self.update_meta(idx["active"])  # 刷 updated_at

    # ── 导出存档 ─────────────────────────────────────────────────────────────
    def export_path(self, name: str) -> str:
        """给一次导出分配存档路径（带时间戳，不互相覆盖），并顺手修剪超限旧档。"""
        os.makedirs(self.exports_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name or "resume").strip("_") or "resume"
        fname = f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}.pdf"
        self._prune_exports()
        return os.path.join(self.exports_dir, fname)

    def list_exports(self) -> list:
        if not os.path.isdir(self.exports_dir):
            return []
        out = []
        for fn in os.listdir(self.exports_dir):
            if not fn.endswith(".pdf"):
                continue
            p = os.path.join(self.exports_dir, fn)
            out.append({"file": fn, "size": os.path.getsize(p),
                        "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
        out.sort(key=lambda x: x["file"], reverse=True)  # 文件名以时间戳开头
        return out

    def export_file(self, fname: str) -> str:
        if "/" in fname or "\\" in fname or ".." in fname:
            raise ValueError(f"非法文件名: {fname}")
        p = os.path.join(self.exports_dir, fname)
        if not os.path.isfile(p):
            raise FileNotFoundError(fname)
        return p

    def delete_export(self, fname: str) -> None:
        os.remove(self.export_file(fname))

    def _prune_exports(self) -> None:
        files = self.list_exports()
        for it in files[EXPORT_KEEP - 1:]:  # 留出本次的位置
            try:
                os.remove(os.path.join(self.exports_dir, it["file"]))
            except OSError:
                pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
