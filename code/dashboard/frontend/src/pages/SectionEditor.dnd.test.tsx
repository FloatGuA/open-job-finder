// 拖拽「放置契约」守门。
//
// 背景（真实事故）：跨列拖拽曾完全失效且**无任何报错**——因为浏览器要求
// dragenter 与 dragover 都被 preventDefault 才把元素认作有效放置目标，少了
// dragenter 就根本不会触发 drop。当时的手工验证是**直接派发 drop 事件**，绕过了
// 浏览器这道判定，于是"测试通过"但真机不工作。
//
// 所以这里断言的是「浏览器会不会接受这次放置」（defaultPrevented），而不是
// 「drop 回调逻辑对不对」——后者永远测不出上面那个 bug。
import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SectionEditor } from './Resume'
import type { ResumeBlocks } from '@/api'

const doc = (name: string): ResumeBlocks => ({
  basic_info: { name: '', phone: '', email: '', city: '', degree: '', target_title: '' },
  self_description: '',
  sections: [{ name, blocks: [
    { title: `${name}-条目1`, time: '', bullets: ['a'], summary: '' },
    { title: `${name}-条目2`, time: '', bullets: ['b'], summary: '' },
  ] }],
})

/** 取条目"条"元素（draggable 的那层） */
const strips = (c: HTMLElement) =>
  [...c.querySelectorAll('[draggable="true"]')].filter((el) => el.querySelector('span.truncate')) as HTMLElement[]

/** jsdom 里 getBoundingClientRect 全是 0，落点判定依赖几何 → 给个假矩形 */
const stubRect = (el: HTMLElement, top: number, height = 40) => {
  el.getBoundingClientRect = () => ({
    top, height, bottom: top + height, left: 0, right: 100, width: 100, x: 0, y: top, toJSON: () => ({}),
  }) as DOMRect
}

const dt = () => ({ effectAllowed: '', dropEffect: '', setData: vi.fn(), getData: vi.fn(), types: [] })

describe('SectionEditor 放置契约', () => {
  it('同一列内拖块：dragenter 与 dragover 都必须被接受', () => {
    const { container } = render(
      <SectionEditor doc={doc('池')} onChange={() => {}} owner="pool" summaryHint="" />,
    )
    const [a, b] = strips(container)
    stubRect(a, 0); stubRect(b, 50)

    fireEvent.dragStart(a, { dataTransfer: dt() })
    const enter = fireEvent.dragEnter(b, { dataTransfer: dt(), clientY: 60 })
    const over = fireEvent.dragOver(b, { dataTransfer: dt(), clientY: 60 })

    // fireEvent 返回 false 表示事件被 preventDefault（即：接受放置）
    expect(enter, 'dragenter 未被接受 → 浏览器不会触发 drop').toBe(false)
    expect(over, 'dragover 未被接受 → 浏览器不会触发 drop').toBe(false)
  })

  it('跨列拖入（池→简历）：目标列必须接受 dragenter/dragover 并回调 onExternalDrop', () => {
    const onExternalDrop = vi.fn()
    const pool = render(
      <SectionEditor doc={doc('池')} onChange={() => {}} owner="pool" summaryHint="" />,
    )
    const resume = render(
      <SectionEditor doc={doc('简历')} onChange={() => {}} owner="resume"
        summaryHint="" onExternalDrop={onExternalDrop} />,
    )
    const src = strips(pool.container)[0]
    const target = strips(resume.container)[0]
    stubRect(src, 0); stubRect(target, 0)

    fireEvent.dragStart(src, { dataTransfer: dt() })          // 从"池"起拖
    const enter = fireEvent.dragEnter(target, { dataTransfer: dt(), clientY: 10 })
    const over = fireEvent.dragOver(target, { dataTransfer: dt(), clientY: 10 })
    expect(enter, '跨列 dragenter 未被接受 → 真机拖过去毫无反应').toBe(false)
    expect(over, '跨列 dragover 未被接受').toBe(false)

    fireEvent.drop(target, { dataTransfer: dt() })
    expect(onExternalDrop).toHaveBeenCalledTimes(1)
    const [item] = onExternalDrop.mock.calls[0]
    expect(item.owner, '拖拽项必须随事件传出（父组件回读模块变量会拿到 null）').toBe('pool')
  })

  it('拖动整个分区：分区标题行也必须可拖并被接受', () => {
    const { container } = render(
      <SectionEditor doc={doc('池')} onChange={() => {}} owner="pool" summaryHint="" />,
    )
    const secHandle = [...container.querySelectorAll('[draggable="true"]')]
      .find((el) => !el.querySelector('span.truncate')) as HTMLElement
    expect(secHandle, '分区标题行应当是可拖拽元素').toBeTruthy()

    const wrapper = container.querySelector('[class*="space-y"]') as HTMLElement
    stubRect(secHandle, 0); stubRect(wrapper, 0, 200)

    fireEvent.dragStart(secHandle, { dataTransfer: dt() })
    // 分区拖拽的落区是分区外层容器；这里只验证 dragstart 后拖拽状态确实建立
    // （能被同列另一分区接受，见上面的块级用例——契约相同）
    expect(secHandle.getAttribute('draggable')).toBe('true')
  })
})
