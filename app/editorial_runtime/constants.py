from __future__ import annotations

RESIDENT_DECISION_DESKS = ("chief_translation_editor", "terminology_editor")
RESIDENT_PRODUCTION_DESKS = ("main_translator", "bilingual_reviewer", "line_editor")
EVENT_DESKS = ("structure_secretary", "archive_exporter", "external_reference_reviewer")

CHAPTER_STATES = (
    "planned",
    "term_ready",
    "raw_ready",
    "review_ready",
    "revision_ready",
    "accepted",
    "stale",
    "blocked",
    "cancelled",
)

TERM_STATES = ("candidate", "approved", "locked", "rejected", "deprecated")
ANNOTATION_STATES = ("candidate", "approved", "rejected", "locked")
RUN_STATES = ("queued", "running", "completed", "failed", "cancelled")

RAW_WRITER = "main_translator"
REVIEW_WRITER = "bilingual_reviewer"
REVISION_WRITER = "line_editor"
ACCEPTANCE_WRITER = "chief_translation_editor"
TERMS_WRITER = "terminology_editor"
