# Task 010 — 第一轮 Bug 修复（M1 / M3 / M5）

## 背景

工厂初始构建完成（task_001~009 全部通过审查），本次修复审查遗留的三个 Must Fix：

- **M1 [task_003]**：`ClaudeCLIProvider.complete()` subprocess 使用 list 形式正确，需加安全注释说明不使用 `shell=True`
- **M3 [task_006]**：`ResumeManager.render_pdf()` 在 `weasyprint` 未安装时抛出 `ModuleNotFoundError`，用户无法得到有效指引
- **M5 [task_009]**：`POST /api/resume/upload` 缺文件大小限制，攻击者可上传超大文件导致内存耗尽

注意：M2（task_005，打招呼用户名）和 M4（task_008，SCORED 状态 score_result）在代码中已经正确实现，无需修改。

---

## 修改范围

### 文件 1：`services/llm_client.py`

**位置**：`ClaudeCLIProvider.complete()` 方法，`subprocess.run(...)` 调用处（约第 36 行）

**修改**：在 `subprocess.run(...)` 调用上方添加单行注释，说明始终使用 list 形式而非 `shell=True`，以防止 shell injection：

```python
# Use list form (never shell=True) to prevent shell injection from prompt content.
result = subprocess.run(
    ["claude", "-p", full_prompt],
    ...
)
```

### 文件 2：`services/resume_manager.py`

**位置**：`render_pdf()` 方法开头的 import 语句（约第 61 行）

**修改**：将 `from weasyprint import HTML` 包裹在 try/except ImportError 中，捕获后抛出含安装指引的 `RuntimeError`：

```python
try:
    from weasyprint import HTML
except ImportError as exc:
    raise RuntimeError(
        "WeasyPrint is not installed. Install it with:\n"
        "  pip install weasyprint\n"
        "On Linux you may also need: apt-get install libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0"
    ) from exc
```

### 文件 3：`dashboard/server.py`

**位置**：`upload_resume()` 函数，`content = await file.read()` 之后（约第 217 行）

**修改**：在写入文件之前检查内容大小，超过 10MB 则抛出 HTTP 400：

```python
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

content = await file.read()
if len(content) > MAX_UPLOAD_BYTES:
    raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
```

常量 `MAX_UPLOAD_BYTES` 定义在函数体内（局部常量），保持代码局部性。

---

## 验收标准

1. `llm_client.py` 中 `subprocess.run` 调用上方有注释说明 list 形式及 no-shell 原因
2. `resume_manager.py` 在 weasyprint 未安装时，抛出 `RuntimeError` 并包含安装命令文本
3. `dashboard/server.py` 上传超过 10MB 文件时返回 HTTP 400，小于 10MB 文件正常处理
4. 三处修改均不引入新的依赖或改变现有行为逻辑

---

## 不在本次范围内

- 安装或验证 WeasyPrint（需系统级依赖，手动操作）
- Boss直聘 登录 session 测试
- 其他功能扩展（第二轮迭代内容）
