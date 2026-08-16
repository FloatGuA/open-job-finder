职位：{{job_title}}
公司：{{company}}

已知的求职者个人资料（key -> 值，你只能从这些 key 里选，不能编造新值）：
{{personal_info_keys}}

网页表单里当前为空、需要处理的字段：
{{fields}}

请给每个字段判断 kind 并给出候选：
- demographic：能在上面"已知的求职者个人资料"里找到对应 key 的字段（如姓名/邮箱/电话/性别/出生日期/证件签发国家/证件类型）。返回该 key 的名字（demographic_key），不要自己编值。
- open_question：需要结合职位/公司组织语言回答的开放性字段（如自我评价、期望薪资说明、为什么应聘）。生成一段候选文本（candidate_value）。
- unknown_fact：事实性字段（学校、专业、城市、日期、公司名、证书……），但上面的"已知资料"里**没有**对应内容。这类字段**留空**，candidate_value 必须是空字符串——由本人来填。
  **判据：答案是不是一个只有本人知道的事实？** 是 → unknown_fact，绝不要写"请填写您的学校名称（例如：XX大学）"这种填写说明来充数；那不是答案，是把问题原样退回去。
- government_id：政府证件号码本身（身份证号、护照号等）。注意"证件类型""证件签发国家"这类描述性字段属于 demographic，不是 government_id——government_id 专指号码本身。这类字段**只标记，绝不给出候选值**，candidate_value 必须是空字符串。

请返回 JSON 数组，每个元素对应一个字段：
[
  {
    "field_id": "<原样照抄该字段的 field_id>",
    "kind": "<demographic | open_question | government_id | unknown_fact>",
    "demographic_key": "<kind=demographic 时必填，且必须是上面已知资料里出现过的 key；其余情况留 null>",
    "candidate_value": "<**只有** kind=open_question 时填生成的候选文本；其余三种一律留空字符串>"
  }
]

kind 只能是以下之一：demographic | open_question | government_id | unknown_fact
