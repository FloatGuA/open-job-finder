export interface M1FormIssues {
  /** 有值就不该让它跑：填了也是白跑一趟 */
  blocking?: string
  /** 能跑，但大概率不是你想要的结果 */
  warning?: string
}

/**
 * 点「开始选岗」之前的检查。
 *
 * warning 那条是有来历的：把筛选条件编进入口页 URL 会**静默**过滤掉整类岗位
 * （实测带 project= 的地址只剩 87 条，去掉后 134 条）。不拦死是因为有些站的
 * 入口页本身就带参数。
 *
 * 提示文案一律 \uXXXX：它们会渲染到界面上，裸中文会被 Windows GBK 工具链
 * 静默损坏（注释不在此列，转义了就没人读得懂了）。
 */
export function checkM1Form(site: string, searchUrl: string): M1FormIssues {
  const s = site.trim()
  const u = searchUrl.trim()
  if (!s) return { blocking: '\u8bf7\u586b\u7ad9\u70b9\u6807\u8bc6' }
  if (!u) return { blocking: '\u8bf7\u586b\u5165\u53e3\u9875 URL' }
  if (!/^https?:\/\//i.test(u)) return { blocking: 'URL \u8981\u4ee5 http(s):// \u5f00\u5934' }
  if (u.includes('?')) {
    return { warning: '\u8fd9\u4e2a\u5730\u5740\u5e26\u7b5b\u9009\u53c2\u6570\uff0c\u53ef\u80fd\u9759\u9ed8\u6ee4\u6389\u6574\u7c7b\u5c97\u4f4d\uff08\u5b9e\u6d4b 87 \u6761 vs \u53bb\u6389\u540e 134 \u6761\uff09\u3002\u5efa\u8bae\u53ea\u7ed9\u62db\u8058\u9996\u9875\uff0c\u7b5b\u9009\u4ea4\u7ed9 agent\u3002' }
  }
  return {}
}
