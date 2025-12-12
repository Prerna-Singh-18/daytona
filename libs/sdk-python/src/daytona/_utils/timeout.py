# Copyright 2025 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

import asyncio
import ctypes
import functools
import inspect
import signal
import sys
import threading
from typing import Callable, Optional, TypeVar

from ..common.errors import DaytonaError, DaytonaTimeoutError

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")


class _TimeoutMarker(BaseException):
    """Internal marker exception for threading timeout.
    
    This is raised via PyThreadState_SetAsyncExc and then caught and converted
    to DaytonaTimeoutError with a proper error message. We use BaseException
    (not Exception) to ensure it's not accidentally caught by generic exception handlers.
    """
    pass


def _async_raise(target_tid: int, exception: type) -> None:
    """Raises an exception asynchronously in another thread.
    
    This uses the CPython API PyThreadState_SetAsyncExc to raise an exception
    in a different thread. This allows interrupting blocking operations.
    
    Args:
        target_tid: Target thread identifier
        exception: Exception class to be raised in that thread
        
    Raises:
        ValueError: If the thread ID is invalid
        SystemError: If PyThreadState_SetAsyncExc fails
    
    Note:
        Requires Python 3.7+ where thread IDs are unsigned long.
    """
    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(target_tid),
        ctypes.py_object(exception)
    )
    if ret == 0:
        raise ValueError(f"Invalid thread ID {target_tid}")
    elif ret > 1:
        # If it returns > 1, we need to clear it
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(target_tid), None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


class _ThreadingTimeout:
    """Context manager for timeout using threading.Timer and async exception raising.
    
    This implements a timeout mechanism that raises DaytonaTimeoutError in the calling
    thread after a specified duration. It properly executes finally blocks because
    the exception is raised as if it came from within the protected code.
    """
    
    def __init__(self, seconds: float, func_name: str):
        """Initialize the threading timeout.
        
        Args:
            seconds: Timeout duration in seconds
            func_name: Name of the function being timed (for error messages)
        """
        self.seconds = seconds
        self.func_name = func_name
        self.target_tid = threading.current_thread().ident
        self.timer: Optional[threading.Timer] = None
        self.timed_out = False
        
    def _timeout_handler(self) -> None:
        """Called by timer thread when timeout occurs."""
        self.timed_out = True
        if self.target_tid:
            _async_raise(self.target_tid, _TimeoutMarker)
    
    def __enter__(self) -> "_ThreadingTimeout":
        """Start the timeout timer."""
        self.timer = threading.Timer(self.seconds, self._timeout_handler)
        self.timer.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop the timeout timer and handle timeout exception."""
        if self.timer:
            self.timer.cancel()
        
        # If we timed out via our marker exception, convert to DaytonaTimeoutError
        if exc_type is _TimeoutMarker and self.timed_out:
            raise DaytonaTimeoutError(
                f"Function '{self.func_name}' exceeded timeout of {self.seconds} seconds."
            ) from None
        
        return False  # Don't suppress any exceptions


def with_timeout() -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to add timeout mechanism that executes finally blocks properly.
    
    This decorator ensures that finally blocks and context managers execute properly
    when a timeout occurs, allowing for proper resource cleanup. The TimeoutError is
    raised as if it originated from within the decorated function's workflow.
    
    Platform Support:
        - **Async functions**: All platforms (uses asyncio task cancellation)
        - **Sync functions (Unix/Linux, main thread)**: Uses SIGALRM signal
        - **Sync functions (Windows or threads)**: Uses threading.Timer with async exception raising
    
    Behavior:
        - **Finally blocks**: Execute properly on timeout for both sync and async
        - **Context managers**: __exit__ methods are called with the timeout exception
        - **Resource cleanup**: Guaranteed to execute cleanup code
    
    Limitations:
        - **Async with blocking code**: Cannot interrupt blocking operations like time.sleep().
          Use proper async code (await asyncio.sleep()) instead.
        - **Nested timeouts (Unix)**: SIGALRM is process-wide, may conflict with nested timeouts
    
    Returns:
        Decorated function with timeout enforcement.
    
    Raises:
        DaytonaTimeoutError: When the function exceeds the specified timeout.
        DaytonaError: If timeout is negative.
    
    Example:
        ```python
        @with_timeout()
        async def create_resource(self, timeout=60):
            resource = None
            try:
                resource = await allocate_resource()
                await resource.initialize()
                return resource
            finally:
                # This cleanup ALWAYS executes, even on timeout
                if resource and not resource.initialized:
                    await resource.cleanup()
        ```
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        # Extract timeout from args/kwargs
        def _extract_timeout(args: tuple, kwargs: dict) -> Optional[float]:
            names = func.__code__.co_varnames[: func.__code__.co_argcount]
            bound = dict(zip(names, args))
            return kwargs.get("timeout", bound.get("timeout", None))

        if inspect.iscoroutinefunction(func):
            # Async function: Use asyncio.wait_for (works on all platforms)
            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                timeout = _extract_timeout(args, kwargs)
                if timeout is None or timeout == 0:
                    return await func(*args, **kwargs)
                if timeout < 0:
                    raise DaytonaError("Timeout must be a non-negative number or None.")

                # Use asyncio.wait_for with task cancellation
                # This executes finally blocks via CancelledError propagation
                task = asyncio.create_task(func(*args, **kwargs))
                
                try:
                    return await asyncio.wait_for(task, timeout=timeout)
                except asyncio.TimeoutError:
                    # wait_for already cancelled the task
                    # Wait briefly for cleanup to complete
                    try:
                        await asyncio.wait_for(task, timeout=0.1)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                    except Exception:
                        pass
                    
                    raise DaytonaTimeoutError(
                        f"Function '{func.__name__}' exceeded timeout of {timeout} seconds."
                    )  # pylint: disable=raise-missing-from
                except asyncio.CancelledError:
                    raise DaytonaTimeoutError(
                        f"Function '{func.__name__}' exceeded timeout of {timeout} seconds."
                    )  # pylint: disable=raise-missing-from

            return async_wrapper

        # Sync function: Use best available method
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            timeout = _extract_timeout(args, kwargs)
            if timeout is None or timeout == 0:
                return func(*args, **kwargs)
            if timeout < 0:
                raise DaytonaError("Timeout must be a non-negative number or None.")

            # Strategy 1: Unix/Linux main thread - use signals (fastest, most efficient)
            if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
                def _timeout_handler(signum, frame):
                    raise DaytonaTimeoutError(f"Function '{func.__name__}' exceeded timeout of {timeout} seconds.")

                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(int(timeout) + (1 if timeout % 1 > 0 else 0))

                try:
                    result = func(*args, **kwargs)
                    signal.alarm(0)
                    return result
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            
            # Strategy 2: Windows or non-main thread - use threading timeout (cross-platform)
            else:
                with _ThreadingTimeout(timeout, func.__name__):
                    return func(*args, **kwargs)

        return sync_wrapper

    return decorator
