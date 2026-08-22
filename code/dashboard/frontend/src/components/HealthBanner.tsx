import { useEffect, useState } from 'react'

import { API, type HealthAlert } from '@/api'

const T_TITLE = '\u9700\u8981\u4f60\u770b\u4e00\u773c'
const T_HINT = '\u8fd9\u4e9b\u5224\u65ad\u53ea\u770b\u8c03\u5ea6\u65e5\u5fd7\u548c\u81ea\u68c0\u8bb0\u5f55\uff1b\u5b83\u4e0d\u4f1a\u5728\u4f60\u6ca1\u6253\u5f00\u8fd9\u4e2a\u9875\u9762\u65f6\u63d0\u9192\u4f60\u3002'

// 「有东西坏了但没人发现」的横幅。渠道选 Dashboard 是用户 2026-08-22 定的
// （别的都要接 MCP，更复杂）。**它的边界**：解决不了「三天没打开」，
// 解决的是「打开了但没看出来有问题」——所以还有个标签页标题角标兜着
// （见 App.tsx 的 useAlertTitleBadge），后台挂着的标签也能看见。
//
// 判据全在后端 services/health_alerts，这里一条判断都不做。
export default function HealthBanner() {
  const [alerts, setAlerts] = useState<HealthAlert[]>([])

  useEffect(() => {
    const load = () => void API.getHealthAlerts()
      .then((r) => setAlerts(r.alerts ?? []))
      .catch(() => {})          // 拿不到就不显示，别在告警条上再报一个错
    load()
    const id = window.setInterval(load, 60_000)
    return () => window.clearInterval(id)
  }, [])

  if (alerts.length === 0) return null
  const worst = alerts.some((a) => a.level === 'error') ? 'error' : 'warn'
  const color = worst === 'error' ? '#ff453a' : '#ff9f0a'

  return (
    <div
      className="rounded-2xl px-4 py-3"
      style={{ background: `${color}14`, border: `1px solid ${color}40` }}
    >
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider" style={{ color }}>
        {T_TITLE}{' ('}{alerts.length}{')'}
      </p>
      <ul className="space-y-1.5">
        {alerts.map((a) => (
          <li key={a.id} className="text-[13px] leading-relaxed">
            <span className="font-medium text-text-1">{a.title}</span>
            {a.detail && <span className="text-text-2">{' \u2014 '}{a.detail}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-text-3">{T_HINT}</p>
    </div>
  )
}
