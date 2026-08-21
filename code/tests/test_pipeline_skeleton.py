"""W1/W2/W3 的步骤骨架：后端声明一份，测试盯着它别跟代码漂移。

**为什么需要它**：前端原来手抄了一份 `SKELETON`，它是**空闲态那张图**的数据源
（"预期步骤 vs 实际步骤对照——哪步没出现就是没跑到"）。抄的东西会烂：

    W3  SKELETON 只有 scan/locate/send/verify，代码里还有
        freshness / detect / resume / upsert —— **少了 4 个步骤**
    W2  代码里有 wechat 步，SKELETON 里没有

而这种烂法**不会报错**：少登记一个步骤，那一步在空闲态就是不存在，跑起来才冒出来。

**判据只盯步骤名，不盯工具**：`send_pipeline.py` 一个文件里有 4 个 `set_context`
和 8 个 `_reg.call`，哪个工具属于哪一步靠正则分不出来——那种聪明的静态分析本身
就是新的脆弱点。工具列表已从前端删掉，改成只显示实际观测到的：空闲态本来就
**不知道**会调哪些工具，装作知道比不显示更糟。
"""
import os
import re

import pytest

from pipeline.skeleton import LOOP_STEPS, RUN_STEPS, STEPS

PIPELINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "pipeline")
_CTX = re.compile(r'set_context\(\s*["\'](\w+)["\']')


def _steps_in_source(workflow: str) -> set:
    """源码里这条流程真正 set_context 过的步骤名。"""
    found = set()
    base = os.path.join(PIPELINE_DIR, workflow)
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            if fn.endswith(".py") and fn != "__init__.py":
                with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                    found.update(_CTX.findall(f.read()))
    return found


@pytest.mark.parametrize("workflow", ["w1", "w2", "w3"])
class TestDeclarationMatchesTheCode:
    def test_every_step_in_the_code_is_declared(self, workflow):
        """**加了一步却忘了登记，空闲态那张图就少一个节点，而且不会报错。**
        真机上 W3 就这么少了 4 步、W2 少了 wechat。"""
        missing = _steps_in_source(workflow) - set(STEPS[workflow])
        assert not missing, (
            f"{workflow} 代码里有这些步骤但 pipeline/skeleton.py 没登记：{sorted(missing)}")

    def test_nothing_declared_that_the_code_does_not_have(self, workflow):
        """反向也要守：删了一步却留着声明，空闲态会显示一个永远不会亮的节点。"""
        extra = set(STEPS[workflow]) - _steps_in_source(workflow)
        assert not extra, (
            f"{workflow} 声明了这些步骤但代码里没有：{sorted(extra)}")

    def test_run_and_loop_partition_the_steps(self, workflow):
        """每一步要么是 run 级（整轮跑一次）要么是循环级（每个岗位/会话一次）——
        **不能既不属于也不重复**，否则前端渲染时那一步会掉出去或画两遍。"""
        run, loop = set(RUN_STEPS[workflow]), set(LOOP_STEPS[workflow])
        assert not (run & loop), f"{workflow} 这些步骤两边都登记了：{sorted(run & loop)}"
        assert run | loop == set(STEPS[workflow]), (
            f"{workflow} 没归类的步骤：{sorted(set(STEPS[workflow]) - run - loop)}")
