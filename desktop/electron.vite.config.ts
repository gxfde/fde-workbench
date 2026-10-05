import { resolve } from "node:path"

import { defineConfig } from "electron-vite"

/**
 * The renderer ships a CSP of `style-src 'self'`. While the dev server is
 * running, Vite injects CSS as an inline <style> tag, which that directive
 * blocks - the whole stylesheet is dropped and the UI renders unstyled.
 *
 * Relax the directive for the dev server only. Production builds emit a real
 * <link rel="stylesheet">, so the strict policy stays intact there.
 */
const devInlineStyleCsp = {
  name: "dev-inline-style-csp",
  apply: "serve" as const,
  transformIndexHtml(html: string) {
    return html.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
  },
}

export default defineConfig({
  main: {
    build: {
      rollupOptions: {
        input: resolve(__dirname, "src/main/index.ts"),
      },
    },
  },
  preload: {
    build: {
      rollupOptions: {
        input: resolve(__dirname, "src/preload/index.ts"),
      },
    },
  },
  renderer: {
    root: resolve(__dirname, "src/renderer"),
    plugins: [devInlineStyleCsp],
    build: {
      rollupOptions: {
        input: resolve(__dirname, "src/renderer/index.html"),
      },
    },
  },
})
