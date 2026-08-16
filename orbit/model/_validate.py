"""Shared field validators used by the model types.

Why validation lives here rather than at an API layer: topologies, traffic matrices and
scenarios are *user-supplied structured data* (docs/04-threat-model.md T4). The model
constructor is the innermost trust boundary and the only one that every path — CLI, YAML
loader, future HTTP API, property test — must cross. Validating here means an invalid
model object cannot exist anywhere in the system.

These helpers are deliberately strict:

* `bool` is rejected where a number is expected. `True` is a valid `int` in Python, so
  `capacity_mbps=True` would otherwise become a 1 Mbps link.
* NaN is always rejected. A NaN capacity propagates silently through the allocator and
  poisons every downstream metric.
* Infinity is rejected unless explicitly allowed (only `Flow.duration_s` allows it).
"""

from __future__ import annotations

import math

from orbit.errors import ValidationError


def require_id(value: object, *, field: str, owner: str) -> str:
    """Return `value` if it is a usable identifier, else raise.

    Identifiers are strings because they come from human-written topology specs and end
    up as Parquet column values and dictionary keys. Sorting them is what makes iteration
    order deterministic (docs/03-simulation-model.md §3).
    """
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{owner}: {field} must be a non-empty string, got {value!r}")
    return value


def require_number(
    value: object,
    *,
    field: str,
    owner: str,
    minimum: float | None = None,
    maximum: float | None = None,
    allow_infinite: bool = False,
) -> float:
    """Return `value` as a float if it is a real number inside the given bounds, else raise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{owner}: {field} must be a real number, got {value!r}")
    number = float(value)
    if math.isnan(number):
        raise ValidationError(f"{owner}: {field} must not be NaN")
    if math.isinf(number) and not allow_infinite:
        raise ValidationError(f"{owner}: {field} must be finite, got {number!r}")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{owner}: {field} must be >= {minimum}, got {number!r}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{owner}: {field} must be <= {maximum}, got {number!r}")
    return number


def require_tags(value: object, *, field: str, owner: str) -> frozenset[str]:
    """Return `value` coerced to a frozenset of non-empty tag strings, else raise.

    Coercion (rather than demanding a `frozenset` from the caller) keeps model objects
    hashable no matter what the spec loader hands over, which matters because the model
    types are frozen and a mutable `set` field would break hashing.
    """
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise ValidationError(f"{owner}: {field} must be an iterable of strings, got {value!r}")
    tags = frozenset(value)
    for tag in tags:
        if not isinstance(tag, str) or not tag:
            raise ValidationError(
                f"{owner}: {field} entries must be non-empty strings, got {tag!r}"
            )
    return tags
