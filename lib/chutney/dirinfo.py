import dataclasses
import enum

from typing import List, Optional, Any, Iterable, Union


class DirInfoStatusCode(enum.Enum):
    INTERNAL_ERROR = -500
    MISSING_FILE = -400
    NO_RECORDS = -300
    NOT_YET_IMPLEMENTED = -200
    SHORT_FILE = -100
    NO_PROGRESS = 0
    SUCCESS = 100
    ONIONDESC_PUBLISHED = 200

    def __str__(self) -> str:
        return f"{self.value} ({self.name})"


@dataclasses.dataclass
class DirInfoStatus:
    percent_or_code: Union[int, DirInfoStatusCode]
    keyword: str
    message: str
