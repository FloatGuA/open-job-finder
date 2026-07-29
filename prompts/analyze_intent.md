公司：{{company}}
职位：{{job_title}}
最近消息（最新在后，最多 5 条）：
{{messages}}

判断准则：
- 以 HR **最近一条**消息为主判断当前意图；更早的简历/信息交流只是背景。
- **不要因为对话里出现过简历就判 resume_request**——只有 HR 当前正在索要简历才算；简历若已发过，HR 之后的“收到”“好的”等只是客套，属于 general_notice。

请返回 JSON：
{
  "intent": "<interview_invite | offer | rejection | resume_request | general_inquiry | general_notice | unknown>",
  "confidence": "<high | medium | low>"
}

intent 只能为以下之一：interview_invite | offer | rejection | resume_request | general_inquiry | general_notice | unknown
- interview_invite: HR 邀请面试或安排具体面试时间
- offer: HR 发送录用通知或进行薪资谈判
- rejection: HR 委婉拒绝或说明职位已满/不合适
- resume_request: HR **当前正在**请求发送附件简历（历史里已发过、现在只是客套的，不算）
- general_inquiry: HR **当前**主动提出需要你回应的新问题或索要新信息（开放式沟通）
- general_notice: HR 的客套、确认或通知，或简历/信息已提供后的收到、致谢、“我看看”“等通知”等，无需你回应（如“好的”“欢迎投递”“已收到简历”）
- unknown: 无法确定意图
