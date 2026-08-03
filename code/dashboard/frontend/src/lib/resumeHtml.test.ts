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
})
