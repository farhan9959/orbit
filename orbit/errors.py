"""Exception types for the ORBIT library.

`ValidationError` subclasses `ValueError` so that callers who expect ordinary Python
semantics (`except ValueError`) still work, while code that wants to distinguish
ORBIT's own rejections from arbitrary library errors can catch `OrbitError`.

Every rejection raised by this package carries the offending identifier and value in
its message: an unhelpful "invalid input" is a debugging cost paid on every future run.
"""

from __future__ import annotations


class OrbitError(Exception):
    """Base class for every error raised deliberately by ORBIT."""


class ValidationError(OrbitError, ValueError):
    """A model object, spec, or algorithm input violated a documented constraint."""
