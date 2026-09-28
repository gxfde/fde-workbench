// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest'
import {OBSERVE_BROWSER} from '../../src/main/lcsc-browser-ui'

afterEach(()=>{vi.restoreAllMocks();document.body.innerHTML=''})
it('discovers unfamiliar read-only controls without business-specific query keywords',()=>{
  document.body.innerHTML='<main><button>环保合规声明</button><span style="cursor:help">湿敏等级解释</span><button>加入购物车</button><button>领取礼品</button></main>'
  for (const element of document.querySelectorAll('*')) Object.defineProperty(element,'innerText',{get(){return element.textContent || ''},configurable:true})
  vi.spyOn(Element.prototype,'getBoundingClientRect').mockReturnValue({x:0,y:0,top:0,bottom:20,left:0,right:100,width:100,height:20,toJSON(){}})
  const observation=window.eval(OBSERVE_BROWSER)
  expect(observation.actions.some((a:any)=>a.title==='点击控件：环保合规声明')).toBe(true)
  expect(observation.actions.some((a:any)=>a.title==='查看悬浮说明：湿敏等级解释')).toBe(true)
  expect(observation.actions.some((a:any)=>a.kind==='click' && /购物车|领取/.test(a.title))).toBe(false)
})
