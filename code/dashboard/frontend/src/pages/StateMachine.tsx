import { useEffect, useState } from 'react'
import { API, type ArchitectureLive } from '@/api'
import { useAppContext } from '@/context/app-context'
import DevLabel from '@/components/dev/DevLabel'

// Architecture navigator: a static, hand-maintained map of the whole system with a
// thin live overlay (row counts + current running workflow). Four in-page tabs:
//   arch (backend 4 layers) - flow (W1/W2) - state machines (3) - data model (tables + LLM)
// The static content is kept in lockstep with CLAUDE.md backend layering, the W1/W2
// pipelines, schemas.py AppStatus, STAGE_ORDER and analyze_intent _VALID_INTENTS.
// The live overlay comes from GET /api/architecture (tracker.get_lifecycle_counts).

// -- shared bits -----------------------------------------------------

function Dot({ color }: { color: string }) {
  return <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
}

function CountPill({ n }: { n: number }) {
  return (
    <span
      className="ml-2 shrink-0 rounded-full px-1.5 py-px font-mono text-[13.5px] font-semibold"
      style={{ background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.75)' }}
    >
      {n}
    </span>
  )
}

function Section({ badge, title, sub, children }: {
  badge: string; title: string; sub: string; children: React.ReactNode
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <div className="mb-3 flex items-baseline gap-2.5">
        <span className="rounded font-mono text-[15px] font-bold px-1.5 py-0.5 bg-signal-blue/18 text-signal-bright">{badge}</span>
        <span className="text-[18px] font-semibold text-text-1">{title}</span>
        <span className="text-[15px] text-text-3">{sub}</span>
      </div>
      {children}
    </div>
  )
}

// \u53ef\u5c55\u5f00\u7684\u6280\u672f\u8bb2\u89e3\u5757\uff1a\u6807\u9898\u59cb\u7ec8\u53ef\u89c1\uff0c\u6df1\u5165\u5185\u5bb9\u70b9\u5f00\u624d\u663e\u793a——\u907f\u514d\u6574\u9875\u5806\u6ee1\u957f\u6587\u3002
function Collapsible({ title, hint, accent, children, defaultOpen = false }: {
  title: string; hint?: string; accent: string; children: React.ReactNode; defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} className="group rounded-xl" style={{ background: `${accent}0f`, border: `1px solid ${accent}30` }}>
      <summary
        className="flex cursor-pointer select-none list-none items-center gap-2 px-3.5 py-2.5 [&::-webkit-details-marker]:hidden"
      >
        <span className="text-[13px] transition-transform duration-150 group-open:rotate-90" style={{ color: accent }}>{'▸'}</span>
        <span className="text-[15px] font-semibold" style={{ color: accent }}>{title}</span>
        {hint && <span className="text-[13.5px] text-text-3">{hint}</span>}
      </summary>
      <div className="px-3.5 pb-3.5 pt-0.5">{children}</div>
    </details>
  )
}

// -- (1) architecture tab ---------------------------------------------

type Layer = { layer: string; color: string; what: string; judge: string; files: string }
const LAYER_ROWS: Layer[] = [
  { layer: 'tools/', color: '#0a84ff',
    what: '\u5bf9\u5916\u90e8\u7cfb\u7edf\u7684\u5355\u4e2a\u526f\u4f5c\u7528\u64cd\u4f5c\uff08\u6d4f\u89c8\u5668/DB/LLM\uff09\uff0c\u7ecf registry.call \u8c03\u7528\uff0c\u81ea\u52a8 trace/SSE',
    judge: '\u662f\u4e0d\u662f\u4e00\u6b21\u78b0\u6d4f\u89c8\u5668/DB/LLM \u7684\u6d3b\u513f',
    files: 'browser/ \u00b7 db/ \u00b7 llm/ \u00b7 biz_logic/' },
  { layer: 'pipeline/ (Step)', color: '#30d158',
    what: '\u628a\u591a\u4e2a tool \u7f16\u6392\u6210\u5de5\u4f5c\u6d41\u7684\u4e00\u4e2a\u9636\u6bb5\uff08W1/W2/W3\uff09',
    judge: '\u662f\u4e0d\u662f\u67d0\u6761\u5de5\u4f5c\u6d41\u91cc\u7684\u4e00\u6bb5',
    files: 'w1/ \u00b7 w2/ \u00b7 w3/ \u00b7 common' },
  { layer: 'services/', color: '#ff9f0a',
    what: '\u5171\u4eab\u57fa\u5efa/\u5355\u4f8b\uff08tracker\u3001llm_client\u3001config_manager\uff09+ \u4ece server.py \u4e0b\u6c89\u7684\u7f16\u6392 service',
    judge: '\u662f\u4e0d\u662f\u88ab\u591a\u5904\u5171\u7528\u7684\u57fa\u5efa\uff0c\u6216\u4ece\u63a5\u7ebf\u5c42\u62c6\u51fa\u7684\u6709\u72b6\u6001\u7f16\u6392',
    files: 'tracker \u00b7 llm_client \u00b7 config_manager \u00b7 scheduler_service \u00b7 workflow_orchestration \u00b7 run_log_reader \u00b7 run_diagnostics' },
  { layer: 'dashboard/server.py', color: '#bf5af2',
    what: '\u53ea\u505a HTTP \u63a5\u7ebf\uff1a\u89e3\u6790\u8bf7\u6c42 \u2192 \u8c03 tool/step/service \u2192 \u5e8f\u5217\u5316\u8fd4\u56de\uff082026-07 \u51cf\u91cd 2638\u21922038 \u884c\uff09',
    judge: '\u7aef\u70b9\u4e0d\u51c6\u5185\u8054\u6d4f\u89c8\u5668/LLM/\u4e1a\u52a1\u903b\u8f91\uff0c\u7f16\u6392\u4e0b\u6c89 service',
    files: 'server.py + SSE\uff08\u8c03\u5ea6/\u961f\u5217\u6267\u884c/\u81ea\u68c0/\u65e5\u5fd7\u89e3\u6790\u5df2\u4e0b\u6c89\uff09' },
]

type FeRow = { part: string; color: string; what: string; files: string }
const FE_ROWS: FeRow[] = [
  { part: '\u58f3 / \u5e03\u5c40', color: '#64d2ff', what: 'Sidebar + Topbar + main \u4e09\u6bb5\uff0c\u9875\u9762\u6302\u5728 main \u91cc\u6eda\u52a8', files: 'App.tsx \u00b7 components/layout' },
  { part: '\u8def\u7531', color: '#0a84ff', what: '\u6ca1\u7528 react-router\uff1a\u4e00\u4e2a page \u72b6\u6001 + \u6620\u5c04\u8868\u624b\u52a8\u5207 8 \u9875', files: 'App.tsx \u00b7 PAGE_COMPONENTS' },
  { part: '\u72b6\u6001', color: '#bf5af2', what: '\u5355\u4e2a React Context \u7ba1\u5168\u5c40\uff0c\u65e0 Redux/Zustand', files: 'context/app-context.ts' },
  { part: 'API \u5c42', color: '#30d158', what: '\u7edf\u4e00\u5c01\u88c5 fetch + \u7c7b\u578b\uff0c\u9875\u9762\u53ea\u8c03 API.xxx()', files: 'api/index.ts' },
  { part: '\u5b9e\u65f6\u6d41', color: '#ff9f0a', what: 'EventSource \u5e38\u9a7b\u8fde\u63a5 + 2s \u65ad\u7ebf\u81ea\u52a8\u91cd\u8fde', files: 'hooks/useWorkflowStream.ts' },
  { part: '\u7ec4\u4ef6', color: '#5e5ce6', what: 'dev / layout / ui / workflow \u56db\u7ec4\u590d\u7528\u4ef6', files: 'components/' },
  { part: '\u6784\u5efa', color: '#8e8e93', what: 'Vite \u6253\u5305 \u2192 static/\uff0cversion.ts \u6253\u8fdb\u4ea7\u7269', files: 'vite \u00b7 scripts/build.mjs' },
]
const FE_FLOW = ['SSE \u4e00\u5e27 JSON', 'useWorkflowStream \u56de\u8c03', 'pendingEventsRef \u7f13\u51b2', '\u6bcf 200ms flush', 'state \u00b7 \u7559\u6700\u540e 200', '\u91cd\u6e32\u67d3 UI']


