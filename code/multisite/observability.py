"""把 m1/m2 接到项目统一的 run 日志上（`logs/runs/*.jsonl` + SSE）。

这里只有两件事：一次运行的生命周期（`run_scope`）和一个阶段的记录（`traced_stage`）。
两者都刻意**不碰浏览器、不碰 LangGraph**——它们原本长在 `run_layer1` 和图的组装
代码里，而那些要开真 Chrome 才跑得起来，等于永远测不到。
"""
import time
from contextlib import contextmanager

from pipeline.run_logger import RunLogger


class _Run:
    """一次运行期间的把手：logger 拿去记步骤，summary 往里塞、收尾时写进 run_end。"""

    def __init__(self, logger: RunLogger) -> None:
        self.logger = logger
        self.summary: dict = {}


@contextmanager
def run_scope(workflow: str, emitter=None, meta: dict = None):
    """一次 m1/m2 运行的生命周期。**无论怎么离开都写 run_end**。

    `emitter` 给了就同时推 SSE；不给也照样落 JSONL——JSONL 是完整数据源，SSE 只是
    实时镜像，命令行跑的那次事后同样要能回放。

    **失败时刻意不发 `finish_workflow`**：队列的 `run_item` 已经在它的 except 里
    发过了，两边都发前端会收到两个终止事件。
    """
    logger = RunLogger(pipeline=workflow, emitter=emitter, debug=True, meta=meta)
    run = _Run(logger)
    if emitter is not None:
        emitter.start_workflow(workflow, meta=meta)
    try:
        yield run
    except Exception:
        logger.close("failed", summary=run.summary)
        raise
    logger.close("done", summary=run.summary)
    if emitter is not None:
        emitter.finish_workflow(workflow, str(run.summary), status="done")


def traced_stage(name, fn, logger, summarize=None, snapshot_provider=None):
    """包一层，让这个阶段跑完在 run 日志里留下一条记录。

    `summarize(out) -> dict` **跟着阶段走**，不由这里认识每个阶段的输出形状：
    否则加一个阶段要改两个地方，而漏改只表现为日志里少几个数字，不会有东西变红。

    `snapshot_provider() -> str` 失败时用来取"当时最近一张"完整 a11y 快照。
    **不能改用 `state["snapshot_text"]`**：它只在阶段成功返回时才写回，阶段失败时
    装的是上一个阶段的快照——正好在最需要它的时候是错的。
    """

    async def wrapped(state):
        started = time.monotonic()
        try:
            out = await fn(state)
        except Exception as exc:
            data = {}
            if snapshot_provider is not None:
                from services.run_logger import run_artifacts_dir
                # `layer1_agent` 已经在顶部 import 了 observability，顶层反向
                # import 会成环，所以这里放函数体内。
                from multisite.layer1_agent import _dump_debug_snapshot
                tag = f"{name}_snapshot"
                _dump_debug_snapshot(tag, snapshot_provider() or "",
                                     target_dir=run_artifacts_dir(logger.run_id))
                data["snapshot_file"] = f"{tag}.txt"
            logger.log_step(name, {}, "failed",
                            int((time.monotonic() - started) * 1000),
                            data=data, error=str(exc))
            raise   # 记日志不是处理异常
        # **没跑完就不许报成功。** agent 步数耗尽时 `create_react_agent` 不抛异常、
        # 只塞一句固定文案就正常返回，两种结局的返回值一模一样（见 agent_runtime
        # 的 `hit_step_limit`）。节点把这件事写进 state 的 `truncated`，这里翻译成
        # 一个**不是绿色**的状态：`partial` 经 `_ui_status` 原样透出，前端画成黄色。
        # 报 successful 的代价不是"少一个提示"，是让人得出错误结论——看到「游戏 0/2」
        # 会以为站上没有这类岗，而真相可能是压根没扫到。
        truncated = bool(isinstance(out, dict) and out.get("truncated"))
        data = summarize(out) if summarize else {}
        if truncated:
            data = {**data, "truncated": True}
        logger.log_step(name, {}, "partial" if truncated else "successful",
                        int((time.monotonic() - started) * 1000), data=data)
        return out

    return wrapped


def agent_step_sink(logger, step: str):
    """给 `run_agent(on_step=...)` 用的回调：把 agent 每一轮记到这个阶段名下。

    `logger` 为 None（命令行 `--direct` 路径）时返回 None——让 run_agent 保持
    原来的行为，而不是塞一个什么都不做的函数进去。
    """
    if logger is None:
        return None
    return lambda record: logger.log_agent_step(step, record)
