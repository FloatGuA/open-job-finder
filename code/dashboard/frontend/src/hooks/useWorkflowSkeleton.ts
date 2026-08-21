import { useEffect, useState } from 'react'

import { API } from '@/api'

// W1/W2/W3 有哪些步骤、每步是 run 级还是循环级。**从后端导出，前端不再手抄**——
// 抄的那份烂过：W3 少了 4 个步骤（freshness/detect/resume/upsert）、W2 少了 wechat，
// 而且不会报错（少登记的步骤在空闲态就是不存在，跑起来才冒出来）。
// 后端的声明由 tests/test_pipeline_skeleton.py 双向盯着，跟源码不一致就红。
export interface WorkflowSkeleton {
  steps: Record<string, string[]>
  run_steps: Record<string, string[]>
  loop_steps: Record<string, string[]>
}

const EMPTY: WorkflowSkeleton = { steps: {}, run_steps: {}, loop_steps: {} }

// 一次会话里这份数据不会变，而 WorkflowTrack 里有两个组件要用它——
// 各拉各的就是同一份数据的 N 次请求。模块级缓存 + 共享 in-flight promise。
let cache: WorkflowSkeleton | null = null
let inflight: Promise<WorkflowSkeleton> | null = null

/** 仅供测试：清掉模块级缓存，让用例之间互不影响。 */
export function __resetSkeletonCache(): void {
  cache = null
  inflight = null
}

export function useWorkflowSkeleton(): WorkflowSkeleton {
  // 初值是空 map 而不是 undefined：调用方写的是 `run_steps[wf] ?? []`，
  // run_steps 本身 undefined 的话那一行就炸了。
  const [data, setData] = useState<WorkflowSkeleton>(cache ?? EMPTY)

  useEffect(() => {
    if (cache) {
      setData(cache)
      return
    }
    if (!inflight) {
      inflight = API.workflowSkeleton().then((r) => {
        cache = r
        return r
      })
    }
    let alive = true
    inflight
      .then((r) => { if (alive) setData(r) })
      .catch(() => { inflight = null })   // 失败就让下一个挂载重试，别把空态钉死
    return () => { alive = false }
  }, [])

  return data
}
