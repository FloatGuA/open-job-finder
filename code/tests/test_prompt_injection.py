"""PromptManager 用户自定义注入（global 系统层 + per-task 任务层）。"""
from services.prompt_manager import PromptManager


def test_no_injection_leaves_prompt_unchanged():
    pm_plain = PromptManager()
    pm_empty = PromptManager(injection={"global": "", "score_job": ""})
    ctx = {"title": "T", "company": "C", "jd_text": "J", "profile_summary": "P"}
    assert pm_plain.render("score_job", ctx) == pm_empty.render("score_job", ctx)


def test_global_injection_appended_to_all_tasks():
    pm = PromptManager(injection={"global": "我看重远程"})
    score = pm.render("score_job", {"title": "T", "company": "C", "jd_text": "J", "profile_summary": "P"})
    reply = pm.render("generate_reply", {"company": "C", "job_title": "T", "intent": "general", "messages": "m"})
    assert "我看重远程" in score
    assert "我看重远程" in reply  # generate_reply 不吃 system，全局注入也必须覆盖到它
    assert "补充指令" in score


def test_task_injection_only_targets_its_own_prompt():
    pm = PromptManager(injection={"score_job": "远程岗位加分"})
    score = pm.render("score_job", {"title": "T", "company": "C", "jd_text": "J", "profile_summary": "P"})
    reply = pm.render("generate_reply", {"company": "C", "job_title": "T", "intent": "general", "messages": "m"})
    assert "远程岗位加分" in score
    assert "远程岗位加分" not in reply  # 任务层不外溢到别的 prompt


def test_global_and_task_stack():
    pm = PromptManager(injection={"global": "全局说明", "generate_reply": "语气主动"})
    reply = pm.render("generate_reply", {"company": "C", "job_title": "T", "intent": "general", "messages": "m"})
    assert "全局说明" in reply
    assert "语气主动" in reply


def test_unrelated_injection_key_never_leaks():
    # 只有显式白名单里的 task 键会被取用；无关键（如 name）不会进 prompt。
    pm = PromptManager(injection={"name": "张三", "analyze_intent": "看重意图"})
    intent = pm.render("analyze_intent", {"company": "C", "job_title": "T", "messages": "m"})
    assert "看重意图" in intent
    assert "张三" not in intent
