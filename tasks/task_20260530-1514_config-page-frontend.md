# Task: Frontend Config Page — 求职偏好配置页

## Goal
在 Dashboard 新增"配置"页面，允许用户通过 UI 编辑 `profile.yaml`（求职偏好），调用 T044 提供的 `/api/config/profile` API。

## Background
目前用户必须手动编辑 `data/profile.yaml` 才能修改求职关键词、城市、薪资期望等参数，没有 UI 入口。本 task 补全这个缺口。

## Depends On
- task_20260530-1513_config-manager — 依赖 `GET /api/config/profile` 和 `PUT /api/config/profile` 端点

## Change Scope
- **In scope**:
  - `dashboard/frontend/src/pages/Config.tsx`（新建）
  - `dashboard/frontend/src/api/index.ts`（新增 getProfile / updateProfile）
  - `dashboard/frontend/src/context/app-context.ts`（Page 类型扩展）
  - `dashboard/frontend/src/App.tsx`（注册 Config 页面）
  - `dashboard/frontend/src/components/layout/Sidebar.tsx`（新增导航项）
- **Out of scope**: LLM provider 配置 UI（复杂度高，单独做）、系统配置（schedule、thresholds）

## Implementation Requirements

**重要编码规则**：所有 JSX 文件中的中文字符必须用 `\uXXXX` Unicode escape，包括 JSX 文本节点（`{'\uXXXX'}`）和 JS 表达式属性（`label={'\uXXXX'}`）。JSX 属性双引号字符串（`label="..."`）不能包含中文，必须改成 JS 表达式形式。

### 1. `src/api/index.ts` — 新增两个方法

```typescript
getProfile: (): Promise<ProfileConfig> =>
  requestJson('/api/config/profile'),

updateProfile: (data: Partial<ProfileConfig>): Promise<{ ok: boolean }> =>
  requestJson('/api/config/profile', { method: 'PUT', body: JSON.stringify(data) }),
```

其中 `ProfileConfig` 类型：
```typescript
interface ProfileConfig {
  keywords?: string[]
  cities?: string[]
  salary?: string
  experience?: string[]
  extra_notes?: string
}
```

### 2. `src/pages/Config.tsx`（新建）

页面功能：
- 挂载时调用 `API.getProfile()` 加载当前配置
- 可编辑字段：
  - **关键词**（keywords）：tag 输入框，回车/逗号新增，点 × 删除
  - **目标城市**（cities）：同上
  - **薪资期望**（salary）：单行文本输入
  - **工作经验描述**（experience）：同 tag 输入
  - **其他备注**（extra_notes）：多行文本区域
- 底部"保存"按钮，调用 `API.updateProfile()` 提交
- 保存中禁用按钮，显示 loading 状态
- 保存成功提示（inline，3 秒后消失）；保存失败显示错误信息

Tag 输入组件行为：
- 输入框回车或输入逗号 → 将当前值 trim 后加入列表，清空输入框
- 空值不添加；重复值不添加
- 列表中每个 tag 旁有 × 按钮可删除

样式：沿用项目现有设计令牌（`bg-bg-card`、`text-text-1/2/3`、`text-brand`、圆角 `rounded-xl`），不引入新的颜色变量。

#### Examples

| 操作 | 预期结果 |
|------|---------|
| 页面加载，profile.yaml 有 `keywords: ["Python"]` | 显示一个 tag "Python" |
| 在关键词输入框输入 "Go" 后按回车 | 列表变为 ["Python", "Go"] |
| 点击 "Python" 旁的 × | 列表变为 ["Go"] |
| 点击保存 | 调用 PUT /api/config/profile，按钮变 disabled，成功后显示"已保存" |

### 3. `src/context/app-context.ts`

`Page` 类型新增 `'config'`。

### 4. `src/App.tsx`

在 `PAGES` 对象中注册：
```typescript
config: <Config />,
```

### 5. `src/components/layout/Sidebar.tsx`

在导航列表中新增配置项，位于 Logs 之后：
- 图标：`Settings`（来自 lucide-react）
- 标签：`'配置'`（配置）
- page key：`'config'`

## Test Requirements
- Automated: no（前端 UI 组件）
- 手动验证：
  1. `npm run build` 零 TypeScript 错误
  2. 访问 Dashboard，Sidebar 出现"配置"入口
  3. 进入配置页，显示当前 profile 内容
  4. 编辑并保存，刷新后数据持久化

## Acceptance Criteria
- [ ] `npm run build` 零错误，零 TypeScript 类型错误
- [ ] Sidebar 有"配置"导航项
- [ ] 配置页加载时显示当前 profile 数据
- [ ] Tag 输入支持回车添加和 × 删除
- [ ] 保存调用 `PUT /api/config/profile`，成功后有 inline 提示
- [ ] 所有中文字符均为 `\uXXXX` escape（无裸中文）

## Ambiguity Protocol
如有歧义，实现最合理的解释并在 report.md 的 Deviations 节说明。
