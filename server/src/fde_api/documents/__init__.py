"""Project document domain models."""

from fde_api.documents.models import (
    DOCUMENT_GENERATION_STATUSES,
    DOCUMENT_STATES,
    DOCUMENT_TEMPLATE_STATUSES,
    DOCUMENT_TEMPLATE_VERSION_STATUSES,
    DOCUMENT_TYPE_KEYS,
    DOCUMENT_VERSION_SOURCES,
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentDraft,
    ProjectDocumentVersion,
)

__all__ = [
    "DOCUMENT_GENERATION_STATUSES",
    "DOCUMENT_STATES",
    "DOCUMENT_TEMPLATE_STATUSES",
    "DOCUMENT_TEMPLATE_VERSION_STATUSES",
    "DOCUMENT_TYPE_KEYS",
    "DOCUMENT_VERSION_SOURCES",
    "DocumentGenerationJob",
    "DocumentTemplate",
    "DocumentTemplateVersion",
    "ProjectDocument",
    "ProjectDocumentDraft",
    "ProjectDocumentVersion",
]
