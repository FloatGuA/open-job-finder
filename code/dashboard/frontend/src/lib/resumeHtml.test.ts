// 简历 HTML 渲染规则守门（预览与导出 PDF 同源，这里错了两边一起错）
import { describe, expect, it } from 'vitest'
import { buildResumeHtml } from './resumeHtml'
import type { ResumeBlocks } from '@/api'

const blk = (title: string, bullets: string[] = [], time = '') =>
  ({ title, time, bullets, summary: '' })

const doc = (sections: ResumeBlocks['sections']): ResumeBlocks => ({
  basic_info: { name: '张三', phone: '', email: 'a@b.c', city: '', degree: '', target_title: '' },
  self_description: '',
  sections,
})

describe('buildResumeHtml', () => {
  it('只有分区名、没有任何条目时也要渲染标题（否则新建分区预览毫无反馈）', () => {
    const html = buildResumeHtml(doc([{ name: '志愿服务', blocks: [] }]))
    expect(html).toContain('志愿服务')
  })

  it('分区名与内容都为空才整块跳过', () => {
    const html = buildResumeHtml(doc([{ name: '   ', blocks: [] }]))
    expect(html).not.toContain('<div class="s-title">')   // 注意 CSS 里也有 .s-title，须匹配标签
  })

  it('空白条目不渲染，但同分区里的有效条目照常渲染', () => {
    const html = buildResumeHtml(doc([
      { name: '项目经历', blocks: [blk(''), blk('真项目', ['做了事'])] },
    ]))
    expect(html).toContain('真项目')
    expect(html).toContain('做了事')
    expect(html.match(/class="entry"/g) ?? []).toHaveLength(1)   // 空条目没进去
  })

  it('分区顺序严格跟随 sections 数组（拖拽排序的结果要如实反映）', () => {
    const html = buildResumeHtml(doc([
      { name: '游戏经历', blocks: [blk('手游')] },
      { name: '教育经历', blocks: [blk('某大学')] },
    ]))
    expect(html.indexOf('游戏经历')).toBeLessThan(html.indexOf('教育经历'))
  })

  it('bullets 里的空行被过滤', () => {
    const html = buildResumeHtml(doc([
      { name: '项目', blocks: [blk('P', ['有效', '   ', ''])] },
    ]))
    expect(html.match(/<li>/g) ?? []).toHaveLength(1)
  })

  it('HTML 特殊字符转义，防止内容破坏文档结构', () => {
    const html = buildResumeHtml(doc([
      { name: '<script>', blocks: [blk('A & B', ['<b>x</b>'])] },
    ]))
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('A &amp; B')
    expect(html).not.toContain('<b>x</b>')
  })

  it('没有时间的条目不渲染日期元素', () => {
    const withTime = buildResumeHtml(doc([{ name: 'S', blocks: [blk('T', ['b'], '2020')] }]))
    const noTime = buildResumeHtml(doc([{ name: 'S', blocks: [blk('T', ['b'])] }]))
    expect(withTime).toContain('<span class="e-date">')
    expect(noTime).not.toContain('<span class="e-date">')
  })

  it('\u6807\u9898\u7528\u9ed1\u4f53\u3001\u6b63\u6587\u7528\u5fae\u8f6f\u96c5\u9ed1', () => {
    const html = buildResumeHtml(doc([{ name: 'S', blocks: [blk('T', ['b'])] }]))
    expect(html).toContain('font-family: "Microsoft YaHei"')          // body \u6b63\u6587
    expect(html).toMatch(/\.s-title, \.e-title \{ font-family: SimHei/)   // \u5206\u533a/\u6761\u76ee\u6807\u9898\u9ed1\u4f53
    expect(html).toMatch(/\.name \{[^}]*font-family: "STZhongsong"/)      // \u59d3\u540d\u5355\u72ec\u7528\u8845\u7ebf
  })

  it('\u5b57\u6bb5\u7ea7\u7c97/\u659c/\u4e0b\u5212\u7ebf\u53ea\u4f5c\u7528\u4e8e\u6307\u5b9a\u5b57\u6bb5', () => {
    const html = buildResumeHtml(doc([{ name: 'S', blocks: [{
      ...blk('T', ['b1'], '2026'),
      style: { title: { bold: true, underline: true }, bullets: { italic: true } },
    }] }]))
    expect(html).toContain('class="e-title" style="font-weight:700;text-decoration:underline"')
    expect(html).toContain('<li style="font-style:italic">b1</li>')
    expect(html).toContain('<span class="e-date">2026</span>')         // \u65f6\u95f4\u672a\u8bbe \u2192 \u4e0d\u5199 style
  })

  it('\u6ca1\u6709 style \u65f6\u4e0d\u8f93\u51fa inline \u6837\u5f0f\uff08\u8d70\u6a21\u677f\u9884\u8bbe\uff0c\u8001\u6570\u636e/AI \u751f\u6210\u884c\u4e3a\u4e0d\u53d8\uff09', () => {
    const html = buildResumeHtml(doc([{ name: 'S', blocks: [blk('T', ['b'], '2026')] }]))
    expect(html).toContain('<span class="e-title">T</span>')
    expect(html).toContain('<li>b</li>')
  })
})
