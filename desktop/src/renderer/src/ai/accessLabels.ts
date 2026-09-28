export const aiAccessLabels: Record<string, string> = {
  disabled: "未开通 AI",
  assistant_read: "AI 只读助手",
  project_operator: "AI 项目操作员",
  project_manager: "AI 项目管理员",
  system_operator: "AI 系统管理员（完全权限）",
}

export const aiCapabilityLabels: Record<string, string> = {
  "project.read": "查看项目资料",
  "project.summarize": "总结项目资料",
  "file.search": "检索项目文件库",
  "memo.personal.write": "编辑个人笔记",
  "research.draft.generate": "生成调研草稿",
  "opportunity.draft.generate": "AI 机会识别与方案整理",
  "task.assigned.update": "更新自己的任务",
  "workbench.write": "通过 AI 执行工作台操作",
  "memo.shared.write": "编辑共享纪要",
  "task.batch_assign": "批量分配任务",
  "project.schedule.manage": "管理项目排期",
  "project.members.manage": "管理项目成员",
  "system.health": "查看系统运行情况",
  "system.logs": "查看系统日志",
  "system.release": "管理系统发布",
  "system.database.migrate": "管理数据库迁移",
  "system.dsh.switch": "管理 AI Server 服务",
}
