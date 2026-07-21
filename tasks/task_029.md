# Task 029 — Profile 页 + Setup 页

## 背景

task_028 完成了 Chat 页。本 task 实现最后两个页面：
- **Profile 页**（`pages/Profile.tsx`）：查看和编辑求职偏好表单
- **Setup 页**（`pages/Setup.tsx`）：系统状态检查 + 简历上传

完成后前端迁移全部收尾。旧的 `static/app.js` 和 `static/style.css` 已由 Vite `emptyOutDir: true` 在 task_025 构建时清除，无需额外处理。

---

## 涉及文件

**修改：**
- `code/dashboard/frontend/src/pages/Profile.tsx`
- `code/dashboard/frontend/src/pages/Setup.tsx`
- `code/dashboard/frontend/src/api/index.ts`（扩展 `Profile` 接口）

---

## 一、Profile 接口扩展（api/index.ts）

现有 `Profile` 接口仅有部分字段，需补全服务端实际返回的字段：

```typescript
export interface Profile {
  name?: string
  keywords?: string[]
  cities?: string[]
  experience?: string[]
  degree?: string[]
  salary?: string
  scale?: string[]
  job_types?: string[]
  financing?: string[]
  districts?: string[]
  position_types?: string[]
  industries?: string[]
  boss_online?: boolean
}
```

---

## 二、Profile.tsx

### 功能

加载 `API.getProfile()`，以可编辑表单展示，用户修改后点击"保存"调用 `API.saveProfile(data)`。

### 字段映射

| 字段 | 输入类型 | 说明 |
|------|---------|------|
| `name` | 文本输入 | 姓名 |
| `salary` | 文本输入 | 期望薪资，如 "15k-25k" |
| `keywords` | 逗号分隔文本输入 | 职位关键词，如 "Python, 后端, AI" |
| `cities` | 逗号分隔文本输入 | 求职城市，如 "上海, 北京" |
| `experience` | 逗号分隔文本输入 | 经验年限选项 |
| `degree` | 逗号分隔文本输入 | 学历要求 |
| `scale` | 逗号分隔文本输入 | 公司规模 |
| `job_types` | 逗号分隔文本输入 | 职位类型 |
| `financing` | 逗号分隔文本输入 | 融资阶段 |
| `industries` | 逗号分隔文本输入 | 行业 |

`districts`、`position_types` 字段较复杂（Boss直聘 内部 ID），在本页面以只读文字展示当前值（不提供编辑）。

### 实现细节

```tsx
// 内部状态：将数组字段转为逗号分隔字符串便于编辑
const [form, setForm] = useState({
  name: '',
  salary: '',
  keywords: '',  // "Python, AI, 后端"
  cities: '',
  experience: '',
  degree: '',
  scale: '',
  job_types: '',
  financing: '',
  industries: '',
})
const [saving, setSaving] = useState(false)
const [saved, setSaved] = useState(false)
const [error, setError] = useState<string | null>(null)

// 保存时将逗号分隔字符串解析回数组
const parseArr = (s: string) =>
  s.split(',').map(t => t.trim()).filter(Boolean)

const handleSave = async () => {
  setSaving(true)
  setSaved(false)
  setError(null)
  try {
    await API.saveProfile({
      name: form.name,
      salary: form.salary,
      keywords: parseArr(form.keywords),
      cities: parseArr(form.cities),
      experience: parseArr(form.experience),
      degree: parseArr(form.degree),
      scale: parseArr(form.scale),
      job_types: parseArr(form.job_types),
      financing: parseArr(form.financing),
      industries: parseArr(form.industries),
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  } catch (e) {
    setError((e as Error).message)
  } finally {
    setSaving(false)
  }
}
```

### 布局

卡片式表单，两列网格（大屏）：

