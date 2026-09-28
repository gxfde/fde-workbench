import type { ProjectFileVersionDto } from "./types"

export const MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024

/** Formats the desktop client can render without asking the user to download. */
const PREVIEWABLE_EXTENSIONS = new Set([
  ".docx",
  ".xlsx",
  ".pptx",
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".txt",
  ".csv",
  ".md",
  ".json",
  ".log",
])

const TEXT_PREVIEW_EXTENSIONS = new Set([".txt", ".csv", ".md", ".json", ".log"])
const IMAGE_PREVIEW_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp"])
const OFFICE_PDF_PREVIEW_EXTENSIONS = new Set([".docx", ".xlsx", ".pptx"])

export type FilePreviewKind = "docx" | "pdf" | "image" | "text" | "converted-pdf" | "none"

export function filenameExtension(filename: string): string {
  const leaf = filename.trim().split(/[\\/]/).pop() ?? ""
  const dot = leaf.lastIndexOf(".")
  return dot > 0 ? leaf.slice(dot).toLowerCase() : ""
}

export function filePreviewKind(filename: string): FilePreviewKind {
  const extension = filenameExtension(filename)
  if (extension === ".pdf") return "pdf"
  if (IMAGE_PREVIEW_EXTENSIONS.has(extension)) return "image"
  if (TEXT_PREVIEW_EXTENSIONS.has(extension)) return "text"
  if (OFFICE_PDF_PREVIEW_EXTENSIONS.has(extension)) return "converted-pdf"
  return "none"
}

export function decodeTextPreview(data: ArrayBuffer, filename = ""): string {
  const bytes = new Uint8Array(data)
  let text: string
  if (bytes[0] === 0xff && bytes[1] === 0xfe) {
    text = new TextDecoder("utf-16le").decode(bytes.subarray(2))
  } else if (bytes[0] === 0xfe && bytes[1] === 0xff) {
    text = new TextDecoder("utf-16be").decode(bytes.subarray(2))
  } else {
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    } catch {
      text = new TextDecoder("gb18030").decode(bytes)
    }
  }
  if (filenameExtension(filename) === ".json") {
    try { return JSON.stringify(JSON.parse(text), null, 2) } catch { return text }
  }
  return text
}

export function versionCanBePreviewed(
  version: ProjectFileVersionDto | null | undefined,
  fallbackFilename = "",
): boolean {
  if (!version || (version.status !== "available" && version.status !== "deprecated")) return false
  return PREVIEWABLE_EXTENSIONS.has(filenameExtension(version.original_filename || fallbackFilename))
}

export function fileTooLarge(file: Pick<File, "size">): boolean {
  return file.size > MAX_UPLOAD_SIZE_BYTES
}
