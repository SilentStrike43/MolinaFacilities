# app/core/logging_config.py
"""
Centralized logging configuration for the application.
Provides structured logging with rotation and different levels.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Add colors to console logging for better readability."""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logging(app_name: str = "facilities_app", log_level: str = None, log_dir: str = None):
    """
    Configure application logging with file rotation and console output.
    
    Args:
        app_name: Application name for log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files (default: app/logs)
    """
    # Determine log level
    if log_level is None:
        log_level = os.environ.get('LOG_LEVEL', 'INFO')
    
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create logs directory
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / 'logs'
    else:
        log_dir = Path(log_dir)
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # ============== Console Handler ==============
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    console_format = ColoredFormatter(
        fmt='%(levelname)-8s [%(asctime)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # ============== File Handler (General) ==============
    # Rotating file handler - rotates at 10MB, keeps 5 backups
    general_log = log_dir / f'{app_name}.log'
    file_handler = logging.handlers.RotatingFileHandler(
        general_log,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    file_format = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)
    
    # ============== Error File Handler ==============
    # Separate file for errors and above
    error_log = log_dir / f'{app_name}_errors.log'
    error_handler = logging.handlers.RotatingFileHandler(
        error_log,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_format)
    root_logger.addHandler(error_handler)
    
    # ============== Security Audit Handler ==============
    # Dedicated handler for security events
    security_log = log_dir / f'{app_name}_security.log'
    security_handler = logging.handlers.RotatingFileHandler(
        security_log,
        maxBytes=10 * 1024 * 1024,
        backupCount=20,  # Keep more security logs
        encoding='utf-8'
    )
    security_handler.setLevel(logging.WARNING)
    
    # Only log security-related events to this file
    class SecurityFilter(logging.Filter):
        def filter(self, record):
            return 'SECURITY EVENT' in record.getMessage() or \
                   record.name.endswith('security') or \
                   record.name.endswith('auth')
    
    security_handler.addFilter(SecurityFilter())
    security_format = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(message)s | IP:%(ip_address)s | User:%(username)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        defaults={'ip_address': 'N/A', 'username': 'N/A'}
    )
    security_handler.setFormatter(security_format)
    root_logger.addHandler(security_handler)
    
    # ============== Database Handler ==============
    # Separate handler for database operations
    db_log = log_dir / f'{app_name}_database.log'
    db_handler = logging.handlers.RotatingFileHandler(
        db_log,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    db_handler.setLevel(logging.WARNING)
    
    class DatabaseFilter(logging.Filter):
        def filter(self, record):
            return 'database' in record.name.lower() or \
                   'sqlite' in record.getMessage().lower()
    
    db_handler.addFilter(DatabaseFilter())
    db_handler.setFormatter(file_format)
    root_logger.addHandler(db_handler)
    
    # ============== Request Handler (for Flask) ==============
    # Log all HTTP requests
    request_log = log_dir / f'{app_name}_requests.log'
    request_handler = logging.handlers.TimedRotatingFileHandler(
        request_log,
        when='midnight',
        interval=1,
        backupCount=30,  # Keep 30 days of request logs
        encoding='utf-8'
    )
    request_handler.setLevel(logging.INFO)
    
    request_format = logging.Formatter(
        fmt='%(asctime)s | %(method)s %(path)s | %(status)s | %(duration)sms | %(remote_addr)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        defaults={
            'method': 'N/A',
            'path': 'N/A',
            'status': 'N/A',
            'duration': 'N/A',
            'remote_addr': 'N/A'
        }
    )
    request_handler.setFormatter(request_format)
    
    # Get or create request logger
    request_logger = logging.getLogger('werkzeug')
    request_logger.addHandler(request_handler)
    
    # Reduce noise from external libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    logging.info(f"Logging initialized - Level: {log_level} | Directory: {log_dir}")
    
    return root_logger


def log_request(request, response, duration_ms: float):
    """
    Log HTTP request details.
    
    Args:
        request: Flask request object
        response: Flask response object
        duration_ms: Request duration in milliseconds
    """
    logger = logging.getLogger('werkzeug')
    
    # Skip static files and health checks
    if request.path.startswith('/static') or request.path == '/healthz':
        return
    
    logger.info(
        f"{request.method} {request.path}",
        extra={
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration': f'{duration_ms:.2f}',
            'remote_addr': request.remote_addr,
            'user_agent': request.user_agent.string[:100] if request.user_agent else 'N/A'
        }
    )


def setup_flask_logging(app):
    """
    Integrate logging with Flask application.
    
    Args:
        app: Flask application instance
    """
    import time
    from flask import request, g
    
    # Setup application logging
    log_level = app.config.get('LOG_LEVEL', 'INFO')
    setup_logging(app_name='facilities_app', log_level=log_level)
    
    # Attach request timing
    @app.before_request
    def start_timer():
        g.start_time = time.time()
    
    @app.after_request
    def log_request_info(response):
        if hasattr(g, 'start_time'):
            duration_ms = (time.time() - g.start_time) * 1000
            log_request(request, response, duration_ms)
        return response
    
    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(f"Flask application started - Environment: {app.config.get('ENV', 'production')}")
    logger.info(f"Debug mode: {app.debug}")


# Quick test if run directly
if __name__ == '__main__':
    logger = setup_logging('test_app', 'DEBUG')
    
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    
    # Test security logging
    security_logger = logging.getLogger('app.core.security')
    security_logger.warning(
        "SECURITY EVENT - failed_login: Test security event",
        extra={'ip_address': '192.168.1.1', 'username': 'testuser'}
    )
    
    print("\nCheck the logs directory for output files!")