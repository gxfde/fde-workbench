// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ initialize: vi.fn(), render: vi.fn() }))
vi.mock('mermaid', () => ({ default: mocks }))
import { MemoMarkdown, MermaidDiagram, normalizeMemoDiagrams, prepareMermaidSource } from '../../src/renderer/src/research/MemoMarkdown'
afterEach(() => { cleanup(); vi.resetAllMocks() })
it('serializes Mermaid HTML line breaks into valid SVG XML and handles image failures', async () => {
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200"><foreignObject><div><p>工程<br>资料</p></div></foreignObject></svg>' })
  render(<MemoMarkdown>{'```mermaid\nflowchart TD\nA["工程<br/>资料"]\n```'}</MemoMarkdown>)
  const image = await screen.findByAltText('备忘录流程图')
  const svg = decodeURIComponent(image.getAttribute('src')!.split(',').slice(1).join(','))
  const parsed = new DOMParser().parseFromString(svg, 'image/svg+xml')
  expect(parsed.querySelector('parsererror')).toBeNull()
  expect(parsed.documentElement.getAttribute('height')).toBe('200')
  fireEvent.error(image)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(screen.queryByAltText('备忘录流程图')).not.toBeInTheDocument()
})
it('renders diagrams as isolated images and keeps source available', async () => {
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>测试</text></svg>' })
  render(<MemoMarkdown>{'正文\n\n```mermaid\nflowchart TD\nA --> B\n```'}</MemoMarkdown>)
  expect(await screen.findByAltText('备忘录流程图')).toHaveAttribute('src', expect.stringContaining('data:image/svg+xml'))
  expect(screen.getByText('正文')).toBeVisible()
  expect(mocks.initialize).toHaveBeenCalledWith(expect.objectContaining({ securityLevel: 'strict' }))
})
it('keeps invalid diagrams as source without hiding surrounding text', async () => {
  mocks.render.mockRejectedValue(new Error('syntax'))
  render(<MemoMarkdown>{'正文\n\n```mermaid\ninvalid\n```'}</MemoMarkdown>)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(screen.getByText('invalid')).toBeVisible()
  expect(screen.getByText('正文')).toBeVisible()
})
it('does not execute diagram configuration overrides', async () => {
  render(<MemoMarkdown>{'```mermaid\n%%{init: {securityLevel: "loose"}}%%\nflowchart TD\nA-->B\n```'}</MemoMarkdown>)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(mocks.render).not.toHaveBeenCalled()
})

const configuredUserDiagram = `%%{init: {
  "theme": "base",
  "flowchart": {
    "curve": "basis",
    "nodeSpacing": 34,
    "rankSpacing": 46
  },
  "themeVariables": {
    "fontFamily": "Arial, Microsoft YaHei, sans-serif",
    "fontSize": "14px",
    "primaryColor": "#F5F8FF",
    "primaryTextColor": "#1F2937",
    "primaryBorderColor": "#94A3B8",
    "lineColor": "#94A3B8",
    "secondaryColor": "#F8FAFC",
    "tertiaryColor": "#FFFFFF"
  }
}}%%

flowchart TB
    U["研发人员"] --> W["进入研发工作台"]
    W --> M["手动选择已启用模块<br/>上传文件或选择库内资料"]`

it('ignores the complete user init block only in the render copy and retains the exact original source', async () => {
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 200"><text>研发人员</text></svg>' })
  render(<MermaidDiagram source={configuredUserDiagram} />)

  expect(await screen.findByAltText('备忘录流程图')).toBeVisible()
  expect(screen.queryByText(/配置已忽略/)).not.toBeInTheDocument()
  expect(document.querySelector('details code')?.textContent).toBe(configuredUserDiagram)
  expect(mocks.render.mock.calls[0][1]).toBe(configuredUserDiagram.slice(configuredUserDiagram.indexOf('}}%%') + 4))
  expect(mocks.render.mock.calls[0][1]).not.toContain('init')
  expect(mocks.render.mock.calls[0][1]).toContain('<br/>')
  expect(mocks.initialize).toHaveBeenCalledWith(expect.objectContaining({
    securityLevel: 'strict', startOnLoad: false, suppressErrorRendering: true,
    maxTextSize: 20000, maxEdges: 300, theme: 'base', flowchart: { htmlLabels: false, curve: 'basis', nodeSpacing: 34, rankSpacing: 46 },
  }))
  expect(mocks.initialize.mock.calls[0][0].themeVariables).toMatchObject({ primaryColor: '#F5F8FF', fontSize: '14px' })
})

