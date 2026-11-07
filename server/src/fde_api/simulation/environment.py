"""模拟环境与工具白名单（G3，G1 §6 的技术落点）。

**隔离是强制的，不是约定的**：工具路由在**网关层**按名前缀裁决——只有
``sim.*`` 在模拟面可达；其余一切（含真实邮件、真实 CRM、真实库写）在被调用
的瞬间被拒，并落 Trace（`boundary_violation`）⇒ 直接构成 HF-01 硬性失败证据。

「提示词里写不要发真邮件」不是隔离；「网关只认前缀」才是隔离。

数据面：全部在**内存**里（来自场景 ``seed_data``），不落库、不出网、不碰真实
系统。``sim.mail.send`` 只写本环境的内存发件箱——**没有 SMTP 通道**。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from fde_api.simulation.models import SIM_TOOL_PREFIX


class SimulationBoundaryViolation(Exception):
    """越界调用：模拟面试图调用白名单外的工具。"""

    def __init__(self, tool: str, reason: str = "tool_not_in_simulation_allowlist") -> None:
        super().__init__(f"工具「{tool}」不在模拟白名单内，已拒绝。")
        self.code = "boundary_violation"
        self.tool = tool
        self.reason = reason


class SimulationToolError(Exception):
    """虚拟工具内部故障（对应场景的故障注入）。"""

    def __init__(self, tool: str, error_code: str) -> None:
        super().__init__(f"工具「{tool}」返回模拟故障：{error_code}")
        self.code = error_code
        self.tool = tool


class SimulationEnvironment:
    """虚拟业务环境：只提供 ``sim.*`` 工具，数据全在内存，调用全留痕。"""

    def __init__(
        self,
        *,
        seed_data: dict[str, Any] | None = None,
        trace: Any | None = None,
        faults: list[dict[str, Any]] | None = None,
    ) -> None:
        self._data: dict[str, Any] = dict(seed_data or {})
        self._trace = trace
        self._faults: list[dict[str, Any]] = list(faults or [])
        self._mailbox: list[dict[str, Any]] = []
        self._calls: list[dict[str, Any]] = []
        # **越界**（调了非 sim.* 工具）�� **注入故障**（sim 工具按场景失败）是两件事：
        # 前者是安全越界 ⇒ 硬性失败；后者是场景机制 ⇒ 只记录，不判硬失败。
        self._boundary_violations: list[dict[str, Any]] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "sim.crm.list_leads": self._list_leads,
            "sim.crm.search_leads": self._search_leads,
            "sim.erp.list_materials": self._list_materials,
            "sim.erp.list_orders": self._list_orders,
            "sim.mes.list_batches": self._list_batches,
            "sim.mes.list_workstations": self._list_workstations,
            "sim.quality.list_defects": self._list_quality_defects,
            "sim.fs.read_document": self._read_document,
            "sim.customerdb.search": self._search_customerdb,
            "sim.mail.list_messages": self._list_messages,
            "sim.mail.send": self._send_mail,
            "sim.api.fetch": self._fetch,
        }

    # -- 工具目录 ---------------------------------------------------------

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    # -- 调用面（强制白名单） ---------------------------------------------

    def call_tool(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用虚拟工具。非 ``sim.*`` 工具直接拒绝（不执行、不落副作用）。"""
        arguments = dict(arguments or {})
        if not isinstance(tool, str) or not tool.startswith(SIM_TOOL_PREFIX):
            violation = SimulationBoundaryViolation(tool)
            self._record_call(tool, arguments, kind="boundary", reason=violation.reason)
            raise violation
        handler = self._tools.get(tool)
        if handler is None:
            violation = SimulationBoundaryViolation(tool, reason="unknown_sim_tool")
            self._record_call(tool, arguments, kind="boundary", reason=violation.reason)
            raise violation
        fault = self._match_fault(tool)
        if fault is not None:
            error_code = str(fault.get("error") or "sim_tool_crash")
            self._record_call(tool, arguments, kind="fault", reason=error_code)
            raise SimulationToolError(tool, error_code)
        try:
            result = handler(arguments)
        except SimulationToolError:
            raise
        self._record_call(tool, arguments, kind="ok", reason=None)
        return {"tool": tool, "ok": True, "data": result}

    def _match_fault(self, tool: str) -> dict[str, Any] | None:
        for fault in self._faults:
            match = fault.get("match")
            if not isinstance(match, dict):
                continue
            wanted = match.get("tool")
            if wanted and wanted != tool:
                continue
            return fault
        return None

    def _record_call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        kind: str,
        reason: str | None,
    ) -> None:
        """记一次工具调用。``kind`` ∈ ok / boundary / fault。"""
        record = {
            "tool": tool,
            "arguments": arguments,
            "kind": kind,
            "rejected": kind == "boundary",
            "reason": reason,
        }
        self._calls.append(record)
        if kind == "boundary":
            self._boundary_violations.append(record)
        elif kind == "fault":
            self._tool_failures.append(record)
        if self._trace is not None:
            self._trace.record(
                phase="implementation",
                event_type="tool_failure" if kind == "fault" else (
                    "boundary_violation" if kind == "boundary" else "tool_call"
                ),
                payload={"tool": tool, "kind": kind, "reason": reason},
                tool_call=record,
            )

    # -- 状态快照（可复现） -----------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "data": json.loads(json.dumps(self._data, ensure_ascii=False, default=str)),
            "mailbox": list(self._mailbox),
            "calls": list(self._calls),
        }

    @property
    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

    @property
    def mailbox(self) -> list[dict[str, Any]]:
        return list(self._mailbox)

    @property
    def rejected_calls(self) -> list[dict[str, Any]]:
        """**越界**调用（安全越界 ⇒ 硬性失败证据）。"""
        return list(self._boundary_violations)

    @property
    def failed_calls(self) -> list[dict[str, Any]]:
        """**注入故障**（场景机制 ⇒ 只记录，不判硬失败）。"""
        return list(self._tool_failures)

    # -- 各虚拟系统实现 ---------------------------------------------------

    def _namespace(self, name: str) -> Any:
        return self._data.get(name)

    def _list_leads(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("crm") or {}
        return list(rows.get("leads") or [])

    def _search_leads(self, arguments: dict[str, Any]) -> Any:
        keyword = str(arguments.get("q") or "").strip().lower()
        leads = self._list_leads({})
        if not keyword:
            return leads
        return [
            lead
            for lead in leads
            if keyword in str(lead.get("company", "")).lower()
            or keyword in str(lead.get("email", "")).lower()
        ]

    def _list_materials(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("erp") or {}
        return list(rows.get("materials") or [])

    def _list_orders(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("orders") or self._namespace("erp") or {}
        return list(rows.get("orders") or [])

    def _list_batches(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("mes") or {}
        return list(rows.get("batches") or [])

    def _list_workstations(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("mes") or {}
        return list(rows.get("workstations") or [])

    def _list_quality_defects(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("quality_db") or {}
        return list(rows.get("defect_records") or [])

    def _read_document(self, arguments: dict[str, Any]) -> Any:
        name = str(arguments.get("name") or "")
        documents = self._namespace("documents") or {}
        for document in documents.get("files") or []:
            if str(document.get("name")) == name:
                return document
        raise SimulationToolError("sim.fs.read_document", "sim_document_not_found")

    def _search_customerdb(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("customerdb") or {}
        return list(rows.get("customers") or [])

    def _list_messages(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("mail") or {}
        return list(rows.get("messages") or [])

    def _send_mail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """只写**本环境的内存发件箱**——本模块没有 SMTP 通道，无真实外发可能。"""
        message = {
            "to": str(arguments.get("to") or ""),
            "subject": str(arguments.get("subject") or ""),
            "body": str(arguments.get("body") or ""),
            "simulation_only": True,
        }
        self._mailbox.append(message)
        return dict(message)

    def _fetch(self, arguments: dict[str, Any]) -> Any:
        rows = self._namespace("api") or {}
        return list(rows.get("responses") or [])
