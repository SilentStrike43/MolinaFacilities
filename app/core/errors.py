# app/core/errors.py
"""
Centralized error handling for the application.
Provides consistent error responses and logging.
"""

import logging
import traceback
from typing import Optional, Tuple
from flask import Flask, render_template, jsonify, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


# ==================== Custom Exceptions ====================

class AppError(Exception):
    """Base exception for application errors."""
    status_code = 500
    
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__()
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload or {}
    
    def to_dict(self):
        rv = dict(self.payload)
        rv['error'] = self.message
        rv['status'] = self.status_code
        return rv


class ValidationError(AppError):
    """Raised when input validation fails."""
    status_code = 400


class AuthenticationError(AppError):
    """Raised when authentication fails."""
    status_code = 401


class AuthorizationError(AppError):
    """Raised when authorization fails."""
    status_code = 403


class NotFoundError(AppError):
    """Raised when a resource is not found."""
    status_code = 404


class ConflictError(AppError):
    """Raised when there's a conflict (e.g., duplicate entry)."""
    status_code = 409


class DatabaseError(AppError):
    """Raised when database operations fail."""
    status_code = 500


# ==================== Error Handlers ====================

def register_error_handlers(app: Flask):
    """Register all error handlers with the Flask app."""
    
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        """Handle custom application errors."""
        logger.warning(f"Application error: {error.message}", extra={'status': error.status_code})
        
        if request.is_json or request.path.startswith('/api/'):
            return jsonify(error.to_dict()), error.status_code
        
        return render_template(
            'error.html',
            error_code=error.status_code,
            error_message=error.message,
            show_details=app.debug
        ), error.status_code
    
    @app.errorhandler(404)
    def handle_404(error):
        """Handle 404 Not Found errors."""
        logger.info(f"404 Not Found: {request.path}")
        
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'Resource not found', 'status': 404}), 404
        
        return render_template(
            'error.html',
            error_code=404,
            error_message="The page you're looking for doesn't exist.",
            show_details=False
        ), 404
    
    @app.errorhandler(403)
    def handle_403(error):
        """Handle 403 Forbidden errors."""
        logger.warning(f"403 Forbidden: {request.path} by {request.remote_addr}")
        
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'Access forbidden', 'status': 403}), 403
        
        return render_template(
            'error.html',
            error_code=403,
            error_message="You don't have permission to access this resource.",
            show_details=False
        ), 403
    
    @app.errorhandler(500)
    def handle_500(error):
        """Handle 500 Internal Server Error."""
        logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        
        if request.is_json or request.path.startswith('/api/'):
            response = {'error': 'Internal server error', 'status': 500}
            if app.debug:
                response['details'] = str(error)
            return jsonify(response), 500
        
        return render_template(
            'error.html',
            error_code=500,
            error_message="An internal error occurred. Please try again later.",
            error_details=str(error) if app.debug else None,
            show_details=app.debug
        ), 500
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        """Handle all other HTTP exceptions."""
        logger.warning(f"HTTP {error.code}: {error.description}")
        
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({
                'error': error.description,
                'status': error.code
            }), error.code
        
        return render_template(
            'error.html',
            error_code=error.code,
            error_message=error.description,
            show_details=False
        ), error.code
    
    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        """Handle any unexpected exceptions."""
        # Log full traceback
        logger.critical(
            f"Unexpected error: {type(error).__name__}: {error}",
            exc_info=True,
            extra={
                'path': request.path,
                'method': request.method,
                'remote_addr': request.remote_addr
            }
        )
        
        if request.is_json or request.path.startswith('/api/'):
            response = {'error': 'An unexpected error occurred', 'status': 500}
            if app.debug:
                response['details'] = str(error)
                response['traceback'] = traceback.format_exc()
            return jsonify(response), 500
        
        return render_template(
            'error.html',
            error_code=500,
            error_message="An unexpected error occurred. Please contact support.",
            error_details=traceback.format_exc() if app.debug else None,
            show_details=app.debug
        ), 500


# ==================== Error Logging Utilities ====================

def log_security_event(event_type: str, details: str, severity: str = "warning"):
    """
    Log security-related events.
    
    Args:
        event_type: Type of security event (e.g., "failed_login", "unauthorized_access")
        details: Event details
        severity: Log severity ("info", "warning", "error", "critical")
    """
    log_func = getattr(logger, severity, logger.warning)
    log_func(
        f"SECURITY EVENT - {event_type}: {details}",
        extra={
            'event_type': event_type,
            'remote_addr': request.remote_addr if request else 'N/A',
            'user_agent': request.user_agent.string if request else 'N/A',
            'path': request.path if request else 'N/A'
        }
    )


def log_data_error(operation: str, error: Exception, context: Optional[dict] = None):
    """
    Log data-related errors with context.
    
    Args:
        operation: Operation being performed (e.g., "create_user", "update_asset")
        error: The exception that occurred
        context: Additional context (e.g., user_id, asset_id)
    """
    logger.error(
        f"Data error during {operation}: {type(error).__name__}: {error}",
        exc_info=True,
        extra={
            'operation': operation,
            'error_type': type(error).__name__,
            'context': context or {}
        }
    )


# ==================== Safe Error Messages ====================

def get_safe_error_message(error: Exception, default: str = "An error occurred") -> str:
    """
    Get a user-safe error message.
    Hides technical details from users while logging them internally.
    
    Args:
        error: The exception
        default: Default message if error message is too technical
    
    Returns:
        User-friendly error message
    """
    # If it's one of our custom errors, use its message
    if isinstance(error, AppError):
        return error.message
    
    # Map common exceptions to user-friendly messages
    error_type = type(error).__name__
    
    friendly_messages = {
        'IntegrityError': 'This record already exists or violates a constraint',
        'OperationalError': 'Database operation failed. Please try again',
        'FileNotFoundError': 'The requested file was not found',
        'PermissionError': 'Permission denied',
        'ValueError': 'Invalid value provided',
        'KeyError': 'Required data is missing',
        'TimeoutError': 'The operation timed out. Please try again',
    }
    
    return friendly_messages.get(error_type, default)


# ==================== Context Managers for Error Handling ====================

from contextlib import contextmanager

@contextmanager
def handle_errors(operation: str, default_message: str = "Operation failed", 
                  raise_on_error: bool = False):
    """
    Context manager for consistent error handling.
    
    Usage:
        with handle_errors("create_user", "Failed to create user"):
            # Your code here
            create_user_in_db(...)
    
    Args:
        operation: Name of the operation for logging
        default_message: Default error message for users
        raise_on_error: Whether to re-raise the exception after handling
    """
    try:
        yield
    except AppError:
        # Re-raise our custom errors
        raise
    except Exception as e:
        # Log the error with full context
        log_data_error(operation, e)
        
        # Get a safe message for the user
        safe_message = get_safe_error_message(e, default_message)
        
        if raise_on_error:
            raise AppError(safe_message) from e
        else:
            from flask import flash
            flash(safe_message, "danger")


# ==================== Decorator for Safe Routes ====================

from functools import wraps

def safe_route(operation: str = None, default_error: str = "An error occurred"):
    """
    Decorator to wrap routes with error handling.
    
    Usage:
        @app.route('/users/create')
        @safe_route(operation="create_user", default_error="Failed to create user")
        def create_user():
            # Your code here
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            try:
                return func(*args, **kwargs)
            except AppError:
                raise  # Let the error handler deal with it
            except Exception as e:
                log_data_error(op_name, e)
                raise AppError(get_safe_error_message(e, default_error))
        return wrapper
    return decorator