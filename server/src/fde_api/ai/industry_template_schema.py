"""Strict contracts for the industry-template AI workflow."""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict, cast

from fde_api.auth.models import VALID_ROLES
from fde_api.research.definitions import validate_research_definition
from fde_api.research.models import SUBJECT_TYPES
from fde_api.workbench.scheduling import ScheduleTask, SchedulingError, validate_acyclic


STABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_MESSAGES = 40
MAX_MESSAGE_LENGTH = 4_000
MAX_TOTAL_LENGTH = 30_000


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ChatDecision(TypedDict):
    status: Literal["need_more_information", "ready_to_generate"]
    message: str
    known_information: dict[str, Any]
    missing_fields: list[str]
    questions: list[str]


class AIContractError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


def validate_chat_messages(value: object) -> list[ChatMessage]:
    if not isinstance(value, list) or len(value) > MAX_MESSAGES:
        raise AIContractError("invalid_messages", "messages", "对话消息数量不符合要求。")
    normalized: list[ChatMessage] = []
    total = 0
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {"role", "content"}:
            raise AIContractError("invalid_message", f"messages[{index}]", "对话消息格式不正确。")
        role = raw.get("role")
        content = raw.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise AIContractError("invalid_message", f"messages[{index}]", "对话消息格式不正确。")
        content = content.strip()
        if not content or len(content) > MAX_MESSAGE_LENGTH:
            raise AIContractError("invalid_message", f"messages[{index}].content", "单条消息长度不符合要求。")
        total += len(content)
        normalized.append(cast(ChatMessage, {"role": role, "content": content}))
    if total > MAX_TOTAL_LENGTH:
        raise AIContractError("messages_too_long", "messages", "对话内容过长，请精简后重试。")
    return normalized


def parse_chat_decision(value: object) -> ChatDecision:
    if not isinstance(value, dict):
        raise AIContractError("invalid_chat_decision", "", "AI 回复格式不正确。")
    allowed = {"status", "message", "known_information", "missing_fields", "questions"}
    if set(value) != allowed:
        raise AIContractError("invalid_chat_decision", "", "AI 回复字段不完整。")
    status = value.get("status")
    message = value.get("message")
    known = value.get("known_information")
    missing = value.get("missing_fields")
    questions = value.get("questions")
    if status not in {"need_more_information", "ready_to_generate"}:
        raise AIContractError("invalid_status", "status", "AI 回复状态不正确。")
    if not isinstance(message, str) or not message.strip() or len(message) > 2_000:
        raise AIContractError("invalid_message", "message", "AI 回复文案不正确。")
    if not isinstance(known, dict):
        raise AIContractError("invalid_known_information", "known_information", "已知信息格式不正确。")
    if not _string_list(missing, maximum=20):
        raise AIContractError("invalid_missing_fields", "missing_fields", "缺失字段格式不正确。")
    if not _string_list(questions, maximum=3):
        raise AIContractError("invalid_questions", "questions", "补充问题最多三个。")
    if status == "ready_to_generate" and questions:
        raise AIContractError("invalid_questions", "questions", "信息充分后不能继续追问。")
    return cast(ChatDecision, {
        "status": status,
        "message": message.strip(),
        "known_information": known,
        "missing_fields": missing,
        "questions": questions,
    })


