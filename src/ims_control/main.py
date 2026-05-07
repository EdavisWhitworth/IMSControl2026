"""Application entrypoint for the IMS control desktop UI."""

from __future__ import annotations

import logging
from pathlib import Path
import sys
import threading
import traceback

from PyQt5.QtWidgets import QApplication

from ims_control.ui.main_window import MainWindow


def _configure_crash_logging() -> None:
    """Route uncaught exceptions to a persistent log file and stderr."""
    log_path = Path.home() / "ims_control_crash.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    def _log_exception(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Unhandled exception:\n%s", text)
        sys.stderr.write(text)
        sys.stderr.flush()

    def _log_thread_exception(args) -> None:
        _log_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _log_exception
    threading.excepthook = _log_thread_exception


def main() -> int:
    """Create the Qt application, show the main window, and run the event loop."""
    _configure_crash_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec_()
    if exit_code != 0:
        logging.error("Application exited with non-zero code: %s", exit_code)
        sys.stderr.write(f"Application exited with non-zero code: {exit_code}\n")
        sys.stderr.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
