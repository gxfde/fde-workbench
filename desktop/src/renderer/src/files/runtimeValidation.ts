import type {
  BusinessCategory,
  FileCategory,
  FileScanStatus,
  FileVersionStatus,
  FileUrlDto,
  ProjectFileDto,
  ProjectFileVersionDto,
  UploadCompleteDto,
  UploadedPartDto,
  UploadSessionDto,
} from "./types"

const VERSION_STATUSES: readonly FileVersionStatus[] = ["uploading", "quarantined", "available", "deprecated", "rejected", "failed"]
const SCAN_STATUSES: readonly FileScanStatus[] = ["pending", "scanning", "clean", "infected", "error", "not_required"]
const CATEGORIES: readonly FileCategory[] = ["attachment", "document"]
const BUSINESS_CATEGORIES: readonly string[] = ["商务合约", "预调研", "调研", "PoV验证", "生产部署", "培训预交接"]

export function isUploadSessionDto(value: unknown): value is UploadSessionDto {
  return isRecord(value)
    && hasStrings(value, ["id", "project_id", "name", "mime_type", "expires_at", "idempotency_key", "upload_id"])
    && isCategory(value.category)
    && isBusinessCategory(value.business_category)
    && isPositiveInteger(value.size_bytes)
    && isPositiveInteger(value.part_size)
}

export function isUploadedPartDto(value: unknown): value is UploadedPartDto {
  return isRecord(value)
    && typeof value.url === "string"
    && isPositiveInteger(value.part_number)
    && isPositiveInteger(value.expires_seconds)
}

export function isUploadCompleteDto(value: unknown): value is UploadCompleteDto {
  return isRecord(value)
    && typeof value.version_id === "string"
    && (value.file_id === null || typeof value.file_id === "string")
    && isVersionStatus(value.status)
    && isScanStatus(value.scan_status)
}

export function isProjectFileVersionDto(value: unknown): value is ProjectFileVersionDto {
  return isRecord(value)
    && typeof value.id === "string"
    && isPositiveInteger(value.version_number)
    && isVersionStatus(value.status)
    && isScanStatus(value.scan_status)
}

export function isProjectFileDto(value: unknown): value is ProjectFileDto {
  return isRecord(value)
    && hasStrings(value, ["id", "project_id", "display_name"])
    && isCategory(value.category)
    && isBusinessCategory(value.business_category)
    && (value.status === "active" || value.status === "archived")
    && (value.current_version_id === null || typeof value.current_version_id === "string")
    && (value.current_version === null || isProjectFileVersionDto(value.current_version))
    && (value.latest_version === undefined || value.latest_version === null || isProjectFileVersionDto(value.latest_version))
    && (value.created_by === null || typeof value.created_by === "string")
    && (value.generation_status === undefined || value.generation_status === null || ["queued", "generating", "succeeded", "failed"].includes(String(value.generation_status)))
    && (value.generation_message === undefined || typeof value.generation_message === "string")
    && (value.generation_export_id === undefined || value.generation_export_id === null || typeof value.generation_export_id === "string")
    && (value.generation_form_id === undefined || value.generation_form_id === null || typeof value.generation_form_id === "string")
    && (value.generation_updated_at === undefined || value.generation_updated_at === null || typeof value.generation_updated_at === "string")
}

export function isProjectFileListDto(value: unknown): value is { items: ProjectFileDto[] } {
  return isRecord(value)
    && Array.isArray(value.items)
    && value.items.every(isProjectFileDto)
}

export function isFileUrlDto(value: unknown): value is FileUrlDto {
  return isRecord(value)
    && typeof value.url === "string"
    && isPositiveInteger(value.expires_seconds)
}

function isCategory(value: unknown): value is FileCategory {
  return typeof value === "string" && CATEGORIES.some((category) => category === value)
}

function isBusinessCategory(value: unknown): value is BusinessCategory | null {
  return value === undefined || value === null || (typeof value === "string" && BUSINESS_CATEGORIES.some((category) => category === value))
}

function isVersionStatus(value: unknown): value is FileVersionStatus {
  return typeof value === "string" && VERSION_STATUSES.some((status) => status === value)
}

function isScanStatus(value: unknown): value is FileScanStatus {
  return typeof value === "string" && SCAN_STATUSES.some((status) => status === value)
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