function ArchTab({ live, running }: { live: ArchitectureLive | null; running: string | null }) {
  void live
  return (
    <div className="space-y-4">
      <SystemOverview running={running} />
      <CommsDetail />
      <Section badge={'\u2462'} title={'\u540e\u7aef\u56db\u5c42\u67b6\u6784'} sub={'\u526f\u4f5c\u7528\u2192tool \u00b7 \u9636\u6bb5\u2192step \u00b7 \u57fa\u5efa\u2192service \u00b7 \u7aef\u70b9\u53ea\u63a5\u7ebf'}>
        <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="grid grid-cols-[210px_1fr_1fr] gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
            style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span>{'\u5c42'}</span>
            <span>{'\u653e\u4ec0\u4e48'}</span>
            <span>{'\u5224\u636e / \u4ee3\u8868'}</span>
          </div>
          {LAYER_ROWS.map((r) => (
            <div key={r.layer} className="grid grid-cols-[210px_1fr_1fr] items-start gap-2 px-3 py-2.5"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="flex items-center gap-2">
                <Dot color={r.color} />
                <span className="font-mono text-[15px] text-text-1">{r.layer}</span>
              </span>
              <span className="text-[15px] leading-relaxed text-text-2">{r.what}</span>
              <span className="text-[14.5px] leading-relaxed text-text-3">
                {r.judge}
                <span className="mt-0.5 block font-mono text-[14px] text-text-2">{r.files}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 space-y-2">
          <Collapsible title={'ToolRegistry\uff1a\u628a\u56db\u5c42\u7c98\u8d77\u6765'} hint={'\u4e3a\u4ec0\u4e48 step \u4e0d\u76f4\u63a5 new tool'} accent="#0a84ff">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'step \u4e0d\u76f4\u63a5 new tool\uff0c\u800c\u662f registry.call(name, ...)\u3002registry \u6301\u6709 browser/db/llm \u5171\u4eab\u8d44\u6e90\uff0c\u5e76\u5728\u6bcf\u6b21\u8c03\u7528\u524d\u540e\u81ea\u52a8\u8bb0 trace + \u63a8 SSE\u2014\u2014\u7ed5\u5f00 registry \u5c31\u6ca1\u4e86\u53ef\u89c2\u6d4b\u6027\u3002'}
            </p>
          </Collapsible>
          <Collapsible title={'\u94c1\u5f8b\uff1a\u7aef\u70b9\u4e0d\u51c6\u5185\u8054\u526f\u4f5c\u7528'} hint={'\u4e3a\u4ec0\u4e48\u8fd9\u6761\u6700\u8981\u547d'} accent="#ff453a">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'\u7aef\u70b9\u5185\u8054\u6d4f\u89c8\u5668/LLM/\u4e1a\u52a1\u903b\u8f91 \u2192 \u5fc5\u7136\u5236\u9020\u4e24\u4efd\u5206\u53c9\u5b9e\u73b0\uff08\u52a0\u56fa\u4e00\u4e2a\u6f0f\u4e00\u4e2a\uff09+ \u4e0d\u53ef\u89c2\u6d4b\u3002\u7eaf\u8bfb\u7aef\u70b9\uff08GET /api/jobs\u3001/api/stats\uff09\u53ef\u76f4\u8c03 tracker\uff0c\u4e0d\u5f3a\u884c tool \u5316\u3002'}
            </p>
          </Collapsible>
          <Collapsible title={'\u94c1\u5f8b 2\uff1a\u4e00\u4e2a\u72b6\u6001\u8f6c\u6362\u53ea\u80fd\u6709\u4e00\u4efd SQL'} hint={'\u4e00\u6b21\u5ba1\u67e5\u8fde\u6293\u56db\u4f8b\u5206\u53c9'} accent="#ff453a">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'tracker \u72ec\u5360\u8fde\u63a5/schema/\u8fc1\u79fb\u4e0e\u6bcf\u4e2a\u5199\u64cd\u4f5c\u7684\u552f\u4e00\u5b9e\u73b0\uff1btools/db/* \u662f\u8584\u58f3\u8c03 tracker\uff1b\u7aef\u70b9\u65e0 SQL\u3002\u540c\u4e00\u8f6c\u6362\u5b58\u5728\u4e24\u4efd\u5b9e\u73b0\u5fc5\u7136\u6f02\u79fb\u2014\u20142026-07 \u4e00\u6b21\u5ba1\u67e5\u8fde\u6293\u56db\u4f8b\uff1a\u6807\u8bb0\u5df2\u53d1\u9001\uff08\u4e00\u4efd\u5199 NULL \u800c\u975e sent \u2192 \u53ef\u80fd\u4e8c\u6b21\u53d1\u9001\uff09\u3001\u5199\u5206\u6790\u7ed3\u679c\uff08\u7f3a\u6c34\u4f4d\u7ebf\u5b57\u6bb5\uff09\u3001\u6295\u9012\u65f6\u95f4\u8bed\u4e49\u76f8\u53cd\u3001\u5192\u70df\u81ea\u6301\u6267\u884c\u8def\u5f84\u3002\u5224\u636e\uff1a\u540c\u4e00\u5217\u5728\u4e0d\u540c\u5b9e\u73b0\u91cc\u7684 CASE \u5206\u652f\u4e0d\u4e00\u81f4\u3002'}
            </p>
          </Collapsible>
          <Collapsible title={'server.py \u51cf\u91cd\uff1a\u7f16\u6392\u4e0b\u6c89 service\uff082026-07\uff0c-600 \u884c\uff09'} hint={'\u63a5\u7ebf\u5c42\u600e\u4e48\u7626\u8eab\u7684'} accent="#bf5af2">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'server.py \u66fe\u628a\u8c03\u5ea6\u3001\u961f\u5217\u6267\u884c\u3001\u81ea\u68c0\u3001\u9650\u6d41\u3001run \u65e5\u5fd7\u89e3\u6790\u7b49\u6709\u72b6\u6001\u7f16\u6392\u6df7\u8fdb\u63a5\u7ebf\u5c42\uff082638 \u884c\uff09\u3002\u4e09\u6279\u4e0b\u6c89\u4e3a service\uff1a'}
            </p>
            <ul className="mt-2 space-y-1.5 text-[14px] text-text-2">
              <li><span className="font-mono text-signal-amber">scheduler_service</span>{' \u2014 APScheduler \u751f\u547d\u5468\u671f\uff0c\u8de8\u7c07\u4f9d\u8d56\u6ce8\u5165'}</li>
              <li><span className="font-mono text-signal-amber">workflow_orchestration</span>{' \u2014 \u961f\u5217 runner + W1/W2/W3 \u6267\u884c + \u9650\u6d41 + \u81ea\u68c0 + \u5192\u70df\uff0cget_state \u8bbf\u95ee\u5668'}</li>
              <li><span className="font-mono text-signal-amber">run_log_reader</span>{' \u2014 run \u65e5\u5fd7\u53ea\u8bfb\u89e3\u6790\uff0c\u7eaf\u51fd\u6570'}</li>
            </ul>
            <p className="mt-2 text-[13.5px] leading-relaxed text-text-3">
              {'\u4f9d\u8d56\u6ce8\u5165\u65b9\u5f0f\u6309\u300c\u6709\u65e0\u72b6\u6001\u300d\u9009\uff1a\u6709\u72b6\u6001\u7684\u7528 service \u7c7b + \u6ce8\u5165\u4f9d\u8d56\uff08\u53ef\u8131\u79bb FastAPI \u5355\u6d4b\uff09\uff0c\u65e0\u72b6\u6001\u7684\u7528\u7eaf\u51fd\u6570 + \u8def\u5f84\u4f20\u53c2\u3002\u7aef\u70b9\u56de\u5f52\u8584\u63a5\u7ebf\uff0cserver.py \u964d\u5230 2038 \u884c\u3002'}
            </p>
          </Collapsible>
        </div>
      </Section>
      <Section badge={'\u2463'} title={'\u524d\u7aef\u67b6\u6784'} sub={'React SPA \u00b7 \u58f3/\u8def\u7531/\u72b6\u6001/API/\u7ec4\u4ef6 \u00b7 \u4e00\u4efd Context \u7ba1\u5168\u5c40'}>
        <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="grid grid-cols-[130px_1fr_1fr] gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
            style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span>{'\u90e8\u5206'}</span>
            <span>{'\u804c\u8d23'}</span>
            <span>{'\u4ee3\u8868\u6587\u4ef6'}</span>
          </div>
          {FE_ROWS.map((r) => (
            <div key={r.part} className="grid grid-cols-[130px_1fr_1fr] items-start gap-2 px-3 py-2.5"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="flex items-center gap-2">
                <Dot color={r.color} />
                <span className="text-[15px] text-text-1">{r.part}</span>
              </span>
              <span className="text-[15px] leading-relaxed text-text-2">{r.what}</span>
              <span className="font-mono text-[14px] leading-relaxed text-text-3">{r.files}</span>
            </div>
          ))}
        </div>

        <p className="mb-2 mt-4 text-[14px] font-semibold uppercase tracking-wider text-text-3">{'\u524d\u7aef\u5185\u90e8\u6570\u636e\u6d41 \u00b7 \u4e00\u5e27 SSE \u5230\u5c4f\u5e55'}</p>
        <div className="flex flex-wrap items-center gap-x-1 gap-y-2">
          {FE_FLOW.map((s, i) => (
            <span key={s} className="flex items-center gap-1">
              <span className="rounded-lg px-2.5 py-1.5 text-[13.5px] text-text-2"
                style={{ background: 'rgba(100,210,255,0.08)', border: '1px solid rgba(100,210,255,0.2)' }}>{s}</span>
              {i < FE_FLOW.length - 1 && <span className="text-text-3">{'\u2192'}</span>}
            </span>
          ))}
        </div>
        <p className="mt-2 text-[13.5px] leading-relaxed text-text-3">{'\u53e6\u6709 10s \u8f6e\u8be2\u515c\u5e95\u540c\u6b65 workflow / control \u72b6\u6001\uff0cSSE \u65ad\u4e86\u4e5f\u4e0d\u4f1a\u4e00\u76f4\u5361\u5728\u65e7\u72b6\u6001\u3002'}</p>

        <div className="mt-3 space-y-2">
          <Collapsible title={'\u4e3a\u4ec0\u4e48\u4e0d\u7528 react-router'} hint={'8 \u4e2a\u9875\u9762\u9760\u4e00\u4e2a page \u72b6\u6001\u5207'} accent="#64d2ff">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'\u6574\u4e2a\u540e\u53f0\u662f\u5355\u9875\u5e94\u7528\uff0c\u4e0d\u9700\u8981\u6d4f\u89c8\u5668 URL \u8def\u7531\u3002App.tsx \u91cc\u4e00\u4e2a page \u72b6\u6001 + PAGE_COMPONENTS \u6620\u5c04\u8868\uff0cSidebar \u70b9\u4e00\u4e0b\u5c31\u6362 main \u91cc\u6302\u7684\u7ec4\u4ef6\u2014\u20148 \u4e2a\u9875\u9762\u5168\u9760\u5b83\u5207\u3002\u7b80\u5355\u80dc\u8fc7\u5f15\u4e00\u4e2a\u8def\u7531\u5e93\u3002'}
            </p>
          </Collapsible>
          <Collapsible title={'SSE \u6d2a\u6d41\u4e3a\u4ec0\u4e48\u8981\u7f13\u51b2\u9650\u6d41'} hint={'\u5426\u5219\u6807\u7b7e\u9875\u80fd\u6da8\u5230\u6570 GB'} accent="#30d158">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'debug \u6a21\u5f0f\u4e0b\u6bcf\u6b21 registry.call \u90fd\u63a8\u4e00\u4e2a tool \u7ea7\u4e8b\u4ef6\uff0c\u4e00\u6b21\u957f\u8dd1\u4e0a\u4e07\u6761\u3002\u9010\u6761 setState \u4f1a\u628a\u6574\u68f5\u7ec4\u4ef6\u6811\u91cd\u6e32\u67d3\u4e0a\u4e07\u6b21\u3001\u5185\u5b58\u6491\u5230\u6570 GB\u3002\u6240\u4ee5\u4e8b\u4ef6\u5148\u585e\u8fdb pendingEventsRef \u7f13\u51b2\uff0c\u6bcf 200ms(5Hz) \u624d flush \u5230 state\uff0c\u4e14\u53ea\u7559\u6700\u540e 200 \u6761\uff1b\u9a8c\u8bc1\u7801\u63d0\u793a\u8fd9\u7c7b\u4fbf\u5b9c\u7684\u526f\u4f5c\u7528\u4ecd\u9010\u6761\u5373\u65f6\u5904\u7406\u3002'}
            </p>
          </Collapsible>
          <Collapsible title={'\u4e00\u4efd Context \u7ba1\u5168\u5c40'} hint={'\u65e0 Redux/Zustand'} accent="#bf5af2">
            <p className="text-[14.5px] leading-relaxed text-text-2">
              {'page / workflowRunning / progressEvents / isPaused \u5168\u653e\u4e00\u4e2a AppContext\uff0c\u4efb\u4f55\u9875\u9762 useAppContext() \u5c31\u80fd\u8bfb\u3002\u6ca1\u5f15\u72b6\u6001\u7ba1\u7406\u5e93\u2014\u2014\u6570\u636e\u89c4\u6a21\u6491\u5f97\u4f4f\uff0c\u518d\u914d\u5408 10s \u8f6e\u8be2\u515c\u5e95\uff0c\u72b6\u6001\u4e0d\u4f1a\u6f02\u3002'}
            </p>
          </Collapsible>
        </div>
      </Section>
    </div>
  )
}


// -- (0) system overview (whole-system architecture diagram) --------------

function OverBox({ x, y, w, h, color, title, sub }: {
  x: number; y: number; w: number; h: number; color: string; title: string; sub: string
}) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={12}
        fill={`${color}14`} stroke={`${color}88`} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + h / 2 - 8} textAnchor="middle" dominantBaseline="central"
        fontSize={14.5} fontWeight={600} fill="#f5f5f7">{title}</text>
      <text x={x + w / 2} y={y + h / 2 + 11} textAnchor="middle" dominantBaseline="central"
        fontSize={11.5} fill="#a1a1a6">{sub}</text>
    </g>
  )
}

