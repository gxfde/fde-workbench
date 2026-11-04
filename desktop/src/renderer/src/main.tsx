import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App } from "./App"
import { PRODUCT_NAME } from "../../shared/brand"
import "./styles.css"
import "./pages/pages.css"

// 红线①：index.html 的 <title> 是静态初值，渲染入口用它运行时覆盖——
// 改名只改 shared/brand.ts，不再同步 HTML（HTML 初值仅是首帧占位）。
document.title = PRODUCT_NAME

const root = document.getElementById("root")
if (!root) throw new Error("Renderer root is missing.")

createRoot(root).render(<StrictMode><App /></StrictMode>)
