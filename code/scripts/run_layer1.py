"""
Layer 1（识别 agent）手动触发脚本。

存在理由：Layer 1 不是 W1/W2/W3 pipeline 的一部分（docs/multi-site-expansion-
design.md 的四层架构是独立于 Boss 直聘那套流程的新轨道），没有 Dashboard 入口，
只能命令行触发。第一次运行必须有头（不能 --headless），因为目标站点大概率还
没有持久化登录态，需要人工在弹出的 Chrome 窗口里手动登录一次。

用法（在 code/ 目录下执行）。`--search-url` 与 `--job-url` 二选一：

  # 正常用法：给招聘入口页，agent 按 data/profile.yaml 的求职偏好自己找岗位
  python scripts/run_layer1.py --search-url https://xxx.jobs.../campus/ --site bambulab

  # 调试/复现：已经知道要投哪个岗位，跳过选岗
  python scripts/run_layer1.py --job-url https://xxx.jobs.../position/123 --site bambulab

  # 指定简历（默认用 data/resume_pdfs/exports/ 里最新导出的那份）
  python scripts/run_layer1.py --search-url ... --site huawei --resume path/to/resume.pdf

  # 已确认该站点登录态持久化生效后可以 headless 跑
  python scripts/run_layer1.py --search-url ... --site huawei --headless

`--site` 必填，决定用哪个站点专属的持久化登录目录
（data/browser_profile_multisite/<site>/）——不同站点账号不同，不能共用。
第一次跑某个站点必须有头（不加 --headless），需要人工在弹出的 Chrome 窗口里登录。

跑完之后去 Dashboard「跨站点投递」页审批这条记录——这是验收的关键一步，
不是命令行打印"成功"就算完。**自主选岗上线后还要多看一件事：agent 挑的岗位对不
对**（"选错岗"是这一版新引入的错误类型，字段填错反而是老问题）。
"""
import argparse
import asyncio
import io
import sys
from collections import Counter
from pathlib import Path

# 脚本在 code/scripts/ 内，把 code/ 加入 import 路径
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