function SystemOverview({ running }: { running: string | null }) {
  const W = 720
  const H = 440
  const cx = W / 2
  const agent = running
    ? { color: '#30d158', label: `\u8fd0\u884c\u4e2d\uff1a${running.toUpperCase()}` }
    : { color: 'rgba(255,255,255,0.35)', label: '\u7a7a\u95f2' }
  return (
    <Section badge={'\u2460'} title={'\u7cfb\u7edf\u5168\u666f'} sub={'\u524d\u7aef \u00b7 \u540e\u7aef \u00b7 \u6570\u636e\u5e93 \u00b7 \u5916\u90e8\uff0c\u8c01\u8fde\u8c01\u4e00\u773c\u770b\u6e05'}>
      <div className="mb-3 flex items-center gap-2 text-[15px] text-text-3">
        <Dot color={agent.color} />
        <span>{'\u5f53\u524d agent'}</span>
        <span className="font-mono text-text-2">{agent.label}</span>
      </div>
      <div className="overflow-x-auto">
        <svg width={W} height={H} style={{ display: 'block' }}>
          <defs>
            <marker id="ov-arw" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="rgba(255,255,255,0.5)" />
            </marker>
          </defs>

          <line x1={cx - 14} y1={80} x2={cx - 14} y2={138} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <line x1={cx + 14} y1={138} x2={cx + 14} y2={80} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <text x={cx + 32} y={102} fontSize={12} fill="#c7c7cc">{'HTTP \u4e00\u95ee\u4e00\u7b54'}</text>
          <text x={cx + 32} y={122} fontSize={12} fill="#c7c7cc">{'SSE \u5b9e\u65f6\u63a8\u9001'}</text>

          <line x1={cx} y1={200} x2={cx} y2={228} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} />
          <line x1={129} y1={228} x2={591} y2={228} stroke="rgba(255,255,255,0.25)" strokeWidth={1.5} />
          <line x1={129} y1={228} x2={129} y2={262} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <line x1={360} y1={228} x2={360} y2={262} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <line x1={591} y1={228} x2={591} y2={262} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <text x={cx + 12} y={220} fontSize={12} fill="#8e8e93">{'\u59d4\u6258 registry.call'}</text>

          <line x1={129} y1={318} x2={129} y2={368} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <line x1={360} y1={318} x2={360} y2={368} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <line x1={591} y1={318} x2={591} y2={368} stroke="rgba(255,255,255,0.4)" strokeWidth={1.5} markerEnd="url(#ov-arw)" />
          <text x={129} y={354} textAnchor="middle" fontSize={11.5} fill="#8e8e93">{'\u64cd\u63a7\u6d4f\u89c8\u5668'}</text>
          <text x={360} y={354} textAnchor="middle" fontSize={11.5} fill="#8e8e93">{'\u8bfb\u5199 SQL'}</text>
          <text x={591} y={354} textAnchor="middle" fontSize={11.5} fill="#8e8e93">{'\u8c03 LLM'}</text>

          <OverBox x={cx - 105} y={22} w={210} h={58} color="#64d2ff" title={'\u6d4f\u89c8\u5668 \u00b7 React \u9762\u677f'} sub={'\u524d\u7aef \u00b7 \u4f60\u770b\u5230\u548c\u70b9\u7684\u754c\u9762'} />
          <OverBox x={cx - 115} y={140} w={230} h={60} color="#bf5af2" title={'FastAPI \u670d\u52a1\u5668 :8765'} sub={'\u540e\u7aef\u5927\u95e8 \u00b7 \u53ea\u63a5\u7ebf\u8f6c\u53d1'} />
          <OverBox x={24} y={262} w={210} h={56} color="#30d158" title={'pipeline \u00b7 W1/W2/W3 \u6d41\u7a0b'} sub={'\u628a tool \u4e32\u6210\u5de5\u4f5c\u6d41'} />
          <OverBox x={255} y={262} w={210} h={56} color="#ff9f0a" title={'services \u00b7 \u5171\u7528\u57fa\u5efa'} sub={'\u6d4f\u89c8\u5668/DB/LLM \u5355\u4f8b'} />
          <OverBox x={486} y={262} w={210} h={56} color="#0a84ff" title={'tools \u00b7 \u5355\u4e2a\u52a8\u4f5c'} sub={'\u4e00\u6b21\u78b0\u6d4f\u89c8\u5668/DB/LLM'} />
          <OverBox x={24} y={368} w={210} h={56} color="#8e8e93" title={'\u771f\u5b9e Chrome \u2192 Boss\u76f4\u8058'} sub={'DrissionPage \u64cd\u63a7'} />
          <OverBox x={255} y={368} w={210} h={56} color="#ff9f0a" title={'SQLite \u6570\u636e\u5e93'} sub={'jobs.db \u00b7 \u6c38\u4e45\u8d26\u672c'} />
          <OverBox x={486} y={368} w={210} h={56} color="#5e5ce6" title={'LLM \u5927\u8111'} sub={'\u6253\u5206 / \u8bfb\u61c2 HR'} />
        </svg>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl p-3" style={{ background: 'rgba(100,210,255,0.06)', border: '1px solid rgba(100,210,255,0.18)' }}>
          <p className="text-[15px] font-semibold" style={{ color: '#64d2ff' }}>{'\u524d\u7aef\u53ea\u505a\u4e24\u4ef6\u4e8b'}</p>
          <p className="mt-1 text-[14.5px] leading-relaxed text-text-2">{'\u2460 \u628a\u6570\u636e\u753b\u6210\u754c\u9762\u7ed9\u4f60\u770b\uff1b\u2461 \u4f60\u4e00\u70b9\uff0c\u5c31\u628a\u8bf7\u6c42\u53d1\u7ed9\u540e\u7aef\u3002\u5b83\u81ea\u5df1\u4e0d\u78b0\u6d4f\u89c8\u5668 / AI / \u6570\u636e\u5e93\u3002'}</p>
        </div>
        <div className="rounded-xl p-3" style={{ background: 'rgba(191,90,242,0.06)', border: '1px solid rgba(191,90,242,0.18)' }}>
          <p className="text-[15px] font-semibold" style={{ color: '#bf5af2' }}>{'\u4e24\u6761\u8fde\u63a5\u7ebf'}</p>
          <p className="mt-1 text-[14.5px] leading-relaxed text-text-2">{'\u2460 HTTP \u4e00\u95ee\u4e00\u7b54\uff1a\u4f60\u70b9 \u2192 \u524d\u7aef\u95ee \u2192 \u540e\u7aef\u7b54\uff1b\u2461 SSE \u5b9e\u65f6\u63a8\u9001\uff1a\u540e\u7aef\u6bcf\u5b8c\u6210\u4e00\u6b65\u5c31\u5e7f\u64ad\uff0c\u8fdb\u5ea6\u6761\u5b9e\u65f6\u8df3\u3002'}</p>
        </div>
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-text-3">{'\u540e\u7aef\u5927\u95e8\uff08server.py\uff09\u53ea\u63a5\u7ebf\u8f6c\u53d1\uff0c\u771f\u6b63\u5e72\u6d3b\u4ea4\u7ed9 pipeline / services / tools\uff0c\u5b83\u4eec\u518d\u53bb\u64cd\u63a7\u771f\u5b9e\u6d4f\u89c8\u5668\u3001\u8bfb\u5199\u6570\u636e\u5e93\u3001\u8c03 LLM\u3002\u8fd9\u4e5f\u662f\u5168\u9879\u76ee\u7684\u94c1\u5f8b\uff1a\u7aef\u70b9\u4e0d\u5185\u8054\u526f\u4f5c\u7528\u3002'}</p>
    </Section>
  )
}


// -- (1b) comms detail: how frontend & backend talk ----------------------

function RoundTrip({ n, t }: { n: string; t: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[12px] font-bold"
        style={{ background: 'rgba(255,255,255,0.1)', color: '#f5f5f7' }}>{n}</span>
      <span className="text-[14px] leading-relaxed text-text-2">{t}</span>
    </div>
  )
}

function Wire({ label, accent, lines }: { label: string; accent: string; lines: string[] }) {
  return (
    <div>
      <p className="mb-1 text-[13px] font-semibold" style={{ color: accent }}>{label}</p>
      <div className="overflow-x-auto whitespace-pre rounded-lg p-2.5 font-mono text-[12.5px] leading-relaxed text-text-2"
        style={{ background: 'rgba(0,0,0,0.28)' }}>
        {lines.map((ln, i) => <div key={i}>{ln === '' ? '\u00a0' : ln}</div>)}
      </div>
    </div>
  )
}

function CommsDetail() {
  const reqLines = [
    'POST /api/workflow/apply HTTP/1.1',
    'Host: localhost:8765',
    'Content-Type: application/json',
    '',
    '{"max_cards":15,"score_threshold":60,"dry_run":false}',
  ]
  const respLines = [
    'HTTP/1.1 200 OK',
    'Content-Type: application/json',
    '',
    '{"status":"started","workflow":"apply"}',
  ]
  const sseLines = [
    'GET /api/workflow/stream   \u2190 \u5f00\u9875\u65f6\u5c31\u8fde\u4e0a\uff0c\u4e00\u76f4\u5f00\u7740',
    'HTTP/1.1 200 OK',
    'Content-Type: text/event-stream',
    '',
    'data: {"workflow":"w1","step":"navigate","status":"running","message":"\u6253\u5f00 Boss \u641c\u7d22\u9875"}',
    '',
    'data: {"workflow":"w1","step":"score","status":"done","message":"\u7b97\u6cd5\u5de5\u7a0b\u5e08 \u00b7 82\u5206 \u8fbe\u6807","scope":{"job_id":"abc123"}}',
    '',
    'data: {"workflow":"w1","step":"apply","status":"done","message":"\u5df2\u6295\u9012"}',
    '',
    'data: {"workflow":"w1","step":"done","status":"done","message":"\u672c\u6b21\u6295\u4e86 2 \u4e2a\uff0c\u8df3\u8fc7 13 \u4e2a"}',
  ]
  return (
    <Section badge={'\u2461'} title={'\u524d\u540e\u7aef\u600e\u4e48\u6c9f\u901a'} sub={'\u8bf7\u6c42 / \u63a8\u9001\u4e24\u6761\u7ebf \u00b7 \u6570\u636e\u90fd\u662f JSON'}>
      <div className="mb-3 rounded-xl p-3" style={{ background: 'rgba(255,159,10,0.06)', border: '1px solid rgba(255,159,10,0.2)' }}>
        <p className="text-[14.5px] leading-relaxed text-text-2">
          <span className="font-semibold text-signal-amber">{'JSON \u2260 JSONL\uff1a'}</span>
          {'\u5b9e\u65f6\u901a\u4fe1\u6d41\u52a8\u7684\u662f\u4e00\u6761\u6761 JSON\uff08\u4e00\u5305\u6570\u636e\uff09\u3002\u540e\u7aef\u628a\u8fd9\u4e9b\u4e8b\u4ef6\u300c\u4e00\u884c\u4e00\u6761\u300d\u8ffd\u52a0\u5199\u8fdb\u78c1\u76d8\u5b58\u6863\uff0c\u90a3\u4e2a\u6587\u4ef6\u624d\u53eb JSONL\u3002\u524d\u7aef\u53ea\u6709\u56de\u653e\u5386\u53f2\u8fd0\u884c\uff08'}
          <span className="font-mono text-text-3">{'GET /api/runs/{id}/events'}</span>
          {'\uff09\u65f6\u624d\u8bfb JSONL \u2014\u2014 \u5b83\u5c31\u662f\u8fd9\u4e9b JSON \u843d\u76d8\u540e\u7684\u5b58\u6863\u5f62\u6001\u3002'}
        </p>
      </div>

      <div className="grid gap-2 lg:grid-cols-2">
        <div className="rounded-xl p-3.5" style={{ background: 'rgba(100,210,255,0.05)', border: '1px solid rgba(100,210,255,0.18)' }}>
          <p className="text-[15.5px] font-semibold" style={{ color: '#64d2ff' }}>{'\u2460 \u4f60\u95ee\u5b83\u7b54 \u00b7 HTTP \u8bf7\u6c42'}</p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-text-2">{'\u524d\u7aef\u7528\u6d4f\u89c8\u5668\u81ea\u5e26\u7684 fetch \u53d1\u4e00\u4e2a\u8bf7\u6c42\uff0c\u540e\u7aef\u529e\u5b8c\u628a\u7ed3\u679c\u4f5c\u4e3a JSON \u8fd4\u56de\u3002\u4e24\u79cd\u7528\u9014\uff1a'}</p>
          <ul className="mt-2 space-y-1.5 text-[14px] text-text-2">
            <li><span className="font-mono text-signal-green">GET</span>{' \u53d6\u6570\u636e \u2014\u2014 '}<span className="font-mono text-text-3">{'/api/jobs \u00b7 /api/stats'}</span></li>
            <li><span className="font-mono text-signal-amber">POST</span>{' \u89e6\u53d1\u52a8\u4f5c \u2014\u2014 '}<span className="font-mono text-text-3">{'/api/workflow/apply \u00b7 /api/workflow/check'}</span></li>
          </ul>
        </div>
        <div className="rounded-xl p-3.5" style={{ background: 'rgba(48,209,88,0.05)', border: '1px solid rgba(48,209,88,0.18)' }}>
          <p className="text-[15.5px] font-semibold" style={{ color: '#30d158' }}>{'\u2461 \u5b83\u4e3b\u52a8\u64ad\u62a5 \u00b7 SSE \u5b9e\u65f6\u63a8\u9001'}</p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-text-2">{'\u6295\u9012\u8981\u8dd1\u51e0\u5206\u949f\uff0c\u4e0d\u80fd\u8ba9\u4f60\u4e00\u76f4\u5237\u65b0\u3002\u524d\u7aef\u4e00\u5f00\u9875\u5c31\u5e38\u9a7b\u4e00\u6761\u8fde\u63a5 '}<span className="font-mono text-signal-bright">{'GET /api/workflow/stream'}</span>{'\uff0c\u540e\u7aef\u6bcf\u5b8c\u6210\u4e00\u6b65\u5c31\u987a\u7740\u8fd9\u6761\u7ebf\u63a8\u4e00\u6761 JSON \u4e8b\u4ef6\u8fc7\u6765\uff0c\u8fdb\u5ea6\u6761\u81ea\u5df1\u8df3\u3002'}</p>
        </div>
      </div>

      <details className="mt-3 rounded-xl" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
        <summary className="cursor-pointer select-none px-3.5 py-2.5 text-[14.5px] font-semibold text-signal-bright">{'\u70b9\u5f00\u770b\u300c\u9010\u5b57\u8282\u5b9e\u51b5\u300d\uff1a\u70b9\u4e00\u6b21\u5f00\u59cb\u6295\u9012\uff0c\u7f51\u7ebf\u4e0a\u5230\u5e95\u8dd1\u4e86\u4ec0\u4e48'}</summary>
        <div className="space-y-3 px-3.5 pb-3.5">
          <Wire label={'\u2460 \u524d\u7aef\u53d1\u51fa\u7684\u8bf7\u6c42\uff08\u539f\u59cb HTTP \u62a5\u6587\uff09'} accent="#64d2ff" lines={reqLines} />
          <Wire label={'\u2461 \u540e\u7aef\u51e0\u5341\u6beb\u79d2\u5c31\u56de\u7684\u54cd\u5e94 \u2014\u2014 \u771f\u6b63\u7684\u6d3b\u513f\u8f6c\u53bb\u540e\u53f0\u8dd1'} accent="#30d158" lines={respLines} />
          <Wire label={'\u2462 \u90a3\u6761\u5e38\u9a7b SSE \u8fde\u63a5\u4e0a\uff0c\u540e\u7aef\u4e00\u5e27\u4e00\u5e27\u5730\u63a8\uff08\u6bcf\u5e27 = data: \u4e00\u884c JSON \u4e00\u4e2a\u7a7a\u884c\uff09'} accent="#bf5af2" lines={sseLines} />
          <p className="text-[13px] leading-relaxed text-text-3">{'\u524d\u7aef EventSource \u6bcf\u6536\u5230\u4e00\u5e27\u5c31 JSON.parse \u51fa\u5bf9\u8c61\uff0c\u5237\u65b0\u8fdb\u5ea6\uff1b\u6536\u5230 status:"done" \u90a3\u5e27\u5c31\u77e5\u9053\u7ed3\u675f\u3002\u8fd9\u4e9b\u5e27\u540c\u65f6\u88ab\u4e00\u884c\u884c\u5199\u8fdb\u672c\u6b21\u8fd0\u884c\u7684 .jsonl \u5b58\u6863 \u2014\u2014 \u90a3\u4efd\u6587\u4ef6\u5c31\u662f JSONL\u3002'}</p>
        </div>
      </details>

      <p className="mb-1.5 mt-3.5 text-[14px] font-semibold uppercase tracking-wider text-text-3">{'\u70b9\u4e00\u6b21\u300c\u5f00\u59cb\u6295\u9012\u300d\u7684\u5b8c\u6574\u6765\u56de'}</p>
      <div className="space-y-1.5">
        <RoundTrip n={'1'} t={'\u524d\u7aef POST /api/workflow/apply \u2014\u2014 \u540e\u7aef\u79d2\u56de 200\uff0c\u771f\u6b63\u7684\u6d3b\u513f\u5728\u540e\u53f0\u5f00\u8dd1\uff08\u4e0d\u5360\u7740\u8fd9\u6761\u8bf7\u6c42\u7b49\u5b83\u8dd1\u5b8c\uff09\u3002'} />
        <RoundTrip n={'2'} t={'\u90a3\u6761\u5e38\u9a7b\u7684 SSE \u8fde\u63a5\uff08\u5f00\u9875\u65f6\u5c31\u8fde\u4e0a\u4e86\uff09\u5f00\u59cb\u6536\u4e8b\u4ef6\uff1a\u641c\u7d22 \u2192 \u6253\u5206 \u2192 \u6295\u9012\uff0c\u6bcf\u4e00\u6b65\u4e00\u6761\u3002'} />
        <RoundTrip n={'3'} t={'\u524d\u7aef\u8fb9\u6536\u8fb9\u753b\uff1a\u8fdb\u5ea6\u6761\u63a8\u8fdb\u3001\u65e5\u5fd7\u4e00\u6761\u6761\u5192\u3001\u6295\u9012\u6570\u5b57\u5f80\u4e0a\u52a0\u3002'} />
        <RoundTrip n={'4'} t={'\u540e\u7aef\u63a8\u4e00\u6761 status=done \u7684\u4e8b\u4ef6 \u2192 \u524d\u7aef\u77e5\u9053\u7ed3\u675f\uff0c\u663e\u793a\u6700\u7ec8\u6210\u7ee9\u5355\u3002'} />
      </div>
      <p className="mt-2.5 text-[13px] leading-relaxed text-text-3">{'\u6ce8\uff1a\u5e95\u5c42\u90fd\u662f HTTP\u3002\u7edd\u5927\u591a\u6570\u7528 JSON \u6253\u5305\uff0c\u5c11\u6570\u4f8b\u5916 \u2014\u2014 \u4e0a\u4f20\u7b80\u5386\u662f multipart \u4e8c\u8fdb\u5236\u6587\u4ef6\uff0c\u4e0b\u8f7d\u6295\u9012\u5931\u8d25\u622a\u56fe\u662f PNG \u56fe\u7247\u3002'}</p>
    </Section>
  )
}


