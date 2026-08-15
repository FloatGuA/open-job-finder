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
# Optional 是 resolve_key 的返回标注。Python 3.14 的延迟标注（PEP 649）让漏导入不会
# 当场报错，但任何 get_type_hints / 旧版本 Python 上都会炸——补上。
from typing import Dict, List, Optional

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

# 同义字段名归一表：不同网站对同一个事实的叫法不一样（「生日」/「出生日期」/
# 「出生年月」/ birthday 都是 birth_date）。没有这层归一会有两个后果，且都是
# 静默的：①填表时 `personal_info.get("生日")` 查不到 birth_date，字段留空但没人
# 知道为什么；②`save_new_facts` 把「生日」当成没见过的新字段又存一份，identity.yaml
# 里同一个事实攒出好几个 key，越用越乱。
#
# 刻意用确定性规则表而不是 LLM：这正是 docs/multi-site-expansion-design.md 定的
# 「人口学字段规则映射、开放问题才用 LLM」分工（调研牛客网申助手也验证了同一划分
# ——它的实现就是"字段名映射库 + 同义词归一化"，纯规则）。新增同义词直接往这里加。
_KEY_ALIASES: Dict[str, str] = {
    # name
    "姓名": "name", "名字": "name", "真实姓名": "name", "本人姓名": "name",
    "fullname": "name", "yourname": "name",
    # phone
    "电话": "phone", "手机": "phone", "手机号": "phone", "手机号码": "phone",
    "联系电话": "phone", "联系方式": "phone", "移动电话": "phone",
    "mobile": "phone", "telephone": "phone", "phonenumber": "phone", "tel": "phone",
    # email
    "邮箱": "email", "电子邮箱": "email", "电子邮件": "email", "邮件": "email",
    "常用邮箱": "email", "mail": "email", "emailaddress": "email",
    # gender
    "性别": "gender", "sex": "gender",
    # birth_date
    "生日": "birth_date", "出生日期": "birth_date", "出生年月": "birth_date",
    "出生年月日": "birth_date", "出生日": "birth_date",
    "birthday": "birth_date", "dateofbirth": "birth_date", "dob": "birth_date",
    # id_country
    "证件签发国家": "id_country", "证件签发国家地区": "id_country",
    "签发国家": "id_country", "证件国家": "id_country", "国籍": "id_country",
    # id_type
    "证件类型": "id_type", "证件种类": "id_type", "idtype": "id_type",
}


def _normalize_key(raw: str) -> str:  # noqa: E302  (紧跟别名表，便于对照阅读)
    """把字段名归一到可比较的形态：去空白/下划线/连字符、去必填星号和冒号、
    ASCII 转小写。目的是让「手机号码 *」「Phone Number」「phone_number」这些
    写法落到同一个串上——真机扫到的 label 经常带 ` *` 后缀（必填标记）。"""
    s = (raw or "").strip()
    for ch in ("*", "＊", "：", ":", " ", "　", "_", "-", "(", ")", "（", "）"):
        s = s.replace(ch, "")
    return s.lower()


# 归一形态 → 规范名。**规范名自己也要能查到自己**（`birth_date` 归一成
# `birthdate`，它不在别名表的 key 里）——否则"用规范名去找存成中文别名的 key"
# 这个方向查不通，单测 test_resolves_when_stored_key_is_itself_a_synonym 抓到过。
_CANONICAL_BY_NORMALIZED: Dict[str, str] = {
    _normalize_key(alias): canonical for alias, canonical in _KEY_ALIASES.items()
}
for _canonical in set(_KEY_ALIASES.values()):
    _CANONICAL_BY_NORMALIZED.setdefault(_normalize_key(_canonical), _canonical)


def resolve_key(label: str, known_keys) -> Optional[str]:
    """把一个表单字段名解析成 personal_info 里实际存在的 key，解析不出返回 None。

    三级匹配，逐级放宽：①原样命中；②归一化后命中（吃掉星号/空格/大小写差异）；
    ③过同义表拿到规范名，再正反两个方向找（label 是别名而存储用规范名，或反过来
    存储里存的就是中文别名）。三级都不中说明这确实是个没见过的字段，交给调用方
    处理（填表时留空等人工填，保存时当新事实存）。
    """
    if not label:
        return None
    known = list(known_keys)
    if label in known:
        return label

    normalized = _normalize_key(label)
    by_normalized = {_normalize_key(k): k for k in known}
    if normalized in by_normalized:
        return by_normalized[normalized]

    canonical = _CANONICAL_BY_NORMALIZED.get(normalized)
    if canonical:
        if canonical in known:
            return canonical
        # 存储里的 key 本身也可能是某个同义词（比如审批时人工存成了「生日」），
        # 那就反查：哪个已有 key 跟这个 label 归一到同一个规范名。
        for key in known:
            if _CANONICAL_BY_NORMALIZED.get(_normalize_key(key)) == canonical:
                return key
    return None


