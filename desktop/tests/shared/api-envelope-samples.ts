// QR-112（goal-crv-fix2 批 R7）等价性静态钉样本：**响应面**信封判定。
// 双桥（main/api-ipc.ts::parseApiResponse / renderer/src/fde-web-bridge.ts）
// 消费 shared/api-safety.ts::parseApiEnvelope 同一判定——本清单逐样本钉死
// 四条不变量（ok∧error 拒／!ok∧¬error 拒／!ok data 置空／错误体形态校验）。
export interface ApiSafetyEnvelopeSample {
  payload: unknown
  status: number
  /** 双桥统一期望判定：shared parseApiEnvelope 的 kind / invalid reason。 */
  expected:
    | { kind: "ok" }
    | { kind: "error" }
    | { kind: "invalid"; reason: "not_envelope_shape" | "error_body_shape" | "ok_with_error" | "not_ok_without_error" }
  note: string
}

export const ENVELOPE_SAMPLES: readonly ApiSafetyEnvelopeSample[] = [
  // —— 正常信封 ——
  {
    payload: { data: { id: "a1" }, error: null },
    status: 200,
    expected: { kind: "ok" },
    note: "200 标准信封 → ok（data 原样透传）",
  },
  {
    payload: { data: [1, 2, 3], error: null },
    status: 201,
    expected: { kind: "ok" },
    note: "201 创建成功 → ok",
  },
  {
    payload: { data: null, error: { code: "not_found", message: "不存在" } },
    status: 404,
    expected: { kind: "error" },
    note: "404 错误信封 → error（data 由消费侧置 null）",
  },
  {
    payload: { data: null, error: { code: "x", message: "m", details: { a: 1 } } },
    status: 409,
    expected: { kind: "error" },
    note: "409 带 details → error（details 由桌面侧脱敏、web 侧透传）",
  },
  // —— ①ok∧error 拒 ——
  {
    payload: { data: { id: "a1" }, error: { code: "weird", message: "成功却带错误" } },
    status: 200,
    expected: { kind: "invalid", reason: "ok_with_error" },
    note: "ok∧error → invalid（web 桥旧实现放行＝缺口①）",
  },
  {
    payload: { data: { id: "a1" }, error: { code: "weird", message: "m" } },
    status: 201,
    expected: { kind: "invalid", reason: "ok_with_error" },
    note: "201 同属 2xx → ok∧error 拒",
  },
  // —— ②!ok∧¬error 拒 ——
  {
    payload: { data: null, error: null },
    status: 500,
    expected: { kind: "invalid", reason: "not_ok_without_error" },
    note: "!ok∧¬error → invalid（web 桥旧实现放行 null error＝缺口②）",
  },
  {
    payload: { data: { partial: true }, error: null },
    status: 502,
    expected: { kind: "invalid", reason: "not_ok_without_error" },
    note: "502 带 data 无 error → invalid（!ok data 不得透传＝缺口③）",
  },
  // —— 信封形状 ——
  {
    payload: null,
    status: 200,
    expected: { kind: "invalid", reason: "not_envelope_shape" },
    note: "null 体 → not_envelope_shape",
  },
  {
    payload: { only_data: 1 },
    status: 200,
    expected: { kind: "invalid", reason: "not_envelope_shape" },
    note: "缺 error 键 → not_envelope_shape",
  },
  {
    payload: { only_error: null },
    status: 200,
    expected: { kind: "invalid", reason: "not_envelope_shape" },
    note: "缺 data 键 → not_envelope_shape",
  },
  {
    payload: [{ data: 1, error: null }],
    status: 200,
    expected: { kind: "invalid", reason: "not_envelope_shape" },
    note: "数组体拒绝",
  },
  // —— ④错误体形态 ——
  {
    payload: { data: null, error: { code: 1, message: "m" } },
    status: 400,
    expected: { kind: "invalid", reason: "error_body_shape" },
    note: "error.code 非字符串 → error_body_shape（web 桥旧实现 toApiError 回退 request_failed＝缺口④）",
  },
  {
    payload: { data: null, error: { code: "x" } },
    status: 400,
    expected: { kind: "invalid", reason: "error_body_shape" },
    note: "error 缺 message → error_body_shape",
  },
  {
    payload: { data: null, error: "boom" },
    status: 400,
    expected: { kind: "invalid", reason: "error_body_shape" },
    note: "error 非对象 → error_body_shape",
  },
  {
    payload: { data: null, error: [] },
    status: 400,
    expected: { kind: "invalid", reason: "error_body_shape" },
    note: "error 数组 → error_body_shape",
  },
]

/** 脱敏纯函数样本（sanitizeEnvelopeDetails / redactSensitiveString 双桥共用）。 */
export interface ApiSafetyRedactionSample {
  value: unknown
  secrets: string[]
  expected: unknown
  note: string
}

export const REDACTION_SAMPLES: readonly ApiSafetyRedactionSample[] = [
  {
    value: { code: "x", message: "token abc 坏了" },
    secrets: ["abc"],
    expected: { code: "x", message: "token [REDACTED] 坏了" },
    note: "message 串内命中 secret → 替换",
  },
  {
    value: { details: { password: "p1", keep: "v" } },
    secrets: ["p1"],
    expected: { details: { password: "[REDACTED]", keep: "v" } },
    note: "敏感键值整体替换（双层）",
  },
  {
    value: { details: { nested: { api_token: "t" } } },
    secrets: [],
    expected: { details: { nested: { api_token: "[REDACTED]" } } },
    note: "空 secrets 下敏感键仍整体替换（键级判定独立于串级）",
  },
  {
    value: "plain-secret",
    secrets: ["secret"],
    expected: "plain-[REDACTED]",
    note: "顶层字符串替换",
  },
  {
    value: { big: Array.from({ length: 60 }, (_, i) => String(i)) },
    secrets: [],
    expected: { big: Array.from({ length: 50 }, (_, i) => String(i)) },
    note: "数组截断 50",
  },
]
