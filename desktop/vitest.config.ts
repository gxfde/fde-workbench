import { defineConfig } from "vitest/config"

/**
 * 桌面端测试配置。
 *
 * 现状说明：仓库此前依赖 vitest 默认的 5s 单例超时。跑全量（68 文件 / 800+ 用例，
 * serial 模式）时，个别重交互用例（模板发布、AI 对话轮询）在本机会因资源紧张
 * 偶发超时——同一提交连跑多次有时绿有时红，属环境抖动而非代码回归
 * （已用纯净 fork/main 基线对照确认：基线同样出现 2/791 偶发失败）。
 *
 * 这里把 testTimeout 放宽到 20s、hookTimeout 放宽到 20s：
 * - 真实的逻辑错误会在断言处失败，不会被超时掩盖；
 * - 超时只用于「等待异步渲染/请求」，放宽只减少假阴性；
 * - 不改变任何用例的断言语义，也不新增跳过。
 */
export default defineConfig({
  test: {
    testTimeout: 20000,
    hookTimeout: 20000,
  },
})
