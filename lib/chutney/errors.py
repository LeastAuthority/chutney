from __future__ import annotations

from typing import List


class ChutneyError(Exception):
    """Base class for "normal" errors originating from this module

    i.e. any public functions in this module raising an exception that *isn't*
    a subclass of this indicates a programming error in this module.
    """

    pass


class ChutneyUnimplementedError(ChutneyError):
    """Requested functionality is unimplemented."""

    pass


class ChutneyMissingBinaryError(ChutneyError):
    def __init__(self, name: str, cmdline: List[str], help: str):
        self._name = name
        self._cmdline = cmdline
        self._help = help

    @staticmethod
    def for_missing_tor(tor_name: str, cmdline: List[str]) -> ChutneyMissingBinaryError:
        """Create an exception for a missing tor binary, with help for how to fix it."""
        help_msg_fmt = (
            "Set the '{0}' environment variable to the path of "
            + "'{1}'. If using test-network.sh, set the 'TOR_DIR' "
            + "environment variable to the directory containing '{1}'."
        )
        help_msg = ""
        if tor_name == "tor":
            help_msg = help_msg_fmt.format("CHUTNEY_TOR", tor_name)
        elif tor_name == "tor-gencert":
            help_msg = help_msg_fmt.format("CHUTNEY_TOR_GENCERT", tor_name)
        elif tor_name == "arti":
            help_msg = help_msg_fmt.format("CHUTNEY_ARTI", tor_name)
        else:
            raise ValueError("Unknown tor_name: '{}'".format(tor_name))
        return ChutneyMissingBinaryError(tor_name, cmdline, help_msg)

    def __str__(self) -> str:
        return (
            f"Cannot find the {self._name} binary"
            + f" at '{self._cmdline[0]}'"
            + f" for the command line '{' '.join(self._cmdline)}'."
            + f" {self._help}"
        )


class ChutneyTimeoutError(ChutneyError):
    pass


class ChutneyErrorGroup(ChutneyError):
    """A list of errors.

    For use in methods like `start` where we want to continue after the first error,
    but collect all of the errors.

    Analogous to python 3.11's `ExceptionGroup`
    """

    def __init__(self, description: str, errs: List[ChutneyError]):
        self._description = description
        self._errs = errs
        ChutneyError.__init__(self, description, errs)

    def __str__(self) -> str:
        return (
            self._description
            + " [\n  "
            + "\n  ".join([str(e) for e in self._errs])
            + "\n]\n"
        )


class ChutneyInternalError(ChutneyError):
    """Indicates a bug in Chutney"""

    pass