def validate_generated_template(
    value: object, *, active_module_keys: set[str]
) -> dict[str, Any]:
    required_fields = {"name", "industry_name", "description", "modules"}
    allowed_fields = {*required_fields, "research_definition"}
    if (
        not isinstance(value, dict)
        or not required_fields.issubset(value)
        or not set(value).issubset(allowed_fields)
    ):
        raise AIContractError("invalid_template", "", "生成模板字段不完整。")
    name = _required_text(value.get("name"), "name", 160)
    industry = _required_text(value.get("industry_name"), "industry_name", 160)
    description = _optional_text(value.get("description"), "description")
    modules = value.get("modules")
    if not isinstance(modules, list) or not modules:
        raise AIContractError("invalid_modules", "modules", "至少需要一个项目模块。")

    module_keys: set[str] = set()
    task_keys: set[str] = set()
    tasks: list[ScheduleTask] = []
    normalized_modules: list[dict[str, Any]] = []
    for module_index, raw_module in enumerate(modules):
        path = f"modules[{module_index}]"
        if not isinstance(raw_module, dict) or set(raw_module) != {
            "module_key", "name", "description", "sort_order", "tasks"
        }:
            raise AIContractError("invalid_module", path, "模块格式不正确。")
        module_key = _stable_key(raw_module.get("module_key"), f"{path}.module_key")
        if module_key in module_keys:
            raise AIContractError("duplicate_module_key", f"{path}.module_key", "模块标识重复。")
        if module_key not in active_module_keys:
            raise AIContractError("inactive_module", f"{path}.module_key", "模块未启用。")
        module_keys.add(module_key)
        raw_tasks = raw_module.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise AIContractError("invalid_tasks", f"{path}.tasks", "每个模块至少需要一个任务。")
        normalized_tasks: list[dict[str, Any]] = []
        for task_index, raw_task in enumerate(raw_tasks):
            task_path = f"{path}.tasks[{task_index}]"
            if not isinstance(raw_task, dict) or set(raw_task) != {
                "task_key", "name", "description", "duration_days",
                "default_assignee_role", "sort_order", "dependency_keys",
            }:
                raise AIContractError("invalid_task", task_path, "任务格式不正确。")
            task_key = _stable_key(raw_task.get("task_key"), f"{task_path}.task_key")
            if task_key in task_keys:
                raise AIContractError("duplicate_task_key", f"{task_path}.task_key", "任务标识重复。")
            task_keys.add(task_key)
            duration = raw_task.get("duration_days")
            role = raw_task.get("default_assignee_role")
            sort_order = raw_task.get("sort_order")
            dependencies = raw_task.get("dependency_keys")
            if type(duration) is not int or duration < 1:
                raise AIContractError("invalid_duration", f"{task_path}.duration_days", "工期必须是正整数。")
            if role not in VALID_ROLES:
                raise AIContractError("invalid_role", f"{task_path}.default_assignee_role", "默认负责角色无效。")
            if type(sort_order) is not int:
                raise AIContractError("invalid_sort_order", f"{task_path}.sort_order", "任务排序必须是整数。")
            if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
                raise AIContractError("invalid_dependencies", f"{task_path}.dependency_keys", "前置任务格式不正确。")
            if task_key in dependencies or len(set(dependencies)) != len(dependencies):
                raise AIContractError("cyclic_dependency", f"{task_path}.dependency_keys", "任务依赖形成循环。")
            normalized_task = {
                "task_key": task_key,
                "name": _required_text(raw_task.get("name"), f"{task_path}.name", 200),
                "description": _optional_text(raw_task.get("description"), f"{task_path}.description"),
                "duration_days": duration,
                "default_assignee_role": role,
                "sort_order": sort_order,
                "dependency_keys": dependencies,
            }
            normalized_tasks.append(normalized_task)
            tasks.append(ScheduleTask(task_key, duration, tuple(dependencies)))
        normalized_modules.append({
            "module_key": module_key,
            "name": _required_text(raw_module.get("name"), f"{path}.name", 160),
            "description": _optional_text(raw_module.get("description"), f"{path}.description"),
            "sort_order": _integer(raw_module.get("sort_order"), f"{path}.sort_order"),
            "tasks": normalized_tasks,
        })

    missing_dependencies = {dependency for task in tasks for dependency in task.dependency_keys} - task_keys
    if missing_dependencies:
        raise AIContractError("missing_dependency", "modules", "前置任务不存在。")
    try:
        validate_acyclic(tasks)
    except (SchedulingError, ValueError) as error:
        raise AIContractError("cyclic_dependency", "modules", "任务依赖形成循环。") from error

    definition = value.get("research_definition")
    if definition is None:
        return {
            "name": name,
            "industry_name": industry,
            "description": description,
            "modules": normalized_modules,
            "research_definition": None,
        }
    if not isinstance(definition, dict):
        raise AIContractError("invalid_research_definition", "research_definition", "调研表格式不正确。")
    issues = validate_research_definition(definition)
    if issues:
        issue = issues[0]
        raise AIContractError(issue.code, f"research_definition.{issue.path}", issue.message)
    forms = definition.get("forms", [])
    actual_types = {form.get("subject_type") for form in forms if isinstance(form, dict)}
    missing_types = set(SUBJECT_TYPES) - actual_types
    if missing_types:
        raise AIContractError("missing_research_subject_type", "research_definition.forms", "必须生成项目、部门、岗位、流程和 AI 机会五类调研表。")
    for index, form in enumerate(forms):
        if form.get("module_key") not in module_keys:
            raise AIContractError("unknown_form_module_key", f"research_definition.forms[{index}].module_key", "调研表所属模块不在模板中。")
    return {
        "name": name,
        "industry_name": industry,
        "description": description,
        "modules": normalized_modules,
        "research_definition": definition,
    }


def _required_text(value: object, path: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise AIContractError("invalid_text", path, "文本为空或长度不符合要求。")
    return value.strip()


def _optional_text(value: object, path: str) -> str:
    if not isinstance(value, str) or len(value) > 20_000:
        raise AIContractError("invalid_text", path, "文本长度不符合要求。")
    return value.strip()


def _stable_key(value: object, path: str) -> str:
    if not isinstance(value, str) or STABLE_KEY.fullmatch(value) is None:
        raise AIContractError("invalid_stable_key", path, "稳定标识格式不正确。")
    return value


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise AIContractError("invalid_sort_order", path, "排序必须是整数。")
    return value


def _string_list(value: object, *, maximum: int) -> bool:
    return isinstance(value, list) and len(value) <= maximum and all(
        isinstance(item, str) and bool(item.strip()) and len(item) <= 500 for item in value
    )
