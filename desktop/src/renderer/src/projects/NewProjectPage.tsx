import { useEffect, useMemo, useRef, useState } from "react"

import { ApiClientError } from "../api/client"
import { useAuth } from "../auth/AuthProvider"
import { fetchAllPages } from "../workbench/fetchAllPages"
import {
  isProjectDto,
  isTemplateVersionDto,
  isWorkbenchUserDto,
} from "../workbench/runtimeValidation"
import type {
  TemplateVersionDto,
  WorkbenchUserDto,
} from "../workbench/types"
import {
  emptyProjectBasics,
  ProjectBasicsStep,
  type ProjectBasics,
} from "./ProjectBasicsStep"
import { ProjectModulesStep } from "./ProjectModulesStep"
import { ProjectReviewStep } from "./ProjectReviewStep"
import { ProjectTemplateStep } from "./ProjectTemplateStep"

type WizardStep = 1 | 2 | 3 | 4

export function NewProjectPage() {
  const { apiRequest, user } = useAuth()
  const [step, setStep] = useState<WizardStep>(1)
  const [basics, setBasics] = useState<ProjectBasics>(emptyProjectBasics)
  const [templates, setTemplates] = useState<TemplateVersionDto[]>([])
  const [templateVersionId, setTemplateVersionId] = useState("")
  const [template, setTemplate] = useState<TemplateVersionDto | null>(null)
  const [leaders, setLeaders] = useState<WorkbenchUserDto[]>([])
  const [leaderUserId, setLeaderUserId] = useState("")
  const [selectedModuleKeys, setSelectedModuleKeys] = useState<string[]>([])
  const [dependencyNotice, setDependencyNotice] = useState("")
  const [resourcesLoading, setResourcesLoading] = useState(true)
  const [templateLoading, setTemplateLoading] = useState(false)
  const [resourceError, setResourceError] = useState("")
  const [stepError, setStepError] = useState("")
  const [submitError, setSubmitError] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const detailSequence = useRef(0)
  const lifecycleGeneration = useRef(0)
  const submittingRef = useRef(false)
  const sessionIdentity = `${user?.id ?? ""}:${user?.role ?? ""}`
  const sessionIdentityRef = useRef(sessionIdentity)
  sessionIdentityRef.current = sessionIdentity

  useEffect(() => {
    const generation = ++lifecycleGeneration.current
    submittingRef.current = false
    setSubmitting(false)
    return () => {
      if (lifecycleGeneration.current === generation) lifecycleGeneration.current += 1
    }
  }, [sessionIdentity])

  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    let active = true
    setResourcesLoading(true)
    setResourceError("")
    void Promise.all([
      listPublishedTemplates(apiRequest, controller.signal),
      listEligibleLeaders(apiRequest, user, controller.signal),
    ])
      .then(([publishedTemplates, eligibleLeaders]) => {
        if (!active) return
        setTemplates(publishedTemplates)
        setLeaders(eligibleLeaders)
        setTemplateVersionId((current) => (
          publishedTemplates.some((item) => item.version_id === current)
            ? current
            : publishedTemplates[0]?.version_id ?? ""
        ))
        setLeaderUserId((current) => {
          if (user.role === "project_lead") return user.id
          if (eligibleLeaders.some((leader) => leader.id === current)) return current
          if (eligibleLeaders.some((leader) => leader.id === user.id)) return user.id
          return ""
        })
      })
      .catch((caught) => {
        if (active) setResourceError(resourceLoadError(caught))
      })
      .finally(() => {
        if (active) setResourcesLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [apiRequest, user?.id, user?.role])

  useEffect(() => {
    if (!templateVersionId) {
      setTemplate(null)
      return
    }
    let active = true
    const sequence = ++detailSequence.current
    setTemplateLoading(true)
    setResourceError("")
    void apiRequest<unknown>(
      `/api/v1/industry-templates/versions/${encodeURIComponent(templateVersionId)}`,
      { method: "GET" },
    )
      .then((detail) => {
        if (!active || sequence !== detailSequence.current) return
        if (!isTemplateVersionDto(detail) || detail.status !== "published") {
          setTemplate(null)
          setResourceError("所选模板版本已不可用，请重新选择。")
          return
        }
        setTemplate(detail)
      })
      .catch((caught) => {
        if (!active || sequence !== detailSequence.current) return
        setTemplate(null)
        setResourceError(resourceLoadError(caught))
      })
      .finally(() => {
        if (active && sequence === detailSequence.current) setTemplateLoading(false)
      })
    return () => {
      active = false
    }
  }, [apiRequest, templateVersionId, user?.id])

  const leader = useMemo(
    () => leaders.find((item) => item.id === leaderUserId) ?? null,
    [leaderUserId, leaders],
  )

  function changeTemplate(versionId: string): void {
    if (versionId === templateVersionId) return
    setTemplateVersionId(versionId)
    setTemplate(null)
    setSelectedModuleKeys([])
    setDependencyNotice("")
    setStepError("")
  }

  function nextStep(): void {
    setStepError("")
    setSubmitError("")
    if (step === 1) {
      if (!basics.name.trim() || !basics.enterpriseName.trim() || !basics.plannedStartDate) {
        setStepError("请填写项目名称、企业名称和计划开始日期。")
        return
      }
      if (basics.plannedEndDate && basics.plannedEndDate < basics.plannedStartDate) {
        setStepError("计划结束日期不能早于开始日期。")
        return
      }
      setStep(2)
      return
    }
    if (step === 2) {
      if (resourcesLoading || templateLoading) {
        setStepError("正在加载模板详情，请稍候。")
        return
      }
      if (resourceError || !template || template.version_id !== templateVersionId || !leader) {
        setStepError("请选择可用的已发布模板版本和项目负责人。")
        return
      }
      setStep(3)
      return
    }
    if (step === 3) {
      if (selectedModuleKeys.length === 0) {
        setStepError("请至少选择一个首期模块。")
        return
      }
      setStep(4)
    }
  }

  function previousStep(): void {
    setStepError("")
    setSubmitError("")
    setStep((current) => current === 4 ? 3 : current === 3 ? 2 : 1)
  }

  function toggleModule(moduleKey: string, selected: boolean): void {
    if (!template) return
    setStepError("")
    if (selected) {
      const initial = new Set([...selectedModuleKeys, moduleKey])
      const closed = dependencyClosure(template, initial)
      const added = template.modules.filter((module) => closed.has(module.module_key) && !initial.has(module.module_key))
      const selectedModule = template.modules.find((module) => module.module_key === moduleKey)
      setSelectedModuleKeys(orderedModuleKeys(template, closed))
      setDependencyNotice(added.length > 0
        ? `${selectedModule?.name ?? moduleKey} 需要前置模块“${added.map((module) => module.name).join("、")}”，已自动选择。`
        : "")
      return
    }
    const withoutTarget = new Set(selectedModuleKeys.filter((key) => key !== moduleKey))
    const closed = dependencyClosure(template, withoutTarget)
    if (closed.has(moduleKey)) {
      const module = template.modules.find((item) => item.module_key === moduleKey)
      setDependencyNotice(`${module?.name ?? moduleKey} 是已选模块的前置，不能移除。`)
      return
    }
    setSelectedModuleKeys(orderedModuleKeys(template, closed))
    setDependencyNotice("")
  }

  async function createProject(): Promise<void> {
    if (submittingRef.current || !template || !leader || selectedModuleKeys.length === 0) return
    const submittedSession = sessionIdentityRef.current
    const submittedGeneration = lifecycleGeneration.current
    submittingRef.current = true
    setSubmitError("")
    setSubmitting(true)
    try {
      const created = await apiRequest<unknown>("/api/v1/projects", {
        method: "POST",
        body: {
          name: basics.name.trim(),
          enterprise_name: basics.enterpriseName.trim(),
          contact_name: basics.contactName.trim(),
          contact_phone: basics.contactPhone.trim(),
          address: basics.address.trim(),
          background: basics.background.trim(),
          notes: basics.notes.trim(),
          project_code: basics.projectCode.trim(),
          planned_start_date: basics.plannedStartDate,
          planned_end_date: basics.plannedEndDate || null,
          template_version_id: template.version_id,
          leader_user_id: leader.id,
          module_keys: orderedModuleKeys(template, new Set(selectedModuleKeys)),
        },
      })
      if (submittedGeneration !== lifecycleGeneration.current || submittedSession !== sessionIdentityRef.current) return
      if (!isProjectDto(created)) throw new ApiClientError({
        code: "invalid_api_response",
        message: "The created project response is invalid.",
      })
      window.location.hash = `#projects/${encodeURIComponent(created.id)}`
    } catch (caught) {
      if (submittedGeneration === lifecycleGeneration.current && submittedSession === sessionIdentityRef.current) {
        setSubmitError(projectCreateError(caught))
      }
    } finally {
      if (submittedGeneration === lifecycleGeneration.current && submittedSession === sessionIdentityRef.current) {
        submittingRef.current = false
        setSubmitting(false)
      }
    }
  }

  return (
    <div id="new-project" className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">项目管理</p>
          <h1>新建项目</h1>
          <p className="supporting-copy">四步确定企业资料、模板快照、负责人和首期交付范围。</p>
        </div>
        <a className="secondary-button button-link" href="#projects">返回项目列表</a>
      </header>

      <ol className="wizard-progress" aria-label="项目创建进度">
        {["基础信息", "模板与负责人", "首期模块", "确认创建"].map((label, index) => (
          <li key={label} className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""}><span>{index + 1}</span>{label}</li>
        ))}
      </ol>

      {step === 1 ? <ProjectBasicsStep value={basics} onChange={setBasics} /> : null}
      {step === 2 ? <ProjectTemplateStep
        templates={templates}
        template={template}
        templateVersionId={templateVersionId}
        leaders={leaders}
        leaderUserId={leaderUserId}
        loading={resourcesLoading || templateLoading}
        error={resourceError}
        leaderLocked={user?.role === "project_lead"}
        onTemplateChange={changeTemplate}
        onLeaderChange={setLeaderUserId}
      /> : null}
      {step === 3 && template ? <ProjectModulesStep
        template={template}
        selectedModuleKeys={selectedModuleKeys}
        dependencyNotice={dependencyNotice}
        onToggle={toggleModule}
      /> : null}
      {step === 4 && template && leader ? <ProjectReviewStep
        basics={basics}
        template={template}
        leader={leader}
        selectedModuleKeys={selectedModuleKeys}
      /> : null}

      {stepError ? <p className="form-error banner" role="alert">{stepError}</p> : null}
      {submitError ? <p className="form-error banner" role="alert">{submitError}</p> : null}
      <div className="wizard-actions">
        {step > 1 ? <button className="secondary-button" type="button" disabled={submitting} onClick={previousStep}>上一步</button> : <span />}
        {step < 4 ? <button className="primary-button" type="button" onClick={nextStep}>下一步</button> : (
          <button className="primary-button" type="button" disabled={submitting} onClick={() => void createProject()}>{submitting ? "正在创建…" : "创建项目"}</button>
        )}
      </div>
    </div>
  )
}

