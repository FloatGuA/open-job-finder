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


def traced_stage(name, fn, logger, summarize=None):
    """包一层，让这个阶段跑完在 run 日志里留下一条记录。

    `summarize(out) -> dict` **跟着阶段走**，不由这里认识每个阶段的输出形状：
    否则加一个阶段要改两个地方，而漏改只表现为日志里少几个数字，不会有东西变红。
    """

    async def wrapped(state):
        started = time.monotonic()
        try:
            out = await fn(state)
        except Exception as exc:
            logger.log_step(name, {}, "failed",
                            int((time.monotonic() - started) * 1000), error=str(exc))
            raise   # 记日志不是处理异常
        logger.log_step(name, {}, "successful", int((time.monotonic() - started) * 1000),
                        data=summarize(out) if summarize else {})
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
