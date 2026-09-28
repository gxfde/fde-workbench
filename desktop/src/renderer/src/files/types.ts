/**
 * Project file DTOs.
 *
 * DTOs deliberately retain the server's snake_case serialization so that
 * the renderer can pass them straight back to the File/OSS API endpoints.
 */

import type { BusinessCategory } from "../businessCategory"

export type { BusinessCategory }

export type FileCategory = "attachment" | "document"
export type FileVersionStatus = "uploading" | "quarantined" | "available" | "deprecated" | "rejected" | "failed"
export type FileScanStatus = "pending" | "scanning" | "clean" | "infected" | "error" | "not_required"
export type FileProjectStatus = "active" | "archived"

/** `POST /api/v1/projects/{projectId}/files` create upload session response `data`. */
export interface UploadSessionDto {
  id: string
  project_id: string
  name: string
  category: FileCategory
  /** Optional business stage; `null`/absent means uncategorized. */
  business_category?: BusinessCategory | null
  size_bytes: number
  mime_type: string
  part_size: number
  upload_id: string
  expires_at: string
  idempotency_key: string
}

/** `POST /api/v1/projects/{projectId}/files/{sessionId}/parts` response `data`. */
export interface UploadedPartDto {
  url: string
  part_number: number
  expires_seconds: number
}

/** `POST /api/v1/projects/{projectId}/files/{sessionId}/complete` response `data`. */
export interface UploadCompleteDto {
  version_id: string
  file_id: string | null
  status: FileVersionStatus
  scan_status: FileScanStatus
}

/** Nested current-version shape returned by `GET /api/v1/projects/{projectId}/files` items. */
export interface ProjectFileVersionDto {
  id: string
  version_number: number
  status: FileVersionStatus
  scan_status: FileScanStatus
  preview_status?: "none" | "pending" | "ready" | "failed"
  source?: string
  original_filename?: string
  mime_type?: string
  size_bytes?: number
  uploaded_by?: string | null
  uploaded_at?: string
  deprecated_by?: string | null
  deprecated_at?: string | null
  deprecation_reason?: string
}

export interface ProjectFileVersionListDto { items: ProjectFileVersionDto[] }

/** A single item from `GET /api/v1/projects/{projectId}/files` `data.items`. */
export interface ProjectFileDto {
  id: string
  project_id: string
  display_name: string
  category: FileCategory
  /** Optional business stage; `null`/absent means uncategorized. */
  business_category?: BusinessCategory | null
  status: FileProjectStatus
  current_version_id: string | null
  current_version: ProjectFileVersionDto | null
  /** Highest numbered version, including an explicitly deprecated latest version. */
  latest_version?: ProjectFileVersionDto | null
  created_by: string | null
  /** Latest asynchronous generation task associated with this file identity. */
  generation_status?: "queued" | "generating" | "succeeded" | "failed" | null
  generation_message?: string
  generation_export_id?: string | null
  generation_form_id?: string | null
  generation_updated_at?: string | null
}

/** `GET /api/v1/projects/{projectId}/files/{versionId}/preview-url` and `download-url` response `data`. */
export interface FileUrlDto {
  url: string
  expires_seconds: number
}

/** Local upload queue item driving the per-file progress UI. */
export type UploadItemStatus = "pending" | "uploading" | "completed" | "failed" | "cancelled"

export interface UploadItem {
  id: string
  name: string
  displayName?: string
  fileId?: string
  sizeBytes: number
  mimeType: string
  status: UploadItemStatus
  /** 0..100 */
  progress: number
  /** Reused when a failed upload is retried so the server can deduplicate. */
  idempotencyKey: string
  /** Business stage chosen in the upload toolbar; `null`/absent means uncategorized. */
  businessCategory?: BusinessCategory | null
  sessionId?: string
  partSize?: number
  error?: string
}
