from __future__ import annotations

from typing import Any, Callable

from .annotation_handlers import ANNOTATION_ACTION_HANDLERS
from .inspect_handlers import INSPECT_ACTION_HANDLERS
from .project_handlers import PROJECT_ACTION_HANDLERS
from .provider_handlers import PROVIDER_ACTION_HANDLERS
from .stage_handlers import STAGE_ACTION_HANDLERS

ActionHandler = Callable[[dict[str, str]], dict[str, Any]]


def _merge_action_handlers(*groups: dict[str, ActionHandler]) -> dict[str, ActionHandler]:
    merged: dict[str, ActionHandler] = {}
    for group in groups:
        duplicated_keys = set(merged).intersection(group)
        if duplicated_keys:
            duplicated = ", ".join(sorted(duplicated_keys))
            raise RuntimeError(f"重复注册 action handler: {duplicated}")
        merged.update(group)
    return merged


ACTION_HANDLERS = _merge_action_handlers(
    PROJECT_ACTION_HANDLERS,
    PROVIDER_ACTION_HANDLERS,
    STAGE_ACTION_HANDLERS,
    ANNOTATION_ACTION_HANDLERS,
    INSPECT_ACTION_HANDLERS,
)
