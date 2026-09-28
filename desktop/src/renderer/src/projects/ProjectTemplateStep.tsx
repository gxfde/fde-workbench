import type { TemplateVersionDto, WorkbenchUserDto } from "../workbench/types"

export function ProjectTemplateStep({
  templates,
  template,
  templateVersionId,
  leaders,
  leaderUserId,
  loading,
  error,
  leaderLocked,
  onTemplateChange,
  onLeaderChange,
}: {
  templates: TemplateVersionDto[]
  template: TemplateVersionDto | null
  templateVersionId: string
  leaders: WorkbenchUserDto[]
  leaderUserId: string
  loading: boolean
  error: string
  leaderLocked: boolean
  onTemplateChange(versionId: string): void
  onLeaderChange(userId: string): void
}) {
  return (
    <section className="panel wizard-panel" aria-labelledby="project-template-title">
      <h2 id="project-template-title">2. 模板与负责人</h2>
      <p className="supporting-copy">仅可使用当前有效的已发布版本；版本会随项目快照保留。</p>
      {loading ? <p role="status">正在加载模板与负责人…</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="template-choice-grid">
        <div className="field">
          <label htmlFor="template-version">行业模板版本</label>
          <select id="template-version" value={templateVersionId} disabled={loading || templates.length === 0} onChange={(event) => onTemplateChange(event.target.value)}>
            {templates.length === 0 ? <option value="">暂无可用模板</option> : null}
            {templates.map((item) => <option key={item.version_id} value={item.version_id}>{item.template_name} v{item.version_number}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="project-leader-choice">项目负责人</label>
          <select id="project-leader-choice" value={leaderUserId} disabled={loading || leaderLocked} onChange={(event) => onLeaderChange(event.target.value)}>
            <option value="">请选择负责人</option>
            {leaders.map((leader) => <option key={leader.id} value={leader.id}>{leader.display_name}</option>)}
          </select>
          {leaderLocked ? <span className="field-hint">项目负责人账号创建项目时固定为本人。</span> : null}
        </div>
      </div>
      {template ? (
        <div className="template-preview">
          <div><span>行业</span><strong>{template.industry_name}</strong></div>
          <div><span>模块</span><strong>{template.modules.length} 个</strong></div>
          <div><span>任务</span><strong>{template.modules.reduce((total, module) => total + module.tasks.length, 0)} 项</strong></div>
          <p>{template.description || "无模板说明"}</p>
        </div>
      ) : null}
    </section>
  )
}
