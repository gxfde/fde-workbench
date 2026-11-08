// G6 浏览器回归 harness：在浏览器里跑真实 renderer。
//
// 桌面端正常运行时 renderer 通过 Electron preload 拿到 window.fde 桥
// （auth / api / bridge / app），浏览器里没有这个桥。本 harness 用一个
// dev-only 插件把等价实现注入页面：
//   - api.request → 直接 fetch 后端 http://127.0.0.1:8010（与 main/api-ipc.ts
//     同样的 URL 拼装与错误信封）；
//   - auth.* → 后端 /api/v1/auth/*（与 main/auth-ipc.ts 同契约）；
//   - bridge.capture → 返回「本 harness 无宿主计划任务」的明确失败，
//     集成桥页的按钮态与失败提示仍走真实前端代码路径。
//
// 只在 harness 模式下注入：生产构建与正常 electron-vite dev 不受影响。
import { defineConfig } from "vite"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const rendererRoot = path.resolve(here, "..", "src", "renderer")
// 同源代理：浏览器页面在 127.0.0.1:5199，/api 代理到后端 8010。
// 桌面端走 Electron IPC 从不受 CORS 约束，浏览器必须同源，故用 dev 代理，
// 不改服务端（服务端加 CORS 会放宽生产边界）。
const apiBase = ""
const apiProxyTarget = process.env.FDE_HARNESS_API ?? "http://127.0.0.1:8010"

