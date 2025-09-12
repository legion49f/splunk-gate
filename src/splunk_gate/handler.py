import asyncio
import logging
import queue
import socket
import threading
import time
from typing import Any, Optional

import httpx
import tenacity

try:
    import uvloop
except ImportError:
    uvloop = None


def _write_to_console(debug: bool, message: str):
    if debug:
        print(message)


class _AIOHandler:
    """An asynchronous handler to send log events to Splunk using httpx and asyncio."""

    def __init__(
        self,
        url: str,
        hostname: str,
        index: str,
        source: str,
        sourcetype: str,
        queue: queue.Queue,
        session: httpx.AsyncClient,
        timeout: float,
        target_request_size: int,
        flush_interval: float,
        retry_multiplier: int,
        retry_min_wait: int,
        retry_max_wait: int,
        retry_max_attempts: int,
        debug: bool = False,
    ):
        self._url = url
        self._hostname = hostname
        self._index = index
        self._source = source
        self._sourcetype = sourcetype
        self._queue = queue
        self._session = session
        self._timeout = timeout
        self._target_request_size = target_request_size
        self._flush_interval = flush_interval
        self._debug = debug

        # Set up the retry decorator for sending events
        retry_decorator = tenacity.retry(
            wait=tenacity.wait_exponential(
                multiplier=retry_multiplier, min=retry_min_wait, max=retry_max_wait
            ),
            stop=tenacity.stop_after_attempt(retry_max_attempts),
            reraise=True,
        )
        self.send_with_retry = retry_decorator(self._send)

        # Pre-calculate the overhead bytes for each log record to estimate request sizes
        self._map_bytes: int = (
            len(self._hostname.encode("utf-8"))
            + len(self._index.encode("utf-8"))
            + len(self._source.encode("utf-8"))
            + len(self._sourcetype.encode("utf-8"))
            + 50  # Extra bytes for JSON formatting and other fields
        )
        self._should_stop = False
        if uvloop is not None:
            _write_to_console(self._debug, "Using uvloop event loop")
            self._event_loop = uvloop.new_event_loop()
        else:
            _write_to_console(self._debug, "Using default asyncio event loop")
            self._event_loop = asyncio.new_event_loop()

    @property
    def should_stop(self) -> bool:
        return self._should_stop

    @should_stop.setter
    def should_stop(self, value: bool):
        self._should_stop = value

    def _size(self, record: str) -> int:
        size = len(record.encode("utf-8")) + self._map_bytes
        return size

    def _payload(self, records: list[str]) -> Any:
        return [
            {
                "time": time.time(),
                "host": self._hostname,
                "index": self._index,
                "source": self._source,
                "sourcetype": self._sourcetype,
                "event": r,
            }
            for r in records
        ]

    async def _send(self, payload: list[dict], size: int):
        _write_to_console(self._debug, f"Sending {len(payload)} records to Splunk")
        _write_to_console(self._debug, f"Payload size: {size} bytes")
        _write_to_console(self._debug, f"Payload content: {payload}")
        response = await self._session.post(self._url, json=payload, timeout=self._timeout)
        _write_to_console(
            self._debug, f"Splunk response status: {response.status_code}, body: {response.text}"
        )
        response.raise_for_status()

    async def _send_events(self, records: list[str], size: int):
        try:
            payload = self._payload(records)
            await self.send_with_retry(payload, size)
        except httpx.HTTPError as e:
            _write_to_console(self._debug, f"SplunkHandler failed to send logs with error: {e!r}")

    async def _run(self):
        _write_to_console(self._debug, "Starting SplunkHandler run loop")

        to_send: list[str] = []
        current_size = 0
        last_flush = time.time()
        while not self.should_stop:
            # If should_stop is set and there are no events to send, close the session and exit
            if self.should_stop and not to_send:
                _write_to_console(self._debug, "Got stop signal for SplunkHandler run loop")
                break
            try:
                # Flush if the flush interval has passed and there are events to send
                if last_flush + self._flush_interval <= time.time() and to_send:
                    _write_to_console(self._debug, "Flushing due to flush interval")
                    asyncio.create_task(self._send_events(to_send, current_size))
                    to_send = []
                    current_size = 0
                    last_flush = time.time()

                record = self._queue.get_nowait()
                size = self._size(record)

                # If adding this record exceeds the target request size, send the current batch first
                if current_size + size > self._target_request_size and to_send:
                    _write_to_console(self._debug, "Flushing due to target request size")
                    asyncio.create_task(self._send_events(to_send, current_size))
                    to_send = []
                    current_size = 0
                    last_flush = time.time()

                to_send.append(record)
                current_size += size

            except queue.Empty:
                # If there are events to send and the flush interval has passed, send them
                if to_send:
                    _write_to_console(self._debug, "Flushing due to flush interval since last event")
                    asyncio.create_task(self._send_events(to_send, current_size))
                    to_send = []
                    current_size = 0
                    last_flush = time.time()
                await asyncio.sleep(0.1)

    def start(self):
        """Run the asynchronous event loop to process log records."""
        asyncio.set_event_loop(self._event_loop)
        main_task = self._event_loop.create_task(self._run())

        try:
            self._event_loop.run_forever()
        finally:
            if not main_task.done():
                main_task.cancel()
                _write_to_console(self._debug, "Main task cancelled")

            closing_tasks = [self._session.aclose(), self._event_loop.shutdown_asyncgens()]
            self._event_loop.run_until_complete(
                asyncio.gather(*closing_tasks, return_exceptions=True)
            )
            self._event_loop.close()

    def stop(self):
        """Stop the event loop and close the session."""
        self.should_stop = True
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)


