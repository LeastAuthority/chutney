# Future imports for Python 2.7, mandatory in 3.0
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os

from collections.abc import Iterable
from typing import Callable, TypeVar, Any, Optional, overload
from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")


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
