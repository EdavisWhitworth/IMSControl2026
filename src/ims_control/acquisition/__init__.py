"""Lazy imports for acquisition-side Qt worker objects."""

from __future__ import annotations

__all__ = ["AcquisitionWorker"]


def __getattr__(name: str):
	"""Import acquisition worker types on demand to avoid eager Qt imports."""
	if name == "AcquisitionWorker":
		from .worker_thread import AcquisitionWorker

		return AcquisitionWorker
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