async function listPublishedTemplates(
  apiRequest: Parameters<typeof fetchAllPages<TemplateVersionDto>>[0]["apiRequest"],
  signal: AbortSignal,
): Promise<TemplateVersionDto[]> {
  const all = await fetchAllPages({
    apiRequest,
    pathForPage: (page, pageSize) => `/api/v1/industry-templates?page=${page}&page_size=${pageSize}`,
    itemKey: (item: TemplateVersionDto) => item.version_id,
    validateItem: isTemplateVersionDto,
    signal,
  })
  return all
    .filter((item) => item.status === "published")
    .sort((left, right) => {
      const publishedOrder = (right.published_at ?? "").localeCompare(left.published_at ?? "")
      if (publishedOrder !== 0) return publishedOrder
      const versionOrder = right.version_number - left.version_number
      return versionOrder || left.template_name.localeCompare(right.template_name, "zh-CN")
    })
}

export async function listEligibleLeaders(
  apiRequest: Parameters<typeof fetchAllPages<WorkbenchUserDto>>[0]["apiRequest"],
  user: NonNullable<ReturnType<typeof useAuth>["user"]>,
  signal: AbortSignal,
): Promise<WorkbenchUserDto[]> {
  if (user.role === "project_lead") {
    return [{
      id: user.id,
      username: user.username,
      display_name: user.displayName,
      role: user.role,
      is_active: user.isActive,
      must_change_password: user.mustChangePassword,
      created_at: "",
      updated_at: "",
    }]
  }
  const roles = ["admin", "project_lead"] as const
  const pages = await Promise.all(roles.map((role) => fetchAllPages({
    apiRequest,
    pathForPage: (page, pageSize) => `/api/v1/users?role=${role}&active=true&page=${page}&page_size=${pageSize}`,
    itemKey: (item: WorkbenchUserDto) => item.id,
    validateItem: isWorkbenchUserDto,
    signal,
  })))
  const leaders = new Map<string, WorkbenchUserDto>()
  for (const rolePage of pages) {
    for (const leader of rolePage) {
      if (leader.is_active && (leader.role === "admin" || leader.role === "project_lead")) leaders.set(leader.id, leader)
    }
  }
  return [...leaders.values()].sort((left, right) => left.display_name.localeCompare(right.display_name, "zh-CN"))
}

