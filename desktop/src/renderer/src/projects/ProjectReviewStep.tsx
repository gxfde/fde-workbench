import type { TemplateVersionDto, WorkbenchUserDto } from "../workbench/types"
import type { ProjectBasics } from "./ProjectBasicsStep"

export function ProjectReviewStep({
  basics,
  template,
  leader,
  selectedModuleKeys,
}: {
  basics: ProjectBasics
  template: TemplateVersionDto
  leader: WorkbenchUserDto
  selectedModuleKeys: string[]
}) {
  const modules = template.modules.filter((module) => selectedModuleKeys.includes(module.module_key))
  const tasks = modules.flatMap((module) => module.tasks)
  return (
    <section className="panel wizard-panel" aria-labelledby="project-review-title">
      <h2 id="project-review-title">4. 确认创建</h2>
      <p className="supporting-copy">创建后将按模板快照原子生成首期模块、任务与排期。</p>
      <div className="review-grid" role="region" aria-label="创建摘要">
        <ReviewItem label="项目" value={basics.name} />
        <ReviewItem label="企业" value={basics.enterpriseName} />
        <ReviewItem label="模板版本" value={`${template.template_name} v${template.version_number}`} />
        <ReviewItem label="负责人" value={leader.display_name} />
        <ReviewItem label="首期模块" value={modules.map((module) => module.name).join("、")} wide />
        <ReviewItem label="初始任务" value={tasks.map((task) => task.name).join("、")} wide />
        <ReviewItem label="计划日期" value={`${basics.plannedStartDate} 至 ${basics.plannedEndDate || "按任务自动排期"}`} wide />
      </div>
    </section>
  )
}

function ReviewItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <div className={wide ? "wide-review" : undefined}><span>{label}</span><strong>{value || "—"}</strong></div>
}
