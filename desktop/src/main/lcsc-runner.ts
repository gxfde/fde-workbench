import { app, BrowserWindow, type Session } from 'electron'
import {showLcscFinishDialog} from './lcsc-finish-dialog'
import { pointAt, OBSERVE_BROWSER, type BrowserObservation } from './lcsc-browser-ui'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import type { ApiRequestHandler } from './api-ipc'

const HOME = 'https://www.szlcsc.com/'
export function isLcscPage(value: string): boolean {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password && ['www.szlcsc.com', 'so.szlcsc.com', 'item.szlcsc.com'].includes(u.hostname) } catch { return false }
}
export function isLcscPdf(value: string): boolean {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password && u.hostname === 'atta.szlcsc.com' && /\.pdf$/i.test(u.pathname) } catch { return false }
}
type Step = { at_ms: number; duration_ms: number; action: string; detail: string; status: string }
type Candidate = { title: string; url: string; visible_text: string }
type Run = { id: string; status: string; result: { selected_product?: Candidate | null; next_action?: { index?: number | null; retry?: boolean; rejected_indices?: number[] }; other_assessment?: { complete: boolean; stop: boolean; reason: string } }; steps: Array<{ detail: string }> }
let running = false

export async function executeDesktopLcsc(input: { accessToken: string; body: unknown }, requestApi: ApiRequestHandler, browserSession: Session) {
  if (running) throw new Error('已有立创查询正在执行，请等待完成。')
  const body = input.body as { query?: unknown; fields?: unknown; track?: unknown; skill_key?: unknown; purpose?: string }
  if (!body || typeof body.query !== 'string' || body.query.length > 120 || !Array.isArray(body.fields) || !body.fields.length || body.fields.some(f => !['parameters', 'pins', 'price', 'datasheet', 'other'].includes(f)) || typeof body.track !== 'boolean') throw new Error('查询参数无效。')
  running = true
  let win: BrowserWindow | undefined
  let run: Run | undefined
  const steps: Step[] = []
  const started = performance.now()
  const elapsed = () => Math.round(performance.now() - started)
  const fields = body.fields as string[]
  const result: Record<string, unknown> = { missing: [] as string[] }
  const missing = result.missing as string[]
  const pointer = async (target: string) => { if (body.track && win && !win.isDestroyed()) await pointAt(win, target) }
  function notifyFinished(completed: Run) {
    if (!body.track || !win || win.isDestroyed()) return
    showLcscFinishDialog(win, completed.status)
  }
  async function api(path: string, value: unknown): Promise<Run> {
    const response = await requestApi({ path: `/api/v1/ai/lcsc-runs/desktop${path}`, method: 'POST', body: value, accessToken: input.accessToken })
    if (response.error || response.status >= 400) throw new Error(response.error?.message || '执行记录保存失败。')
    return response.data as Run
  }
  async function step<T>(action: string, detail: string, task: () => Promise<T>): Promise<T> {
    const at = elapsed()
    try { const value = await task(); steps.push({ at_ms: at, duration_ms: elapsed() - at, action, detail, status: 'succeeded' }); return value }
    catch (e) { steps.push({ at_ms: at, duration_ms: elapsed() - at, action, detail: `${detail}：未完成`, status: 'failed' }); throw e }
  }
  async function evaluate<T>(source: string): Promise<T> {
    if (!win || win.isDestroyed()) throw new Error('执行浏览器已关闭，本次查询已停止。')
    if (!isLcscPage(win.webContents.getURL())) throw new Error('浏览器离开了立创商城，查询已停止。')
    return win.webContents.executeJavaScript(source, true) as Promise<T>
  }
  async function waitFor(source: string, description: string, timeout = 25_000) {
    const end = performance.now() + timeout
    while (performance.now() < end) {
      try { const value = await evaluate(source); if (value) return value } catch (e) { if (win?.isDestroyed()) throw e }
      await new Promise(resolve => setTimeout(resolve, 150))
    }
    throw new Error(`${description}超时；页面可能需要验证或结构已变化。`)
  }
  async function go(url: string) {
    if (!isLcscPage(url)) throw new Error('商品地址不属于立创商城。')
    await Promise.race([win!.loadURL(url), new Promise<never>((_, reject) => setTimeout(() => reject(new Error('商城页面加载超时。')), 30_000))])
  }
  try {
    run = await api('/start', body)
    win = new BrowserWindow({ width: 1180, height: 820, show: body.track, title: '立创查询执行跟踪 · FDE 工作台',
      webPreferences: { session: browserSession, contextIsolation: true, sandbox: true, nodeIntegration: false, webviewTag: false, backgroundThrottling: false } })
    await step('navigate', '打开立创商城首页', () => go(HOME))
    await step('fill', `输入搜索内容：${body.query}`, async () => {
      await waitFor(`Boolean(document.querySelector('input[placeholder]'))`, '等待搜索栏')
      await pointer(`[...document.querySelectorAll('input[placeholder]')].find(e=>e.getBoundingClientRect().width>0)`)
      await evaluate(`(() => { const input = [...document.querySelectorAll('input[placeholder]')].find(e => e.getBoundingClientRect().width > 0); if (!input) throw Error('搜索栏不可见'); input.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(body.query)}); input.dispatchEvent(new Event('input', {bubbles:true})); input.dispatchEvent(new Event('change', {bubbles:true})); })()`)
    })
    await step('search', '点击搜索并读取商城候选商品', async () => {
      await pointer(`[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='搜索'&&e.getBoundingClientRect().width>0)`)
      await evaluate(`(() => { const button = [...document.querySelectorAll('button')].find(e => e.textContent.trim() === '搜索' && e.getBoundingClientRect().width > 0); if (!button) throw Error('搜索按钮不可见'); button.click(); })()`)
      await waitFor(`location.hostname === 'so.szlcsc.com' && document.querySelector('.product-group-leader')`, '等待搜索结果')
    })
    const candidates = await step('candidates', '提取前 8 个可见候选商品及同一份判断依据', () => evaluate<Candidate[]>(`(() => {
      const normalize = s => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
      return [...document.querySelectorAll('.product-group-leader')].slice(0,8).map(node => {
        const links = [...node.querySelectorAll('a[href]')].filter(a => a.href.startsWith('https://item.szlcsc.com/') && a.textContent.trim());
        const link = links.find(a => normalize(a.textContent.trim()) === normalize(${JSON.stringify(body.query)})) || links.find(a => a.textContent.trim().length > 4 && !['爆款','立推'].includes(a.textContent.trim())) || links[0];
        return {title:link?.textContent.trim().slice(0,160)||'',url:link ? new URL(link.href).origin + new URL(link.href).pathname : '',visible_text:node.innerText.slice(0,2400)};
      }).filter(c => c.title && c.url);
    })()`))
    if (!candidates.length) throw new Error('没有找到可用候选商品，请调整关键词。')
    run = await api(`/${run.id}/select`, { candidates, steps, at_ms: elapsed() })
    if (run.status === 'failed') throw new Error(run.steps.at(-1)?.detail || '模型判断失败。')
    const selected = run.result.selected_product
    if (!selected) throw new Error('模型未找到符合要求的商品，请调整搜索条件。')
    await step('product', `打开选中的商品：${selected.title}`, () => go(selected.url))
    if (fields.includes('parameters')) {
      const parameters = await step('parameters', '读取商品参数表', async () => {
        await waitFor(`Boolean([...document.querySelectorAll('table')].find(t => t.innerText.includes('参数值')))`, '等待商品参数')
        return evaluate<Array<{ name: string; value: string }>>(`(() => [...document.querySelectorAll('table')].filter(t => t.innerText.includes('参数值')).flatMap(t => [...t.querySelectorAll('tbody tr')].map(row => {const cells=[...row.querySelectorAll('td')].map(c=>c.innerText.trim()); return {name:cells.at(-2),value:cells.at(-1)};})).filter(v=>v.name&&v.value).slice(0,100))()`)
      })
      result.parameters = parameters
      if (!parameters.length) missing.push('商品参数未公开显示')
    }
    if (fields.includes('price')) {
      result.prices = await step('price', '按选中商品的商城结果读取数量阶梯与人民币售价', async () => {
        const lines = selected.visible_text.split('\n').map(s => s.trim()).filter(Boolean)
        const prices: Array<{ quantity: string; price: string; source: string }> = []
        let offer = '商城现货报价（查询时）'
        for (let i = 0; i < lines.length - 1; i++) {
          if (lines[i] === '立推售价') offer = '立推报价（交期以商品页为准）'
          if (/^[\d,]+\+$/.test(lines[i]) && /^[￥¥]\s*[\d.]+$/.test(lines[i + 1])) prices.push({ quantity: lines[i], price: lines[i + 1], source: offer })
        }
        if (!prices.length) missing.push('售价未公开显示，可能需要登录或询价')
        return prices
      })
    }
    if (fields.includes('pins') || fields.includes('datasheet')) {
      try {
        await step('datasheet_dialog', '点击数据手册并展开弹窗', async () => {
          await waitFor(`Boolean([...document.querySelectorAll('button,a')].find(e=>e.textContent.trim()==='数据手册'))`, '等待数据手册按钮')
          await pointer(`[...document.querySelectorAll('button,a')].find(e=>e.textContent.trim()==='数据手册')`)
          await evaluate(`(() => { const e=[...document.querySelectorAll('button,a')].find(e=>e.textContent.trim()==='数据手册'); e.scrollIntoView({block:'center'}); e.click(); })()`)
          await waitFor(`Boolean(document.querySelector('[role="dialog"][data-state="open"]'))`, '等待数据手册弹窗')
        })
        if (fields.includes('pins')) {
          try {
            const pins = await step('pins', '从数据手册弹窗的引脚图读取引脚编号与名称', async () => {
              await waitFor(`Boolean(document.querySelector('[role="dialog"] [c_partid="part_pin"]'))`, '等待引脚图', 15_000)
              return evaluate<Array<{ number: string; name: string }>>(`(() => [...document.querySelectorAll('[role="dialog"] [c_partid="part_pin"]')].map(p=>({number:p.getAttribute('c_spicepin'),name:p.querySelector('text')?.textContent||''})).filter(p=>p.number))()`)
            })
            result.pins = { count: new Set(pins.map(p => p.number)).size, items: pins, source: '数据手册弹窗 · 引脚图' }
            try {
              const screenshot = await step('pin_screenshot', '截取数据手册弹窗中的引脚图', async () => {
                const rect = await evaluate<{x:number;y:number;width:number;height:number}>(`(() => {document.getElementById('fde-automation-pointer')?.remove();const e=document.querySelector('[role="dialog"] [c_partid="part_pin"]').closest('svg');e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:Math.max(0,Math.floor(r.x)),y:Math.max(0,Math.floor(r.y)),width:Math.max(1,Math.floor(Math.min(r.right,innerWidth)-Math.max(0,r.x))),height:Math.max(1,Math.floor(Math.min(r.bottom,innerHeight)-Math.max(0,r.y)))}})()`)
                await new Promise(resolve=>setTimeout(resolve,100))
                const capture=await win!.webContents.capturePage(rect, { stayHidden: !body.track })
                const png=capture.resize({width:Math.min(700,capture.getSize().width)}).toPNG()
                if(png.length>250_000 || png.length<100) throw new Error('截图无效或过大')
                return 'data:image/png;base64,'+png.toString('base64')
              })
              ;(result.pins as Record<string,unknown>).screenshot=screenshot
            } catch { missing.push('引脚数已读取，但引脚图截图未能保存') }
          } catch { missing.push('数据手册弹窗未提供可读取的引脚图') }
        }
        if (fields.includes('datasheet')) {
          try {
            result.datasheet = await step('download', '从数据手册弹窗定位规格书并下载 PDF', async () => {
              await waitFor(`Boolean([...document.querySelectorAll('iframe')].find(f=>f.src.includes('atta.szlcsc.com')&&f.src.toLowerCase().includes('.pdf')))`, '等待规格书 PDF')
              const sheet = await evaluate<{ url: string; name: string }>(`(() => ({url:[...document.querySelectorAll('iframe')].find(f=>f.src.includes('atta.szlcsc.com')&&f.src.toLowerCase().includes('.pdf')).src,name:document.querySelector('[role="dialog"] a[title]')?.textContent.trim()||'规格书.pdf'}))()`)
              const url = new URL(sheet.url); url.hash = ''
              const saved = await savePdf(browserSession, url.href, selected.title)
              return { name: sheet.name, url: url.href, filename: saved, status: 'downloaded' }
            })
          } catch { missing.push('规格书下载未完成，未保存为成功文件') }
        }
      } catch { missing.push('数据手册弹窗未能打开') }
    }
    if (fields.includes('other')) {
      await step('wait', '等待页面异步内容加载', async()=>{await new Promise(resolve=>setTimeout(resolve,1800))})
      const history: string[] = [], visited = new Set<string>()
      for (let sequence=1;sequence<=12;sequence++) {
        const observed = await step('observe', `观察当前页面，准备 AI 实时操作第 ${sequence} 步`, () => evaluate<BrowserObservation>(OBSERVE_BROWSER))
        const actions=observed.actions.filter(a=>!visited.has(observed.url+'|'+a.title))
        run=await api(`/${run.id}/next`, { sequence, at_ms:elapsed(), steps, options:actions.map(a=>({kind:a.kind,title:a.title,visible_text:a.visible_text})),context:{url:observed.url,page:observed.page,history} })
        if(run.status==='failed') throw new Error(run.steps.at(-1)?.detail || '实时模型判断失败')
        for (const rejected of run.result.next_action?.rejected_indices || []) {
          if(actions[rejected]) visited.add(observed.url+'|'+actions[rejected].title)
        }
        const assessment=run.result.other_assessment
        if(assessment?.stop) {
          await step('goal_result', assessment.complete ? 'AI 已逐项核验，全部查询目的已达到' : 'AI 核验未全部通过：'+assessment.reason, async()=>{})
          if(!assessment.complete) missing.push('其他目的：'+assessment.reason)
          break
        }
        const index=run.result.next_action?.index
        if(run.result.next_action?.retry && index==null) continue
        if(index==null || !actions[index]) { missing.push('其他目的：AI 未找到满足目的的证据或可安全继续的操作'); break }
        const action=actions[index]
        visited.add(observed.url+'|'+action.title);history.push(action.title)
        await step('agent_action', action.title, async()=>{
          if(win!.webContents.getURL()!==observed.url) throw new Error('页面已变化，停止应用过期操作')
          if(action.kind==='scroll') await evaluate(`window.scrollBy(0,innerHeight*${action.target==='up'?-0.75:0.75})`)
          else if(action.kind==='wait') await new Promise(resolve=>setTimeout(resolve,1800))
          else if(action.kind==='dismiss') { win!.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});win!.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'}) }
          else {
            const target=`document.querySelector('[data-fde-action="${action.target}"]')`
            await pointer(target)
            if(action.kind==='navigate') await go(action.url!)
            else if(action.kind==='hover') {
              const point=await evaluate<{x:number;y:number}>(`(() => {const e=${target};if(!e)throw Error('控件已变化');e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`)
              win!.webContents.sendInputEvent({type:'mouseMove',x:point.x,y:point.y})
            }
            else await evaluate(`(() => {const e=${target};if(!e)throw Error('页面控件已变化');e.click()})()`)
          }
          await new Promise(resolve=>setTimeout(resolve,450))
        })
        if(sequence===12) missing.push('其他目的：已达到 12 步安全上限，尚未确认结果')
      }
    }
    const completed=await api(`/${run.id}/complete`, { result, steps, duration_ms: elapsed(), browser_url: win.webContents.getURL() })
    notifyFinished(completed)
    return { status: 200, data: completed, error: null }
  } catch (error) {
    const message = error instanceof Error ? error.message : '查询未完成。'
    if (!run) return { status: 400, data: null, error: { code: 'lcsc_start_failed', message } }
    steps.push({ action: 'error', detail: message, at_ms: elapsed(), duration_ms: 0, status: 'failed' })
    const completed=await api(`/${run.id}/complete`, { result, steps, duration_ms: elapsed(), failed: true, error: message,
      browser_url: win && !win.isDestroyed() && isLcscPage(win.webContents.getURL()) ? win.webContents.getURL() : '' })
    notifyFinished(completed)
    return { status: 200, data: completed, error: null }
  } finally {
    if (win && !win.isDestroyed() && !body.track) win.close()
    running = false
  }
}

async function savePdf(browserSession: Session, url: string, title: string): Promise<string> {
  if (!isLcscPdf(url)) throw new Error('规格书来源无效。')
  const response = await browserSession.fetch(url, { redirect: 'error', signal: AbortSignal.timeout(60_000) })
  if (!response.ok || !response.body) throw new Error('规格书无法下载。')
  const reader = response.body.getReader(), chunks: Uint8Array[] = []
  let bytes = 0
  try { while (true) { const { done, value } = await reader.read(); if (done) break; bytes += value.byteLength; if (bytes > 40 * 1024 * 1024) throw new Error('规格书超过 40 MB。'); chunks.push(value) } }
  finally { await reader.cancel().catch(() => {}) }
  const data = Buffer.concat(chunks)
  if (!data.subarray(0, 1024).includes(Buffer.from('%PDF-'))) throw new Error('返回内容不是 PDF。')
  const filename = `${title.replace(/[^\p{L}\p{N}._-]/gu, '_').slice(0,70)}-${randomUUID().slice(0,8)}.pdf`
  const directory = join(app.getPath('downloads'), 'FDE规格书')
  await mkdir(directory, { recursive: true })
  await writeFile(join(directory, filename), data, { flag: 'wx' })
  return filename
}
