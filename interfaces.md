# Interface Registry

## Implemented

| Interface | File | Signature | Description |
|-----------|------|-----------|-------------|
| `ApplicationTracker.__init__` | `code/services/tracker.py` | `__init__(db_path: str = "data/jobs.db")` | SQLite tracker 初始化 |
| `ApplicationTracker._create_tables (new schema)` | `code/services/tracker.py` | DDL 重写（T030） | applications/hr_conversations/hr_messages 新 schema；actions 表删除 |
| `ApplicationTracker.upsert` | `code/services/tracker.py` | `upsert(record: ApplicationRecord) -> None` | 插入或更新投递记录（新 schema，无废弃字段） |
| `ApplicationTracker.get` | `code/services/tracker.py` | `get(job_id: str) -> Optional[ApplicationRecord]` | 按 job_id 查询记录 |
| `ApplicationTracker.update_status` | `code/services/tracker.py` | `update_status(job_id: str, new_status: AppStatus, **extra_fields) -> None` | 直接 SQL UPDATE 状态；extra_fields 仅 score/applied_at/hr_name |
| `ApplicationTracker.upsert_hr_conversation` | `code/services/tracker.py` | `upsert_hr_conversation(conv: HRConversation, boss_conv_id: str = "") -> None` | 写入 HR 会话（新 schema；intent/reply 字段由 update_hr_analysis 单独管理） |
| `ApplicationTracker.update_hr_analysis` | `code/services/tracker.py` | `update_hr_analysis(conv_id: str, intent: str, reply_text: Optional[str], reply_status: Optional[str]) -> None` | 写入 LLM 分析结果；CASE 保护 approved/sent 状态不覆写 |
| `ApplicationTracker.insert_hr_messages` | `code/services/tracker.py` | `insert_hr_messages(conv_id: str, messages: List[dict]) -> int` | 批量写入消息，INSERT OR IGNORE，返回 inserted_count |
| `ApplicationTracker.get_hr_messages` | `code/services/tracker.py` | `get_hr_messages(conv_id: str) -> List[dict]` | 按 conv_id 查询消息历史，按 id 排序 |
| `ApplicationTracker.get_approved_replies` | `code/services/tracker.py` | `get_approved_replies() -> List[HRConversation]` | 查询已批准回复 |
| `ApplicationTracker.mark_reply_sent` | `code/services/tracker.py` | `mark_reply_sent(conv_id: str) -> None` | 发送后清空 reply_status=NULL, reply_text=NULL |
| `StepStatus` | `code/pipeline/base.py` | `Enum: SUCCESSFUL/DEGRADED/SKIPPED/FAILED` | Step 执行状态枚举 |
| `StepOutput` | `code/pipeline/base.py` | `@dataclass(status: StepStatus, error: Optional[str])` | Step 输出基类 |
| `RunLogger` | `code/services/run_logger.py` | `RunLogger(run_id: str, pipeline: str)` + `log_run_start/log_run_end/log_step/log_tool/log_business_event` | per-run JSONL 写入器，新格式 |
| `BaseTool` | `code/tools/base.py` | `ABC: name/description/input_schema/execute(**kwargs)->ToolResult` | Tool 抽象基类 |
| `ToolResult` | `code/tools/base.py` | `@dataclass(ok: bool, data: dict={}, error: Optional[str]=None)` | Tool 执行结果 |
| `ToolRegistry` | `code/tools/registry.py` | `ToolRegistry(browser, db, llm_client, prompt_manager, logger)` + `register/get/list_tools/call` | Tool 统一持有和调用 |

## Planned

| Interface | Planned Task | Signature | Description |
|-----------|--------------|-----------|-------------|
| `PromptManager` | `code/services/prompt_manager.py` | `PromptManager(prompts_dir=None)` + `load(name)->str` + `render(name, context)->str` | 提示词文件加载和占位符渲染；缺占位符抛 ValueError |
| `ProfileLoader` | `code/services/profile_loader.py` | `ProfileLoader(profile_path=None)` + `load()->Profile` | profile.yaml 读取；name 必填；缺字段给默认值 |
| `ReflectionMemory` | `code/memory/base.py` | `ABC: read(query)->Optional[str] / write(key,value) / summarize()->str` | Reflection Memory 接口（当前仅 NullReflectionMemory 实现） |
