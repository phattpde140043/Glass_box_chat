import asyncio


async def sleep_ms(milliseconds: int) -> None:
    """Sleep for a millisecond duration."""
    await asyncio.sleep(milliseconds / 1000.0)
