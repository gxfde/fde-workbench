import type {
  BusinessCategory,
  DocumentDetailDto,
  DocumentDraftDto,
  DocumentListDto,
  DocumentStatus,
  DocumentSummaryDto,
  DocumentTypeKey,
  DocumentUrlDto,
  DocumentVersionDto,
  DocumentVersionSource,
  DocumentVersionStatus,
  DocumentVersionSummary,
} from "./types"
import { DOCUMENT_TYPE_KEYS } from "./types"

const STATUSES: readonly (DocumentStatus | DocumentVersionStatus)[] = ["draft", "confirmed", "archived"]
const SOURCES: readonly DocumentVersionSource[] = ["generated", "online_revised", "manual_upload"]
const PREVIEW_STATUSES: readonly string[] = ["none", "pending", "ready", "failed"]
const BUSINESS_CATEGORIES: readonly string[] = ["商务合约", "预调研", "调研", "PoV验证", "生产部署", "培训预交接"]

export function isDocumentSummary(value: unknown): value is DocumentSummaryDto {
  return isRecord(value)
    && hasStrings(value, ["id", "project_id", "business_code", "created_at"])
    && isDocumentType(value.document_type)
    && isDocumentStatus(value.status)
    && isBusinessCategory(value.business_category)
    && (value.source_opportunity_id === undefined || value.source_opportunity_id === null || typeof value.source_opportunity_id === "string")
    && (value.library_file_id === undefined || value.library_file_id === null || typeof value.library_file_id === "string")
    && isPositiveInteger(value.version)
    && (value.current_version_id === null || typeof value.current_version_id === "string")
    && (value.current_version === null || isDocumentVersionSummary(value.current_version))
    && (value.generation_status === undefined || value.generation_status === null || ["queued", "running", "succeeded", "failed", "cancelled"].includes(String(value.generation_status)))
    && (value.generation_message === undefined || typeof value.generation_message === "string")
    && (value.updated_at === undefined || typeof value.updated_at === "string")
}

export function isDocumentListDto(value: unknown): value is DocumentListDto {
  return isRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isDocumentSummary)
}

export function isDocumentVersionSummary(value: unknown): value is DocumentVersionSummary {
  return isRecord(value)
    && typeof value.id === "string"
    && isPositiveInteger(value.version_number)
    && isDocumentSource(value.source)
    && isDocumentStatus(value.status)
    && (value.docx_file_version_id === undefined || value.docx_file_version_id === null || typeof value.docx_file_version_id === "string")
    && (value.preview_file_version_id === undefined || value.preview_file_version_id === null || typeof value.preview_file_version_id === "string")
    && (value.preview_status === undefined || isPreviewStatus(value.preview_status))
}

export function isDocumentVersion(value: unknown): value is DocumentVersionDto {
  return isRecord(value)
    && hasStrings(value, ["id", "document_id", "created_at"])
    && isPositiveInteger(value.version_number)
    && isDocumentSource(value.source)
    && isDocumentStatus(value.status)
    && (value.docx_file_version_id === undefined || value.docx_file_version_id === null || typeof value.docx_file_version_id === "string")
    && (value.preview_file_version_id === undefined || value.preview_file_version_id === null || typeof value.preview_file_version_id === "string")
    && (value.preview_status === undefined || isPreviewStatus(value.preview_status))
    && (value.sha256 === undefined || typeof value.sha256 === "string")
    && (value.confirmed_by === undefined || value.confirmed_by === null || isDocumentUser(value.confirmed_by))
    && (value.confirmed_at === undefined || value.confirmed_at === null || typeof value.confirmed_at === "string")
}

export function isDocumentDraft(value: unknown): value is DocumentDraftDto {
  return isRecord(value)
    && hasStrings(value, ["id", "document_id", "created_at", "updated_at"])
    && isPositiveInteger(value.version)
    && (value.field_overrides === undefined || isRecord(value.field_overrides))
    && (value.list_selections === undefined || isRecord(value.list_selections))
}

export function isDocumentDetail(value: unknown): value is DocumentDetailDto {
  return isRecord(value)
    && hasStrings(value, ["id", "project_id", "business_code", "created_at"])
    && isDocumentType(value.document_type)
    && isDocumentStatus(value.status)
    && isBusinessCategory(value.business_category)
    && (value.source_opportunity_id === undefined || value.source_opportunity_id === null || typeof value.source_opportunity_id === "string")
    && (value.library_file_id === undefined || value.library_file_id === null || typeof value.library_file_id === "string")
    && isPositiveInteger(value.version)
    && (value.current_version_id === null || typeof value.current_version_id === "string")
    && (value.current_version === null || isDocumentVersion(value.current_version))
    && (value.draft === null || isDocumentDraft(value.draft))
    && Array.isArray(value.history)
    && value.history.every(isDocumentVersionSummary)
    && (value.owner === undefined || value.owner === null || isDocumentUser(value.owner))
}

export function isDocumentUrl(value: unknown): value is DocumentUrlDto {
  return isRecord(value)
    && typeof value.url === "string"
    && isPositiveInteger(value.expires_seconds)
}

function isDocumentUser(value: unknown): boolean {
  return isRecord(value) && typeof value.id === "string" && typeof value.display_name === "string"
}

function isDocumentType(value: unknown): value is DocumentTypeKey {
  return typeof value === "string" && (DOCUMENT_TYPE_KEYS as readonly string[]).includes(value)
}

function isDocumentStatus(value: unknown): value is DocumentStatus {
  return typeof value === "string" && STATUSES.some((status) => status === value)
}

function isDocumentSource(value: unknown): value is DocumentVersionSource {
  return typeof value === "string" && SOURCES.some((source) => source === value)
}

function isPreviewStatus(value: unknown): boolean {
  return typeof value === "string" && PREVIEW_STATUSES.some((status) => status === value)
}

function isBusinessCategory(value: unknown): value is BusinessCategory | null {
  return value === undefined || value === null || (typeof value === "string" && BUSINESS_CATEGORIES.some((category) => category === value))
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasStrings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string")
}
