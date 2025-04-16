import dataclasses
import enum

from typing import Union


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


class DirFormat(enum.Enum):
    # cached-descriptors in c-tor
    DESC = enum.auto()
    # cached-descriptors.new in c-tor
    DESC_NEW = enum.auto()
    # cached-consensus in c-tor
    NS_CONS = enum.auto()
    # cached-microdesc-consensus in c-tor
    MD_CONS = enum.auto()
    # cached-microdescs in c-tor
    MD = enum.auto()
    # cached-microdescs.new in c-tor
    MD_NEW = enum.auto()
    # networkstatus-bridges in c-tor
    BR_STATUS = enum.auto()

    # The following represent aggregates of the former when summarizing
    # descriptor statuses.
    # TODO: Maybe move to a separate type/enum?

    # DESC or DESC_NEW
    DESC_ALTS = enum.auto()
    # MD or MD_NEW
    MD_ALTS = enum.auto()
    # NS_CONS or MD_CONS
    CONS_ALL = enum.auto()
    # DESC, DESC_NEW, MD, MD_NEW
    DESC_ALL = enum.auto()
    # Overall
    NODE_DIR = enum.auto()

    def __str__(self) -> str:
        return self.name