// -- (2) flow tab -----------------------------------------------------------

type Branch = { short: string; title: string; node: string; file: string; desc: string; kind: 'fail' | 'cond' }
type FlowStep = { short: string; title: string; node: string; file: string; desc: string; cond?: boolean; branch?: Branch }

const W1_STEPS: FlowStep[] = [
  { short: '\u641c\u7d22', title: '\u641c\u7d22 \u00b7 \u626b\u63cf\u5361', node: 'NavigateStep \u00b7 search_with_panel',
    file: 'pipeline/w1/steps/navigate', desc: '\u6309 profile \u62fc\u641c\u7d22 URL\uff0c\u6eda\u52a8\u52a0\u8f7d\u5361\u7247\u5217\u8868' },
  { short: '\u6293 JD', title: '\u6293 JD', node: 'FetchJDStep \u00b7 fetch_job_detail',
    file: 'pipeline/w1/steps/fetch_jd', desc: '\u6253\u5f00\u8be6\u60c5\u9875\u6293 JD \u6587\u672c + \u516c\u53f8\u52a0\u5bc6 id' },
  { short: '\u8bc4\u5206', title: 'LLM \u8bc4\u5206', node: 'ScoreStep \u00b7 score_job',
    file: 'pipeline/w1/steps + tools/llm', desc: '5 \u7ef4\u5ea6\u72ec\u7acb\u6253\u5206\uff0cPython \u7aef\u52a0\u6743\u6c42\u548c\uff08code decides\uff09' },
  { short: '\u6295\u9012', title: '\u6295\u9012', node: 'ApplyStep \u00b7 apply_job',
    file: 'pipeline/w1/steps/apply', desc: '\u8d85\u9608\u503c\u70b9\u300c\u7acb\u5373\u6c9f\u901a\u300d\uff0c\u5904\u7406\u7ee7\u7eed\u6295\u9012\u5f39\u7a97',
    branch: { short: '\u622a\u56fe', title: '\u6295\u9012\u5931\u8d25\u622a\u56fe\u8bca\u65ad', node: 'capture_screenshot',
      file: 'tools/browser/w1/capture_screenshot', kind: 'fail',
      desc: '\u6295\u9012\u5931\u8d25\uff08\u6309\u94ae\u672a\u627e\u5230/\u5f39\u7a97\u62e6\u622a\uff09\u2192 \u622a\u56fe\u5b58\u6863 + job_apply_failed\uff0c\u4e0d\u8ba1 applied' } },
  { short: '\u843d\u5e93', title: '\u843d\u5e93', node: 'upsert_application (+ upsert_hr_conversation)',
    file: 'tools/db/w1 \u00b7 tools/db/w2', desc: '\u5199 applications\uff08\u542b content_hash\uff09\uff0c\u72b6\u6001 \u2192 APPLIED\uff1b\u6210\u529f\u540e\u5efa conv_id=job_id \u5360\u4f4d\uff08W1\u2192W2 \u786c\u5173\u8054\uff09' },
]
const W2_STEPS: FlowStep[] = [
  { short: '\u626b\u63cf\u5217\u8868', title: '\u626b\u63cf\u5217\u8868', node: 'ScanStep \u00b7 extract_conversation_list',
    file: 'pipeline/w2/scan_step \u00b7 tools/browser/w2', desc: '\u8bfb getGeekFriendList API \u62ff\u6574\u9875\u4f1a\u8bdd\uff08\u542b job_id/lastTS\uff09\uff0c\u6eda\u52a8\u7d2f\u79ef\u5168\u91cf' },
  { short: '\u810f\u68c0\u67e5', title: '\u810f\u68c0\u67e5\uff08\u589e\u91cf\uff09', node: 'filter_conversations',
    file: 'tools/biz_logic', desc: '\u6309 lastTS \u6beb\u79d2\u65f6\u95f4\u6233\u6bd4\u5bf9\u5b58\u91cf\uff0c\u53ea\u653e\u884c\u6709\u53d8\u5316/\u672a\u8bfb/\u65b0\u4f1a\u8bdd' },
  { short: '\u5bfc\u822a', title: '\u5bfc\u822a', node: 'NavigateStep',
    file: 'pipeline/w2/steps/navigate', desc: '\u641c\u7d22\u5b9a\u4f4d / \u6253\u5f00\u5355\u4e2a\u4f1a\u8bdd' },
  { short: '\u8bfb\u6d88\u606f', title: '\u8bfb\u6d88\u606f', node: 'ReadStep \u00b7 read_messages',
    file: 'pipeline/w2/steps/read', desc: '\u8bfb\u6c14\u6ce1\uff1b\u5e73\u53f0\u63d0\u793a\u91cd\u5206\u7c7b\u4e3a system' },
  { short: '\u5206\u6790', title: '\u5206\u6790\u610f\u56fe', node: 'AnalyzeStep \u00b7 analyze_hr_intent',
    file: 'pipeline/w2/steps/analyze', desc: '\u96f6 HR \u6d88\u606f\u5b88\u95e8\uff1bLLM \u5224 intent + \u8d77\u8349\u56de\u590d' },
  { short: '\u53d1\u7b80\u5386', title: '\u53d1\u7b80\u5386', node: 'ResumeStep \u00b7 send_resume', cond: true,
    file: 'pipeline/w2/steps/resume', desc: 'HR \u7d22\u8981\u5219\u53d1\uff08\u6309\u9700\uff0cdetect_resume \u5224\u5b9a\uff09' },
  { short: '\u843d\u5e93', title: '\u843d\u5e93', node: 'write_hr_messages / update_hr_analysis',
    file: 'tools/db/w2', desc: '\u5199 conversations + messages + intent/stage/job_id/lastTS' },
  { short: '\u6536\u5c3e', title: '\u6536\u5c3e', node: 'FinalizeStep',
    file: 'pipeline/w2/finalize_step', desc: '\u8d85\u65f6\u8f6f\u5173\u95ed + sync \u56de\u586b\u72b6\u6001 + backfill \u8865 application\uff08\u4e0d\u53d1\u56de\u590d\uff0c\u90a3\u662f W3\uff09' },
]
const W3_STEPS: FlowStep[] = [
  { short: '\u53d6\u5df2\u6279\u51c6', title: '\u53d6\u5df2\u6279\u51c6\u56de\u590d', node: 'get_approved_replies',
    file: 'tools/db/w2', desc: '\u53d6\u7528\u6237\u5ba1\u6279\u8fc7\u7684\u5f85\u53d1\u56de\u590d\uff08approved/revision\uff09' },
  { short: '\u5b9a\u4f4d', title: '\u641c\u7d22\u5b9a\u4f4d\u4f1a\u8bdd', node: 'search_locate_conversation',
    file: 'tools/browser/w3', desc: '\u7528\u804a\u5929\u641c\u7d22\u6846\u5b9a\u4f4d\u4f1a\u8bdd\u5e76\u6253\u5f00\uff08\u6c89\u5e95\u4f1a\u8bdd\u4e5f\u80fd\u627e\u5230\uff09' },
  { short: '\u53d1\u9001', title: '\u53d1\u9001', node: 'send_chat_message',
    file: 'tools/browser/w2', desc: '\u628a\u56de\u590d\u6587\u672c\u586b\u5165\u5e76\u63d0\u4ea4\uff08\u4ec5\u4ee3\u7406\u52a8\u4f5c\uff0c\u4e0d\u4ee3\u8868\u9001\u8fbe\uff09' },
  { short: '\u9a8c\u8bc1', title: '\u91cd\u626b\u9a8c\u8bc1\u9001\u8fbe', node: 'read_messages + write_hr_messages',
    file: 'pipeline/w3/send_pipeline', desc: '\u91cd\u626b\u4f1a\u8bdd\u786e\u8ba4\u56de\u590d\u5df2\u4f5c\u4e3a\u300c\u6211\u65b9\u300d\u6c14\u6ce1\u843d\u5730\u5e76\u5199\u5e93',
    branch: { short: '\u4fdd\u7559', title: '\u672a\u9a8c\u8bc1\u5219\u4fdd\u7559 approved', node: '\uff08\u4e0d\u8c03 mark_reply_sent\uff09',
      file: 'pipeline/w3/send_pipeline', kind: 'fail',
      desc: '\u9001\u8fbe\u672a\u9a8c\u8bc1 \u2192 \u4fdd\u6301 approved\u3001\u6587\u672c\u4e0d\u6e05\uff0c\u7b49\u4e0b\u6b21 W3 \u91cd\u8bd5\uff08\u4e0d\u8bef\u6807\u5df2\u53d1\uff09' } },
  { short: '\u6807\u8bb0', title: '\u6807\u8bb0\u5df2\u53d1', node: 'mark_reply_sent',
    file: 'tools/db/w2', desc: '\u4ec5\u9a8c\u8bc1\u901a\u8fc7\u624d\u6807\u8bb0 sent' },
]

