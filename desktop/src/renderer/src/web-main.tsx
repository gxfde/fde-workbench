// 浏览器发行入口。桌面端仍由 index.html -> main.tsx 启动，不经过这里。
//
// 顺序有语义：先执行 fde-web-bridge 把 window.fde 挂好，再执行 main.tsx 渲染 App，
// 避免 AuthProvider 首帧读到未定义的桥。main.tsx 本体零改动，桌面/Web 共用同一套 UI。
import "./fde-web-bridge"
import "./main"
