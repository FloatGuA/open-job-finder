# Task 027 — Jobs 页（职位进度表格）

## 背景

task_026 完成了 Dashboard 主页。本 task 实现"职位进度"页面（`pages/Jobs.tsx`），
展示所有求职记录的进度表格，支持状态筛选 Tabs、分页导航和职位详情弹窗。

---

## 涉及文件

**修改：**
- `code/dashboard/frontend/src/pages/Jobs.tsx` — 从占位升级为完整页面

**新建（允许内联在 Jobs.tsx，也允许拆分为独立文件）：**
- 职位详情 Dialog（可内联为 `JobDetailDialog` 组件）

---

## 一、状态 Tab 筛选

在页面顶部显示一行 Tab 按钮，对应以下状态过滤值：

| Tab 标签 | 传给 API 的 `status` 参数 |
|----------|--------------------------|
| 全部     | `undefined`（不传）       |
| 已发现   | `DISCOVERED`             |
| 已评分   | `SCORED`                 |
| 已投递   | `APPLIED`                |
| 已回复   | `RESPONDED`              |
| 简历请求 | `RESUME_REQUESTED`       |
| 面试     | `INTERVIEW`              |
| Offer    | `OFFER`                  |
| 已拒绝   | `REJECTED`               |
| 错误     | `ERROR`                  |

切换 Tab 时，重置 `page` 为 1，重新调用 `API.getJobs(status, 1, PAGE_SIZE)`。

---

## 二、Jobs 表格

每行显示以下字段（按 API `_serialize_record` 实际返回）：

| 列名   | 字段         | 说明                              |
|--------|--------------|-----------------------------------|
| 公司   | `company`    |                                   |
| 职位   | `title`      |                                   |
| 状态   | `status`     | Badge 组件，不同状态不同颜色      |
| 评分   | `score`      | 数字，无值显示 `—`                |
| 决策   | `decision`   | 字符串，无值显示 `—`              |
| 投递时间| `applied_at` | 格式化日期，无值显示 `—`         |
| 操作   |              | "详情" 按钮，点击打开 Dialog       |

**注意**：`city` 和 `salary` 字段服务端始终返回空字符串（已知限制），不在表格中展示。

### 状态 Badge 颜色

| 状态               | 颜色               |
|--------------------|-------------------|
| APPLIED            | 品牌蓝（brand）    |
| RESPONDED / RESUME_REQUESTED | 绿色（emerald）|
| INTERVIEW / OFFER  | 黄色（amber）      |
| REJECTED / ERROR   | 红色（rose）       |
| 其他（DISCOVERED/SCORED） | 灰色（text-3）|

---

## 三、分页

显示"上一页"和"下一页"按钮，以及"第 X 页 / 共 Y 页"文字。

```
每页大小 PAGE_SIZE = 20
total_pages = Math.ceil(total / PAGE_SIZE)
```

- 第 1 页时"上一页"disabled
- 最后一页时"下一页"disabled
- `total === 0` 时显示"暂无数据"替代表格

---

## 四、JobDetailDialog

点击"详情"后，用原生 `<dialog>` 元素（或手写叠层 div）展示单条职位的完整信息。

**展示字段：**
- company、title、status、score、decision、critic_verdict
- applied_at、responded_at、resume_path、error_msg
- url（可点击链接）

**打开/关闭：**
```tsx
const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
const selectedJob = jobs.find(j => j.job_id === selectedJobId)
// selectedJobId !== null 时显示 Dialog
```

不调用 `API.getJob(id)` 单独拉取（表格已有完整数据，避免额外请求）。

---

## 五、数据加载

```tsx
const PAGE_SIZE = 20

export default function Jobs() {
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<JobsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    API.getJobs(status, page, PAGE_SIZE)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [status, page])
  // ...
}
```

---

## 六、JobDetailDialog 样式

叠层方案（不依赖 shadcn）：

```tsx
{selectedJob && (
  <div
    className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
    onClick={() => setSelectedJobId(null)}
  >
    <div
      className="w-full max-w-lg rounded-2xl border border-border-subtle bg-bg-card p-6 shadow-2xl"
      onClick={e => e.stopPropagation()}
    >
      {/* 内容 */}
      <button onClick={() => setSelectedJobId(null)}>✕</button>
    </div>
  </div>
)}
```

---

## 七、整体样式

- 页面容器：`space-y-4`
- Tabs 行：`flex flex-wrap gap-2`
- Tab 按钮（活跃）：`rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white`
- Tab 按钮（非活跃）：`rounded-lg border border-border-default bg-bg-card2 px-3 py-1.5 text-xs font-medium text-text-2 hover:bg-bg-hover hover:text-text-1`
- 表格容器：`rounded-2xl border border-border-subtle bg-bg-card overflow-hidden`
- 表头：`border-b border-border-subtle bg-bg-card2 px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-3`
- 表格行：`border-b border-border-subtle px-4 py-3 text-sm text-text-1`（最后一行去掉 `border-b`）
- 交替行背景：`even:bg-bg-card2/30`
- 分页行：`flex items-center justify-between text-sm text-text-2`
- 分页按钮：与 Topbar 的 pause 按钮同款（`rounded-xl border border-border-default bg-bg-card2 px-4 py-2 text-sm font-medium text-text-1 hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed`）

---

## 八、构建验证

完成后在 `code/dashboard/frontend/` 执行：

```bash
npm run build
```

确认无 TypeScript 错误。

---

## 约束

- 不修改后端任何文件
- 不安装新的 npm 包
- Dialog 使用手写叠层 div（不引入 @radix-ui/dialog 或 shadcn Dialog，避免依赖膨胀）
- `city` 和 `salary` 已知为空，不在 UI 上展示，不添加占位符
- 所有字符串直接写 UTF-8 中文

---

## 验证点

1. `npm run build` 通过
2. 点击侧边栏"职位进度"显示表格（API 未连接时显示空行/暂无数据）
3. Tab 切换正确过滤状态
4. 分页按钮正确翻页
5. 点击"详情"打开 Dialog，点击背景或 ✕ 关闭
