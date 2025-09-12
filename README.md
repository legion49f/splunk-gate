# splunk-gate

A high-performance asynchronous Splunk logging handler for Python applications.

[![PyPI version](https://img.shields.io/pypi/v/splunk-gate.svg)](https://pypi.org/project/splunk-gate/)
[![Python versions](https://img.shields.io/pypi/pyversions/splunk-gate.svg)](https://pypi.org/project/splunk-gate/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

`splunk-gate` provides an efficient way to send log events from Python applications to Splunk Enterprise instances running the Splunk HTTP Event Collector (HEC). It's designed with performance in mind, featuring asynchronous processing, intelligent batching, and robust retry mechanisms.

### Key Features

- **🚀 Asynchronous processing** - Non-blocking logging that won't slow down your application
- **📦 Efficient batching** - Smart aggregation of logs to reduce HTTP requests
- **🔄 Automatic retries** - Built-in exponential backoff for handling network issues
- **💾 Configurable buffer size** - Control memory usage with queue size limits
- **⚡ Performance optimization** - Optional uvloop support for enhanced speed
- **🛡️ Robust error handling** - Graceful handling of network failures and timeouts
- **🔧 Highly configurable** - Extensive customization options for different use cases

## Installation

```bash
pip install splunk-gate
```

For improved performance, install with the optional uvloop dependency:

```bash
pip install splunk-gate[uvloop]
```

## Quick Start

```python
import logging
from splunk_gate import SplunkHandler

# Configure the Splunk handler
splunk_handler = SplunkHandler(
    host="splunk.example.com",
    token="your-splunk-hec-token",
    index="main",
    source="my_application",
    sourcetype="python_logs"
)

# Add the handler to your logger
logger = logging.getLogger("my_app")
logger.setLevel(logging.INFO)
logger.addHandler(splunk_handler)

# Start logging!
logger.info("Application started successfully")
logger.error("Something went wrong", exc_info=True)

# Make sure to close the handler when your application exits
# This ensures all pending log events are sent to Splunk
splunk_handler.close()
```

## Configuration Options

The `SplunkHandler` class accepts many configuration options to customize its behavior:

```python
splunk_handler = SplunkHandler(
    # Required parameters
    host="splunk.example.com",             # Splunk host
    token="your-splunk-hec-token",         # HEC token
    index="main",                          # Splunk index
    source="my_application",               # Source name
    sourcetype="python_logs",              # Sourcetype
    
    # Optional parameters
    port=8088,                             # Port (default: 8088)
    timeout=8.0,                           # HTTP request timeout in seconds
    flush_interval=5.0,                    # How often to flush the event buffer
    force_keep_ahead=False,                # Block if buffer is full
    protocol="https",                      # HTTP or HTTPS
    verify=True,                           # Verify SSL certificates
    hostname="custom-hostname",            # Override hostname in events
    max_log_buffer_size=50000,             # Maximum buffer size (0 = unlimited)
    target_request_size=15 * 1024 * 1024,  # Target batch size in bytes (15MB)
    retry_multiplier=2,                    # Retry backoff multiplier
    retry_min_wait=4,                      # Minimum retry wait time in seconds
    retry_max_wait=30,                     # Maximum retry wait time in seconds
    retry_max_attempts=3,                  # Maximum number of retry attempts
    debug=False                            # Enable debug output
)
```

### Parameter Details

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | **Required** | Splunk server hostname or IP address |
| `token` | str | **Required** | Splunk HTTP Event Collector token |
| `index` | str | **Required** | Target Splunk index |
| `source` | str | **Required** | Source field for events |
| `sourcetype` | str | **Required** | Sourcetype field for events |
| `port` | int | `8088` | Splunk HEC port |
| `timeout` | float | `8.0` | HTTP request timeout in seconds |
| `flush_interval` | float | `5.0` | Buffer flush interval in seconds |
| `force_keep_ahead` | bool | `False` | Block when buffer is full |
| `protocol` | str | `"https"` | Protocol (http/https) |
| `verify` | bool | `True` | Verify SSL certificates |
| `hostname` | str | `socket.gethostname()` | Hostname for events |
| `max_log_buffer_size` | int | `50000` | Maximum buffer size (0 = unlimited) |
| `target_request_size` | int | `15MB` | Target batch size in bytes |

## Advanced Usage

### Custom HTTP Session

For advanced users, you can provide a custom `httpx.AsyncClient` session:

```python
import httpx
from splunk_gate import SplunkHandler

# Create a custom session with specific parameters
session = httpx.AsyncClient(
    limits=httpx.Limits(
        max_connections=20, 
        max_keepalive_connections=10
    ),
    timeout=10.0
)

# Use the custom session
splunk_handler = SplunkHandler(
    host="splunk.example.com",
    token="your-splunk-hec-token",
    index="main",
    source="my_application",
    sourcetype="python_logs",
    session=session
)
```

### Context Manager Usage

```python
from splunk_gate import SplunkHandler
import logging

# Use as a context manager to ensure proper cleanup
with SplunkHandler(
    host="splunk.example.com",
    token="your-token",
    index="main",
    source="my_app",
    sourcetype="python_logs"
) as handler:
    logger = logging.getLogger("my_app")
    logger.addHandler(handler)
    logger.info("This will be sent to Splunk")
    # Handler is automatically closed when exiting the context
```

### Structured Logging

```python
import logging
import json
from splunk_gate import SplunkHandler

# Configure for structured logging
splunk_handler = SplunkHandler(
    host="splunk.example.com",
    token="your-token",
    index="main",
    source="my_app",
    sourcetype="_json"  # Use _json sourcetype for automatic field extraction
)

logger = logging.getLogger("my_app")
logger.addHandler(splunk_handler)

# Log structured data
event_data = {
    "user_id": "12345",
    "action": "login",
    "success": True,
    "ip_address": "192.168.1.100"
}

logger.info(json.dumps(event_data))
```

## Performance Considerations

### Optimizing for High-Volume Logging

1. **Batch Size**: The default `target_request_size` of 15MB is suitable for most applications. For high-volume scenarios, consider increasing this value:

```python
# For high-volume logging
splunk_handler = SplunkHandler(
    # ... other parameters ...
    target_request_size=50 * 1024 * 1024,  # 50MB batches
    flush_interval=10.0,  # Longer flush interval
    max_log_buffer_size=100000  # Larger buffer
)
```

2. **Buffer Management**: 
   - Set `max_log_buffer_size=0` for unlimited buffering (monitor memory usage)
   - Use `force_keep_ahead=True` to prevent log loss when buffer is full
   - Adjust `flush_interval` based on your latency requirements

3. **uvloop Integration**: Install uvloop for improved event loop performance:

```bash
pip install splunk-gate[uvloop]
```

### Memory Usage Guidelines

- Default buffer size (50,000 records) typically uses ~50-100MB of memory
- Each log record consumes approximately 1-2KB in memory
- Monitor memory usage in high-volume applications

## Error Handling

The handler includes comprehensive error handling:

### Retry Mechanism

- **Exponential backoff**: Automatically retries failed requests with increasing delays
- **Configurable retry attempts**: Set `retry_max_attempts` to control retry behavior
- **Network resilience**: Handles temporary network failures gracefully

### Buffer Overflow Protection

```python
# Configure buffer overflow behavior
splunk_handler = SplunkHandler(
    # ... other parameters ...
    max_log_buffer_size=10000,      # Limit buffer size
    force_keep_ahead=True,          # Block instead of dropping logs
    debug=True                      # Enable debug output for monitoring
)
```

When `force_keep_ahead=True`:
- Application blocks if buffer becomes full
- Prevents log loss but may impact application performance

When `force_keep_ahead=False` (default):
- New log events are dropped when buffer is full
- Application continues running without blocking

## Production Deployment

### Recommended Settings

```python
# Production-ready configuration
splunk_handler = SplunkHandler(
    host="splunk.production.com",
    token=os.environ["SPLUNK_HEC_TOKEN"],  # Use environment variables
    index="application_logs",
    source="my_service",
    sourcetype="python_app",
    
    # Performance settings
    target_request_size=25 * 1024 * 1024,  # 25MB
    flush_interval=10.0,                    # 10 seconds
    max_log_buffer_size=100000,             # 100k records
    
    # Reliability settings
    retry_max_attempts=5,
    retry_max_wait=60,
    timeout=15.0,
    
    # Security settings
    verify=True,
    protocol="https"
)
```

### Health Monitoring

```python
import logging
from splunk_gate import SplunkHandler

# Enable debug mode for monitoring
splunk_handler = SplunkHandler(
    # ... configuration ...
    debug=True  # Enables console output for monitoring
)

# Monitor handler health
logger = logging.getLogger("health_check")
logger.addHandler(splunk_handler)

# This will output debug information to console
logger.info("Health check message")
```

## Requirements

- Python 3.9+
- httpx >= 0.28.1
- tenacity >= 9.1.2
- uvloop >= 0.21.0 (optional, for improved performance)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/legion49f/splunk-gate.git
cd splunk-gate

# Install development dependencies
pip install poetry
poetry install --with dev,uvloop

# Run tests
poetry run pytest

# Format code
poetry run ruff format

# Lint code
poetry run ruff check
```

## Support

For questions, issues, or feature requests, please open an issue on the [GitHub repository](https://github.com/legion49f/splunk-gate).

## Acknowledgments

- Built with [httpx](https://www.python-httpx.org/) for async HTTP requests
- Retry functionality powered by [tenacity](https://github.com/jd/tenacity)
- Optional performance enhancement with [uvloop](https://github.com/MagicStack/uvloop)

---

*Inspired by [splunk-handler](https://github.com/zach-taylor/splunk_handler), reimagined for modern asynchronous Python applications.*

