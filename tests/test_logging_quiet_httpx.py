import logging

from hl_observer.utils.logging import configure_logging


def test_configure_logging_keeps_httpx_success_noise_out_of_terminal():
    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
