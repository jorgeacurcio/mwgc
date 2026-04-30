from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path

ProgressCallback = Callable[[str, float], None]


class UploadOutcome(Enum):
    UPLOADED = "uploaded"
    DUPLICATE = "duplicate"


def upload(
    fit_path: Path,
    on_progress: ProgressCallback | None = None,
) -> UploadOutcome:
    raise NotImplementedError("uploader.upload is implemented in task 7")