it('never applies executable or security-related values in otherwise valid JSON configuration', async () => {
  const directive = '%%{init: {"securityLevel":"loose","startOnLoad":true,"maxTextSize":9999999,"maxEdges":999999,"themeCSS":"@import url(https://unsafe.invalid/theme.css)","flowchart":{"htmlLabels":true},"__proto__":{"polluted":true}}}%%'
  const body = 'flowchart TD\nA[安全] --> B[结束]'
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>安全</text></svg>' })
  render(<MermaidDiagram source={`${directive}\n${body}`} />)

  expect(await screen.findByAltText('备忘录流程图')).toBeVisible()
  expect(mocks.render.mock.calls[0][1]).toBe(`\n${body}`)
  expect(JSON.stringify(mocks.initialize.mock.calls[0][0])).not.toContain('unsafe.invalid')
  expect(mocks.initialize.mock.calls[0][0]).toMatchObject({ securityLevel: 'strict', maxEdges: 300, maxTextSize: 20000, flowchart: { htmlLabels: false } })
  expect(Object.prototype).not.toHaveProperty('polluted')
})

it('removes multiple complete standalone init blocks without changing diagram statements', () => {
  const result = prepareMermaidSource('%%{init: {"theme":"dark"}}%%\r\nflowchart LR\r\n%%{init: {"theme":"base"}}%%\r\nA-->B')
  expect(result).toMatchObject({ renderSource: '\nflowchart LR\n\nA-->B', ignoredConfiguration: false, ignoredStyles: false, config: { theme: 'base' } })
  expect(prepareMermaidSource('flowchart TD\nA-->B')).toEqual({ renderSource: 'flowchart TD\nA-->B', ignoredConfiguration: false, ignoredStyles: false, config: {} })
})

it.each([
  ['unclosed configuration', '%%{init: {"theme":"base"}\nflowchart TD\nA-->B'],
  ['invalid nested JSON', '%%{init: {"theme":{"name":"base"}}%%\nflowchart TD\nA-->B'],
  ['JavaScript expression', '%%{init: {"theme":alert("bad")}}%%\nflowchart TD\nA-->B'],
  ['array configuration', '%%{init: [{"theme":"base"}]}%%\nflowchart TD\nA-->B'],
  ['null configuration', '%%{init: null}%%\nflowchart TD\nA-->B'],
  ['trailing inline command', '%%{init: {"theme":"base"}}%% click A "https://unsafe.invalid"\nflowchart TD\nA-->B'],
  ['embedded directive', 'flowchart TD; %%{init: {"securityLevel":"loose"}}%%\nA-->B'],
  ['unsupported initialize directive', '%%{initialize: {"theme":"base"}}%%\nflowchart TD\nA-->B'],
  ['unsupported wrap directive', '%%{wrap}%%\nflowchart TD\nA-->B'],
  ['YAML configuration', '---\nconfig:\n  securityLevel: loose\n---\nflowchart TD\nA-->B'],
  ['separate click command', 'flowchart TD\nA-->B\nclick A "https://unsafe.invalid"'],
  ['semicolon click command', 'flowchart TD; A-->B; click A "https://unsafe.invalid"'],
  ['semicolon class definition', 'flowchart TD; A-->B; classDef bad fill:url(https://unsafe.invalid)'],
  ['semicolon style command', 'flowchart TD; A-->B; style A fill:red'],
  ['semicolon link style', 'flowchart TD; A-->B; linkStyle 0 stroke:red'],
  ['click after removed init', '%%{init: {"theme":"base"}}%%\nflowchart TD\nA-->B\nclick A callback'],
])('rejects %s before invoking Mermaid and exposes source fallback', async (_name, source) => {
  render(<MermaidDiagram source={source} />)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(document.querySelector('details')).toHaveAttribute('open')
  expect(document.querySelector('details code')?.textContent).toBe(source)
  expect(mocks.initialize).not.toHaveBeenCalled()
  expect(mocks.render).not.toHaveBeenCalled()
})

it('counts discarded init text against the input size limit', () => {
  expect(() => prepareMermaidSource(`%%{init: {"themeCSS":"${'a'.repeat(20000)}"}}%%\nflowchart TD\nA-->B`)).toThrow('diagram too large')
})

