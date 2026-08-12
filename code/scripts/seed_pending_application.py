"""
造几条假的 pending_applications 记录，供开发/验收「跨站点投递审批」页面用。

存在理由：Layer 1（识别/写入 pending_application 的 agent）还没实现，审批页
（Layer 2）没有真实数据可看。字段结构照抄 docs/multi-site-expansion-design.md
里华为 recon 的真实发现——姓名/邮箱/自我评价解析成功，性别/证件类型/证件号码/
出生日期/联系电话留空；government_id 类字段 candidate_value 永远是空字符串，
只在这里做占位展示，真实值需审批时人工填入。

用法（在 code/ 目录下执行）：
  python scripts/seed_pending_application.py           # 插入 3 条样例记录
  python scripts/seed_pending_application.py --clear    # 先清空 pending_applications 表再插入
"""
import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from services.tracker import ApplicationTracker


def _huawei_fields() -> list:
    return [
        {"field_id": "name", "label": "姓名", "kind": "demographic", "candidate_value": "张三"},
        {"field_id": "email", "label": "邮箱", "kind": "demographic", "candidate_value": "zhangsan@example.com"},
        {"field_id": "self_intro", "label": "自我评价", "kind": "open_question",
         "candidate_value": "五年后端开发经验，熟悉分布式系统与高并发场景。"},
        {"field_id": "gender", "label": "性别", "kind": "demographic", "candidate_value": ""},
        {"field_id": "phone", "label": "联系电话", "kind": "demographic", "candidate_value": ""},
        {"field_id": "birth_date", "label": "出生日期", "kind": "demographic", "candidate_value": ""},
        {"field_id": "id_type", "label": "证件类型", "kind": "government_id", "candidate_value": ""},
        {"field_id": "id_number", "label": "证件号码", "kind": "government_id", "candidate_value": ""},
    ]


def _hytera_fields() -> list:
    return [
        {"field_id": "name", "label": "姓名", "kind": "demographic", "candidate_value": "张三"},
        {"field_id": "email", "label": "邮箱", "kind": "demographic", "candidate_value": "zhangsan@example.com"},
        {"field_id": "school", "label": "毕业院校", "kind": "demographic", "candidate_value": "某某大学"},
        {"field_id": "english_level", "label": "英语能力", "kind": "open_question", "candidate_value": "CET-6"},
        {"field_id": "id_number", "label": "证件号码", "kind": "government_id", "candidate_value": ""},
    ]


SAMPLES = [
    dict(site_name="huawei", job_title="后端开发工程师", company="华为", job_url="https://career.huawei.com/job/1",
         fields=_huawei_fields()),
    dict(site_name="huawei", job_title="AI应用开发工程师", company="华为", job_url="https://career.huawei.com/job/2",
         fields=_huawei_fields()),
    dict(site_name="hytera", job_title="测试开发工程师", company="海能达", job_url="https://app.mokahr.com/su/xxx",
         fields=_hytera_fields()),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="插入前先清空 pending_applications 表")
    args = parser.parse_args()

    tracker = ApplicationTracker()
    if args.clear:
        with tracker.conn:
            tracker.conn.execute("DELETE FROM pending_applications")
        print("已清空 pending_applications 表")

    for sample in SAMPLES:
        app_id = tracker.add_pending_application(**sample)
        print(f"插入 id={app_id} site={sample['site_name']} job_title={sample['job_title']}")

    tracker.close()


if __name__ == "__main__":
    main()
