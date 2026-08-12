"""
Layer 1（识别 agent）手动触发脚本。

存在理由：Layer 1 不是 W1/W2/W3 pipeline 的一部分（docs/multi-site-expansion-
design.md 的四层架构是独立于 Boss 直聘那套流程的新轨道），没有 Dashboard 入口，
只能命令行触发。第一次运行必须有头（不能 --headless），因为目标站点大概率还
没有持久化登录态，需要人工在弹出的 Chrome 窗口里手动登录一次。

用法（在 code/ 目录下执行）：
  python scripts/run_layer1.py <job_url> --site huawei
      跑一次，headed 模式，用最新导出的简历 PDF（data/resume_pdfs/exports/ 里
      文件名最大的那个），跑完打印写入的 pending_applications id。--site 必填，
      决定用哪个站点专属的持久化登录目录（data/browser_profile_multisite/<site>/），
      不同站点账号不同，不能共用。
  python scripts/run_layer1.py <job_url> --site bambulab --resume path/to/resume.pdf
      指定简历 PDF（不使用最新导出的那份）。
  python scripts/run_layer1.py <job_url> --site huawei --headless
      已确认该站点登录态持久化生效后可以 headless 跑。

跑完之后去 Dashboard「跨站点投递」页审批这条记录——这是本轮验收的关键一步，
不是命令行打印"成功"就算完。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 脚本在 code/scripts/ 内，把 code/ 加入 import 路径
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_url", help="目标职位详情页 URL")
    parser.add_argument("--site", required=True, help="站点标识（如 huawei / bambulab），决定用哪个持久化登录目录")
    parser.add_argument("--resume", default=None, help="简历 PDF 路径（默认用最新导出的那份）")
    parser.add_argument("--headless", action="store_true", help="无头模式（仅在已确认登录态持久化后使用）")
    args = parser.parse_args()

    resume_path = args.resume or _default_resume_path()
    print(f"[layer1] job_url={args.job_url}")
    print(f"[layer1] resume={resume_path}")
    print(f"[layer1] headless={args.headless}")

    from multisite.layer1_agent import run_layer1

    app_id = asyncio.run(
        run_layer1(
            job_url=args.job_url,
            resume_pdf_path=resume_path,
            site_name=args.site,
            headless=args.headless,
        )
    )
    print(f"[layer1] 写入 pending_applications id={app_id}，去 Dashboard「跨站点投递」页审批")
    return 0


if __name__ == "__main__":
    sys.exit(main())