// -- SVG topology geometry (fixed coords derived from step index) --
const NODE_W = 118
const NODE_H = 48
const GAP = 46
const PITCH = NODE_W + GAP
const PAD_X = 18
const ROW_Y = 30
const BRANCH_Y = ROW_Y + NODE_H + 46

type Selected = { key: string; step: FlowStep | Branch; accent: string }

function FlowLane({ tag, title, steps, accent, active, selectedKey, onSelect }: {
  tag: string; title: string; steps: FlowStep[]; accent: string; active: boolean
  selectedKey: string | null; onSelect: (s: Selected) => void
}) {
  const n = steps.length
  const laneW = PAD_X * 2 + n * NODE_W + (n - 1) * GAP
  const hasBranch = steps.some((s) => s.branch)
  const laneH = (hasBranch ? BRANCH_Y + NODE_H : ROW_Y + NODE_H) + 18
  const xOf = (i: number) => PAD_X + i * PITCH
  const mid = NODE_H / 2

  // `key` is a reserved React prop (not forwarded), so the click target is passed
  // explicitly via nodeKey/step -- reading props.key would be undefined.
  function Node({ x, y, nodeKey, step, tint, dim }: {
    x: number; y: number; nodeKey: string; step: FlowStep | Branch; tint: string; dim?: boolean
  }) {
    const sel = selectedKey === nodeKey
    return (
      <g style={{ cursor: 'pointer' }} onClick={() => onSelect({ key: nodeKey, step, accent })}>
        <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={11}
          fill={sel ? `${tint}26` : 'rgba(255,255,255,0.045)'}
          stroke={sel ? tint : dim ? `${tint}55` : active ? `${accent}44` : 'rgba(255,255,255,0.14)'}
          strokeWidth={sel ? 2 : 1} strokeDasharray={dim ? '4 3' : undefined} />
        <text x={x + NODE_W / 2} y={y + mid} textAnchor="middle" dominantBaseline="central"
          fontSize={14} fontWeight={600} fill={sel ? '#f5f5f7' : '#d1d1d6'}>{step.short}</text>
      </g>
    )
  }

  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl"
        style={{ border: active ? `1px solid ${accent}66` : '1px solid rgba(255,255,255,0.08)' }} />
      <div className="mb-3 flex items-center gap-2.5">
        <span className="rounded font-mono text-[15px] font-bold px-1.5 py-0.5"
          style={{ background: `${accent}22`, color: accent }}>{tag}</span>
        <span className="text-[18px] font-semibold text-text-1">{title}</span>
        {active && (
          <span className="ml-auto flex items-center gap-1.5 text-[14px] font-semibold" style={{ color: accent }}>
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: accent }} />
            {'\u8fd0\u884c\u4e2d'}
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <svg width={laneW} height={laneH} style={{ display: 'block' }}>
          <defs>
            <marker id={`arw-${tag}`} markerWidth="7" markerHeight="7" refX="5.5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="rgba(255,255,255,0.4)" />
            </marker>
            <marker id={`arwf-${tag}`} markerWidth="7" markerHeight="7" refX="5.5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#ff453a" />
            </marker>
          </defs>
          {/* main-chain arrows */}
          {steps.slice(0, -1).map((_, i) => {
            const dashed = steps[i + 1].cond
            return (
              <line key={`a${i}`} x1={xOf(i) + NODE_W} y1={ROW_Y + mid} x2={xOf(i + 1)} y2={ROW_Y + mid}
                stroke="rgba(255,255,255,0.32)" strokeWidth={1.5} strokeDasharray={dashed ? '5 4' : undefined}
                markerEnd={`url(#arw-${tag})`} />
            )
          })}
          {/* conditional label */}
          {steps.map((s, i) => s.cond ? (
            <text key={`c${i}`} x={xOf(i) - GAP / 2} y={ROW_Y + mid - 7} textAnchor="middle"
              fontSize={11} fill="rgba(255,255,255,0.45)">{'\u6309\u9700'}</text>
          ) : null)}
          {/* failure branches */}
          {steps.map((s, i) => s.branch ? (
            <g key={`b${i}`}>
              <path d={`M${xOf(i) + NODE_W / 2},${ROW_Y + NODE_H} L${xOf(i) + NODE_W / 2},${BRANCH_Y}`}
                stroke="#ff453a" strokeWidth={1.5} strokeDasharray="5 4" fill="none" markerEnd={`url(#arwf-${tag})`} />
              <text x={xOf(i) + NODE_W / 2 + 10} y={(ROW_Y + NODE_H + BRANCH_Y) / 2} fontSize={11} fill="#ff453a">{'\u5931\u8d25'}</text>
              <Node x={xOf(i)} y={BRANCH_Y} nodeKey={`${tag}:b${i}`} step={s.branch} tint="#ff453a" dim />
            </g>
          ) : null)}
          {/* main nodes */}
          {steps.map((s, i) => (
            <Node key={`n${i}`} x={xOf(i)} y={ROW_Y} nodeKey={`${tag}:${i}`} step={s} tint={accent} />
          ))}
        </svg>
      </div>
    </div>
  )
}

function DetailPanel({ sel }: { sel: Selected | null }) {
  if (!sel) {
    return (
      <div className="rounded-2xl bg-bg-card p-5 text-[14px] text-text-3 shadow-card"
        style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
        {'\u70b9\u51fb\u4e0a\u65b9\u4efb\u4e00\u8282\u70b9\uff0c\u67e5\u770b\u8be5\u9636\u6bb5\u7684 step \u00b7 tool\u3001\u6e90\u7801\u8def\u5f84\u4e0e\u8bf4\u660e\u3002'}
      </div>
    )
  }
  const s = sel.step
  const isFail = 'kind' in s && s.kind === 'fail'
  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card" style={{ border: `1px solid ${sel.accent}44` }}>
      <div className="mb-2 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: isFail ? '#ff453a' : sel.accent }} />
        <span className="text-[17px] font-semibold text-text-1">{s.title}</span>
        {isFail && <span className="rounded px-1.5 py-0.5 text-[12px] font-semibold"
          style={{ background: 'rgba(255,69,58,0.16)', color: '#ff453a' }}>{'\u5931\u8d25\u652f\u8def'}</span>}
      </div>
      <div className="grid grid-cols-[64px_1fr] gap-x-3 gap-y-1.5 text-[14px]">
        <span className="text-text-3">{'step \u00b7 tool'}</span>
        <span className="font-mono text-signal-bright">{s.node}</span>
        <span className="text-text-3">{'\u6e90\u7801'}</span>
        <span className="font-mono text-text-2">{s.file}</span>
        <span className="text-text-3">{'\u8bf4\u660e'}</span>
        <span className="leading-relaxed text-text-2">{s.desc}</span>
      </div>
    </div>
  )
}

function FlowTab({ running }: { running: string | null }) {
  const [sel, setSel] = useState<Selected | null>(null)
  return (
    <div className="space-y-4">
      <p className="text-[15px] leading-relaxed text-text-3">
        {'\u4e09\u6761\u6838\u5fc3\u5de5\u4f5c\u6d41\u90fd\u662f Step \u7f16\u6392\u7684\u62d3\u6251\uff1a\u6bcf\u4e2a\u8282\u70b9\u662f\u4e00\u4e2a\u9636\u6bb5\uff08\u8c03\u4e00\u4e2a\u6216\u591a\u4e2a tool\uff09\uff0c\u7bad\u5934\u662f\u63a8\u8fdb\u65b9\u5411\u3002\u5f53\u524d\u8fd0\u884c\u7684\u5de5\u4f5c\u6d41\u9ad8\u4eae\uff1b\u70b9\u8282\u70b9\u770b\u8be6\u60c5\u3002'}
      </p>
      <FlowLane tag="W1" title={'W1 \u6295\u9012'} steps={W1_STEPS} accent="#0a84ff" active={running === 'w1'}
        selectedKey={sel?.key ?? null} onSelect={setSel} />
      <FlowLane tag="W2" title={'W2 \u68c0\u67e5\u56de\u5e94'} steps={W2_STEPS} accent="#30d158" active={running === 'w2'}
        selectedKey={sel?.key ?? null} onSelect={setSel} />
      <FlowLane tag="W3" title={'W3 \u53d1\u56de\u590d'} steps={W3_STEPS} accent="#bf5af2" active={running === 'w3'}
        selectedKey={sel?.key ?? null} onSelect={setSel} />
      <DetailPanel sel={sel} />
    </div>
  )
}

// -- (3) state-machine tab (existing content) --------------------------------

type Row = { value: string; label: string; color: string; live: boolean; desc: string; enter: string }

const APP_ROWS: Row[] = [
  { value: 'FOUND', label: '\u5df2\u53d1\u73b0', color: 'rgba(255,255,255,0.35)', live: false,
    desc: '\u6295\u9012\u524d\u7684\u5185\u5b58\u6001\uff08Job/ApplicationRecord \u9ed8\u8ba4\u503c\uff09\uff0c\u4ece\u4e0d\u843d\u5165 applications \u8868',
    enter: '\u641c\u7d22\u53d1\u73b0\uff08\u4e0d\u5165\u5e93\uff09' },
  { value: 'APPLIED', label: '\u5df2\u6295\u9012', color: '#0a84ff', live: true,
    desc: '\u5df2\u6295\u9012\uff0c\u542b\u6b63\u5728\u6c9f\u901a\uff08\u6295\u9012\u4e0d\u9700\u8981 HR \u56de\u590d\u5373\u6210\u7acb\uff09',
    enter: 'W1 \u6295\u9012\u6210\u529f\uff1bREJECTED \u590d\u6d3b / \u91cd\u6295' },
  { value: 'INTERVIEWING', label: '\u9762\u8bd5\u4e2d', color: '#ff9f0a', live: true,
    desc: '\u8fdb\u5165\u9762\u8bd5',
    enter: 'sync\uff1a\u4f1a\u8bdd stage=interview' },
  { value: 'OFFER', label: 'Offer', color: '#ffd60a', live: true,
    desc: '\u62ff\u5230 offer',
    enter: 'sync\uff1a\u4f1a\u8bdd stage=offer' },
  { value: 'REJECTED', label: '\u5df2\u62d2\u7edd', color: '#ff453a', live: true,
    desc: '\u4ec5 HR \u660e\u786e\u62d2\u7edd\uff08\u8d85\u65f6/\u65e0\u56de\u5e94\u4e0d\u518d\u7b97 REJECTED\uff09',
    enter: 'sync\uff1a\u4f1a\u8bdd stage=closed \u4e14 intent=rejection' },
]

const APP_TRANSITIONS: string[] = [
  'FOUND \u2192 APPLIED\uff08\u6295\u9012\u6210\u529f\uff09',
  'APPLIED \u2192 INTERVIEWING / OFFER / REJECTED',
  'INTERVIEWING \u2192 OFFER / REJECTED',
  'OFFER \u2192 REJECTED\uff08offer \u64a4\u56de / \u653e\u5f03\uff0c\u7f55\u89c1\uff09',
  'REJECTED \u2192 APPLIED\uff08\u590d\u6d3b\uff1a\u4f1a\u8bdd\u518d\u6d3b\u8dc3 / \u91cd\u6295\uff09',
  '\u975e\u9762\u8bd5/offer \u4e14\u6295\u9012\u6ee1 30 \u5929 \u2192 \u6e05\u7406\u5220\u9664 \u2192 \u91cd\u8d70 W1',
]

