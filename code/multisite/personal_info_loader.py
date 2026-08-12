"""读取 data/personal_info/{basic,identity}.yaml，供 Layer 1 识别 agent 给
demographic 类字段选值用。只做扁平化 + 硬约束校验，不做任何"生成"或"猜测"——
demographic 字段的值应该原样来自这里，Layer 1 只负责挑对 key，不负责编值。
"""
from pathlib import Path
from typing import Dict

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
