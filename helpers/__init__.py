from typing import Callable
from time import sleep
from time import time as unixtime
import os
import re


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


def _get_env_list(
    env: str,
    sep: str = r'[;,]',
) -> list[str]:
    """
    Retrieves a list of values from environment variables (single or multi).
    Uses ENV or ENVS (with 'S' appended).

    Args:
        env (str): Name of the environment variable (singular).
        sep (str): Separator regex for splitting multi-value env.

    Returns:
        list[str]: List of values.

    Raises:
        ValueError: If neither or both env vars are set.
    """
    value = os.getenv(env, '')
    values = os.getenv(env + 'S', '')
    if not value and not values:
        raise ValueError(f"Neither {env} nor {env+'S'} is set in the environment.")

    if value and values:
        raise ValueError(f"Both {env} and {env+'S'} are set. Please set only one.")
    elif value:
        names = [value]
    elif values:
        names = re.split(sep, values)
    else:
        names = []

    return names


def get_project_names() -> list[str]:
    """
    Retrieves project names from environment variables PROJECT_NAME or PROJECT_NAMES.

    Returns:
        list: A list of validated project names.

    Raises:
        ValueError: If neither or both environment variables are set, or if names are invalid.
    """
    pattern = re.compile(r'^[a-z][a-z0-9_\-@+/.]*$')
    names = _get_env_list('PROJECT_NAME')
    for name in names:
        if ' ' in name:
            raise ValueError(f"Project name '{name}' contains spaces.")
        if not name.islower():
            raise ValueError(f"Project name '{name}' contains uppercase letters.")
        if not pattern.match(name):
            raise ValueError(f"Project name '{name}' is invalid. Must start with a letter and only contain a-z, 0-9, _-@+/.")

    return names


def get_ports() -> list[int]:
    """
    Retrieves allowed port numbers from environment variables PORT or PORTS.

    Returns:
        list[int]: A list of validated port numbers.

    Raises:
        ValueError: If neither or both environment variables are set, or if ports are invalid.
    """
    names = _get_env_list('PORT')
    ports = []
    for name in names:
        if not name.isdigit():
            raise ValueError(f"Port '{name}' is not a valid integer.")
        port = int(name)
        if not (1 <= port <= 65535):
            raise ValueError(f"Port '{port}' is out of valid range (1-65535).")
        ports.append(port)
    return ports


def get_env_count(env: str) -> int:
    """
    Retrieves an integer value from the environment variable `env`.

    Args:
        env (str): Name of the environment variable.

    Returns:
        int: The integer value. Default is 0 if not set.

    Raises:
        ValueError: If the variable is not a valid integer or negative.
    """
    value = os.getenv(env, '0')
    try:
        count = int(value)
    except ValueError:
        raise ValueError(f"{env}='{value}' is not a valid integer.")
    if count < 0:
        raise ValueError(f"{env}='{value}' is not a valid positive integer.")
    return count

