# Future imports for Python 2.7, mandatory in 3.0
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from collections.abc import Iterable
from typing import Callable, TypeVar, Any
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