/** 注入 window.fde 桥实现（浏览器等价物，非生产代码）。 */
function fdeBridgePlugin() {
  return {
    name: "fde-harness-bridge",
    apply: "serve" as const,
    transformIndexHtml(html) {
      // harness 需要放宽两处 CSP（仅 dev server，不影响生产构建）：
      //  1. connect-src 放开 'self'——浏览器走同源 /api 代理（桌面端走 IPC，不受 CORS 约束）；
      //  2. style-src 放开 'unsafe-inline'——Vite dev 以 <style> 注入样式表，
      //     生产 CSP 的 'self' 会把它们全部拦掉，页面渲染成无样式。
      const patched = html
        .replace(
          /connect-src http:\/\/127\.0\.0\.1:8010/,
          "connect-src 'self' http://127.0.0.1:8010",
        )
        .replace(
          /style-src 'self'/,
          "style-src 'self' 'unsafe-inline'",
        )
      return {
        html: patched,
        tags: [
          {
            tag: "script",
            injectTo: "head-prepend" as const,
            children: `
(function () {
  var API_BASE = ${JSON.stringify(apiBase)};
  var token = null;
  var refreshToken = null;
  var user = null;

  function envelope(data, error) { return { ok: !error, data: data, error: error || null }; }
  function apiError(code, message, details) { return { code: code, message: message, details: details === undefined ? null : details }; }

  async function request(path, options) {
    options = options || {};
    var method = options.method || "GET";
    var headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;
    var init = { method: method, headers: headers };
    if (options.body !== undefined && method !== "GET") init.body = JSON.stringify(options.body);
    var response;
    try {
      response = await fetch(API_BASE + path, init);
    } catch (error) {
      return envelope(null, apiError("network_error", "无法连接本地服务，请确认服务已启动。"));
    }
    var payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    if (!response.ok) {
      var err = (payload && payload.error) || apiError("request_failed", "请求失败，请稍后重试。");
      if (response.status === 401) {
        var refreshed = await refreshTokens();
        if (refreshed) {
          return request(path, options);
        }
      }
      return envelope(null, err);
    }
    // ApiResponse 契约：{ status, data, error }——status 必带，渲染层据此
    // 判定 204 与错误信封（见 shared/contracts.ts）。
    return envelope({ status: response.status, data: payload ? payload.data : null, error: null }, null);
  }

  async function login(input) {
    // 渲染层字段是 camelCase（deviceLabel），服务端字段是 snake_case
    // （device_label）——桌面端由 preload 做这次转换，harness 自己做。
    var response = await fetch(API_BASE + "/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: input.username,
        password: input.password,
        device_label: input.deviceLabel || "FDE Workbench Desktop"
      })
    });
    var payload = await response.json().catch(function () { return null; });
    if (!response.ok) {
      var err = (payload && payload.error) || apiError("login_failed", "登录失败。");
      return envelope(null, err);
    }
    var data = payload.data || {};
    token = data.access_token || null;
    refreshToken = data.refresh_token || null;
    user = toRendererUser(data.user);
    sessionStorage.setItem("fde-harness-access", token || "");
    sessionStorage.setItem("fde-harness-refresh", refreshToken || "");
    sessionStorage.setItem("fde-harness-user", JSON.stringify(user));
    return envelope({ accessToken: token, accessExpiresAt: data.access_expires_at, refreshExpiresAt: data.refresh_expires_at, user: user }, null);
  }

  // 服务端 user 是 snake_case（display_name），渲染层要 camelCase
  // （displayName）——桌面端由 main/auth-ipc.ts 做这次转换（见其 :377），
  // harness 必须同尺，否则侧栏账号名等 displayName 消费点全渲染成空。
  function toRendererUser(raw) {
    if (!raw) return null;
    return Object.assign({}, raw, { displayName: raw.display_name || raw.displayName || "" });
  }

  async function refreshTokens() {
    if (!refreshToken) return null;
    var response = await fetch(API_BASE + "/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken })
    });
    if (!response.ok) return null;
    var payload = await response.json().catch(function () { return null; });
    var data = (payload && payload.data) || {};
    token = data.access_token || token;
    refreshToken = data.refresh_token || refreshToken;
    sessionStorage.setItem("fde-harness-access", token || "");
    sessionStorage.setItem("fde-harness-refresh", refreshToken || "");
    return token;
  }

  function restore() {
    token = sessionStorage.getItem("fde-harness-access") || null;
    refreshToken = sessionStorage.getItem("fde-harness-refresh") || null;
    var raw = sessionStorage.getItem("fde-harness-user");
    user = raw ? toRendererUser(JSON.parse(raw)) : null;
  }
  restore();

  window.fde = {
    auth: {
      login: function (input) { return login(input); },
      refresh: async function () {
        var ok = await refreshTokens();
        if (!ok) return envelope(null, apiError("session_expired", "会话已过期。"));
        return envelope({ accessToken: token, refreshToken: refreshToken, accessExpiresAt: null, refreshExpiresAt: null, user: user }, null);
      },
      changePassword: async function () { return envelope(null, apiError("unsupported_in_harness", "harness 不支持改密。")); },
      logout: async function () {
        token = null; refreshToken = null; user = null;
        sessionStorage.clear();
        return envelope(null, null);
      }
    },
    api: { request: request },
    bridge: {
      capture: async function () {
        return envelope(null, apiError("bridge_platform", "浏览器 harness 无宿主计划任务，无法手动采集。"));
      }
    },
    app: {
      // 注意：app 桥的契约与 auth/api 不同——version() 直接返回字符串
      // （见 shared/contracts.ts 的 app 段），不是 BridgeResult 信封。
      version: async function () { return "0.2.0-harness"; },
      setLcscEnabled: async function () {},
      openLcscBrowser: async function () {},
      showLcscDownload: async function () {},
      copyLcscRunId: async function () {}
    }
  };
})();
`,
          },
        ],
      }
    },
  }
}

export default defineConfig({
  root: rendererRoot,
  // 不引 @vitejs/plugin-react（仓库未安装）：Vite 用 esbuild 处理 .tsx，
  // jsx 模式取 tsconfig.web.json 的 react-jsx——与 electron-vite 构建同源。
  plugins: [fdeBridgePlugin()],
  esbuild: {
    jsx: "automatic",
  },
  server: {
    host: "127.0.0.1",
    port: 5199,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
    },
  },
  resolve: {
    alias: {
      "@renderer": path.resolve(rendererRoot, "src"),
    },
  },
})