class SplunkHandler(logging.Handler):
    """
    A logging handler to send events to a Splunk Enterprise instance
    running the Splunk HTTP Event Collector.
    """

    def __init__(
        self,
        host: str,
        token: str,
        index: str,
        source: str,
        sourcetype: str,
        port: Optional[int] = None,
        timeout: float = 8.0,
        flush_interval: float = 5.0,
        force_keep_ahead: bool = False,
        protocol: str = "https",
        verify: bool = True,
        hostname: Optional[str] = None,
        session: Optional[httpx.AsyncClient] = None,
        max_log_buffer_size: int = 50000,
        target_request_size: int = 15 * 1024 * 1024,  # 15 Mb
        retry_multiplier: int = 2,
        retry_min_wait: int = 4,
        retry_max_wait: int = 30,
        retry_max_attempts: int = 3,
        debug: bool = False,
    ):
        """
        Args:
            host (str): The hostname or IP address of the Splunk server.
            token (str): The authentication token for the Splunk HTTP Event Collector.
            index (str): The index to which events will be sent.
            source (str): The source field for the events.
            sourcetype (str): The sourcetype field for the events.
            port (int): The port number of the Splunk HTTP Event Collector.
            timeout (float, optional): The timeout in seconds for HTTP requests. Defaults to 8.0 seconds.
            flush_interval (float, optional): The interval in seconds to flush the event buffer. Defaults to 5.0 seconds.
            force_keep_ahead (bool, optional): If True, forces the handler to keep ahead of the flush interval. Defaults to False.
            protocol (str, optional): The protocol to use ('http' or 'https'). Defaults to 'https'.
            verify (bool, optional): Whether to verify SSL certificates. Defaults to True.
            hostname (Optional[str], optional): The hostname to include in the event data. Defaults to socket.gethostname().
            session (Optional[httpx.AsyncClient], optional): An optional httpx.AsyncClient session for making requests. If None, a new session will be created. Defaults to None.
            max_log_buffer_size (int, optional): The maximum number of log records to buffer. If the buffer exceeds this size, new log records will be dropped.
                                                 Set to 0 for unlimited buffer size but be cautious of high memory usage.
            target_request_size (int, optional): The target size in bytes for each HTTP request. Defaults to 50 * 1024 * 1024 (50 MB).
            retry_multiplier (int, optional): The multiplier for exponential backoff between retries. Defaults to 2.
            retry_min_wait (int, optional): The minimum wait time in seconds between retries. Defaults to 4 seconds.
            retry_max_wait (int, optional): The maximum wait time in seconds between retries. Defaults to 30 seconds.
            retry_max_attempts (int, optional): The maximum number of retry attempts for sending events. Defaults to 3.
            debug (bool, optional): If True, prints debug information to the console. Defaults to False.
        Raises:
            ValueError: If the provided session is not an instance of httpx.AsyncClient.
        """
        logging.Handler.__init__(self)

        # prevent infinite recursion by silencing httpcore and httpx loggers
        logging.getLogger("httpx").propagate = False
        logging.getLogger("httpcore.http11").propagate = False
        logging.getLogger("httpcore.connection").propagate = False

        # and do the same for ourselves
        logging.getLogger(__name__).propagate = False

        self._index = index
        self._source = source
        self._sourcetype = sourcetype
        self._flush_interval = flush_interval
        self._force_keep_ahead = force_keep_ahead
        self._verify = verify
        self._hostname = hostname or socket.gethostname()
        self._queue: queue.Queue[str] = (
            queue.Queue(maxsize=max_log_buffer_size) if max_log_buffer_size > 0 else queue.Queue()
        )
        if port is not None:
            self._url = f"{protocol}://{host}:{port}/services/collector/event"
        else:
            self._url = f"{protocol}://{host}/services/collector/event"

        if session and not isinstance(session, httpx.AsyncClient):
            raise ValueError("session must be an instance of httpx.AsyncClient or None")
        if session:
            self._session = session
            self._session.headers.update({"Authorization": f"Splunk {token}"})
        else:
            self._session = httpx.AsyncClient(
                headers={"Authorization": f"Splunk {token}"}, verify=self._verify
            )
        self._debug = debug

        self._handler = _AIOHandler(
            url=self._url,
            hostname=self._hostname,
            index=self._index,
            source=self._source,
            sourcetype=self._sourcetype,
            queue=self._queue,
            session=self._session,
            timeout=timeout,
            flush_interval=flush_interval,
            target_request_size=target_request_size,
            retry_multiplier=retry_multiplier,
            retry_min_wait=retry_min_wait,
            retry_max_wait=retry_max_wait,
            retry_max_attempts=retry_max_attempts,
            debug=debug,
        )
        _write_to_console(debug, "Starting SplunkHandler background thread")
        self._thread = threading.Thread(target=self._handler.start, daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord):
        """Emit a log record."""
        _write_to_console(self._debug, f"Queue size before emit: {self._queue.qsize()}")
        # If force keep_ahead is enabled, block if the queue is full.
        _record = self.format(record)
        if self._force_keep_ahead:
            _write_to_console(self._debug, "Queue full, blocking until space is available")
            self._queue.put(_record, block=True)
            _write_to_console(self._debug, f"Queue size after emit: {self._queue.qsize()}")

        # Otherwise, try to add the record to the queue without blocking and wait at most flush_interval seconds.
        else:
            try:
                self._queue.put(_record, block=False, timeout=self._flush_interval)
                _write_to_console(self._debug, f"Queue size after emit: {self._queue.qsize()}")
            except queue.Full:
                _write_to_console(self._debug, "SplunkHandler log buffer full dropping log record")

    def close(self):
        """Close the handler and wait for the background thread to finish."""
        self._handler.should_stop = True
        self._thread.join(timeout=self._flush_interval + 1)
        logging.Handler.close(self)
