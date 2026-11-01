import { useMemo, useState } from 'react'

import {
  buildTranslationPreview,
  type TranslatorFormState,
} from './preview'

// 翻译器门户骨架（goal-d8，PRD §3.2 P3 预备）：引导式表单 + 实时只读预览。
// 骨架边界：纯前端映射（preview.ts 启发式），不调 AI、不落库；提交入口
// 显式禁用并说明——P3 全量轮接入 guidance 管道与终审台。
const INTERVIEW_MODES: { value: TranslatorFormState['interview_mode']; label: string }[] = [
  { value: 'onsite', label: '现场' },
  { value: 'remote', label: '远程' },
  { value: 'hybrid', label: '混合' },
]

const EMPTY_FORM: TranslatorFormState = {
  industry: '',
  scale: '',
  region: '',
  interview_mode: 'onsite',
  customer_vision: '',
  phase_objective: '',
}

export function TranslatorPortalPage() {
  const [form, setForm] = useState<TranslatorFormState>(EMPTY_FORM)
  const preview = useMemo(() => buildTranslationPreview(form), [form])

  function update<K extends keyof TranslatorFormState>(key: K, value: TranslatorFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <section className="page" aria-label="翻译器门户（骨架）">
      <header className="page-header">
        <div>
          <p className="eyebrow">翻译器门户</p>
          <h1>客户诉求翻译（骨架版）</h1>
          <p>
            把客户的模糊诉求引导式录入，右侧实时生成结构化预览（只读，不落库、不调 AI）。
            <span className="badge warning translator-skeleton">P3 骨架 · 只读预览</span>
          </p>
        </div>
      </header>
      <div className="page-stack">
        <div className="card translator-form">
          <div className="card-heading">
            <div>
              <h3>第一步 · 客户背景</h3>
            </div>
          </div>
          <label>
            行业
            <input
              value={form.industry}
              onChange={(event) => update('industry', event.target.value)}
              placeholder="如：装备制造"
            />
          </label>
          <label>
            规模
            <input
              value={form.scale}
              onChange={(event) => update('scale', event.target.value)}
              placeholder="如：200 人 / 年产值 3 亿"
            />
          </label>
          <label>
            区域
            <input
              value={form.region}
              onChange={(event) => update('region', event.target.value)}
              placeholder="如：苏州"
            />
          </label>
          <label>
            访谈方式
            <select
              value={form.interview_mode}
              onChange={(event) => update('interview_mode', event.target.value as TranslatorFormState['interview_mode'])}
            >
              {INTERVIEW_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>{mode.label}</option>
              ))}
            </select>
          </label>
          <div className="card-heading">
            <div>
              <h3>第二步 · 客户诉求与阶段目标</h3>
            </div>
          </div>
          <label>
            客户诉求原话（按句读切分为拟问题清单）
            <textarea
              value={form.customer_vision}
              onChange={(event) => update('customer_vision', event.target.value)}
              rows={5}
              placeholder="例：仓库出入库必须过系统留痕；管理层看不到实时良率；明年要过客户审计……"
            />
          </label>
          <label>
            阶段目标
            <textarea
              value={form.phase_objective}
              onChange={(event) => update('phase_objective', event.target.value)}
              rows={2}
              placeholder="本期要达成什么（预览会提示是否缺失）"
            />
          </label>
        </div>
        <div className="card translator-preview" aria-live="polite">
          <div className="card-heading">
            <div>
              <h3>实时预览（只读）</h3>
            </div>
          </div>
          <p className="muted">
            客户画像：{preview.profile.industry || '—'} / {preview.profile.scale || '—'} / {preview.profile.region || '—'} / {preview.profile.interview_mode}
          </p>
          {preview.draft_problems.length === 0 ? (
            <p className="muted">暂无拟问题清单。</p>
          ) : (
            <ol className="translator-problems">
              {preview.draft_problems.map((problem, index) => (
                <li key={`${index}-${problem.text}`}>
                  {problem.text}
                  <span className={`badge ${problem.severity === 'high' ? 'warning' : 'muted'} translator-severity`}>
                    {problem.severity === 'high' ? 'severity=high（预标）' : 'severity=待确认'}
                  </span>
                  <span className="badge muted translator-module">module=待认领</span>
                </li>
              ))}
            </ol>
          )}
          {preview.hints.map((hint) => (
            <p key={hint} className="muted translator-hint">{hint}</p>
          ))}
          <button type="button" disabled title="骨架版不落库：P3 全量轮接入 guidance 翻译管道与终审台后开放">
            提交翻译（P3 开放）
          </button>
        </div>
      </div>
    </section>
  )
}
