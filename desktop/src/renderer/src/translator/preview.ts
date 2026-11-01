// 翻译器门户骨架——实时预览映射（goal-d8，PRD §3.2 P3 预备）。
// 纯前端启发式映射：把引导式表单状态实时翻译为「结构化预览卡」，
// 不调 AI、不落库（骨架版只读）；P3 全量时该函数由 AI 翻译管道替换，
// 输出形状对齐 guidance 契约（key_business_problems 的 severity/module 两键，
// goal-d1 增强口径），保证后续管道可平滑接管。

export interface TranslatorFormState {
  industry: string
  scale: string
  region: string
  interview_mode: 'onsite' | 'remote' | 'hybrid'
  customer_vision: string
  phase_objective: string
}

export interface DraftProblem {
  text: string
  severity: 'high' | 'medium' | 'low' | null
  module: string | null
  tentative: boolean
}

export interface TranslationPreview {
  profile: {
    industry: string
    scale: string
    region: string
    interview_mode: TranslatorFormState['interview_mode']
  }
  draft_problems: DraftProblem[]
  hints: string[]
}

const HIGH_SIGNALS = ['必须', '合规', '监管', '停机', '事故', '审计', '验收不过', '罚款']

// 客户诉求原话 → 拟问题清单雏形：按句读切分（≤8 条），高危词触发 severity
// 预标（tentative=true 表示待人工确认）；module 一律 null=待认领。
export function buildTranslationPreview(state: TranslatorFormState): TranslationPreview {
  const vision = state.customer_vision.trim()
  const draftProblems: DraftProblem[] = []
  if (vision) {
    const segments = vision
      .split(/[。；;！!？?\n]+/)
      .map((part) => part.trim())
      .filter((part) => part.length > 0)
      .slice(0, 8)
    for (const segment of segments) {
      const hit = HIGH_SIGNALS.find((word) => segment.includes(word))
      draftProblems.push({
        text: segment,
        severity: hit ? 'high' : null,
        module: null,
        tentative: hit === undefined,
      })
    }
  }
  const hints: string[] = []
  if (!vision) hints.push('填写客户诉求原话后，右侧实时生成拟问题清单雏形。')
  if (draftProblems.length >= 8) hints.push('诉求较长，预览仅取前 8 条；正式翻译管道（P3）将全量结构化。')
  if (!state.phase_objective.trim()) hints.push('阶段目标为空：建议补齐，便于 AI 翻译管道对齐本期范围。')
  return {
    profile: {
      industry: state.industry.trim(),
      scale: state.scale.trim(),
      region: state.region.trim(),
      interview_mode: state.interview_mode,
    },
    draft_problems: draftProblems,
    hints,
  }
}
