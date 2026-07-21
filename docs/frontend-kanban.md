# 前端重构看板（Navigator Kanban）

> 逐个 navigator 的方向与实现思路，供日后实现。基准见 `docs/frontend.md`。
> 列：⬜ 待办 · 🟦 进行中 · ✅ 已适配新前端。最后更新：2026-06-13。

聚合结论：**7 个 navigator 全部已接线、能跑**——瓶颈不在接线，在**设计质量 + 冗余收敛**。

---

## 🟦 Dashboard（总览 / 控制台）
- **现状**：OVERVIEW(stats) · SESSION(检查+登录流程+打开Boss) · WORKFLOW CONTROL(WorkflowPanel) · WORKFLOW PROGRESS(scope×step×tool 层级树) · PENDING REPLIES · AUTO SCHEDULE · SCHEDULE LOG。全接线。
- **问题**：7 区块过长；PENDING REPLIES 与「HR会话」重复；SCHEDULE LOG 与「运行日志」重叠。
- **方向**：定位"总览 + 控制台"。把 reply 审批收敛到 HR会话（dashboard 只留计数/入口）；保留 OVERVIEW + SESSION + CONTROL + PROGRESS + SCHEDULE。
- **实现思路**：用 `ui/Card` + `ui/SectionHeader(adapted)` 重排；PENDING REPLIES 改成指向 HR会话 的摘要卡。
- **状态**：WORKFLOW CONTROL / PROGRESS 已标 ✅；其余区块待重排。

## ⬜ 职位进度（Jobs）— 优先级：高
- **现状**：`getJobs` 分页列表(按 status 过滤) + `getStats` + `clearErrorJobs` + `browseUrl`。岗位流水 DISCOVERED→SCANNED→SCORED→APPLIED→RESPONDED→…
- **方向**：岗位流水主视图——按 stage 看每个岗位的评分 / JD / 投递时间 / HR / 进展。W1 幻影修复后 APPLIED 现在可信。
- **实现思路**：stage 过滤 + 列表/看板切换 + 点开 `getJob` 看详情；与 OVERVIEW 状态分布共用语义色。

## ⬜ HR会话（Chat）— 优先级：高
- **现状**：`getConversations` + reply 审批(approve/revise/dismiss/cancel/markSent) + `browseUrl`。
- **问题**：reply 审批与 dashboard PENDING REPLIES **重复实现**。
- **方向**：HR 会话"收件箱"——会话列表(按公司/阶段) + 详情(消息流 + LLM 意图 + 待审批回复 + 发简历状态)。审批逻辑**收敛到此处唯一实现**。
- **实现思路**：左列表右详情；dashboard 改为引用摘要。

## ⬜ 运行日志（Logs）— 优先级：中
- **现状**：`getRuns` + `getRunDetail`。run 历史(jsonl) + step/tool 详情。
- **方向**：历史 run 浏览器 = WORKFLOW PROGRESS 的"回放版"。选一个 run，用**同一套层级树**渲染它的 scope×step×tool。
- **实现思路**：把 WorkflowTrack 的树渲染抽成共享组件（吃 live 事件 / 吃静态 run detail 两种数据源）；Logs 选 run → getRunDetail → 喂树。

## ⬜ 搜索配置（Profile）— 优先级：高
- **现状**：`getProfile` + `saveProfile` + `previewSearch`。求职偏好(profile.yaml：岗位/城市/薪资/经验) + 预览 Boss 搜索 URL。
- **方向**："求职偏好"——W1 搜什么的源头。结构化表单 + 实时预览搜索 URL/结果。
- **实现思路**：分组表单 + `previewSearch` 即时反馈 + filters(`getDistricts`/`getPositions`/`getIndustries`)联动下拉。

## ⬜ 配置（Config）— 优先级：中
- **现状**：`getConfigProfile` + `getLlmConfig` + update/save。系统配置 + LLM 配置(capabilities fast/balanced/powerful + tool_providers)。
- **问题**：与「搜索配置」「环境配置」三个 config 页边界模糊；**LLM 配置在 Config 和 Setup 都有**。
- **方向**："系统 / LLM 配置"——只管系统级 + LLM 路由，作为 LLM 配置**唯一入口**。
- **实现思路**：分组 系统 / LLM 链路；从 Setup 移除重复的 LLM 配置（改引用）。

## ⬜ 环境配置（Setup）— 优先级：中
- **现状**：`getOnboarding` + `checkSession` + `saveLogin` + LLM config + `uploadResume`。首次引导。
- **问题**：session 登录用 checkSession+saveLogin（**和 dashboard 旧版一样不完整**，缺 open-login/confirm-login）；LLM 配置与 Config 重复。
- **方向**：一次性 setup 向导(session → LLM → 简历)。
- **实现思路**：分步向导；session 登录接 `openLogin`/`confirmLogin`（同 dashboard 已修）；LLM 去重引用 Config。

---

## 横切任务（cross-cutting）
1. **去重三处**：reply 审批（→ HR会话唯一）、LLM 配置（→ Config 唯一）、session 登录流程（统一 openLogin/confirmLogin）。
2. **共享树组件**：抽出 WorkflowTrack 的 scope×step×tool 渲染，供 Logs 回放复用。
3. **ui 基元铺开**：新建/重构页面优先用 `ui/Card` `ui/SectionHeader` `ui/Button`；逐步替换内联重复样式。
4. **逐页打 `adapted` 标记**：每适配完一个 navigator，`SectionHeader adapted` 标上，便于追踪进度。

## 未接线后端能力（按需）
- `check/attachment-resume`（本地简历检查，相关性存疑）、`config/system`（归 Config 页）。
