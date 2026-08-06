"""面试 Prep 卡片加载。内容文件在 gitignore 的 data/ 下，所以这里全部用虚构 fixture。"""
import io
import os

from services import interview_prep


def _write(tmp_path, text: str) -> str:
    p = os.path.join(str(tmp_path), "prep.yaml")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def test_missing_file_returns_empty(tmp_path):
    """文件不存在不该抛——页面自己提示怎么建。"""
    assert interview_prep.load_prep(os.path.join(str(tmp_path), "nope.yaml")) == {"roles": []}


def test_loads_roles_and_cards(tmp_path):
    p = _write(tmp_path, """
roles:
  - key: demo
    name: 示例岗位
    pitch: 一句话陈述
    hook: 钩子
    cards:
      - q: 问题一
        a: 答法一
        evidence:
          - 证据甲
          - 证据乙
        avoid: 别说这个
""")
    out = interview_prep.load_prep(p)
    assert len(out["roles"]) == 1
    role = out["roles"][0]
    assert role["key"] == "demo" and role["name"] == "示例岗位"
    assert role["pitch"] == "一句话陈述" and role["hook"] == "钩子"
    assert role["cards"][0]["q"] == "问题一"
    assert role["cards"][0]["evidence"] == ["证据甲", "证据乙"]
    assert role["cards"][0]["avoid"] == "别说这个"


def test_drops_roles_without_key_or_name(tmp_path):
    p = _write(tmp_path, """
roles:
  - name: 缺 key
  - key: nokey
  - key: ok
    name: 完整的
""")
    assert [r["key"] for r in interview_prep.load_prep(p)["roles"]] == ["ok"]


def test_drops_cards_without_question(tmp_path):
    """没有问题的卡片渲染出来是个空壳，直接丢掉。"""
    p = _write(tmp_path, """
roles:
  - key: k
    name: n
    cards:
      - a: 只有答案没有问题
      - q: 有问题
        a: 有答案
""")
    cards = interview_prep.load_prep(p)["roles"][0]["cards"]
    assert len(cards) == 1 and cards[0]["q"] == "有问题"


def test_optional_fields_default_to_empty(tmp_path):
    """只写 q 也要能渲染，不该 KeyError。"""
    p = _write(tmp_path, """
roles:
  - key: k
    name: n
    cards:
      - q: 光杆问题
""")
    card = interview_prep.load_prep(p)["roles"][0]["cards"][0]
    assert card["a"] == "" and card["evidence"] == [] and card["avoid"] == ""


def test_empty_file_returns_empty(tmp_path):
    assert interview_prep.load_prep(_write(tmp_path, "")) == {"roles": []}


def test_collapses_cjk_fold_spaces(tmp_path):
    """YAML 折叠标量在换行处插空格；中文句中不该留这个空格，中英混排的必须留。"""
    p = _write(tmp_path, """
roles:
  - key: k
    name: n
    cards:
      - q: >-
          落库，
          每次运行
        a: >-
          共 302 行 /
          全项目，使用 SQLite 存储
""")
    card = interview_prep.load_prep(p)["roles"][0]["cards"][0]
    assert card["q"] == "落库，每次运行"                       # CJK 之间的空格收掉
    assert "302 行 / 全项目" in card["a"]                      # 中英混排的空格保留
    assert "使用 SQLite 存储" in card["a"]                     # 英文两侧空格保留
