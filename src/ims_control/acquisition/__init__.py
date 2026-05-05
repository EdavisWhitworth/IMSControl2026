from __future__ import annotations

__all__ = ["AcquisitionWorker"]


def __getattr__(name: str):
	if name == "AcquisitionWorker":
		from .worker_thread import AcquisitionWorker

		return AcquisitionWorker
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
