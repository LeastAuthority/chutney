# [pep 0536](https://peps.python.org/pep-0563/) - Lazy annotation eval via
# stringification.
from __future__ import annotations

# Future imports for Python 2.7, mandatory in 3.0
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os

from collections.abc import Iterable
from pathlib import Path
from typing import Callable, TypeVar, Any, Optional, overload, Generic, Union
from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")
V = TypeVar("V")


def memoized(fn: Callable[P, T]) -> Callable[P, T]:
    """Decorator: memoize a function."""
    # Keys are built from the arg and kwarg parameters passed to the function.
    # It might be nice to somewhow replace the `Any`s below with the actual
    # types derived from the parameter spec `P`, but probably not worth the
    # complexity.
    memory: dict[tuple[Iterable[Any], Iterable[tuple[Any, Any]]], T] = {}

    def memoized_fn(*args: P.args, **kwargs: P.kwargs) -> T:
        key = (args, tuple(sorted(kwargs.items())))
        try:
            result = memory[key]
        except KeyError:
            result = memory[key] = fn(*args, **kwargs)
        return result

    return memoized_fn


class Option(Generic[T]):
    """A wrapper for values that may be None

    Modeled after Rust's Option type.  Unlike typing.Optional, this is a real
    object wrapper that provides methods for safely manipulating the value, and
    that forces to the user to explicitly extract the inner value.

    The default `__str__` method is overridden to fail at runtime, meaning e.g.
    `str(Option(val))` will also fail. Calling code must use methods to access
    the inner value to perform a string conversion. This is done to prevent
    accidental substitution of a value like "None" in string templates, and to
    force call-sites of such conversions to be explicit about how to handle the
    `None` case.
    """

    def __init__(self, val: Optional[T]):
        self._val = val

    def unwrap(
        self, failure_msg: Union[str, Callable[[], str]] = "Unwrapped None"
    ) -> T:
        """Asserts v is not None and returns it"""
        if self._val is not None:
            return self._val
        if not isinstance(failure_msg, str):
            failure_msg = failure_msg()
        raise AssertionError(failure_msg)

    def as_optional(self) -> Optional[T]:
        """Returns the value, or None"""
        return self._val

    def unwrap_or(self, default: T) -> T:
        return self._val if self._val is not None else default

    def is_some(self) -> bool:
        return self._val is not None

    def is_none(self) -> bool:
        return self._val is None

    def replace(self, val: T) -> Optional[T]:
        """Assigns `val` and returns the previous value"""
        prev = self._val
        self._val = val
        return prev

    def map(self, f: Callable[[T], V]) -> Option[V]:
        if self._val is None:
            return Option(None)
        else:
            return Option(f(self._val))

    # Suppress string conversion to prevent unchecked usage
    # in templates, etc. (`repr` still works).
    #
    # Python allows assigning `__str__ = None` here, in which case string
    # conversions will fail at runtime. However doing so requires opting out of
    # mypy (which requires __str__ to be a callable with the expected
    # signature), and likewise doesn't have the benefit one might hope of mypy
    # statically preventing string conversions.
    def __str__(self) -> str:
        raise AssertionError(
            "Option doesn't support str conversion. Get the inner value instead."
        )


@overload
def getenv_type(
    env_var: str,
    default: None,
    type_: Callable[[str], T],
    type_name: Optional[str] = None,
) -> Optional[T]: ...


@overload
def getenv_type(
    env_var: str, default: T, type_: Callable[[str], T], type_name: Optional[str] = None
) -> T: ...


def getenv_type(
    env_var: str,
    default: Optional[T],
    type_: Callable[[str], T],
    type_name: Optional[str] = None,
) -> Optional[T]:
    """
    Return the value of the environment variable 'envar' as type_,
    or 'default' if no such variable exists.

    Raise ValueError using type_name if the environment variable is set,
    but type_() raises a ValueError on its value. (If type_name is None
    or empty, the ValueError uses type_'s string representation instead.)
    """
    strval = os.environ.get(env_var)
    if strval is None:
        return default
    try:
        return type_(strval)
    except ValueError:
        if not type_name:
            type_name = str(type_)
        raise ValueError(
            (
                "Invalid value for environment variable '{}': "
                "expected {}, but got '{}'"
            ).format(env_var, type_name, strval)
        )


@overload
def getenv_int(env_var: str, default: None) -> Optional[int]: ...


@overload
def getenv_int(env_var: str, default: int) -> int: ...


def getenv_int(env_var: str, default: Optional[int]) -> Optional[int]:
    """
    Return the value of the environment variable 'envar' as an int,
    or 'default' if no such variable exists.

    Raise ValueError if the environment variable is set, but is not an int.
    """
    return getenv_type(env_var, default, int, type_name="an int")


def getenv_bool(env_var: str, default: bool) -> bool:
    """
    Return the value of the environment variable 'envar' as a bool,
    or 'default' if no such variable exists.

    Unlike bool(), converts 0, "False", and "No" to False.

    Raise ValueError if the environment variable is set, but is not a bool.
    """
    # TODO: consider simplifying this and:
    # * rejecting ints other than 0 or 1
    # * accepting 'yes' for True
    try:
        # Handle integer values
        return bool(getenv_int(env_var, int(default)))
    except ValueError:
        # Handle values that the user probably expects to be False
        strval = os.environ.get(env_var)
        # If the env var weren't set, the int path above would have succeeded,
        # returning the default.
        assert strval is not None
        if strval.lower() in ["false", "no"]:
            return False
        else:
            return getenv_type(env_var, default, bool, type_name="a bool")


def find_on_path(
    basename: str, path: Optional[Iterable[Path]] = None
) -> Optional[Path]:
    """Find the first occurrence of `basename` in `path`

    Uses the `PATH` environment variable if `path` is not provided.
    """
    _path: Iterable[Path]
    if path is None:
        env_path = os.getenv("PATH")
        if env_path is None:
            _path = []
        else:
            _path = map(Path, env_path.split(":"))
    else:
        _path = path
    for location in _path:
        p = Path(location, basename)
        try:
            s = p.stat()
            if s and s.st_mode & 0x111:
                return p
        except OSError:
            pass
    return None