it('ignores standalone hex-color class definitions while preserving class assignments and structure', async () => {
  const diagram = 'flowchart LR\nA[开始] --> B[结束]\n    classDef entry fill:#EFF6FF,stroke:#60A5FA,color:#1E3A8A;\n    class A,B entry;'
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>开始</text></svg>' })
  render(<MermaidDiagram source={diagram} />)

  expect(await screen.findByAltText('备忘录流程图')).toBeVisible()
  expect(screen.queryByText(/配置已忽略/)).not.toBeInTheDocument()
  expect(mocks.render.mock.calls[0][1]).toContain('classDef entry fill:#EFF6FF,stroke:#60A5FA,color:#1E3A8A;')
  expect(document.querySelector('details code')?.textContent).toBe(diagram)
  expect(mocks.render.mock.calls[0][1]).toContain('#EFF6FF')
})

it('renders a complete generic workflow after ignoring init configuration', async () => {
  const source = '%%{init: {"theme":"base"}}%%\nflowchart TB\nA["Start"] --> B{"Ready?"}\nB -->|Yes| C["Run"]\nB -.->|No| D["Review"]\nclassDef state fill:#EFF6FF,stroke:#60A5FA,color:#1E3A8A;\nclass A,C,D state;'
  mocks.render.mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>研发工作台</text></svg>' })
  render(<MermaidDiagram source={source} />)

  const image = await screen.findByAltText('备忘录流程图')
  expect(image).toBeVisible()
  expect(screen.queryByText(/配置已忽略/)).not.toBeInTheDocument()
  expect(document.querySelector('details code')?.textContent).toBe(source)
  const rendered = mocks.render.mock.calls[0][1] as string
  expect(rendered).not.toContain('%%{')
  expect(rendered).toContain('classDef')
  expect(rendered.match(/<-->|-->|-\.->/g)).toHaveLength(3)
  expect(rendered.match(/^\s*class /gm)).toHaveLength(1)
  expect(rendered).toContain('B -->|Yes| C')
  expect(rendered).toContain('B -.->|No| D')
  fireEvent.error(image)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(screen.queryByText(/配置已忽略/)).not.toBeInTheDocument()
  expect(document.querySelector('details code')?.textContent).toBe(source)
})

it.each([
  ['external CSS URL', 'classDef unsafe fill:url(https://unsafe.invalid/image.svg)'],
  ['escaped URL', 'classDef unsafe fill:u\\72l(https://unsafe.invalid/image.svg)'],
  ['other CSS property', 'classDef unsafe background:#fff'],
  ['font CSS property', 'classDef unsafe font-size:99px'],
  ['named color', 'classDef unsafe fill:red'],
  ['invalid hex', 'classDef unsafe fill:#hello1'],
  ['duplicate property', 'classDef unsafe fill:#fff,fill:#000'],
  ['empty property', 'classDef unsafe fill:#fff,'],
  ['CSS declaration injection', 'classDef unsafe fill:#fff;stroke:red'],
  ['CSS selector class name', 'classDef unsafe:hover fill:#fff'],
  ['inline CSS directive', 'A-->B; classDef unsafe fill:#fff'],
  ['click appended to otherwise safe CSS', 'classDef unsafe fill:#fff; click A callback'],
  ['multiple CSS statements', 'classDef unsafe fill:#fff; classDef other fill:#000;'],
])('rejects %s in class definitions without passing user CSS to Mermaid', async (_name, declaration) => {
  const source = `%%{init: {"theme":"base"}}%%\nflowchart TD\nA-->B\n${declaration}`
  render(<MermaidDiagram source={source} />)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(document.querySelector('details code')?.textContent).toBe(source)
  expect(mocks.initialize).not.toHaveBeenCalled()
  expect(mocks.render).not.toHaveBeenCalled()
})

it('keeps original configured source available when rendering fails after safe configuration removal', async () => {
  mocks.render.mockRejectedValue(new Error('syntax'))
  render(<MermaidDiagram source={configuredUserDiagram} />)
  expect(await screen.findByText(/流程图暂时无法渲染/)).toBeVisible()
  expect(document.querySelector('details code')?.textContent).toBe(configuredUserDiagram)
  expect(screen.queryByText(/配置已忽略/)).not.toBeInTheDocument()
})
it('repairs legacy separated headers without changing normal code blocks', () => {
  expect(normalizeMemoDiagrams('flowchart TD\n\n```\nA --> B\n```')).toBe('```mermaid\nflowchart TD\nA --> B\n```')
  expect(normalizeMemoDiagrams('```js\nconst x = 1\n```')).toBe('```js\nconst x = 1\n```')
})
