import time


def now_hms() -> str:
    """Return local time in HH:MM:SS format used by trace payloads."""
    return time.strftime("%H:%M:%S")
