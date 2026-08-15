"""Intentional process exit codes for the Glider CLI. Single source of truth."""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0                 # success (incl. dry-run and empty-but-intended runs)
    RUNTIME_ERROR = 1      # scrape/preview runtime failure, run-context errors
    INVALID_INPUT = 2      # invalid config, missing/malformed file, bad --format, CLI usage
    PARTIAL_FAILURE = 4    # run completed but >=1 page failed
    INTERRUPTED = 130      # SIGINT / KeyboardInterrupt (128 + signal 2)


EXIT_MAP = {
    "ok": ExitCode.OK,
    "runtime_error": ExitCode.RUNTIME_ERROR,
    "invalid_input": ExitCode.INVALID_INPUT,
    "partial_failure": ExitCode.PARTIAL_FAILURE,
    "interrupted": ExitCode.INTERRUPTED,
}
