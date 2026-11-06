import { ApiClientError } from "../api/client"

/**
 * S2 / F4：统一错误码 → 中文文案表。
 *
 * 目的是让同一个错误在任意页面得到同一句解释。表只收录**跨页复用**的错误码
 * （实测：`forbidden` 20 处、`stale_version` 10 处、`authentication_refreshed_resubmit`
 * 6 处、`stale_session_response` 5 处、`project_not_found` 4 处等）；
 * 各页的**业务专属**错误码仍留在本地函数里，避免一张表变成大杂烩。
 *
 * 用法：`errorMessage(error, "模块操作失败，请稍后重试。")`——第二个参数是
 * 该页的兜底文案，语义仍由页面决定，只是公共部分统一。
 */

/** 跨页复用的公共错误码 → 文案。 */
const COMMON_ERROR_MESSAGES: Record<string, string> = {
  forbidden: "当前账号无权执行此操作。",
  stale_version: "内容已被其他操作更新；本地状态未改变，请刷新后重试。",
  authentication_refreshed_resubmit: "登录状态已刷新，请重新提交本次操作。",
  stale_session_response: "会话已更新，请重新提交本次操作。",
  network_error: "网络连接异常，请检查网络后重试。",
  request_timeout: "请求超时，请稍后重试。",
  invalid_credentials: "账号或密码不正确。",
  password_too_weak: "密码强度不足，请按提示重新设置。",
  project_not_found: "项目不存在或已被删除。",
  document_not_found: "文档不存在或已被删除。",
  file_not_available: "该版本当前不可下载。",
  preview_not_available: "该内容暂不支持预览。",
  invalid_task_member: "所选成员不在该项目成员列表中。",
  invalid_task_assignment: "任务指派不符合当前项目规则。",
}

/** 取出服务端错误码；非 ApiClientError 一律视为未知错误。 */
export function errorCodeOf(error: unknown): string | null {
  return error instanceof ApiClientError ? error.code : null
}

/**
 * 统一错误文案入口。
 *
 * @param error 服务端抛出的错误
 * @param fallback 该页面的兜底文案（语义由页面决定）
 */
export function errorMessage(error: unknown, fallback: string): string {
  const code = errorCodeOf(error)
  if (code) {
    const common = COMMON_ERROR_MESSAGES[code]
    if (common) return common
    // 未收录的业务专属错误码：保留页面自己的兜底文案，避免把服务端原文
    // （可能是英文技术信息）直接暴露给用户。
    return fallback
  }
  return fallback
}

/**
 * 页面**已有专属措辞**时的安全入口：页面本地已给出更具体的文案就保留它，
 * 只有页面没给（fallback 为空）才查公共表。
 *
 * 用于「通用措辞会丢掉页面上下文」的场景，例如 stale_version：
 * 模块页要说明「已保留当前表单」，模板页要说明「本地状态未改变」。
 */
export function errorMessageWithLocal(error: unknown, local: string): string {
  return local.trim() ? local : errorMessage(error, "")
}

/** 该错误码是否命中公共表（供页面判断是否走统一文案）。 */
export function hasCommonErrorMessage(error: unknown): boolean {
  const code = errorCodeOf(error)
  return code !== null && code in COMMON_ERROR_MESSAGES
}

/**
 * 只查公共表，不回退到页面兜底——供「本页已有专属映射表」的页面使用：
 * 命中则用统一文案，未命中返回空串，由页面自己的映射表决定。
 */
export function commonErrorMessage(error: unknown, fallback: string): string {
  const code = errorCodeOf(error)
  if (!code) return fallback
  return COMMON_ERROR_MESSAGES[code] ?? fallback
}
