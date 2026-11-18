---
name: 交付工作台视觉规范
status: draft
updated: 2026-11-18
sources:
  - ../../../desktop/src/renderer/src/styles.css
  - ../../../desktop/src/shared/brand.ts
colors:
  sidebar: '#14181C'
  canvas: '#F6F6F4'
  surface: '#FFFFFF'
  text: '#1A2027'
  secondary-text: '#565F6B'
  line: '#E4E7EB'
  primary: '#C98F2B'
  on-primary: '#14181C'
  selected-bg: '#FBF3E2'
  focus-dark-bg: '#F5B44A'
  success-bg: '#E8F8EF'
  success-text: '#0B6E3D'
  warning-bg: '#FEF3E2'
  warning-text: '#8A3F06'
  danger-bg: '#FDECEA'
  danger-text: '#96261A'
  info-bg: '#EEF1F5'
  info-text: '#2B3340'
typography:
  body:
    fontFamily: 'PingFang SC, PingFang TC, -apple-system, BlinkMacSystemFont, Microsoft YaHei, sans-serif'
  page-title:
    note: 沿用现有全局标题档，不引入展示标题档
  metadata:
    note: 沿用现有标签与辅助文字档，指纹可沿用等宽字
rounded:
  control: 9px
  panel: 12px
  overlay: 14px
spacing:
  inline: 8px
  row: 12px
  section: 24px
  page: 32px
components:
  primary-action:
    background: '{colors.primary}'
    foreground: '{colors.on-primary}'
    radius: '{rounded.control}'
  status-warning:
    background: '{colors.warning-bg}'
    foreground: '{colors.warning-text}'
  status-failure:
    background: '{colors.danger-bg}'
    foreground: '{colors.danger-text}'
  work-list:
    background: '{colors.surface}'
    border: '{colors.line}'
    row-gap: '{spacing.row}'
---

# 交付工作台视觉规范 · 评审草案

## Brand & Style

本轮是对现有样式的继承约定，不是换品牌。保留石墨黑侧栏、琥珀金交互与浅色工作区，不引入新 UI 库、字体或图标体系。界面产品名称继续从共享品牌源读取。此文件只管视觉；功能分组、操作规则、状态语义与验收以 [EXPERIENCE.md](./EXPERIENCE.md) 为准。

## Colors

- 品牌金用于主操作或当前选中项，不代表成功。金底用深色前景；确认通过、风险和失败分别使用现有语义色对，且配置文字或图标，不用颜色单独传达。
- 令牌记录既有值，不要求新增一套 CSS 变量。主色继续映射 `--brand-blue`，主文案映射 `--text`，状态小字复用 `--success-ink`、`--warning-ink` 等。保留现有渐变白名单，不扩展。
- 实现时检查实际叠色下文本、边框与焦点：普通文字 ≥4.5:1，大号文字和必需的非文字控件边界、焦点与相邻色 ≥3:1；浅底焦点若不达标，用既有色阶的深色焦点，不拿原有全局样式代替验收。

## Typography

沿用现有中文字体栈及字号。项目代号、日期、金额、版本适合同行扫读；正文允许自然换行。指纹默认短显，仅在授权详情中支持完整查看。不得缩小字号来挤下导航和表单操作。

## Layout & Spacing

高频队列以列表或表格为主；项目头、业务分组、当前操作区按实际阅读顺序排。宽窗可在同页并排显示列表和详情，窄窗改用单列详情或抽屉，回退保留定位。只允许宽数据表在自己的容器横向滚动，主要动作不得跟着滚出屏幕。固定操作区须给最后一行、错误提示及键盘焦点留足空间。

## Elevation & Depth

用边线和间距区分列表、详情和状态；浮层与确认框用现有阴影。避免为每个汇总值单独铺一张高对比卡片。

## Shapes

保留现有控件、面板、浮层圆角。状态标签与按钮在样式上可辨；不可点击的状态不做成按钮外观。

## Components

| 组件 | 视觉规则 |
|---|---|
| 待办行 | 对象名为主；状态、责任人和期限为辅；可执行动作单独可辨 |
| 下一步区 | 在项目头下方固定位置；优先显示一个动作或一条阻塞，不把多个主按钮排在一起 |
| 状态行与错误条 | 文案就地显示；小字号采用语义深色，错误不能只靠临时浮窗 |
| 确认框 | 标题说明动作，正文列对象与影响；默认不聚焦不可逆动作 |
| 三方差异表 | 明示「打开时／最新值／我的草稿」三列；窄窗按字段纵向堆叠 |

## Do's and Don'ts

保留常用入口和现有外观识别度。不要做新的欢迎大屏，不把百分比渲染为门禁通过，不用品牌色替代状态色，也不把「已提交」画成「已完成」。
