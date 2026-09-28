export interface ProjectBasics {
  name: string
  enterpriseName: string
  projectCode: string
  contactName: string
  contactPhone: string
  address: string
  background: string
  notes: string
  plannedStartDate: string
  plannedEndDate: string
}

export const emptyProjectBasics: ProjectBasics = {
  name: "",
  enterpriseName: "",
  projectCode: "",
  contactName: "",
  contactPhone: "",
  address: "",
  background: "",
  notes: "",
  plannedStartDate: "",
  plannedEndDate: "",
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
      <p className="supporting-copy">先确定项目、企业和起始日期；其他资料可现在补齐，也可稍后在项目中维护。</p>
      <div className="wizard-form-grid">
        <Field label="项目名称" id="project-name" required>
          <input id="project-name" required maxLength={160} value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} />
        </Field>
        <Field label="企业名称" id="enterprise-name" required>
          <input id="enterprise-name" required maxLength={160} value={value.enterpriseName} onChange={(event) => onChange({ ...value, enterpriseName: event.target.value })} />
        </Field>
        <Field label="项目编号" id="project-code">
          <input id="project-code" maxLength={40} value={value.projectCode} onChange={(event) => onChange({ ...value, projectCode: event.target.value })} />
        </Field>
        <Field label="联系人" id="contact-name">
          <input id="contact-name" maxLength={120} value={value.contactName} onChange={(event) => onChange({ ...value, contactName: event.target.value })} />
        </Field>
        <Field label="联系电话" id="contact-phone">
          <input id="contact-phone" maxLength={60} value={value.contactPhone} onChange={(event) => onChange({ ...value, contactPhone: event.target.value })} />
        </Field>
        <Field label="企业地址" id="enterprise-address">
          <input id="enterprise-address" maxLength={255} value={value.address} onChange={(event) => onChange({ ...value, address: event.target.value })} />
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
