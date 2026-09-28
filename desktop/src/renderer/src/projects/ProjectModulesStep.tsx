import type { TemplateVersionDto } from "../workbench/types"

export function ProjectModulesStep({
  template,
  selectedModuleKeys,
  dependencyNotice,
  onToggle,
}: {
  template: TemplateVersionDto
  selectedModuleKeys: string[]
  dependencyNotice: string
  onToggle(moduleKey: string, selected: boolean): void
}) {
  return (
    <section className="panel wizard-panel" aria-labelledby="project-modules-title">
      <h2 id="project-modules-title">3. 选择首期模块</h2>
      <p className="supporting-copy">至少选择一个模块。这里只确定首期范围，后续可追加模块。</p>
      {dependencyNotice ? <p className="dependency-notice" role="status">{dependencyNotice}</p> : null}
      <div className="module-choice-list">
        {template.modules.map((module) => (
          <label key={module.module_key} className={`module-choice${selectedModuleKeys.includes(module.module_key) ? " selected" : ""}`}>
            <input
              type="checkbox"
              aria-label={module.name}
              checked={selectedModuleKeys.includes(module.module_key)}
              onChange={(event) => onToggle(module.module_key, event.target.checked)}
            />
            <span>
              <strong>{module.name}</strong>
              <small>{module.description || "无说明"}</small>
              <em>{module.tasks.length} 项任务</em>
            </span>
          </label>
        ))}
      </div>
    </section>
  )
}
