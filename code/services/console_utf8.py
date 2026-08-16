"""把进程的 stdout/stderr 切成 UTF-8。

**为什么需要**：Windows 上 stdout 重定向到文件（或非 UTF-8 控制台）默认走 GBK，
而 agent 的输出里什么字符都可能有。2026-08-16 首次从 Dashboard 跑 m1 时，agent
说了一句带 ✅ 的话，追踪用的 `print` 抛 `UnicodeEncodeError`，**异常冒泡打死了
整个 find_jobs 节点，已经找到的 8 个岗位全丢**。

这段逻辑原本只长在 `scripts/run_layer1.py` 里，而从 Dashboard 跑走的是 uvicorn
进程、拿不到那一行——同一件事两份实现且其中一份漏了。收敛到这里，两个入口共用。
"""
import io
from typing import Optional


def _is_utf8(stream) -> bool:
    return (getattr(stream, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf8mb4")


def force_utf8_stdout(stream=None) -> None:
    """把这个流（默认 sys.stdout + sys.stderr）切成 UTF-8。

    **它自己绝不能成为新的崩溃点**：改不动就算了（有些环境里 stdout 已经被测试
    框架或日志库换成了别的对象）。少几个可读的中文字符，比因为"修日志"把进程
    弄挂要好——这正是本函数要解决的那类问题的反面。
    """
    targets = [stream] if stream is not None else _default_streams()
    for target in targets:
        if target is None or _is_utf8(target):
            continue
        reconfigure = getattr(target, "reconfigure", None)
        if reconfigure is None or not isinstance(target, io.TextIOWrapper):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _default_streams() -> list:
    import sys

    return [sys.stdout, sys.stderr]


def safe_print(*args, **kwargs) -> Optional[bool]:
    """print 的替身：写不出去就退而求其次，**绝不抛**。

    第二道防线。编码修好了，换个终端、换个重定向目标照样可能有写不出去的字符，
    而调用方（agent 追踪）是纯日志——它没有资格中断业务流程。
    """
    try:
        print(*args, **kwargs)
        return True
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        try:
            print(text.encode("utf-8", "backslashreplace").decode("ascii"), **kwargs)
        except Exception:  # noqa: BLE001 — 日志尽力而为，失败也不能影响调用方
            pass
        return False
