import { type BrowserWindow } from 'electron'
import { LCSC_CURSOR_SVG } from './lcsc-cursor'

/** Visual cue only: it follows actual automation targets, never moves the OS cursor. */
export async function pointAt(win: BrowserWindow, target: string) {
  await win.webContents.executeJavaScript(`(async () => {
    const target = (${target}); if (!target) return;
    target.scrollIntoView({block:'center',behavior:'instant'});
    let cursor = document.getElementById('fde-automation-pointer');
    if (!cursor) {
      cursor = document.createElement('div'); cursor.id='fde-automation-pointer';
      cursor.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;left:24px;top:24px;transition:left .28s ease,top .28s ease;display:flex;gap:2px;align-items:flex-end;color:#fff;font:500 10px "PingFang SC",sans-serif;filter:drop-shadow(0 2px 3px #0002)';
      cursor.innerHTML=${JSON.stringify(LCSC_CURSOR_SVG + '<span style="background:#171b22;color:#fff;border:1px solid #ffffffcc;border-radius:8px;padding:4px 7px;line-height:1.2;letter-spacing:.3px;white-space:nowrap">AI 操作</span>')};
      document.documentElement.append(cursor);
      cursor.getBoundingClientRect();
    }
    const r=target.getBoundingClientRect(); cursor.style.left=(r.left+Math.min(r.width/2,80))+'px'; cursor.style.top=(r.top+Math.min(r.height/2,30))+'px';
    await new Promise(resolve=>setTimeout(resolve,310));
  })()`)
}

export type BrowserAction = { kind: 'click' | 'navigate' | 'scroll' | 'dismiss' | 'hover' | 'wait'; title: string; visible_text: string; target?: string; url?: string }
export type BrowserObservation = { url: string; page: string; actions: BrowserAction[] }

export const OBSERVE_BROWSER = `(() => {
  const root=document.querySelector('[role="dialog"][data-state="open"]') || document.querySelector('main') || document.body;
  const overlays=[...document.querySelectorAll('[role="tooltip"],.el-tooltip__popper,.ant-tooltip,.ant-popover,[data-popper-placement]')].filter(e=>e.getBoundingClientRect().width>0 && !root.contains(e)).map(e=>e.innerText).join(String.fromCharCode(10));
  const page=(overlays+String.fromCharCode(10)+root.innerText).slice(0,18000);
  const actions=[];
  if(root.matches('[role="dialog"]'))actions.push({kind:'dismiss',title:'关闭资料弹窗，返回商品页面',visible_text:'Dismiss the current information dialog to inspect the underlying product page'});
  const denied=/登录|注册|购物车|购买|下单|收藏|关注|提交|支付|删除|询价|客服|上传|评价|举报|领取|兑换|报名|预约|订阅|下载|同意|授权|logout|login|checkout|payment|delete|subscribe|cart/i;
  const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(e).visibility!=='hidden'};
  const label=e=>(e.innerText||e.getAttribute('aria-label')||e.getAttribute('title')||'').trim();
  [...root.querySelectorAll('a[href],button,[role="tab"],[role="button"],summary,[aria-expanded]')].filter(visible).forEach((e,i)=>{
    if(actions.length>=24)return;
    const text=label(e); if(!text || denied.test(text) || text.length>100 || e.disabled || e.closest('form'))return;
    let url;try {url=new URL(e.href)}catch{}
    const navigate=url && url.protocol==='https:' && !url.username && !url.password && ['www.szlcsc.com','so.szlcsc.com','item.szlcsc.com'].includes(url.hostname) && !denied.test(url.href);
    if(e.tagName==='A' && !navigate && !e.getAttribute('href')?.startsWith('#'))return;
    const target='fde-action-'+i; e.setAttribute('data-fde-action',target);
    actions.push({kind:navigate?'navigate':'click',title:(navigate?'打开页面：':'点击控件：')+text,visible_text:(navigate?'Navigate to page: ':'Candidate click (must verify read-only safety): ')+text+'; context: '+(e.parentElement?.innerText||'').slice(0,100),target,...(navigate?{url:url.href}:{})});
  });
  [...root.querySelectorAll('span,[role="button"],a,div,[title],[aria-haspopup]')].filter(visible).forEach((e,i)=>{
    const text=label(e);if(actions.length>=36||!text||text.length>80||[...e.children].some(c=>label(c)===text))return;
    if(!e.hasAttribute('title')&&!e.hasAttribute('aria-haspopup')&&!/pointer|help/.test(getComputedStyle(e).cursor))return;
    const target='fde-hover-'+i;e.setAttribute('data-fde-action',target);
    actions.push({kind:'hover',title:'查看悬浮说明：'+text,visible_text:'Hover to inspect additional information: '+text,target});
  });
  actions.push({kind:'wait',title:'等待页面异步信息加载',visible_text:'Wait for asynchronously loaded content before judging absence'});
  if(window.scrollY>20)actions.push({kind:'scroll',title:'向上查看页面（当前位置 '+Math.round(window.scrollY)+'）',visible_text:'Scroll up to inspect earlier page controls',target:'up'});
  if(window.scrollY+innerHeight<document.documentElement.scrollHeight-20)actions.push({kind:'scroll',title:'向下查看页面（当前位置 '+Math.round(window.scrollY)+'）',visible_text:'Scroll down to reveal more page content'});
  return {url:location.href,page,actions};
})()`
