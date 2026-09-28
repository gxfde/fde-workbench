import {BrowserWindow} from 'electron'
import {LCSC_WARNING_SVG} from './lcsc-warning-icon'

export function finishDialogHtml(status: string) {
  const success=status==='succeeded'
  const title=success?'已执行完成':status==='partial'?'已执行结束，部分项目未完成':'执行未完成'
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>
  *{box-sizing:border-box}body{margin:0;padding:28px;background:#fafbfe;color:#202b3d;font:14px/1.6 'PingFang SC',sans-serif;text-align:center}
  .icon{display:flex;align-items:center;justify-content:center;width:64px;height:64px;border-radius:50%;margin:0 auto 18px;background:${success?'#e5f8ed':'transparent'};color:#249363}
  h1{font-size:17px;font-weight:600;margin:0 0 10px}p{margin:0;color:#67758d}.actions{display:flex;gap:12px;margin-top:24px}a{flex:1;padding:9px 10px;border:1px solid #dce3ee;border-radius:10px;text-decoration:none;color:#27364b;background:white}a:focus-visible{outline:2px solid #3489f6;outline-offset:2px}.primary{background:#edf4ff;color:#286dd2}
  </style><div class="icon">${success?'<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-label="完成"><path d="m5 12 4 4 10-10"/></svg>':LCSC_WARNING_SVG}</div>
  <h1>${title}</h1><p>结果与操作日志已保存到工具详情页。<br>你可以关闭浏览器，或留在当前页面继续查看。</p><div class="actions"><a href="fde-finish:close">关闭浏览器</a><a class="primary" href="fde-finish:stay" autofocus>留在浏览器</a></div></html>`
}

export function showLcscFinishDialog(browser: BrowserWindow, status: string) {
  const popup=new BrowserWindow({parent:browser,modal:true,width:440,height:330,resizable:false,minimizable:false,maximizable:false,title:'FDE 工作台 · 查询结束',show:false,
    webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
  popup.setMenu(null)
  popup.webContents.setWindowOpenHandler(()=>({action:'deny'}))
  popup.webContents.on('will-navigate',(event,url)=>{
    event.preventDefault()
    if(url==='fde-finish:close') {popup.close();if(!browser.isDestroyed())browser.close()}
    else if(url==='fde-finish:stay') popup.close()
  })
  popup.webContents.on('before-input-event',(event,input)=>{if(input.type==='keyDown' && input.key==='Escape'){event.preventDefault();popup.close()}})
  popup.once('ready-to-show',()=>popup.show())
  void popup.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(finishDialogHtml(status))).catch(()=>popup.close())
}
