import { Children, isValidElement, useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { MermaidConfig } from 'mermaid'

let renderId = 0
let diagramQueue: Promise<unknown> = Promise.resolve()
const colorValue = /^(?:#[\da-f]{3}|#[\da-f]{4}|#[\da-f]{6}|#[\da-f]{8})$/i
function safeDiagramConfig(raw: Record<string, unknown>): { config: MermaidConfig; ignored: boolean } {
  const config: MermaidConfig = {}
  let ignored = false
  for (const [key, value] of Object.entries(raw)) {
    if (key === 'theme' && ['base', 'default', 'dark', 'forest', 'neutral'].includes(String(value))) config.theme = value as MermaidConfig['theme']
    else if (key === 'themeVariables' && value && typeof value === 'object' && !Array.isArray(value)) {
      const variables: Record<string, string> = {}
      for (const [name, entry] of Object.entries(value)) {
        const color = /^(primaryColor|primaryTextColor|primaryBorderColor|secondaryColor|secondaryTextColor|secondaryBorderColor|tertiaryColor|tertiaryTextColor|tertiaryBorderColor|lineColor|textColor|mainBkg|nodeBorder|clusterBkg|clusterBorder|edgeLabelBackground|background|titleColor)$/.test(name) && typeof entry === 'string' && colorValue.test(entry)
        const font = name === 'fontFamily' && typeof entry === 'string' && /^[\w\u4e00-\u9fff ,'-]{1,120}$/.test(entry)
        const size = name === 'fontSize' && typeof entry === 'string' && /^(?:[89]|[12]\d|3[0-2])px$/.test(entry)
        if (color || font || size) variables[name] = entry as string
        else ignored = true
      }
      config.themeVariables = variables
    } else if (key === 'flowchart' && value && typeof value === 'object' && !Array.isArray(value)) {
      config.flowchart = {}
      for (const [name, entry] of Object.entries(value)) {
        if ((name === 'nodeSpacing' || name === 'rankSpacing' || name === 'padding') && typeof entry === 'number' && entry >= 0 && entry <= 200) config.flowchart[name] = entry
        else if (name === 'curve' && ['basis', 'linear', 'step', 'stepBefore', 'stepAfter', 'monotoneX', 'monotoneY'].includes(String(entry))) config.flowchart.curve = String(entry) as NonNullable<MermaidConfig['flowchart']>['curve']
        else ignored = true
      }
    } else ignored = true
  }
  return { config, ignored }
}

// Repair only the recognizable legacy layout; stored memo content is never rewritten.
export function normalizeMemoDiagrams(markdown: string): string {
  return markdown.replace(/^(flowchart|graph)\s+(TD|TB|BT|LR|RL)\s*\n\s*\n?```(?:text|plaintext)?\s*\n([\s\S]*?)^```\s*$/gm,
    (_match, kind: string, direction: string, body: string) => `\`\`\`mermaid\n${kind} ${direction}\n${body}\`\`\``)
}

// Extract only allowlisted presentation settings; never evaluate document code.
export function prepareMermaidSource(source: string): { renderSource: string; ignoredConfiguration: boolean; ignoredStyles: boolean; config: MermaidConfig } {
  if (source.length > 20000) throw new Error('diagram too large')
  let ignoredConfiguration = false
  let ignoredStyles = false
  let config: MermaidConfig = {}
  const classes: string[] = []
  const renderSource = source.replace(/\r\n?/g, '\n').replace(
    /^[ \t]*%%\{\s*init\s*:\s*([\s\S]*?)\}%%[ \t]*(?=\n|$)/gim,
    (_directive, json: string) => {
      const configuration: unknown = JSON.parse(json)
      if (!configuration || typeof configuration !== 'object' || Array.isArray(configuration)) throw new Error('invalid init configuration')
      const safe = safeDiagramConfig(configuration as Record<string, unknown>)
      config = { ...config, ...safe.config }
      ignoredConfiguration ||= safe.ignored
      return ''
    },
  ).replace(
    /^[ \t]*classDef[ \t]+([A-Za-z_][A-Za-z0-9_-]*)[ \t]+([^\n]*)$/gm,
    (_declaration, _name: string, rawProperties: string) => {
      const properties = rawProperties.trim().replace(/;$/, '').trim().split(',')
      const seen = new Set<string>()
      for (const property of properties) {
        const pair = /^[ \t]*(fill|stroke|color)[ \t]*:[ \t]*#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})[ \t]*$/i.exec(property)
        if (!pair || seen.has(pair[1].toLowerCase())) throw new Error('unsupported class styling')
        seen.add(pair[1].toLowerCase())
      }
      classes.push(`classDef ${_name} ${properties.map(property => property.trim()).join(',')};`)
      return ''
    },
  )
  // Also reject commands after semicolons, not just at the beginning of a line.
  // Residual directives include malformed, inline, and unsupported configuration.
  if (/%%\s*\{|^\s*---|(?:^|[;\n])\s*(?:click|classDef|style|linkStyle)\b/im.test(renderSource)) throw new Error('unsupported configuration')
  return { renderSource: renderSource + (classes.length ? '\n' + classes.join('\n') : ''), ignoredConfiguration, ignoredStyles, config }
}

export function MermaidDiagram({ source }: { source: string }) {
  const [result, setResult] = useState<{ source: string; image?: string; error?: boolean; ignoredConfiguration?: boolean; ignoredStyles?: boolean } | null>(null)
  useEffect(() => {
    let active = true
    async function render() {
      let ignoredConfiguration = false
      let ignoredStyles = false
      try {
        // Serialize configuration + render so simultaneous diagrams cannot share themes.
        const prepared = prepareMermaidSource(source)
        ignoredConfiguration = prepared.ignoredConfiguration
        ignoredStyles = prepared.ignoredStyles
        const job = diagramQueue.then(async () => {
          const { default: mermaid } = await import('mermaid')
          mermaid.initialize({ ...prepared.config, startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true,
          maxTextSize: 20000, maxEdges: 300, theme: prepared.config.theme ?? 'default', flowchart: { ...prepared.config.flowchart, htmlLabels: false },
          secure: ['secure', 'securityLevel', 'startOnLoad', 'maxTextSize', 'maxEdges', 'suppressErrorRendering', 'themeCSS', 'flowchart'] })
          return mermaid.render(`memo-diagram-${++renderId}`, prepared.renderSource)
        })
        diagramQueue = job.catch(() => undefined)
        const { svg } = await job
        // Mermaid may emit HTML void elements (e.g. <br>) inside foreignObject.
        // Parse that markup as inert HTML, then serialize to well-formed XML for an SVG image.
        const document = new DOMParser().parseFromString(svg, 'text/html')
        const root = document.querySelector('svg')
        if (!root) throw new Error('missing SVG')
        const box = root.getAttribute('viewBox')?.trim().split(/[ ,]+/).map(Number)
        if (box?.length === 4 && box.every(Number.isFinite) && box[2] > 0 && box[3] > 0) {
          root.setAttribute('width', String(box[2])); root.setAttribute('height', String(box[3]))
        }
        const sized = new XMLSerializer().serializeToString(root)
        if (new DOMParser().parseFromString(sized, 'image/svg+xml').querySelector('parsererror')) throw new Error('invalid SVG')
        if (active) setResult({ source, image: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(sized)}`, ignoredConfiguration, ignoredStyles })
      } catch {
        if (active) setResult({ source, error: true, ignoredConfiguration, ignoredStyles })
      }
    }
    void render()
    return () => { active = false }
  }, [source])
  const current = result?.source === source ? result : null
  return <figure className="memo-diagram">
    {current?.image ? <div className="memo-diagram-image"><img src={current.image} alt="备忘录流程图" onError={() => setResult({ source, error: true, ignoredConfiguration: current.ignoredConfiguration, ignoredStyles: current.ignoredStyles })} /></div> : <p role="status">{current?.error ? '流程图暂时无法渲染，请检查 Mermaid 语法（不支持链接、复杂样式指令或不完整的配置）。' : '正在绘制流程图…'}</p>}
    {current?.ignoredConfiguration || current?.ignoredStyles ? <p className="field-hint">部分不支持或不安全的配置已忽略，其余样式已应用。</p> : null}
    <details open={current?.error || undefined}><summary>查看流程图源码</summary><pre><code>{source}</code></pre></details>
  </figure>
}

export function MemoMarkdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    table: ({ children }) => <div className="memo-table-scroll"><table>{children}</table></div>,
    a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
    pre: ({ children }) => {
      const child = Children.toArray(children)[0]
      if (isValidElement<{ className?: string; children?: unknown }>(child)) {
        const source = String(child.props.children ?? '').replace(/\n$/, '')
        if (child.props.className === 'language-mermaid' || (!child.props.className && /^(?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL)\b/.test(source))) return <MermaidDiagram source={source} />
      }
      return <pre>{children}</pre>
    },
  }}>{normalizeMemoDiagrams(children)}</ReactMarkdown>
}
