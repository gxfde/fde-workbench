// V3.2 G2 模拟训练场 · 场景编辑器。
//
// 表单覆盖 G2 要求的案例配置面：客户背景、初始简报、已知系统、约束、隐藏事实
// （含披露阶段）、误导性诉求、预期结果、验收标准与 Rubric 三桶、标签与分类。
//
// 纪律：**参考答案侧字段（预期结果/验收标准/Rubric）标为「评分侧」**——提醒
// 运营者这些字段只进 Judge View，不会暴露给被测方。

import { useState, type ReactElement } from "react"

import { ApiClientError } from "../api/client"
import { AsyncButton, Modal, UiButton } from "../components/ui"
import type { ScenarioWritePayload } from "./api"
import {
  SCENARIO_SPLITS,
  SCENARIO_VARIANTS,
  SPLIT_LABEL,
  VARIANT_LABEL,
  type ScenarioDto,
} from "./types"

const DISCLOSURE_STAGES = [
  { value: "setup", label: "开场即披露" },
  { value: "interview", label: "访谈中披露" },
  { value: "analysis", label: "分析阶段披露" },
  { value: "design", label: "方案阶段披露" },
  { value: "implementation", label: "实施阶段披露" },
  { value: "late", label: "后期才披露" },
]

interface FactDraft {
  fact_id: string
  text: string
  disclosure_stage: string
  probe_keywords: string
}

function lines(value: string | undefined): string[] {
  if (!value) return []
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
}

function errorText(caught: unknown): string {
  if (caught instanceof ApiClientError) {
    const details = caught.details as { errors?: string[] } | undefined
    if (details?.errors?.length) return `${caught.message}（${details.errors.join("、")}）`
    return caught.message
  }
  if (caught instanceof Error) return caught.message
  return "保存失败，请稍后重试。"
}

