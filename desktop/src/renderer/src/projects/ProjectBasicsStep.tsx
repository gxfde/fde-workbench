export interface ProjectBasics {
  name: string
  clientName: string
  enterpriseIndustry: string
  enterpriseCode: string
  projectCode: string
  openfdeEngagement: string
  fdeopsWorkspace: string
  background: string
  notes: string
  plannedStartDate: string
  plannedEndDate: string
}

// r31 对外试用降摩擦（OWNER 裁决）：客户代号不再要求手填三段式，
// 拆成「客户名（手填）+ 行业（下拉，可留空）」——代号由两者拼装：
//   有行业 → `客户名·行业`；无行业 → 纯客户名。服务端已放宽（r31）。
export const ENTERPRISE_INDUSTRY_OPTIONS = [
  "制造业",
  "餐饮连锁",
  "零售连锁",
  "医疗器械",
  "教育培训",
  "物流供应链",
  "专业服务",
  "其他",
] as const

export const emptyProjectBasics: ProjectBasics = {
  name: "",
  clientName: "",
  enterpriseIndustry: "",
  enterpriseCode: "",
  projectCode: "",
  openfdeEngagement: "",
  fdeopsWorkspace: "",
  background: "",
  notes: "",
  plannedStartDate: "",
  plannedEndDate: "",
}

export function composeEnterpriseCode(clientName: string, industry: string): string {
  const trimmedName = clientName.trim()
  const trimmedIndustry = industry.trim()
  if (!trimmedName) return ""
  return trimmedIndustry ? `${trimmedName}·${trimmedIndustry}` : trimmedName
}

export function ProjectBasicsStep({
  value,
  onChange,
}: {
  value: ProjectBasics
  onChange(value: ProjectBasics): void
}) {
  return (
    <section className="panel wizard-panel" aria-labelledby="project-basics-title">
      <h2 id="project-basics-title">1. 基础信息</h2>
      <p className="supporting-copy">先确定项目和客户代号；联系人/电话/地址等实名信息不进本系统（A2 代号化），只在 fdeops/openfde 里维护。</p>
      <div className="wizard-form-grid">
        <Field label="项目名称" id="project-name" required>
          <input id="project-name" required maxLength={160} value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} />
        </Field>
        <Field label="客户名称" id="enterprise-name" required>
          <input
            id="enterprise-name"
            required
            maxLength={60}
            placeholder="例如：星河制造"
            value={value.clientName}
            onChange={(event) =>
              onChange({
                ...value,
                clientName: event.target.value,
                enterpriseCode: composeEnterpriseCode(event.target.value, value.enterpriseIndustry),
              })
            }
          />
          <small className="field-hint">客户名称即项目内的展示称呼；联系人/电话/地址等实名信息不进本系统（A2 代号化），只在 fdeops/openfde 里维护。</small>
        </Field>
        <Field label="所属行业" id="enterprise-industry">
          <select
            id="enterprise-industry"
            value={value.enterpriseIndustry}
            onChange={(event) =>
              onChange({
                ...value,
                enterpriseIndustry: event.target.value,
                enterpriseCode: composeEnterpriseCode(value.clientName, event.target.value),
              })
            }
          >
            <option value="">不选择（可跳过）</option>
            {ENTERPRISE_INDUSTRY_OPTIONS.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </Field>
        <Field label="项目编号" id="project-code">
          <input id="project-code" maxLength={40} value={value.projectCode} onChange={(event) => onChange({ ...value, projectCode: event.target.value })} />
        </Field>
        <Field label="openfde engagement（进阶）" id="openfde-engagement">
          <input id="openfde-engagement" maxLength={100} placeholder="可留空——知识轨 slug，可后补" value={value.openfdeEngagement} onChange={(event) => onChange({ ...value, openfdeEngagement: event.target.value })} />
        </Field>
        <Field label="fdeops 工作区（进阶）" id="fdeops-workspace">
          <input id="fdeops-workspace" maxLength={160} placeholder="可留空——流程轨目录名，可后补" value={value.fdeopsWorkspace} onChange={(event) => onChange({ ...value, fdeopsWorkspace: event.target.value })} />
        </Field>
        <Field label="计划开始日期" id="planned-start-date" required>
          <input id="planned-start-date" required type="date" value={value.plannedStartDate} onChange={(event) => onChange({ ...value, plannedStartDate: event.target.value })} />
        </Field>
        <Field label="计划结束日期" id="planned-end-date">
          <input id="planned-end-date" type="date" min={value.plannedStartDate || undefined} value={value.plannedEndDate} onChange={(event) => onChange({ ...value, plannedEndDate: event.target.value })} />
        </Field>
        <Field label="项目背景" id="project-background" wide>
          <textarea id="project-background" rows={3} value={value.background} onChange={(event) => onChange({ ...value, background: event.target.value })} />
        </Field>
        <Field label="备注" id="project-notes" wide>
          <textarea id="project-notes" rows={3} value={value.notes} onChange={(event) => onChange({ ...value, notes: event.target.value })} />
        </Field>
      </div>
    </section>
  )
}

function Field({
  id,
  label,
  required = false,
  wide = false,
  children,
}: {
  id: string
  label: string
  required?: boolean
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`field${wide ? " wide-field" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  )
}