export function dependencyClosure(template: TemplateVersionDto, initial: Set<string>): Set<string> {
  const closed = new Set(initial)
  const taskModule = new Map<string, string>()
  for (const module of template.modules) {
    for (const task of module.tasks) taskModule.set(task.task_key, module.module_key)
  }
  let changed = true
  while (changed) {
    changed = false
    for (const module of template.modules) {
      if (!closed.has(module.module_key)) continue
      for (const task of module.tasks) {
        for (const dependencyKey of task.dependency_keys) {
          const requiredModule = taskModule.get(dependencyKey)
          if (requiredModule && !closed.has(requiredModule)) {
            closed.add(requiredModule)
            changed = true
          }
        }
      }
    }
  }
  return closed
}

export function orderedModuleKeys(template: TemplateVersionDto, keys: Set<string>): string[] {
  return template.modules.filter((module) => keys.has(module.module_key)).map((module) => module.module_key)
}

function resourceLoadError(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") return ""
  if (error instanceof ApiClientError && error.code === "incomplete_pagination") return "模板或负责人分页数据不完整，请重试。"
  if (error instanceof ApiClientError && error.code === "stale_session_response") return "登录会话已更改，请重新进入新建项目。"
  return "模板或负责人加载失败，请稍后重试。"
}

function projectCreateError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "authentication_refreshed_resubmit") return "登录状态已刷新，全部输入已保留，请重新提交。"
  if (error instanceof ApiClientError && error.code === "missing_required_module_dependency") return "所选模块缺少必要前置，全部输入已保留。"
  if (error instanceof ApiClientError && error.code === "template_version_not_published") return "模板版本已不可用，全部输入已保留，请返回选择。"
  return "项目创建失败，全部输入已保留，请稍后重试。"
}
