"""读取求职者个人信息，供 Layer 1 识别 agent 给 demographic 类字段选值用。
只做扁平化 + 硬约束校验，不做任何"生成"或"猜测"——demographic 字段的值应该
原样来自这里，Layer 1 只负责挑对 key，不负责编值。

两个来源，不重复存（2026-08-13 对齐）：
- 姓名/电话/邮箱：唯一真源是简历系统的 `data/info_pool.yaml`（`basic_info`
  节），这三个字段简历系统已经有完整的编辑 UI + 快照/回滚，personal_info 自己
  不再存一份——写入口只有简历页那一个，避免同一份数据出现两条写路径。
- 性别/出生日期/证件国家/证件类型 等：不属于简历抬头信息，语义上不该进
  info_pool，单独存在 `data/personal_info/identity.yaml`，是一个开放式的、
  会随审批时人工填新字段而增长的字典（见 `save_new_facts`）。
"""
from pathlib import Path
from typing import Dict, List

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "personal_info"
POOL_PATH = Path(__file__).resolve().parent.parent / "data" / "info_pool.yaml"

# info_pool.basic_info 里跟身份相关、可以直接当 demographic 事实用的字段。
# city/degree/target_title 是简历抬头概念（会按场景措辞），不是稳定的身份事
# 实，不纳入。
_POOL_IDENTITY_KEYS = ("name", "phone", "email")

# 政府证件号码类字段是硬性产品边界（DECISION.md「政府证件号码类字段写入 adapter
# 契约作为硬约束」）：任何自动化流程都不应代填，identity.yaml 设计上就不存这类
# 数据。这里额外加一道校验——万一将来有人手滑往文件里加了这类 key，直接报错
# 而不是让它悄悄流进 demographic 候选值。
_FORBIDDEN_KEYS = {"id_number", "id_no", "passport_number", "national_id"}


def load_personal_info(data_dir: Path = DATA_DIR, pool_path: Path = POOL_PATH) -> Dict[str, str]:
    """把 info_pool.basic_info（姓名/电话/邮箱）+ identity.yaml 拍平成一个
    key -> value 的字符串字典。

    文件/字段不存在不报错，直接跳过——Layer 1 遇到找不到值的 demographic
    字段时，正确行为是留空等人工填，而不是编一个假值。空值同样丢弃，理由相同。
    """
    result: Dict[str, str] = {}

    if pool_path.exists():
        pool = yaml.safe_load(pool_path.read_text(encoding="utf-8")) or {}
        basic_info = pool.get("basic_info") or {}
        for key in _POOL_IDENTITY_KEYS:
            value = basic_info.get(key)
            if value:
                result[key] = str(value)

    identity_path = data_dir / "identity.yaml"
    if identity_path.exists():
        content = yaml.safe_load(identity_path.read_text(encoding="utf-8")) or {}
        for key, value in content.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"identity.yaml 里出现了政府证件号码类字段 {key!r}——personal_info "
                    "存储设计上就不该有这类数据，见 DECISION.md「政府证件号码类"
                    "字段写入 adapter 契约作为硬约束」"
                )
            if value:
                result[key] = str(value)
    return result


def save_new_facts(fields: List[dict], data_dir: Path = DATA_DIR, pool_path: Path = POOL_PATH) -> List[str]:
    """L2 审批时，人工给 demographic 类字段填的新值——如果这个字段名在
    personal_info 里原来没有——顺手存回 identity.yaml，供以后其它站点的
    Layer 1 复用，不用同一份资料每次都重新问一遍人（用户 2026-08-13 提出）。

    只存 kind=demographic 且有值的字段：
    - government_id 一律不碰——硬约束，永不代填也永不持久化，双保险；
    - open_question 一律不碰——那是针对具体职位的临时回答（"为什么应聘这个
      岗位"之类），不是稳定的个人事实，存进 personal_info 会污染未来匹配。
    已存在的 key 不覆盖——不管这个 key 现在活在 info_pool 还是 identity.yaml
    里，都不该被某一次审批动作的编辑顺带改掉；只增不改。

    新事实一律写 identity.yaml，不碰 info_pool——info_pool 只有简历页自己的
    UI 一条写入口（见模块 docstring），这里不开第二条，避免同一份数据出现
    两份实现（跟 tracker「一个状态转换只能有一份 SQL」是同一条纪律）。

    fields 是 approve 请求体里审批人编辑过的最终字段数组（field_id/label/kind/
    candidate_value 结构，见 schemas.PendingApplication）。返回新写入的字段名
    列表（空列表表示没有新增），供调用方回显"记住了哪些新信息"。
    """
    existing = load_personal_info(data_dir, pool_path)
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

    identity_path = data_dir / "identity.yaml"
    content = {}
    if identity_path.exists():
        content = yaml.safe_load(identity_path.read_text(encoding="utf-8")) or {}
    content.update(new_facts)
    data_dir.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return list(new_facts.keys())


def load_identity(data_dir: Path = DATA_DIR) -> Dict[str, str]:
    """原样读 identity.yaml（不合并 info_pool）——给「个人信息」管理页用：
    页面只应该编辑这个文件，姓名/电话/邮箱那三个字段的编辑入口在简历页，不在
    这里，所以这里不需要、也不该把它们混进来。"""
    identity_path = data_dir / "identity.yaml"
    if not identity_path.exists():
        return {}
    content = yaml.safe_load(identity_path.read_text(encoding="utf-8")) or {}
    for key in content:
        if key in _FORBIDDEN_KEYS:
            raise ValueError(
                f"identity.yaml 里出现了政府证件号码类字段 {key!r}——personal_info "
                "存储设计上就不该有这类数据，见 DECISION.md「政府证件号码类"
                "字段写入 adapter 契约作为硬约束」"
            )
    return {k: str(v) for k, v in content.items() if v}


def save_identity(data: Dict[str, str], data_dir: Path = DATA_DIR) -> None:
    """整份覆写 identity.yaml——「个人信息」管理页保存用。拒绝任何政府证件号码
    类 key，防止用户在这个页面里手滑存进不该存的东西（跟 load_personal_info
    的运行时校验是同一条硬约束，这里是写入口，宁可在这里就挡住）。"""
    forbidden = _FORBIDDEN_KEYS & set(data.keys())
    if forbidden:
        raise ValueError(
            f"不能保存政府证件号码类字段 {sorted(forbidden)}——这类信息不应存储，"
            "见 DECISION.md「政府证件号码类字段写入 adapter 契约作为硬约束」"
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "identity.yaml").write_text(
        yaml.safe_dump({k: v for k, v in data.items() if v}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