# Windows 上 stdout 重定向到文件时默认走 GBK，agent 追踪里的中文岗位名会被写成
# 不可逆的替换字符（? / �）——真机第一次跑完就是这样，日志里岗位标题全成了
# 乱码，等于追踪白打。追踪的全部意义就是事后能读，所以这里强制 UTF-8。
for _stream in ("stdout", "stderr"):
    _s = getattr(sys, _stream)
    if isinstance(_s, io.TextIOWrapper) and (_s.encoding or "").lower() not in ("utf-8", "utf8"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(CODE_DIR / ".env")  # DEEPSEEK_API_KEY 等；不存在则跳过，不报错


def _default_resume_path() -> str:
    from services.resume_store import ResumeStore

    store = ResumeStore(str(CODE_DIR / "data"))
    exports = store.list_exports()
    if not exports:
        raise SystemExit(
            "data/resume_pdfs/exports/ 里没有任何已导出的简历 PDF——"
            "先在 Dashboard「简历」页导出一份，或用 --resume 指定路径。"
        )
    return str(Path(store.exports_dir) / exports[0]["file"])


def _parse_quota_overrides(items):
    """`--category 产品:3` × N → {"产品": 3}。没给就返回 None（用 profile 的默认）。

    格式错就 SystemExit 而不是忽略：一个写错的 --category 如果被静默跳过，表现是
    "agent 莫名其妙不找这一类"，跟配置漏写完全一样，查起来极费劲。
    """
    if not items:
        return None
    quotas = {}
    for item in items:
        name, sep, num = item.rpartition(":")
        if not sep or not name.strip() or not num.strip().isdigit():
            raise SystemExit(f"--category 格式应为 名称:数量（如 产品:3），收到：{item!r}")
        quotas[name.strip()] = int(num)
    return quotas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # 二选一：给入口页让 agent 自己选岗（正常用法），或直接指定岗位（调试/复现）。
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument("--search-url", help="站点招聘入口页 URL，由 agent 按 profile.yaml 的求职偏好自主选岗")
    entry.add_argument("--job-url", help="直接指定一个岗位详情页 URL，跳过选岗（调试/复现用）")
    parser.add_argument("--site", required=True, help="站点标识（如 huawei / bambulab），决定用哪个持久化登录目录")
    parser.add_argument("--resume", default=None, help="简历 PDF 路径（默认用最新导出的那份）")
    parser.add_argument("--headless", action="store_true", help="无头模式（仅在已确认登录态持久化后使用）")
    parser.add_argument("--max-pages", type=int, default=8,
                        help="每个分类桶最多翻几页（默认 8）")
    parser.add_argument(
        "--category", action="append", default=None, metavar="名称:数量",
        help="覆盖本次的类别名额，可重复：--category 产品:3 --category 开发:5。"
             "不给就用 profile.yaml 的 job_seeking.categories。",
    )
    parser.add_argument("--select-only", action="store_true",
                        help="只跑到 Checkpoint 1（选岗+落库），不上传简历。对外零副作用")
    args = parser.parse_args()

    from multisite import preferences

    quotas = _parse_quota_overrides(args.category)

    resume_path = args.resume or _default_resume_path()
    mode = "指定岗位" if args.job_url else "自主选岗"
    print(f"[layer1] 模式={mode}  入口={args.job_url or args.search_url}")
    print(f"[layer1] resume={resume_path}")
    print(f"[layer1] headless={args.headless}")
    if not args.job_url:
        # 跑之前把 agent 实际在按什么条件筛打出来——这是"agent 选错岗"这类新错误
        # 最便宜的排查入口，比事后翻日志猜它理解成了什么强。
        print(f"[layer1] 求职偏好: {preferences.describe_for_log()}")
        # 按站点解析后的名额——跟上面那行的全局名额可能不同（site_overrides 会
        # 去掉本站没有的类别）。打出来免得事后纳闷"我明明配了游戏怎么没找"。
        eff = quotas or preferences.load_profile().job_seeking.quotas_for_site(args.site)
        print(f"[layer1] 本站生效名额: {eff}")

    from multisite.layer1_agent import run_layer1

    state = asyncio.run(
        run_layer1(
            resume_pdf_path=resume_path,
            site_name=args.site,
            job_url=args.job_url or "",
            search_url=args.search_url or "",
            headless=args.headless,
            max_pages=args.max_pages,
            quotas=quotas,
            select_only=args.select_only,
        )
    )

    # 三种结果分别打印，不要压成一句"成功/失败"——"没找到符合条件的岗位"和
    # "找到了但表单没有需要填的字段"都是合法结果，跟真失败要能区分开。
    jobs = state.get("found_jobs") or []
    by_cat = Counter(j.category for j in jobs)
    print(f"[layer1] 候选岗位 {len(jobs)} 个，按类别：{dict(by_cat) or '(无)'}")
    for j in jobs:
        print(f"          - [{j.category or '未分类'}] {j.title or '(无标题)'} "
              f"| {j.company or '(无公司)'} | {j.why}")
        print(f"            {j.url}")

    new_ids = state.get("pending_job_ids") or []
    print(f"[layer1] 写入 pending_jobs {len(new_ids)} 条待审批"
          f"（{len(jobs) - len(new_ids)} 条因 url 重复跳过）")

    if args.select_only:
        print("[layer1] --select-only：到此为止，未上传简历。去审批 Checkpoint 1 再走填表。")
        return 0

    outcome = state.get("open_result")
    if outcome is not None:
        print(f"[layer1] 表单已打开={outcome.form_opened} 简历已上传={outcome.resume_uploaded}")
        if outcome.note:
            print(f"[layer1] 说明: {outcome.note}")

    app_id = state.get("pending_application_id")
    if app_id:
        n = len(state.get("classified_fields") or [])
        print(f"[layer1] 写入 pending_applications id={app_id}（{n} 个字段），"
              f"去 Dashboard「跨站点投递」页审批")
        return 0

    print("[layer1] 未写入待审批记录（没有找到符合条件的岗位，或表单里没有需要填写的空字段）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
