公司：{{company}}
职位：{{job_title}}
最近消息（最新在后，最多 5 条）：
{{messages}}

请返回 JSON：
{
  "intent": "<interview_invite | offer | rejection | resume_request | general | unknown>",
  "confidence": "<high | medium | low>",
  "needs_reply": <true or false>
}

intent 只能为以下之一：interview_invite | offer | rejection | resume_request | general | unknown
- interview_invite: HR 邀请面试或安排具体面试时间
- offer: HR 发送录用通知或进行薪资谈判
- rejection: HR 委婉拒绝或说明职位已满/不合适
- resume_request: HR 请求发送附件简历
- general: 普通问候、一般性沟通或信息询问
- unknown: 无法确定意图