export function ScenarioEditor({
  scenario,
  onSubmit,
  onCancel,
}: {
  scenario: ScenarioDto | null
  onSubmit(payload: ScenarioWritePayload): Promise<void>
  onCancel(): void
}): ReactElement {
  const content = scenario?.content ?? {}
  const visible = content.visible ?? {}
  const constraints = visible.constraints ?? {}
  const reference = scenario?.reference ?? {}

  const [name, setName] = useState(scenario?.name ?? "")
  const [industry, setIndustry] = useState(scenario?.industry ?? "")
  const [variant, setVariant] = useState(scenario?.variant ?? "normal")
  const [split, setSplit] = useState(scenario?.split ?? "train")
  const [tags, setTags] = useState((scenario?.tags ?? []).join("、"))
  const [brief, setBrief] = useState(lines(visible.initial_brief?.join("\n")).join("\n"))
  const [knownSystems, setKnownSystems] = useState(
    lines(visible.known_systems?.join("\n")).join("\n"),
  )
  const [budget, setBudget] = useState(String(constraints.budget ?? ""))
  const [timeline, setTimeline] = useState(String(constraints.timeline ?? ""))
  const [misleading, setMisleading] = useState(content.misleading_request ?? "")
  const [facts, setFacts] = useState<FactDraft[]>(
    (content.hidden?.facts ?? []).map((fact) => ({
      fact_id: fact.fact_id,
      text: fact.text,
      disclosure_stage: fact.disclosure_stage,
      probe_keywords: (fact.probe_keywords ?? []).join("、"),
    })),
  )
  const [outcomes, setOutcomes] = useState(
    lines(reference.expected_outcomes?.join("\n")).join("\n"),
  )
  const [criteria, setCriteria] = useState(
    lines(reference.acceptance_criteria?.join("\n")).join("\n"),
  )
  const [mustIdentify, setMustIdentify] = useState(
    lines(reference.rubric?.must_identify?.join("\n")).join("\n"),
  )
  const [mustAvoid, setMustAvoid] = useState(
    lines(reference.rubric?.must_avoid?.join("\n")).join("\n"),
  )
  const [mustProduce, setMustProduce] = useState(
    lines(reference.rubric?.must_produce?.join("\n")).join("\n"),
  )
  const [error, setError] = useState("")

  function updateFact(index: number, patch: Partial<FactDraft>): void {
    setFacts((current) =>
      current.map((fact, position) => (position === index ? { ...fact, ...patch } : fact)),
    )
  }

  async function submit(): Promise<void> {
    setError("")
    try {
      await onSubmit({
        name: name.trim(),
        industry: industry.trim(),
        variant,
        split,
        tags: lines(tags.replace(/、/g, "\n")),
        content: {
          ...content,
          case_code: scenario?.scenario_key,
          customer_profile: content.customer_profile ?? {},
          visible: {
            ...visible,
            initial_brief: lines(brief),
            known_systems: lines(knownSystems),
            constraints: { ...constraints, budget, timeline },
          },
          hidden: {
            facts: facts.map((fact) => ({
              fact_id: fact.fact_id.trim(),
              text: fact.text.trim(),
              disclosure_stage: fact.disclosure_stage,
              probe_keywords: lines(fact.probe_keywords.replace(/、/g, "\n")),
            })),
          },
          misleading_request: misleading.trim(),
        },
        reference: {
          ...reference,
          expected_outcomes: lines(outcomes),
          acceptance_criteria: lines(criteria),
          rubric: {
            must_identify: lines(mustIdentify),
            must_avoid: lines(mustAvoid),
            must_produce: lines(mustProduce),
          },
        },
      })
    } catch (caught) {
      setError(errorText(caught))
    }
  }

  return (
    <Modal
      title={scenario ? `编辑场景 · ${scenario.scenario_key}` : "新建场景"}
      description="编辑会追加新版本，历史版本保持不可变。"
      onClose={onCancel}
      footer={
        <>
          <UiButton onClick={onCancel}>取消</UiButton>
          <AsyncButton
            variant="primary"
            actionKey="scenario-save"
            onRun={async () => {
              await submit()
            }}
          >
            保存
          </AsyncButton>
        </>
      }
    >
      {error ? (
        <p className="simulation-error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="simulation-form">
        <label>
          <span>案例名称</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>行业分类</span>
          <input value={industry} onChange={(event) => setIndustry(event.target.value)} />
        </label>
        <label>
          <span>客户行为</span>
          <select
            value={variant}
            onChange={(event) => setVariant(event.target.value as typeof variant)}
          >
            {SCENARIO_VARIANTS.map((value) => (
              <option key={value} value={value}>
                {VARIANT_LABEL[value]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>数据集</span>
          <select
            value={split}
            onChange={(event) => setSplit(event.target.value as typeof split)}
          >
            {SCENARIO_SPLITS.map((value) => (
              <option key={value} value={value}>
                {SPLIT_LABEL[value]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>标签（顿号或换行分隔）</span>
          <input value={tags} onChange={(event) => setTags(event.target.value)} />
        </label>
        <label>
          <span>客户初始简报（每行一条）</span>
          <textarea value={brief} onChange={(event) => setBrief(event.target.value)} rows={3} />
        </label>
        <label>
          <span>客户自述的已知系统（每行一条）</span>
          <textarea
            value={knownSystems}
            onChange={(event) => setKnownSystems(event.target.value)}
            rows={2}
          />
        </label>
        <label>
          <span>预算约束</span>
          <input value={budget} onChange={(event) => setBudget(event.target.value)} />
        </label>
        <label>
          <span>工期约束</span>
          <input value={timeline} onChange={(event) => setTimeline(event.target.value)} />
        </label>
        <label>
          <span>客户初始诉求（通常是误导面）</span>
          <textarea
            value={misleading}
            onChange={(event) => setMisleading(event.target.value)}
            rows={2}
          />
        </label>
      </div>

      <section aria-label="隐藏事实">
        <h3>隐藏事实（按条件逐步披露）</h3>
        <ul className="simulation-fact-list">
          {facts.map((fact, index) => (
            <li key={`${fact.fact_id}-${index}`}>
              <div className="simulation-form">
                <label>
                  <span>事实编号</span>
                  <input
                    value={fact.fact_id}
                    onChange={(event) => updateFact(index, { fact_id: event.target.value })}
                  />
                </label>
                <label>
                  <span>披露阶段</span>
                  <select
                    value={fact.disclosure_stage}
                    onChange={(event) =>
                      updateFact(index, { disclosure_stage: event.target.value })
                    }
                  >
                    {DISCLOSURE_STAGES.map((stage) => (
                      <option key={stage.value} value={stage.value}>
                        {stage.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>事实内容</span>
                  <textarea
                    value={fact.text}
                    onChange={(event) => updateFact(index, { text: event.target.value })}
                    rows={2}
                  />
                </label>
                <label>
                  <span>探针关键词（顿号或换行分隔）</span>
                  <input
                    value={fact.probe_keywords}
                    onChange={(event) => updateFact(index, { probe_keywords: event.target.value })}
                  />
                </label>
              </div>
              <UiButton
                compact
                variant="danger"
                onClick={() => setFacts((current) => current.filter((_, i) => i !== index))}
              >
                删除该事实
              </UiButton>
            </li>
          ))}
        </ul>
        <UiButton
          onClick={() =>
            setFacts((current) => [
              ...current,
              {
                fact_id: `F-${current.length + 1}`,
                text: "",
                disclosure_stage: "interview",
                probe_keywords: "",
              },
            ])
          }
        >
          新增隐藏事实
        </UiButton>
      </section>

      <section aria-label="评分侧">
        <h3>评分侧（仅 Judge View 可见，不暴露给被测方）</h3>
        <div className="simulation-form">
          <label>
            <span>预期结果（每行一条）</span>
            <textarea value={outcomes} onChange={(event) => setOutcomes(event.target.value)} rows={3} />
          </label>
          <label>
            <span>验收标准（每行一条）</span>
            <textarea
              value={criteria}
              onChange={(event) => setCriteria(event.target.value)}
              rows={3}
            />
          </label>
          <label>
            <span>Rubric · 必须识别</span>
            <textarea
              value={mustIdentify}
              onChange={(event) => setMustIdentify(event.target.value)}
              rows={2}
            />
          </label>
          <label>
            <span>Rubric · 必须避免</span>
            <textarea
              value={mustAvoid}
              onChange={(event) => setMustAvoid(event.target.value)}
              rows={2}
            />
          </label>
          <label>
            <span>Rubric · 必须产出</span>
            <textarea
              value={mustProduce}
              onChange={(event) => setMustProduce(event.target.value)}
              rows={2}
            />
          </label>
        </div>
      </section>
    </Modal>
  )
}
