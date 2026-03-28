def clamp_limit(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def clamp_offset(value: int) -> int:
    return max(0, value)
