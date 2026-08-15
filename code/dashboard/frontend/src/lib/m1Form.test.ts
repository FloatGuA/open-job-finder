import { describe, expect, it } from 'vitest'
import { checkM1Form } from './m1Form'

// m1 一旦排进队列就会开一个真 Chrome 跑好几分钟，所以能在点下去之前发现的问题就要在这里发现。
describe('checkM1Form', () => {
  it('blocks when the site is empty', () => {
    // site 决定用哪个持久化登录目录，空了会跑到一个没登录的浏览器里干等。
    expect(checkM1Form('', 'https://acme.example/campus/').blocking).toBeTruthy()
  })

  it('blocks when the entry url is empty', () => {
    expect(checkM1Form('acme', '').blocking).toBeTruthy()
  })

  it('blocks a url that is not http(s)', () => {
    // 拿到一个不是链接的东西，agent 会在空白页上反复截图直到步数耗尽。
    expect(checkM1Form('acme', 'acme.example/campus').blocking).toBeTruthy()
  })

  it('accepts a bare entry page', () => {
    const issues = checkM1Form('acme', 'https://acme.example/campus/')
    expect(issues.blocking).toBeUndefined()
    expect(issues.warning).toBeUndefined()
  })

  it('warns (but does not block) when the url carries query parameters', () => {
    // 真实教训：带 project= 的那个 URL 把日常实习整类过滤掉了（87 条 vs 去掉后 134 条）。
    // 不拦是因为某些站的入口页本身就带参数，拦了就没法用了。
    const issues = checkM1Form('acme', 'https://acme.example/campus/?project=123')
    expect(issues.blocking).toBeUndefined()
    expect(issues.warning).toBeTruthy()
  })

  it('trims whitespace before judging', () => {
    expect(checkM1Form('  ', ' https://acme.example/ ').blocking).toBeTruthy()
    expect(checkM1Form(' acme ', ' https://acme.example/ ').blocking).toBeUndefined()
  })
})
