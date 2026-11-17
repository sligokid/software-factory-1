"""Slice registry: the only place slices are wired into the app.

Add one import and one list entry per slice. A slice is inactive until it is listed here.
"""

from fastapi import APIRouter

SLICE_ROUTERS: list[APIRouter] = []