const STAGE_ROWS: Row[] = [
  { value: 'new', label: '\u65b0', color: 'rgba(255,255,255,0.35)', live: true,
    desc: '\u521a\u5efa\u7acb\u3001\u5c1a\u65e0\u5b9e\u8d28\u5f80\u6765', enter: '\u521d\u59cb' },
  { value: 'active', label: '\u6c9f\u901a\u4e2d', color: '#0a84ff', live: true,
    desc: '\u6709 HR \u6d88\u606f\u3001\u6b63\u5728\u6c9f\u901a', enter: '\u6709 HR \u6d88\u606f\uff1bclosed \u4f1a\u8bdd\u590d\u6d3b' },
  { value: 'resume_sent', label: '\u5df2\u53d1\u7b80\u5386', color: '#30d158', live: true,
    desc: '\u5df2\u5411 HR \u53d1\u9001\u7b80\u5386', enter: '\u53d1\u7b80\u5386\u6210\u529f' },
  { value: 'interview', label: '\u9762\u8bd5', color: '#ff9f0a', live: true,
    desc: 'HR \u7ea6\u9762', enter: 'intent=interview_invite' },
  { value: 'offer', label: 'Offer', color: '#ffd60a', live: true,
    desc: 'HR \u7ed9 offer', enter: 'intent=offer' },
  { value: 'closed', label: '\u5173\u95ed', color: '#ff453a', live: true,
    desc: '\u771f\u62d2\uff08intent=rejection\uff09\u6216 14 \u5929\u65e0\u6d88\u606f\u7684\u505c\u6ede\u8f6f\u6807\u8bb0', enter: 'intent=rejection\uff1b\u6216 mark_timeout' },
]

const STAGE_TRANSITIONS: string[] = [
  'new \u2192 active \u2192(\u53d1\u7b80\u5386) resume_sent',
  'active/\u2026 \u2192 interview \u2192 offer\uff08\u6309 intent \u524d\u8fdb\uff09',
  'active/\u2026 \u2192 closed\uff08intent=rejection\uff1a\u771f\u62d2\uff0c\u5e26 intent \u6807\u8bb0\uff09',
  'active/\u2026 \u2192 closed\uff0814 \u5929\u65e0\u6d88\u606f\uff1a\u505c\u6ede\u8f6f\u6807\u8bb0\uff0cintent \u4e0d\u53d8\uff09',
  'closed \u2192 active\uff08HR \u53c8\u53d1\u6d88\u606f\uff0cfilter \u91cd\u5904\u7406 + upsert \u8986\u5199\u590d\u6d3b\uff09',
]

const INTENT_ROWS: Row[] = [
  { value: 'interview_invite', label: '\u7ea6\u9762\u8bd5', color: '#ff9f0a', live: true,
    desc: 'HR \u9080\u7ea6\u9762\u8bd5', enter: 'LLM \u5224\u5b9a' },
  { value: 'offer', label: '\u53d1 offer', color: '#ffd60a', live: true,
    desc: 'HR \u7ed9 offer', enter: 'LLM \u5224\u5b9a' },
  { value: 'rejection', label: '\u5a49\u62d2', color: '#ff453a', live: true,
    desc: 'HR \u660e\u786e\u62d2\u7edd', enter: 'LLM \u5224\u5b9a' },
  { value: 'resume_request', label: '\u7d22\u8981\u7b80\u5386', color: '#30d158', live: true,
    desc: 'HR \u7d22\u8981\u7b80\u5386', enter: 'LLM \u5224\u5b9a' },
  { value: 'general', label: '\u4e00\u822c\u6c9f\u901a', color: '#0a84ff', live: true,
    desc: '\u666e\u901a\u5f80\u6765', enter: 'LLM \u5224\u5b9a' },
  { value: 'unknown', label: '\u672a\u8bc6\u522b', color: 'rgba(255,255,255,0.35)', live: true,
    desc: '\u65e0 HR \u6d88\u606f\u8df3\u8fc7 LLM\uff0c\u6216 LLM \u5168\u90e8\u964d\u7ea7', enter: '\u786e\u5b9a\u6027\u515c\u5e95' },
]

type MapRow = { intent: string; stage: string; app: string }
const MAP_ROWS: MapRow[] = [
  { intent: 'interview_invite', stage: 'interview', app: 'INTERVIEWING' },
  { intent: 'offer', stage: 'offer', app: 'OFFER' },
  { intent: 'rejection', stage: 'closed (intent=rejection)', app: 'REJECTED' },
  { intent: 'resume_request', stage: 'active', app: '\u4e0d\u53d8\uff08\u53ef\u80fd\u53d1\u7b80\u5386\uff09' },
  { intent: 'general / unknown', stage: 'active', app: '\u4e0d\u53d8' },
  { intent: '\u2014\uff0814 \u5929\u9759\u9ed8\uff09', stage: 'closed\uff08\u8f6f\u6807\u8bb0\uff09', app: '\u4e0d\u53d8' },
  { intent: '\u2014\uff08\u4f1a\u8bdd\u590d\u6d3b active\uff09', stage: 'active', app: 'REJECTED \u2192 APPLIED' },
  { intent: '\u2014\uff08\u6295\u9012\u6ee1 30 \u5929\u65e0\u8fdb\u5c55\uff09', stage: '\uff08\u8fde\u540c\u4f1a\u8bdd\u5220\u9664\uff09', app: '\u5220\u9664 \u2192 \u91cd\u8d70 W1' },
]

function EnumTable({ rows, idxLabel, counts }: { rows: Row[]; idxLabel: string; counts?: Record<string, number> }) {
  return (
    <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
      <div className="grid grid-cols-[210px_1fr_1fr] gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
        style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <span>{idxLabel}</span>
        <span>{'\u542b\u4e49'}</span>
        <span>{'\u8fdb\u5165\u65b9\u5f0f'}</span>
      </div>
      {rows.map((r) => (
        <div key={r.value} className="grid grid-cols-[210px_1fr_1fr] items-start gap-2 px-3 py-2"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
          <span className="flex items-center gap-2">
            <Dot color={r.color} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center font-mono text-[15px] text-text-1">
                {r.value}
                {counts && counts[r.value] !== undefined && <CountPill n={counts[r.value]} />}
              </span>
              <span className="block text-[14px] text-text-3">
                {r.label}{!r.live && <span className="ml-1 text-signal-amber">{'\u00b7 \u5185\u5b58\u6001'}</span>}
              </span>
            </span>
          </span>
          <span className="text-[15px] leading-relaxed text-text-2">{r.desc}</span>
          <span className="font-mono text-[14.5px] leading-relaxed text-text-3">{r.enter}</span>
        </div>
      ))}
    </div>
  )
}

function TransitionList({ items }: { items: string[] }) {
  return (
    <ul className="mt-2 space-y-1">
      {items.map((t, i) => (
        <li key={i} className="font-mono text-[14.5px] leading-relaxed text-text-2">{t}</li>
      ))}
    </ul>
  )
}

