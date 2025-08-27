from typing import Callable
from time import sleep
from time import time as unixtime


def wait_until(check: Callable, kwargs: dict, cond: Callable[[dict], bool], timeout: int=60, wait_interval: int=1):
    """
    Repeatedly calls a function with specified arguments until a condition is met or a timeout occurs.

    Args:
        check (Callable): The function to be called periodically with the specified arguments.
        kwargs (dict): A dictionary of keyword arguments to pass to the `check` function.
        cond (Callable[[dict], bool]): A function that takes the result of `check` and returns True if the desired condition is met.
        timeout (int, optional): The maximum number of seconds to wait for the condition to be met. Defaults to 60 seconds.
        wait_interval (int, optional): The number of seconds to wait between consecutive calls to `check`. Defaults to 1 second.

    Returns:
        bool: The result of the condition check function (`cond`) on the last call to `check`, indicating if the condition was met before the timeout.

    """
    start = t = unixtime()
    result = check(**kwargs)
    while not cond(result) and t < start + timeout:
        result = check(**kwargs)
        if cond(result):
            return cond(result)
        sleep(wait_interval)
        t = unixtime()
    return cond(result)