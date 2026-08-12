"""读取 data/personal_info/{basic,identity}.yaml，供 Layer 1 识别 agent 给
demographic 类字段选值用。只做扁平化 + 硬约束校验，不做任何"生成"或"猜测"——
demographic 字段的值应该原样来自这里，Layer 1 只负责挑对 key，不负责编值。
"""
from pathlib import Path
from typing import Dict, List

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "personal_info"

# 政府证件号码类字段是硬性产品边界（DECISION.md「政府证件号码类字段写入 adapter
# 契约作为硬约束」）：任何自动化流程都不应代填，identity.yaml 设计上就不存这类
# 数据。这里额外加一道校验——万一将来有人手滑往文件里加了这类 key，直接报错
# 而不是让它悄悄流进 demographic 候选值。
_FORBIDDEN_KEYS = {"id_number", "id_no", "passport_number", "national_id"}


def load_personal_info(data_dir: Path = DATA_DIR) -> Dict[str, str]:
    """把 basic.yaml + identity.yaml 拍平成一个 key -> value 的字符串字典。

    文件不存在（目录不存在、或某个文件缺失）不报错，直接跳过——Layer 1 遇到
    找不到值的 demographic 字段时，正确行为是留空等人工填，而不是编一个假值。
    空值（''/None）同样丢弃，理由相同。
    """
    result: Dict[str, str] = {}
    for fname in ("basic.yaml", "identity.yaml"):
        path = data_dir / fname
        if not path.exists():
            continue
        content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, value in content.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"{fname} 里出现了政府证件号码类字段 {key!r}——personal_info "
                    "存储设计上就不该有这类数据，见 DECISION.md「政府证件号码类"
                    "字段写入 adapter 契约作为硬约束」"
                )
            if value:
                result[key] = str(value)
    return result


def save_new_facts(fields: List[dict], data_dir: Path = DATA_DIR) -> List[str]:
    """L2 审批时，人工给 demographic 类字段填的新值——如果这个字段名在
    personal_info 里原来没有——顺手存回 basic.yaml，供以后其它站点的 Layer 1
    复用，不用同一份资料每次都重新问一遍人（用户 2026-08-13 提出）。

    只存 kind=demographic 且有值的字段：
    - government_id 一律不碰——硬约束，永不代填也永不持久化，双保险；
    - open_question 一律不碰——那是针对具体职位的临时回答（"为什么应聘这个
      岗位"之类），不是稳定的个人事实，存进 personal_info 会污染未来匹配。
    已存在的 key 不覆盖——personal_info 是人工维护的权威资料，不该被某一次
    审批动作的编辑顺带改掉；只增不改，跟 identity.yaml「政府证件号码硬约束」
    的谨慎程度对齐。

    fields 是 approve 请求体里审批人编辑过的最终字段数组（field_id/label/kind/
    candidate_value 结构，见 schemas.PendingApplication）。返回新写入的字段名
    列表（空列表表示没有新增），供调用方回显"记住了哪些新信息"。
    """
    existing = load_personal_info(data_dir)
    new_facts: Dict[str, str] = {}
    for f in fields:
        if f.get("kind") != "demographic":
            continue
        key = (f.get("field_id") or f.get("label") or "").strip()
        value = (f.get("candidate_value") or "").strip()
        if not key or not value or key in existing or key in _FORBIDDEN_KEYS:
            continue
        new_facts[key] = value

    if not new_facts:
        return []

    basic_path = data_dir / "basic.yaml"
    content = {}
    if basic_path.exists():
        content = yaml.safe_load(basic_path.read_text(encoding="utf-8")) or {}
    content.update(new_facts)
    data_dir.mkdir(parents=True, exist_ok=True)
    basic_path.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return list(new_facts.keys())
