// \u7b80\u5386\u5e93\u91cc\u7684 PDF \u4e5f\u8981\u80fd\u9884\u89c8\u2014\u2014\u53f3\u4fa7\u90a3\u5757\u9884\u89c8\u533a\u539f\u6765\u53ea\u670d\u52a1\u53ef\u7f16\u8f91\u7b80\u5386\u3002
//
// \u5e93\u91cc\u7684\u662f PDF \u6587\u4ef6\uff0c\u6ca1\u6709"\u5757"\u53ef\u4ee5\u6e32\u67d3\u6210 HTML\uff0c\u6240\u4ee5\u8d70\u6d4f\u89c8\u5668\u81ea\u5e26\u7684 PDF \u663e\u793a\uff1a
// \u4e00\u4e2a iframe \u6307\u5411\u4e0b\u8f7d\u7aef\u70b9\u3002**URL \u62fc\u9519\u662f\u4f1a\u9759\u9ed8\u574f\u6389\u7684\u90a3\u79cd\u95ee\u9898**\uff08iframe \u52a0\u8f7d\u5931\u8d25
// \u4e0d\u629b\u5f02\u5e38\uff0c\u53ea\u662f\u4e00\u7247\u7a7a\u767d\uff09\uff0c\u6240\u4ee5\u8fd9\u6761\u6d4b\u8bd5\u76ef\u7684\u5c31\u662f\u5b83\u3002
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { PdfPreview } from './PdfPreview'

describe('PdfPreview', () => {
  afterEach(cleanup)

  it('points at the library download endpoint for that file', () => {
    const { container } = render(<PdfPreview file={'Agent\u5f00\u53d1_2026-08-17.pdf'} />)
    const iframe = container.querySelector('iframe')!
    expect(iframe.getAttribute('src')).toContain('/api/resume/library/')
    expect(iframe.getAttribute('src')).toContain(encodeURIComponent('Agent\u5f00\u53d1_2026-08-17.pdf'))
  })

  it('encodes a filename that would otherwise break the url', () => {
    // \u6587\u4ef6\u540d\u91cc\u6709\u4e2d\u6587\u3001\u7a7a\u683c\u3001# \u90fd\u5f88\u5e38\u89c1\u2014\u2014\u4e0d\u7f16\u7801\u7684\u8bdd # \u4e4b\u540e\u7684\u90e8\u5206\u4f1a\u88ab\u5f53\u6210 fragment\uff0c
    // \u8bf7\u6c42\u6253\u5230\u4e00\u4e2a\u4e0d\u5b58\u5728\u7684\u6587\u4ef6\u4e0a\uff0c\u800c\u9875\u9762\u53ea\u662f\u7a7a\u767d\u3002
    const tricky = 'Agent \u7b80\u5386 2026#v2.pdf'
    const { container } = render(<PdfPreview file={tricky} />)
    const src = container.querySelector('iframe')!.getAttribute('src')!
    expect(src).toContain(encodeURIComponent(tricky))
    expect(src.split('#')[0]).toContain(encodeURIComponent('#'))
  })
})