```
┌─ 个人画像 ──────────────────────────────────────┐
│  姓名         [________]  期望薪资  [________]  │
│  职位关键词   [____________________________]    │
│  求职城市     [____________________________]    │
│  经验年限     [____________________________]    │
│  学历         [____________________________]    │
│  公司规模     [____________________________]    │
│  职位类型     [____________________________]    │
│  融资阶段     [____________________________]    │
│  行业         [____________________________]    │
│ ─────────────────────────────────────────────── │
│  [保存]   ✓ 已保存                              │
└─────────────────────────────────────────────────┘
```

### 样式

- 外层卡片：`rounded-2xl border border-border-subtle bg-bg-card p-6 max-w-2xl`
- 字段行：`flex flex-col gap-1`，label `text-sm text-text-2`，input `rounded-lg border border-border-default bg-bg-input px-3 py-2 text-sm text-text-1 w-full`
- 两列网格：`grid grid-cols-1 gap-4 sm:grid-cols-2`（姓名和薪资同行，其余各占全宽）
- 保存按钮：`rounded-xl bg-brand px-5 py-2.5 text-sm font-medium text-white`
- "已保存"反馈：`text-sm text-emerald-400`，3 秒后消失

---

## 三、Setup.tsx

### 功能

展示系统就绪状态检查结果，并提供简历上传入口。

### 数据

```tsx
interface OnboardingStatus {
  profile: boolean
  resume: boolean
  session: boolean
  llm_provider: boolean
  attachment_resume: { ready: boolean; path: string; note: string | null }
  all_ok: boolean
}
```

加载：`API.getOnboarding()` 返回以上结构（`/api/onboarding/status`）。

### 卡片列表

每个状态项显示为一张卡片：

| 项目 | 字段 | 说明 |
|------|------|------|
| Profile 配置 | `profile` | 是否存在 `data/profile.yaml` |
| 简历 YAML | `resume` | 是否存在 `data/resume_base.yaml` |
| 浏览器 Session | `session` | 是否存在 `data/session.json` |
| LLM 提供商 | `llm_provider` | LLM 是否可用 |
| 附件简历 PDF | `attachment_resume.ready` | 是否存在 `data/resume_attachment.pdf` |

卡片颜色：`ready=true` → 绿色勾（`text-emerald-400`），`false` → 红色叉（`text-rose-400`）

整体就绪：若 `all_ok` 为 true，显示绿色 Banner "系统已就绪，可以开始运行！"

### 简历上传

**结构化简历上传（生成 resume_base.yaml）：**

文件选择 `accept=".pdf,.docx"`，选择后立即调用 `API.uploadResume(file)`。
上传成功后重新调用 `API.getOnboarding()` 刷新状态。

**附件简历 PDF 上传：**

文件选择 `accept=".pdf"`，上传到 `/api/resume/attachment`（如果该 endpoint 存在）。
注意：`API.uploadResume` 是上传结构化简历（解析为 yaml），不是附件简历。若 `/api/resume/attachment` 不存在，此按钮展示为灰色禁用（显示说明文字即可）。

检查 `attachment_resume.note` 字段，若非 null，在该卡片下显示提示文字。

### 样式

- 页面容器：`space-y-6 max-w-2xl`
- 卡片列表：`grid grid-cols-1 gap-3 sm:grid-cols-2`
- 单卡片：`flex items-center gap-3 rounded-xl border border-border-subtle bg-bg-card p-4`
- 就绪 Banner：`rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-4 py-3 text-sm text-emerald-400`
- 上传区域：`rounded-xl border border-dashed border-border-default bg-bg-card2 p-5 text-center`

---

## 四、构建验证

```bash
cd code/dashboard/frontend
npm run build
```

确认无 TypeScript 错误。

---

## 约束

- 不修改后端任何文件
- 不安装新的 npm 包
- `districts`、`position_types` 字段只读展示，不编辑
- 所有字符串直接写 UTF-8 中文

---

## 验证点

1. `npm run build` 通过
2. Profile 页加载显示当前配置（文件不存在时显示空表单）
3. 修改字段后点击"保存"，成功后显示"已保存"3 秒
4. Setup 页显示各项就绪状态卡片
5. 点击"上传简历"选择 PDF/DOCX，上传后刷新状态
