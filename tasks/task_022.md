# Task 022 — 停止按钮 UI 修复（每个进度卡独立停止按钮 + 正确反馈）

## 背景

当前停止按钮有三个问题：
1. `btn-workflow-stop` 只放在 Apply 进度卡里，Check 进度卡没有停止按钮
2. 点击后 POST /api/workflow/stop 成功时 `.textContent = '⏹ 停止'` 但 `disabled` 未重置，
   按钮显示正常文字却不可点击，用户看不出发生了什么
3. workflow 以 `status="stopped"` 结束时前端没有特殊处理，无"已停止"提示

## 修改范围

只修改以下两个文件：
- `dashboard/static/index.html`
- `dashboard/static/app.js`

不修改后端代码。

---

## 详细要求

### 1. index.html — Check 进度卡加停止按钮

在 `workflow-progress-check` 卡的 card-header 里，和 Apply 卡一样加一个停止按钮：

```html
<div class="card" id="workflow-progress-check">
  <div class="card-header">
    <div>
      <div class="card-title">Check 执行进度</div>
      <div class="card-subtitle" id="workflow-summary-check">等待开始...</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-ghost btn-sm hidden"
              id="btn-workflow-stop-check"
              style="color:var(--color-danger);border-color:var(--color-danger)">
        ⏹ 停止
      </button>
    </div>
  </div>
  <div id="workflow-track-check" class="metro-track"></div>
</div>
```

同时把 Apply 卡的停止按钮 id 从 `btn-workflow-stop` 改为 `btn-workflow-stop-apply`：

```html
<button class="btn btn-ghost btn-sm hidden"
        id="btn-workflow-stop-apply"
        style="color:var(--color-danger);border-color:var(--color-danger)">
  ⏹ 停止
</button>
```

### 2. app.js — 停止按钮显示/隐藏逻辑

将所有引用 `btn-workflow-stop` 的地方替换为按 workflow 区分的逻辑。
写一个辅助函数 `getStopBtn(workflow)` 返回对应按钮元素：

```js
function getStopBtn(workflow) {
  return document.getElementById(
    workflow === 'apply' ? 'btn-workflow-stop-apply' : 'btn-workflow-stop-check'
  );
}
```

#### markWorkflowRunningState 修改

原来只控制一个按钮，现改为：
- 当 `running` 非空时，只显示对应 workflow 的停止按钮，隐藏另一个
- 当 `running` 为 null 时，同时隐藏两个按钮，并恢复两个按钮的可用状态

```js
function markWorkflowRunningState(running) {
  workflowRunning = running || null;
  // ... 原有 applyBtn/checkBtn/tip 逻辑不变 ...

  const applyStopBtn = getStopBtn('apply');
  const checkStopBtn = getStopBtn('check');
  if (applyStopBtn) {
    applyStopBtn.classList.toggle('hidden', running !== 'apply');
    if (!running) { applyStopBtn.disabled = false; applyStopBtn.textContent = '⏹ 停止'; }
  }
  if (checkStopBtn) {
    checkStopBtn.classList.toggle('hidden', running !== 'check');
    if (!running) { checkStopBtn.disabled = false; checkStopBtn.textContent = '⏹ 停止'; }
  }
}
```

#### updateProgressStep 修改

`step === 'stop' && status === 'stopping'` 分支：用 `getStopBtn(workflow)` 获取按钮：

```js
} else if (step === 'stop' && status === 'stopping') {
  const stopBtn = getStopBtn(workflow);
  if (stopBtn) { stopBtn.disabled = true; stopBtn.textContent = '停止中...'; }
}
```

`step === 'done' && status === 'stopped'` 的处理：
在 `step === 'done'` 分支中，根据 `status` 显示不同 toast：

```js
if (step === 'done') {
  markWorkflowRunningState(null);
  if (status === 'error') {
    showToast('Workflow 执行失败', { msg: message, type: 'error', duration: 8000 });
  } else if (status === 'stopped') {
    showToast('已停止', { msg: message, type: 'warning', duration: 5000 });
  }
  loadDashboard();
}
```

### 3. app.js — 停止按钮点击事件

原来只注册一个按钮的事件，改为对两个按钮各注册，逻辑相同：

```js
['apply', 'check'].forEach((wf) => {
  const stopBtn = getStopBtn(wf);
  if (!stopBtn) return;
  stopBtn.addEventListener('click', () => {
    stopBtn.disabled = true;
    stopBtn.textContent = '停止中...';
    fetch('/api/workflow/stop', { method: 'POST' })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          showToast('停止请求已发送', { msg: '当前步骤完成后停止', type: 'info', duration: 3000 });
          // 保持 disabled=true 和"停止中..."直到 SSE done 事件到来
        } else {
          // 没有 workflow 在运行，恢复按钮
          stopBtn.disabled = false;
          stopBtn.textContent = '⏹ 停止';
          showToast('无法停止', { msg: data.detail || '没有正在运行的 workflow', type: 'error', duration: 4000 });
        }
      })
      .catch(() => {
        stopBtn.disabled = false;
        stopBtn.textContent = '⏹ 停止';
        showToast('停止请求失败', { type: 'error', duration: 4000 });
      });
  });
});
```

**关键点**：
- 成功时：保持 `disabled=true` 和"停止中..."，不要立刻恢复——等 SSE `done` 事件触发 `markWorkflowRunningState(null)` 统一恢复
- 失败时（网络错误或 `data.ok === false`）：立刻恢复按钮，弹出错误 toast

---

## 验收标准

1. Apply 进度卡有 `btn-workflow-stop-apply` 按钮，Check 进度卡有 `btn-workflow-stop-check` 按钮
2. Apply workflow 运行时只有 Apply 卡的停止按钮可见，Check 停止按钮隐藏（反之亦然）
3. 点击停止 → 按钮禁用显示"停止中..." → 弹出"停止请求已发送" toast
4. POST /api/workflow/stop 失败时 → 按钮恢复可点击 → 弹出错误 toast
5. Workflow 以 `status="stopped"` 结束时 → 弹出"已停止" warning toast → 线路图保持停止时的状态
6. Workflow 正常结束后两个停止按钮都恢复为 hidden + enabled + "⏹ 停止"

---

## 不需要做的事

- 不修改后端代码
- 不修改 style.css（使用已有的 btn/btn-ghost/btn-sm 类）
- 不改变线路图站点的渲染逻辑