def match_value(label: str, personal_info: Dict[str, str]) -> str:
    """按字段名取值，取不到返回空字符串（不编造）。填表路径的唯一取值入口。"""
    key = resolve_key(label, personal_info.keys())
    return personal_info.get(key, "") if key else ""


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
        if not key or not value or key in _FORBIDDEN_KEYS:
            continue
        # 走同义解析而不是 `key in existing`：某个网站把生日叫「生日」、存储里
        # 存的是 birth_date，直接判 in 会认为这是没见过的新字段又存一份，
        # identity.yaml 里同一个事实攒出多个 key。解析得出说明已经有了 → 跳过。
        if resolve_key(key, existing.keys()) is not None:
            continue
        # 同一批里的同义字段也只留第一个（表单上「生日」「出生日期」同时出现时）。
        if resolve_key(key, new_facts.keys()) is not None:
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


# ── 多值候选（从 info_pool.sections 派生）─────────────────────────────────────
#
# 有些表单字段在池里对应的**不止一个值**：用户有本科和硕士两段学历，表单上一个
# 「学校名称」框，填哪个？**连本人都需要看页面上下文才能决定**（用户 2026-08-15
# 原话："我不知道这里我应该填写的是哪个"）。
#
# 所以这里刻意**不合并、不挑选**，只把候选连同上下文一起摆出来，人点一个。跟
# government_id 留空、跟 site_limit 的 unknown 三态是同一条原则：**系统不知道的
# 事情，不猜**。
#
# 映射表是确定性的、显式的——同 `_KEY_ALIASES`，新增直接往这里加。刻意不用 LLM：
# 这是"字段名 → 池里哪个分区"的路由，不是判断题。
_SECTION_SOURCES: Dict[str, str] = {
    # 归一后的字段名 → info_pool 里的分区名
    "学校名称": "教育经历", "学校": "教育经历", "毕业院校": "教育经历",
    "院校名称": "教育经历", "就读院校": "教育经历", "school": "教育经历",
    "university": "教育经历",
    "公司名称": "实习经历", "工作单位": "实习经历", "实习单位": "实习经历",
    "company": "实习经历",
    "项目名称": "项目经历", "project": "项目经历",
}
_SECTION_SOURCES_NORMALIZED = {_normalize_key(k): v for k, v in _SECTION_SOURCES.items()}


def _block_context(block: dict) -> str:
    """给候选项配一句上下文，让人分得清哪个是哪个。

    只有标题（"甲大学"/"乙大学"）在本硕两段学历上是够用的，但换成两段同公司不同
    岗位的实习就分不出来了。时间 + 首条要点是池里稳定存在、且最能区分的两样。
    """
    parts = [str(block.get("time") or "").strip()]
    bullets = block.get("bullets") or []
    first = str(bullets[0]).strip() if bullets else str(block.get("summary") or "").strip()
    if first:
        parts.append(first[:40])
    return " · ".join([p for p in parts if p])


def load_candidates(label: str, pool_path: Path = POOL_PATH) -> List[dict]:
    """这个表单字段在池里有哪些候选值。**只有一个或一个都没有时返回空列表**。

    返回空的两种情况在调用方看来行为一致（不显示候选区），但含义不同：
      - 映射不到分区 —— 这个字段不是"多值型"的，走 `match_value` 的单值路径；
      - 分区里只有一条 —— 没有歧义，直接填就是了，摆个只有一项的选择器是噪音。
    """
    section_name = _SECTION_SOURCES_NORMALIZED.get(_normalize_key(label))
    if not section_name or not pool_path.exists():
        return []
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8")) or {}
    section = next((s for s in (pool.get("sections") or [])
                    if s.get("name") == section_name), None)
    if section is None:
        return []
    out = [{"value": str(b.get("title") or "").strip(), "context": _block_context(b)}
           for b in (section.get("blocks") or []) if str(b.get("title") or "").strip()]
    return out if len(out) > 1 else []