function StateMachineTab({ live }: { live: ArchitectureLive | null }) {
  const byStatus = live?.by_status
  const byStage = live?.by_stage
  return (
    <div className="space-y-4">
      <p className="text-[15px] leading-relaxed text-text-3">
        {'\u4e09\u4e2a\u72b6\u6001\u673a\uff1a'}
        <span className="text-text-2">{'\u5e94\u8058\u72b6\u6001'}</span>{' \u00b7 '}
        <span className="text-text-2">{'\u4f1a\u8bdd\u9636\u6bb5'}</span>{' \u00b7 '}
        <span className="text-text-2">{'HR \u610f\u56fe\uff08LLM\uff09'}</span>
        {'\u3002\u503c\u65c1\u6570\u5b57\u4e3a\u5f53\u524d\u5b9e\u65f6\u8bb0\u5f55\u6570\u3002'}
      </p>
      <Section badge={'\u2460'} title={'\u5e94\u8058\u72b6\u6001 application status'} sub={'schemas.py AppStatus \u00b7 5 \u4e2a\u503c'}>
        <EnumTable rows={APP_ROWS} idxLabel={'\u72b6\u6001\u503c'} counts={byStatus} />
        <p className="mb-1 mt-3 text-[14px] font-semibold uppercase tracking-wider text-text-3">{'\u8f6c\u79fb'}</p>
        <TransitionList items={APP_TRANSITIONS} />
        <p className="mt-2 text-[14px] leading-relaxed text-text-3">
          {'\u6ce8\uff1a\u8f6c\u79fb\u7531 sync / purge \u7684 SQL \u6267\u884c\uff1btracker.VALID_TRANSITIONS \u4ec5\u4f5c\u544a\u8b66\u6587\u6863\u3002\u5df2\u79fb\u9664 CHATTING / SCORED\uff08live \u4ece\u4e0d\u4ea7\u751f\uff09\u3002'}
        </p>
      </Section>
      <Section badge={'\u2461'} title={'\u4f1a\u8bdd\u9636\u6bb5 conversation stage'} sub={'conversation_pipeline STAGE_ORDER \u00b7 6 \u4e2a\u503c'}>
        <EnumTable rows={STAGE_ROWS} idxLabel={'\u9636\u6bb5\u503c'} counts={byStage} />
        <p className="mb-1 mt-3 text-[14px] font-semibold uppercase tracking-wider text-text-3">{'\u8f6c\u79fb'}</p>
        <TransitionList items={STAGE_TRANSITIONS} />
      </Section>
      <Section badge={'\u2462'} title={'HR \u610f\u56fe LLM intent'} sub={'analyze_intent _VALID_INTENTS \u00b7 6 \u4e2a\u503c'}>
        <EnumTable rows={INTENT_ROWS} idxLabel={'\u610f\u56fe\u503c'} />
        <p className="mt-3 text-[14px] leading-relaxed text-text-3">
          {'\u65e0 HR \u6d88\u606f\u5219\u8df3\u8fc7 LLM = unknown\uff1bLLM \u5168\u90e8\u964d\u7ea7 = unknown\u3002\u610f\u56fe\u6301\u4e45\u5316\u5230 hr_conversations.intent\uff0csync \u9760\u5b83\u533a\u5206 closed \u7684\u4e24\u79cd\u542b\u4e49\u3002'}
        </p>
      </Section>
      <Section badge={'\u21a6'} title={'\u6620\u5c04\u5173\u7cfb'} sub={'intent \u2192 stage \u2192 application'}>
        <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="grid grid-cols-3 gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
            style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span>{'\u2462 LLM intent'}</span>
            <span>{'\u2461 conversation stage'}</span>
            <span>{'\u2460 application'}</span>
          </div>
          {MAP_ROWS.map((m, i) => (
            <div key={i} className="grid grid-cols-3 items-center gap-2 px-3 py-2 font-mono text-[14.5px]"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="text-text-2">{m.intent}</span>
              <span className="text-text-2">{m.stage}</span>
              <span className="text-text-1">{m.app}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}

// -- (4) data-model tab ------------------------------------------------

type TableDef = { key: 'applications' | 'hr_conversations' | 'hr_messages'; name: string; color: string; cols: string; note: string }
const TABLE_ROWS: TableDef[] = [
  { key: 'applications', name: 'applications', color: '#0a84ff',
    cols: 'job_id(PK) \u00b7 status \u00b7 score \u00b7 content_hash \u00b7 applied_at \u00b7 url',
    note: '\u6295\u9012\u8bb0\u5f55\uff1b\u72b6\u6001\u673a\u2460\u3002content_hash \u62e6 Boss \u6362\u9a6c\u7532\u91cd\u6295' },
  { key: 'hr_conversations', name: 'hr_conversations', color: '#30d158',
    cols: 'conv_id(PK)=job_id \u4f18\u5148 / sha256(hr_name|company) \u9000\u5316 \u00b7 last_msg_ts \u00b7 stage \u00b7 intent \u00b7 reply_status',
    note: 'HR \u4f1a\u8bdd\uff1b\u72b6\u6001\u673a\u2461\uff08stage\uff09\u2462\uff08intent\uff09\u3002conv_id \u7528 encryptJobId(job_id) \u505a\u786c\u5173\u8054\u952e\uff0c\u65e0\u5219 sha256 \u9000\u5316' },
  { key: 'hr_messages', name: 'hr_messages', color: '#ff9f0a',
    cols: 'conv_id(FK) \u00b7 sender(me/hr/system) \u00b7 text \u00b7 created_at',
    note: '\u4f1a\u8bdd\u6d88\u606f\uff1b\u5e73\u53f0\u63d0\u793a\u91cd\u5206\u7c7b\u4e3a system\uff0c\u907f\u514d\u6c61\u67d3 intent' },
]

const LLM_PROVIDERS = 'claude_cli \u00b7 codex_cli \u00b7 ollama \u00b7 anthropic_api \u00b7 openai_compatible'
type ChainDef = { name: string; use: string }
const LLM_CHAINS: ChainDef[] = [
  { name: 'scoring', use: '\u804c\u4f4d\u8bc4\u5206\uff08W1\uff09' },
  { name: 'generation', use: '\u7b80\u5386\u751f\u6210' },
  { name: 'analysis', use: 'HR \u610f\u56fe\u5206\u6790\uff08W2\uff1b\u65e0\u6b64 key \u5219 fallback \u5230 scoring\uff09' },
]

function DataTab({ live }: { live: ArchitectureLive | null }) {
  const tables = live?.tables
  return (
    <div className="space-y-4">
      <Section badge={'\u2460'} title={'SQLite \u4e09\u8868'} sub={'data/jobs.db \u00b7 \u7ebf\u7a0b\u5c40\u90e8\u8fde\u63a5 + WAL'}>
        <div className="space-y-2">
          {TABLE_ROWS.map((t) => (
            <div key={t.key} className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div className="flex items-center gap-2">
                <Dot color={t.color} />
                <span className="font-mono text-[16px] text-text-1">{t.name}</span>
                {tables && tables[t.key] !== undefined && <CountPill n={tables[t.key]} />}
              </div>
              <p className="mt-1.5 font-mono text-[14px] leading-relaxed text-text-3">{t.cols}</p>
              <p className="mt-1 text-[14.5px] leading-relaxed text-text-2">{t.note}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 font-mono text-[14.5px] leading-relaxed text-text-2">
          {'applications 1\u2014* hr_conversations\uff08job_id \u4f18\u5148\uff0chr_name+company \u9000\u5316\u5173\u8054\uff09'}
          <span className="mt-0.5 block">{'hr_conversations 1\u2014* hr_messages\uff08conv_id\uff09'}</span>
        </p>
      </Section>

      <Section badge={'\u2461'} title={'LLM \u8def\u7531\u94fe'} sub={'ModelRouter \u2192 FallbackChain \u2192 Provider'}>
        <div className="flex flex-wrap items-center gap-2 text-[15px]">
          <span className="rounded-lg px-2.5 py-1 font-mono text-signal-bright" style={{ background: 'rgba(10,132,255,0.12)', border: '1px solid rgba(10,132,255,0.25)' }}>ModelRouter</span>
          <span className="text-text-3">{'\u2192 \u6309 capability\uff08fast/balanced/powerful\uff09'}</span>
          <span className="rounded-lg px-2.5 py-1 font-mono text-signal-green" style={{ background: 'rgba(48,209,88,0.12)', border: '1px solid rgba(48,209,88,0.25)' }}>FallbackChain</span>
          <span className="text-text-3">{'\u2192 \u4f9d\u6b21\u5c1d\u8bd5'}</span>
          <span className="rounded-lg px-2.5 py-1 font-mono text-text-2" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>{LLM_PROVIDERS}</span>
        </div>
        <div className="mt-3 overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="grid grid-cols-[140px_1fr] gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
            style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span>{'\u547d\u540d\u94fe'}</span>
            <span>{'\u7528\u9014'}</span>
          </div>
          {LLM_CHAINS.map((c) => (
            <div key={c.name} className="grid grid-cols-[140px_1fr] items-center gap-2 px-3 py-2"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="font-mono text-[15px] text-text-1">{c.name}</span>
              <span className="text-[15px] text-text-2">{c.use}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[14px] leading-relaxed text-text-3">
          {'safe_parse_json \u4e09\u5c42\u5bb9\u9519\uff1a\u4ee3\u7801\u5757\u63d0\u53d6 \u2192 json.loads \u2192 json_repair\u3002models judge\uff08\u5206\u7c7b/\u8d77\u8349\uff09\uff0ccode decides\uff08\u52a0\u6743/\u8def\u7531/\u72b6\u6001\uff09\u3002'}
        </p>
      </Section>
    </div>
  )
}

// -- (5) interview-prep tab -------------------------------------------
// Narrative layer for interviews (elevator pitch / highlights / JD-mapping).
// Content is mirrored from docs/interview-prep-futu.md -- that doc stays the
// source of truth; keep this in sync when the doc changes. Deliberately does NOT
// duplicate the flow / state-machine diagrams (those live in the other tabs).

const PREP_SRC_LABEL = '\u7d20\u6750\u6e90\uff1a'
const PREP_SRC_NOTE =
  'docs/interview-prep-futu.md \u4e3a\u5355\u4e00\u771f\u76f8\u6e90\uff1b\u672c\u9875\u662f\u5b83\u7684\u53d9\u4e8b\u7cbe\u534e\uff0c\u6539\u8bdd\u672f\u8bf7\u5148\u6539\u90a3\u4efd doc \u518d\u540c\u6b65\u6b64\u5904\uff0c\u522b\u8ba9\u4e24\u8fb9\u5206\u53c9\u3002'

const PREP_T_PITCH = '\u7535\u68af\u9648\u8ff0'
const PREP_S_PITCH = '\u4e00\u53e5\u8bdd\u8bb2\u6e05\u9879\u76ee'
const PREP_T_HL = '\u56db\u4e2a\u6280\u672f\u4eae\u70b9'
const PREP_S_HL = '\u91d1\u878d\u6d4b\u8bd5\u5b98\u4f1a\u773c\u775b\u4e00\u4eae\u7684\u56db\u70b9'
const PREP_T_JD = 'JD \u80fd\u529b\u6620\u5c04'
const PREP_S_JD = '\u9879\u76ee\u7ecf\u9a8c\u9010\u6761\u7ffb\u8bd1\u6210 JD \u8981\u6c42'
const PREP_H_JD = 'JD \u8981\u6c42'
const PREP_H_ANSWER = '\u7528\u9879\u76ee\u600e\u4e48\u7b54'
const PREP_T_GAP = '\u8bda\u5b9e\u77ed\u677f + \u5e94\u5bf9'
const PREP_S_GAP = '\u88ab\u8ffd\u95ee\u65f6\u4e0d\u614c'

const PREP_PITCH =
  '\u6211\u72ec\u7acb\u505a\u4e86\u4e00\u4e2a Boss\u76f4\u8058 \u81ea\u52a8\u5316\u6c42\u804c Agent\u3002\u5b83\u6a21\u62df\u771f\u5b9e\u6c42\u804c\u8005\u7684\u5b8c\u6574\u94fe\u8def\u2014\u2014\u641c\u7d22\u804c\u4f4d\u3001\u7528\u5927\u6a21\u578b\u591a\u7ef4\u5ea6\u6253\u5206\u51b3\u7b56\u3001\u81ea\u52a8\u6295\u9012\u3001\u518d\u540c\u6b65 HR \u4f1a\u8bdd\u8ffd\u8e2a\u8fdb\u5c55\u3002\u6280\u672f\u4e0a\u662f Python + \u6d4f\u89c8\u5668\u81ea\u52a8\u5316 + LLM + SQLite \u72b6\u6001\u673a + FastAPI/React \u5b9e\u65f6\u770b\u677f\u3002\u5b83\u672c\u8d28\u4e0a\u662f\u4e00\u4e2a\u8dd1\u5728\u771f\u5b9e\u4ea4\u6613\u5f0f\u94fe\u8def\u4e0a\u7684\u81ea\u52a8\u5316\u7cfb\u7edf\uff1a\u6709\u72b6\u6001\u6d41\u8f6c\u3001\u6709\u5e42\u7b49\u9632\u91cd\u3001\u6709\u6570\u636e\u4e00\u81f4\u6027\u6821\u9a8c\u3001\u6709\u5168\u7a0b\u53ef\u89c2\u6d4b\u3002'
const PREP_PITCH_HOOK =
  '\u6700\u540e\u534a\u53e5\u662f\u6545\u610f\u57cb\u7684\u94a9\u5b50\u2014\u2014\u628a\u300c\u6c42\u804c\u81ea\u52a8\u5316\u300d\u7ffb\u8bd1\u6210\u300c\u4ea4\u6613\u7cfb\u7edf\u6d4b\u8bd5\u300d\u9762\u8bd5\u5b98\u542c\u5f97\u61c2\u7684\u8bed\u8a00\u3002'

type Highlight = { title: string; vs: string; point: string; color: string }
const PREP_HIGHLIGHTS: Highlight[] = [
  { color: '#0a84ff',
    title: '\u72b6\u6001\u673a + \u5408\u6cd5\u6d41\u8f6c\u6821\u9a8c',
    vs: '\u5bf9\u6807\u8ba2\u5355 / \u4ea4\u6613\u72b6\u6001\u6d4b\u8bd5',
    point: 'applications \u7528\u663e\u5f0f\u5408\u6cd5\u8fc1\u79fb\u8868\u6321\u975e\u6cd5\u8df3\u8f6c\uff08\u4e0d\u5141\u8bb8 FOUND \u76f4\u8df3 OFFER\uff09\u3002\u8e29\u8fc7\u771f bug\uff1a\u67d0 SQL \u7684 CASE \u4fdd\u62a4\u6f0f\u4e86 sent \u7ec8\u6001\uff0c\u5df2\u53d1\u9001\u7684\u56de\u590d\u88ab\u91cd\u65b0\u5206\u6790\u540e\u8986\u5199\u56de pending \u2192 \u91cd\u590d\u53d1\u9001\uff0c\u6b63\u662f\u300c\u7ec8\u6001\u88ab\u975e\u6cd5\u56de\u9000\u300d\u2014\u2014\u91d1\u878d\u91cc\u5c31\u662f\u300c\u5df2\u7ed3\u7b97\u7684\u8ba2\u5355\u4e0d\u80fd\u88ab\u6539\u56de\u672a\u7ed3\u7b97\u300d\u3002' },
  { color: '#30d158',
    title: '\u5e42\u7b49 + \u5185\u5bb9\u6307\u7eb9\u53bb\u91cd',
    vs: '\u5bf9\u6807\u4ea4\u6613\u9632\u91cd / \u5bf9\u8d26',
    point: 'per-job \u539f\u5b50\u64cd\u4f5c + carryover \u5d29\u6e83\u6062\u590d\u3002Boss \u6bcf\u6b21\u641c\u7d22\u8f6e\u6362 encryptJobId\uff08\u4e3b\u952e\u4f1a\u53d8\uff09\uff0c\u5355\u6309 ID \u53bb\u91cd\u4f1a\u91cd\u590d\u6295\u9012\uff1b\u6539\u7b97 content_hash = sha256(\u6807\u9898|\u516c\u53f8id|JD) \u8bc6\u522b\u6362\u9a6c\u7532\u7684\u540c\u4e00\u5c97\u4f4d\u3002\u672c\u8d28\u662f\u53bb\u91cd\u7ef4\u5ea6\u9009\u9519\u2014\u2014\u4e3b\u952e\u4f1a\u53d8\uff0c\u8981\u627e\u4e1a\u52a1\u4e0a\u771f\u6b63\u7a33\u5b9a\u7684\u6307\u7eb9\uff0c\u5bf9\u8d26\u540c\u7406\u3002' },
  { color: '#bf5af2',
    title: '\u9a8c\u8bc1\u7ed3\u679c \u2260 \u9a8c\u8bc1\u52a8\u4f5c',
    vs: '\u6d4b\u8bd5\u65ad\u8a00\u7684\u7075\u9b42',
    point: '\u56de\u590d\u9001\u8fbe\u9a8c\u8bc1\u66fe\u5047\u9633\u6027\uff1a\u53d1\u5b8c\u7acb\u523b\u5339\u914d\u300c\u542b\u524d\u7f00\u7684\u6211\u65b9\u6c14\u6ce1\u300d\uff0c\u649e\u5230\u5386\u53f2\u65e7\u6c14\u6ce1\u8bef\u62a5\u6210\u529f\uff08duration_ms:1 \u662f\u7ea2\u65d7\uff0c\u6ca1\u7b49\u7f51\u7edc\u5f80\u8fd4\u5c31\u547d\u4e2d\uff09\u3002\u6b63\u89e3\uff1a\u53d1\u9001\u540e\u91cd\u626b\u4f1a\u8bdd\u3001\u7b49\u5f02\u6b65\u6e32\u67d3\u3001\u786e\u8ba4\u65b0\u6d88\u606f\u771f\u843d\u5730\u5e76\u56de\u5199 DB\u3002\u63a5\u53e3\u8fd4\u56de 200 \u2260 \u6d88\u606f\u771f\u9001\u8fbe\u3002' },
  { color: '#ff9f0a',
    title: '\u5168\u94fe\u8def\u53ef\u89c2\u6d4b + JSONL \u56de\u653e',
    vs: '\u5bf9\u6807 JD \u7684\u6d41\u91cf\u56de\u653e',
    point: '\u6bcf\u6b65 tool \u7edf\u4e00\u8d70 registry \u81ea\u52a8\u8bb0 trace\u3001\u7ecf SSE \u5b9e\u65f6\u63a8 React \u770b\u677f\uff1b\u6bcf\u6b21\u8fd0\u884c\u843d\u6210\u6301\u4e45\u5316 JSONL\uff0c\u53ef /api/runs/{id}/events \u56de\u653e\u6574\u6761\u5df2\u8dd1\u6d41\u6c34\u7ebf\u3002\u53ef\u89c2\u6d4b\u6027\u662f\u81ea\u52a8\u5316\u80fd\u5b9a\u4f4d\u95ee\u9898\u7684\u524d\u63d0\uff0c\u4e0d\u53ef\u89c2\u6d4b\u7684\u81ea\u52a8\u5316\u53ea\u4f1a\u63a9\u76d6 bug\u3002' },
]

type JdRow = { jd: string; answer: string }
const PREP_JD_ROWS: JdRow[] = [
  { jd: '\u5b9e\u65f6\u4ea4\u6613\u94fe\u8def / \u6e05\u7ed3\u7b97\u6d4b\u8bd5',
    answer: '\u72b6\u6001\u673a\u9a71\u52a8\u7684\u591a\u9636\u6bb5\u6d41\u6c34\u7ebf\uff08W1/W2/W3\uff09\uff0c\u6bcf\u9636\u6bb5\u6709\u660e\u786e\u524d\u7f6e/\u540e\u7f6e\u72b6\u6001\uff0c\u4e0e\u4ea4\u6613\u2192\u6e05\u7b97\u2192\u7ed3\u7b97\u7684\u591a\u9636\u6bb5\u6d41\u8f6c\u540c\u6784\u3002' },
  { jd: '\u8ba2\u5355 / \u98ce\u63a7 / \u8d44\u4ea7\u7ed3\u7b97\u51c6\u786e\u6027',
    answer: '\u72b6\u6001\u6d41\u8f6c\u5408\u6cd5\u6027\u6821\u9a8c + \u5e42\u7b49\u9632\u91cd + \u5185\u5bb9\u6307\u7eb9\u53bb\u91cd + \u300c\u7ec8\u6001\u88ab\u975e\u6cd5\u56de\u9000\u300d\u771f\u5b9e\u7f3a\u9677\u590d\u76d8\u3002' },
  { jd: '\u8bbe\u8ba1\u6d4b\u8bd5\u7528\u4f8b / \u6a21\u62df\u6295\u8d44\u8005\u884c\u4e3a',
    answer: '\u6574\u4e2a Agent \u5c31\u5728\u6a21\u62df\u771f\u5b9e\u6c42\u804c\u8005\u7684\u884c\u4e3a\u5e8f\u5217\uff1b\u5929\u7136\u505a\u884c\u4e3a\u5efa\u6a21\u4e0e\u8fb9\u754c\uff08\u7a7a HR \u6d88\u606f\u7edd\u4e0d\u8d77\u8349\u3001\u5e73\u53f0\u7cfb\u7edf\u63d0\u793a\u4e0d\u80fd\u8bef\u5224\u6210 HR \u6d88\u606f\uff09\u3002' },
  { jd: '\u81ea\u52a8\u5316\u6d4b\u8bd5',
    answer: '\u6d4f\u89c8\u5668\u81ea\u52a8\u5316\uff08DrissionPage\uff09+ 457 \u4e2a pytest \u5355\u6d4b/\u96c6\u6210\u6d4b\u8bd5\uff0c\u6d4b\u8bd5\u5b88\u95e8\uff08\u7eff\u4e86\u624d\u7b97\u5b8c\u6210\uff09\u3002' },
  { jd: '\u6d41\u91cf\u56de\u653e',
    answer: 'JSONL \u5168\u91cf\u843d\u76d8 + \u56de\u653e\u7aef\u70b9\uff0c\u53ef\u4e8b\u540e\u9010\u6b65\u590d\u73b0\u95ee\u9898\u3002' },
  { jd: 'AI \u8d4b\u80fd\u6d4b\u8bd5',
    answer: 'models judge, code decides\uff1a\u53ea\u6709\u6253\u5206/\u610f\u56fe\u5206\u6790\u4ea4\u7ed9 LLM\uff0c\u8def\u7531/\u72b6\u6001/\u91cd\u8bd5\u7528\u786e\u5b9a\u6027\u4ee3\u7801\uff1bLLM \u8f93\u51fa\u4e09\u5c42\u5bb9\u9519\u89e3\u6790\uff08\u4ee3\u7801\u5757\u63d0\u53d6\u2192json.loads\u2192json-repair \u515c\u5e95\uff09\u3002' },
  { jd: 'Python / \u7f51\u7edc / \u6570\u636e\u5e93',
    answer: 'Python 3.11 \u5168\u6808\uff1bSQLite \u7528 WAL + \u7ebf\u7a0b\u5c40\u90e8\u8fde\u63a5 + busy_timeout \u89e3\u51b3\u5e76\u53d1\u5199\u9501\uff1b\u6d4f\u89c8\u5668\u81ea\u52a8\u5316\u672c\u8eab\u5728\u8ddf HTTP/DOM/\u5f02\u6b65\u6e32\u67d3\u6253\u4ea4\u9053\u3002' },
]

type Gap = { gap: string; cope: string }
const PREP_GAPS: Gap[] = [
  { gap: '\u786e\u5b9e\u6ca1\u505a\u8fc7\u91d1\u878d\u6e05\u7ed3\u7b97\u4e1a\u52a1',
    cope: '\u627f\u8ba4\uff0c\u5f3a\u8c03\u53ef\u8fc1\u79fb\u7684\u6d4b\u8bd5\u5e95\u5c42\u80fd\u529b\uff08\u72b6\u6001\u6821\u9a8c / \u4e00\u81f4\u6027\u5e42\u7b49 / \u65ad\u8a00\u4e25\u8c28\uff09+ \u5b66\u4e60\u610f\u613f\u2014\u2014JD \u660e\u786e\u66f4\u770b\u91cd\u5feb\u901f\u5b66\u4e60\u3002' },
  { gap: '\u9879\u76ee\u662f\u81ea\u52a8\u5316\u5f00\u53d1\u4e0d\u662f\u6d4b\u8bd5\u5c97',
    cope: '\u91cd\u6784\u53d9\u4e8b\uff1a\u81ea\u52a8\u5316\u6d4b\u8bd5\u4e0e\u81ea\u52a8\u5316 Agent \u662f\u540c\u4e00\u5957\u6280\u80fd\u2014\u2014\u90fd\u8981\u9a71\u52a8\u771f\u5b9e\u7cfb\u7edf\u3001\u65ad\u8a00\u771f\u5b9e\u7ed3\u679c\u3001\u5904\u7406\u5f02\u6b65\u4e0e\u4e0d\u786e\u5b9a\u6027\u3002' },
  { gap: '\u88ab\u8ffd\u95ee\u4ea4\u6613 / CFA \u7ecf\u9a8c',
    cope: '\u5982\u5b9e\u8bf4\uff1b\u82e5\u6709\u5b9e\u76d8\u4ea4\u6613 / \u671f\u6743\u7ecf\u5386\u4e00\u5b9a\u8981\u8bb2\uff0c\u6362\u6210\u300c\u5bf9\u4ea4\u6613\u6709\u771f\u5b9e\u5174\u8da3\u300d\u7684\u951a\u70b9\u3002' },
]

function PrepTab() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl p-3" style={{ background: 'rgba(255,159,10,0.06)', border: '1px solid rgba(255,159,10,0.2)' }}>
        <p className="text-[14px] leading-relaxed text-text-2">
          <span className="font-semibold text-signal-amber">{PREP_SRC_LABEL}</span>
          {PREP_SRC_NOTE}
        </p>
      </div>

      <Section badge={'\u2460'} title={PREP_T_PITCH} sub={PREP_S_PITCH}>
        <p className="text-[15.5px] leading-relaxed text-text-1">{PREP_PITCH}</p>
        <div className="mt-3 rounded-xl p-3" style={{ background: 'rgba(10,132,255,0.06)', border: '1px solid rgba(10,132,255,0.18)' }}>
          <p className="text-[14.5px] leading-relaxed text-text-2">{PREP_PITCH_HOOK}</p>
        </div>
      </Section>

      <Section badge={'\u2461'} title={PREP_T_HL} sub={PREP_S_HL}>
        <div className="space-y-2">
          {PREP_HIGHLIGHTS.map((h) => (
            <div key={h.title} className="rounded-xl p-3.5" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div className="mb-1.5 flex items-baseline gap-2.5">
                <Dot color={h.color} />
                <span className="text-[16px] font-semibold text-text-1">{h.title}</span>
                <span className="text-[13.5px] text-text-3">{h.vs}</span>
              </div>
              <p className="text-[14.5px] leading-relaxed text-text-2">{h.point}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section badge={'\u2462'} title={PREP_T_JD} sub={PREP_S_JD}>
        <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="grid grid-cols-[minmax(150px,240px)_1fr] gap-2 px-3 py-2 text-[14px] font-semibold uppercase tracking-wider text-text-3"
            style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span>{PREP_H_JD}</span>
            <span>{PREP_H_ANSWER}</span>
          </div>
          {PREP_JD_ROWS.map((r) => (
            <div key={r.jd} className="grid grid-cols-[minmax(150px,240px)_1fr] items-start gap-2 px-3 py-2.5"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="text-[15px] leading-relaxed text-text-1">{r.jd}</span>
              <span className="text-[14.5px] leading-relaxed text-text-2">{r.answer}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section badge={'\u2463'} title={PREP_T_GAP} sub={PREP_S_GAP}>
        <div className="space-y-2">
          {PREP_GAPS.map((g) => (
            <div key={g.gap} className="rounded-xl p-3" style={{ background: 'rgba(255,69,58,0.05)', border: '1px solid rgba(255,69,58,0.16)' }}>
              <p className="text-[15px] font-semibold text-text-1">{g.gap}</p>
              <p className="mt-1 text-[14.5px] leading-relaxed text-text-2">{g.cope}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}

// -- shell --------------------------------------------------------

type TabKey = 'arch' | 'flow' | 'sm' | 'data' | 'prep'
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'arch', label: '\u67b6\u6784' },
  { key: 'flow', label: '\u6d41\u7a0b' },
  { key: 'sm', label: '\u72b6\u6001\u673a' },
  { key: 'data', label: '\u6570\u636e\u6a21\u578b' },
  { key: 'prep', label: '\u9762\u8bd5Prep' },
]

export default function StateMachine() {
  const { workflowRunning } = useAppContext()
  const [tab, setTab] = useState<TabKey>('arch')
  const [live, setLive] = useState<ArchitectureLive | null>(null)

  // Live overlay is optional - the page renders its static structure regardless of
  // whether the fetch succeeds; refresh on an interval so counts stay current.
  useEffect(() => {
    const load = () => API.getArchitecture().then(setLive).catch(() => {})
    void load()
    const id = window.setInterval(load, 15_000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div className="relative space-y-4">
      <DevLabel name="StateMachine" float />
      <p className="text-[16px] leading-relaxed text-text-2">
        {'\u4ece\u524d\u7aef\u770b\u61c2\u6574\u4e2a\u9879\u76ee\uff1a'}
        <span className="text-text-1">{'\u540e\u7aef\u56db\u5c42\u67b6\u6784'}</span>{' \u00b7 '}
        <span className="text-text-1">{'W1/W2/W3 \u6d41\u7a0b'}</span>{' \u00b7 '}
        <span className="text-text-1">{'\u4e09\u72b6\u6001\u673a'}</span>{' \u00b7 '}
        <span className="text-text-1">{'\u6570\u636e\u6a21\u578b'}</span>
        {'\u3002\u9759\u6001\u7ed3\u6784\u4e0e\u4ee3\u7801\u540c\u6b65\uff0c\u53e0\u52a0\u5b9e\u65f6\u8ba1\u6570\u4e0e\u8fd0\u884c\u72b6\u6001\u3002'}
      </p>

      <div className="flex gap-1 rounded-xl p-1" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-[16px] font-medium transition ${
              tab === t.key ? 'text-text-1' : 'text-text-3 hover:text-text-2'
            }`}
            style={tab === t.key ? { background: 'rgba(10,132,255,0.16)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' } : undefined}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'arch' && <ArchTab live={live} running={workflowRunning} />}
      {tab === 'flow' && <FlowTab running={workflowRunning} />}
      {tab === 'sm' && <StateMachineTab live={live} />}
      {tab === 'data' && <DataTab live={live} />}
      {tab === 'prep' && <PrepTab />}
    </div>
  )
}
