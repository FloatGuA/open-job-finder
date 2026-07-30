你正在把一个职位与一位候选人做匹配评估。
对下面每个维度独立打分（0 到 100）。只返回下面的 JSON，不要输出任何别的内容。

## 职位信息
Title: {{title}}
Company: {{company}}
JD:
{{jd_text}}

## 候选人画像
{{profile_summary}}

## 需要返回的 JSON（每个字段都要填，整数 0-100）：
```json
{
  "dimensions": {
    "skill_match": {
      "score": <0-100>,
      "matched": ["<JD 和简历中都出现的技能>"],
      "missing": ["<JD 要求但简历没有的技能>"]
    },
    "experience_match": {
      "score": <0-100>,
      "jd_requires": "<如 3-5年>",
      "candidate_has": "<来自画像的经验字段>"
    },
    "city_match": {
      "score": <0 或 100>,
      "match": <true|false>
    },
    "salary_match": {
      "score": <0-100>,
      "offered": "<JD 中的薪资>",
      "expected": "<来自画像的期望薪资>"
    },
    "growth_potential": {
      "score": <0-100>,
      "reason": "<一句话，中文>"
    }
  },
  "overall_reason": "<2-3 句话，中文，说明总体评估>"
}
```

打分标准：
- skill_match 90-100：JD 所需技能几乎被简历完全覆盖
- skill_match 50-89：部分重合
- skill_match 0-49：技能差距较大
- experience_match 100：完全匹配；70：差一个档位；0：完全不匹配（如让应届生做要求 10 年经验的岗位）
- city_match：职位城市在候选人城市列表内给 100，否则给 0
- salary_match：offered（提供）>= expected（期望）给 100；更低则按比例下调；无薪资信息给 50
- growth_potential：主观——这个职位是否能推进候选人的职业方向？
