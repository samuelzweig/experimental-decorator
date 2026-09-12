"""Mark provisional Python APIs as experimental, stdlib-style.

The problem: a library wants to ship a function, class, or method without a
stability guarantee, but Python has no standard way to say so. Every project
that needs this ends up hand-rolling its own ``ExperimentalWarning`` with a
``stacklevel`` that quietly points into the library instead of the caller.

This module gives you ``@experimental``: a decorator for functions, classes,
and methods that emits a warning once per call site, pointing at the caller,
with metadata other tools can introspect.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import inspect
import sys
import warnings
from typing import Any, Callable, Iterator, Optional, TypeVar, Union, overload

__all__ = [
    "ExperimentalWarning",
    "ExperimentalInfo",
    "experimental",
    "is_experimental",
    "experimental_info",
    "silence_experimental_warnings",
]

__version__ = "0.1.0"

_F = TypeVar("_F", bound=Callable[..., Any])
_C = TypeVar("_C", bound=type)


class ExperimentalWarning(FutureWarning):
    """Emitted when an API marked ``@experimental`` is used.

    Subclasses ``FutureWarning`` (not ``UserWarning``) so it is visible by
    default under Python's standard warning filters, matching the stdlib's
    own convention for "this will change" warnings (e.g. ``DeprecationWarning``
    is silent by default for library code; ``FutureWarning`` is not).
    """


@dataclasses.dataclass(frozen=True)
class ExperimentalInfo:
    """Introspectable metadata attached to an experimental object."""

    kind: str  # "function", "method", or "class"
    qualname: str
    reason: Optional[str] = None
    since: Optional[str] = None
    removal: Optional[str] = None


# Call sites that have already warned, keyed by (marker, filename, lineno) so
# each decorated target warns once per *call site*, not once per call and not
# once globally. The marker is a private per-decoration object kept alive by
# the wrapper's closure, so identity never collides across decorations.
_WARNED_SITES: set = set()


def _seen_call_site(marker: object, depth: int) -> bool:
    """Record the caller `depth` frames up; return True if already warned.

    `depth` is relative to this function's own frame: 1 is this function's
    caller (the wrapper), 2 is the wrapper's caller (the real call site).
    """
    frame = sys._getframe(depth)
    key = (marker, frame.f_code.co_filename, frame.f_lineno)
    if key in _WARNED_SITES:
        return True
    _WARNED_SITES.add(key)
    return False


def _build_message(
    kind: str,
    qualname: str,
    reason: Optional[str],
    since: Optional[str],
    removal: Optional[str],
) -> str:
    msg = f"{kind} '{qualname}' is experimental and may change or be removed without notice"
    if since:
        msg += f" (since {since})"
    msg += "."
    if removal:
        msg += f" Planned removal: {removal}."
    if reason:
        msg += f" {reason}"
    return msg


def _wrap_callable(
    func: _F,
    kind: str,
    reason: Optional[str],
    since: Optional[str],
    removal: Optional[str],
) -> _F:
    qualname = getattr(func, "__qualname__", getattr(func, "__name__", repr(func)))
    message = _build_message(kind, qualname, reason, since, removal)
    marker = object()

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # depth=2: frame 1 is this wrapper, frame 2 is its caller.
        if not _seen_call_site(marker, depth=2):
            warnings.warn(message, ExperimentalWarning, stacklevel=2)
        return func(*args, **kwargs)

    wrapper.__experimental__ = ExperimentalInfo(  # type: ignore[attr-defined]
        kind=kind, qualname=qualname, reason=reason, since=since, removal=removal
    )
    return wrapper  # type: ignore[return-value]


def _wrap_class(
    cls: _C,
    reason: Optional[str],
    since: Optional[str],
    removal: Optional[str],
) -> _C:
    qualname = cls.__qualname__
    message = _build_message("class", qualname, reason, since, removal)
    marker = object()
    orig_init = cls.__init__

    @functools.wraps(orig_init)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        # type.__call__ (which invokes __init__ on instantiation) is
        # implemented in C and does not push its own Python frame, so the
        # caller of this __init__ *is* the code that wrote `Cls(...)`, same
        # as a plain function call. depth=2 lands there, same as above.
        if not _seen_call_site(marker, depth=2):
            warnings.warn(message, ExperimentalWarning, stacklevel=2)
        orig_init(self, *args, **kwargs)

    cls.__init__ = __init__  # type: ignore[method-assign]
    cls.__experimental__ = ExperimentalInfo(  # type: ignore[attr-defined]
        kind="class", qualname=qualname, reason=reason, since=since, removal=removal
    )
    return cls


@overload
def experimental(obj: _F) -> _F: ...
@overload
def experimental(
    *,
    reason: Optional[str] = ...,
    since: Optional[str] = ...,
    removal: Optional[str] = ...,
) -> Callable[[Union[_F, _C]], Union[_F, _C]]: ...


def experimental(
    obj: Optional[Union[_F, _C]] = None,
    *,
    reason: Optional[str] = None,
    since: Optional[str] = None,
    removal: Optional[str] = None,
):
    """Mark a function, method, or class as experimental.

    Usable bare (``@experimental``) or with keyword-only context
    (``@experimental(reason=..., since=..., removal=...)``). On a class, it
    wraps ``__init__`` so the warning fires on instantiation, not on class
    definition. On a function or method, it fires on each call. Either way
    it warns at most once per call site (the same line calling in a loop
    warns only the first time), and the warning's stacklevel points at the
    caller, not at this library.
    """

    def decorator(target: Union[_F, _C]) -> Union[_F, _C]:
        if inspect.isclass(target):
            return _wrap_class(target, reason, since, removal)  # type: ignore[arg-type]
        kind = "method" if _looks_like_method(target) else "function"
        return _wrap_callable(target, kind, reason, since, removal)  # type: ignore[arg-type]

    if obj is None:
        return decorator
    return decorator(obj)


def _looks_like_method(func: Callable[..., Any]) -> bool:
    """Best-effort guess at whether `func` is defined as a method.

    Only affects the wording of the warning message ("method" vs.
    "function"); a plain function named with a leading `self`/`cls`
    parameter and defined inside a class body is treated as a method. This
    is a heuristic, not a hard requirement: undecorated call behavior is
    identical either way.
    """
    try:
        params = list(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return False
    qualname = getattr(func, "__qualname__", "")
    return bool(params) and params[0] in ("self", "cls") and "." in qualname


def is_experimental(obj: Any) -> bool:
    """Return True if `obj` (function, method, class, or instance) was marked.

    Normal attribute lookup already resolves ``__experimental__`` from an
    instance to its class and from a bound method to its underlying
    function, so a single ``getattr`` covers all four cases.
    """
    return getattr(obj, "__experimental__", None) is not None


def experimental_info(obj: Any) -> ExperimentalInfo:
    """Return the `ExperimentalInfo` for `obj`; raise if it was never marked."""
    info = getattr(obj, "__experimental__", None)
    if info is None:
        raise TypeError(f"{obj!r} is not marked @experimental")
    return info


@contextlib.contextmanager
def silence_experimental_warnings() -> Iterator[None]:
    """Context manager that silences `ExperimentalWarning` for its block.

    Equivalent to, and implemented on top of, the standard library recipe::

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ExperimentalWarning)
            ...

    To silence experimental warnings for an entire process instead of one
    block, use that same recipe at startup without the context manager, or
    set the ``PYTHONWARNINGS`` environment variable.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ExperimentalWarning)
        yield

