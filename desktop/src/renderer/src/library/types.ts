import type { DocumentSummaryDto } from "../documents/types"
import type { ProjectFileDto } from "../files/types"

export type LibraryRow = {
  id: string
  kind: "file"
  title: string
  category: string
  actor: string
  updatedAt: string
  source: ProjectFileDto
} | {
  id: string
  kind: "document"
  title: string
  category: string
  actor: string
  updatedAt: string
  source: DocumentSummaryDto
}
