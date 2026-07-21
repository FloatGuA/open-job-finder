# Task 041 — Dashboard Logs 页

## Goal
按新 JSONL 格式重写 Dashboard Logs 页面：后端两个 API endpoint + 前端 Logs.tsx 双 Tab 视图（Flow / Decisions）。

## Background
现有 Logs.tsx 是基于旧 event_log.py 格式（RunLogger v1）构建的。新格式（T031 产出）区分 Trace event（event="step"/"tool"）和 Business event（event=named），字段结构不同，需要完全重写解析逻辑。

后端需要新的 API 接口分组返回 steps + tools + business_events。前端按新数据结构重写两个 Tab 视图。

依赖：T031（RunLogger JSONL 格式）+ T040（有真实日志文件可测试）。

## Implementation Requirements

### 后端：`code/dashboard/server.py`

**GET /api/runs**

解析 `logs/runs/` 下所有 JSONL 文件，返回 run 列表。

```json
{
  "runs": [
    {
      "run_id": "w1_20260527_0900",
      "pipeline": "w1",
      "status": "successful",
      "duration_ms": 45000,
      "started_at": "2026-05-27T09:00:00",
      "summary": {"cards_viewed": 20, "applied": 5, "skipped": 15}
    }
  ]
}
```

从每个 JSONL 文件中只读取 `event="run_start"` 和 `event="run_end"` 两条，不加载全部事件（性能）。

**GET /api/runs/{run_id}**

读取对应 JSONL 文件的全部内容，返回分组后的结构：

```json
{
  "run_id": "...",
  "pipeline": "w1",
  "status": "successful",
  "started_at": "...",
  "duration_ms": 45000,
  "summary": {...},
  "steps": [
    {
      "step": "fetch_jd",
      "scope": {"job_id": "abc123", "company": "字节跳动"},
      "status": "successful",
      "duration_ms": 820,
      "data": {"salary_decoded": "25-40k"},
      "ts": "...",
      "tools": [
        {
          "tool": "read_panel_jd",
          "status": "successful",
          "duration_ms": 350,
          "data": {"salary_raw": "25k-40k·13薪"},
          "ts": "..."
        }
      ]
    }
  ],
  "business_events": [
    {
      "event": "job_scored",
      "scope": {"job_id": "...", "company": "..."},
      "data": {"score": 78, "reason": "...", "above_threshold": true},
      "ts": "..."
    }
  ]
}
```

steps 按 ts 排序；每个 step 下的 tools 按 ts 排序；business_events 独立列表按 ts 排序。

Tool 事件归属到最近的前一个 Step 事件（按时间戳）。

### 前端：`code/dashboard/frontend/src/pages/Logs.tsx`

完全重写现有 Logs.tsx，保留左栏 run 列表 + 右栏详情的双栏布局。

**左栏（Run 列表）**：
- 显示 run_id / pipeline 类型图标（w1/w2）/ 状态 / 时长 / summary 关键数字
- 点击选中 run → 右栏加载详情
- 顶部 w1/w2 筛选 tab（保持现有功能）

**右栏（两个 Tab）**：

Tab 1：Flow（Trace 视图）
- Step 时间线：每个 Step 一行，显示 step 名 / scope / 状态 / 时长
- 每个 Step 可展开（默认折叠）：展示该 Step 下的 Tool 列表（tool 名 / 状态 / 时长 / data 字段）
- 状态用颜色编码（successful=绿 / degraded=橙 / skipped=灰 / failed=红）

Tab 2：Decisions（Business 视图）
- 按事件时间线展示 business_events
- 每个 event 显示：event 名 / scope / data 的关键字段（不需要全显示，每类 event 选 2-3 个最重要的字段）
- 建议分组：W1 事件（job_scored/applied/skipped）和 W2 事件（intent_analyzed/resume_sent/reply_sent/stage_advanced 等）用小标题区分

**所有中文字符串**：继续遵循项目规范，用 `\uXXXX` escape，不写裸中文。

## Acceptance Criteria

- [ ] 有真实 JSONL 数据时，GET /api/runs 返回正确 run 列表，summary 字段解析正确
- [ ] GET /api/runs/{run_id} 返回 steps + tools 分组结构（Tool 归属到对应 Step）
- [ ] Dashboard Logs 页左栏显示 run 列表，点击后右栏加载 Flow tab
- [ ] Flow tab：Step 时间线可见，展开后显示 Tool 列表
- [ ] Decisions tab：business_events 按时间线展示，每个 event 的 data 字段可读
- [ ] npm run build 无 TypeScript 错误

## Reference
- design/logging.md（JSONL 格式 / Dashboard 消费章节）
- code/dashboard/frontend/src/pages/Logs.tsx（现有文件，读懂后重写）
- code/dashboard/server.py（了解现有路由风格，API 命名约定）
- code/dashboard/frontend/src/api/index.ts（了解 API 调用层结构）
