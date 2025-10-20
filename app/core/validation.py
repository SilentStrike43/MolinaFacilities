# app/core/validation.py
"""
Input validation and sanitization utilities.
Protects against SQL injection, XSS, and invalid data.
"""

import re
import html
import logging
from typing import Any, Optional, List, Dict
from datetime import datetime
from functools import wraps
from flask import request, flash, redirect, url_for

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


# ==================== Basic Sanitization ====================

def sanitize_string(value: Any, max_length: Optional[int] = None, allow_empty: bool = False) -> str:
    """
    Sanitize a string input.
    
    Args:
        value: Input value
        max_length: Maximum allowed length
        allow_empty: Whether to allow empty strings
    
    Returns:
        Sanitized string
    
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        if allow_empty:
            return ""
        raise ValidationError("Value cannot be None")
    
    # Convert to string and strip whitespace
    value = str(value).strip()
    
    if not value and not allow_empty:
        raise ValidationError("Value cannot be empty")
    
    # Check length
    if max_length and len(value) > max_length:
        raise ValidationError(f"Value exceeds maximum length of {max_length}")
    
    # Remove null bytes and other control characters
    value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
    
    return value


def sanitize_html(value: str) -> str:
    """Escape HTML characters to prevent XSS."""
    if not value:
        return ""
    return html.escape(str(value).strip())


def sanitize_sql_like(value: str) -> str:
    """
    Sanitize input for SQL LIKE queries.
    Escapes special characters: % _ [ ]
    """
    if not value:
        return ""
    
    value = str(value).strip()
    # Escape LIKE wildcards
    value = value.replace('\\', '\\\\')  # Escape backslash first
    value = value.replace('%', '\\%')
    value = value.replace('_', '\\_')
    value = value.replace('[', '\\[')
    value = value.replace(']', '\\]')
    
    return value


# ==================== Type Validation ====================

def validate_integer(
    value: Any,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    allow_none: bool = False
) -> Optional[int]:
    """Validate and convert to integer."""
    if value is None or value == "":
        if allow_none:
            return None
        raise ValidationError("Integer value is required")
    
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid integer: {value}")
    
    if min_value is not None and value < min_value:
        raise ValidationError(f"Value must be at least {min_value}")
    
    if max_value is not None and value > max_value:
        raise ValidationError(f"Value must be at most {max_value}")
    
    return value


def validate_float(
    value: Any,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    allow_none: bool = False
) -> Optional[float]:
    """Validate and convert to float."""
    if value is None or value == "":
        if allow_none:
            return None
        raise ValidationError("Float value is required")
    
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid number: {value}")
    
    if min_value is not None and value < min_value:
        raise ValidationError(f"Value must be at least {min_value}")
    
    if max_value is not None and value > max_value:
        raise ValidationError(f"Value must be at most {max_value}")
    
    return value


def validate_date(value: str, format: str = "%Y-%m-%d", allow_empty: bool = False) -> Optional[str]:
    """
    Validate date string.
    
    Args:
        value: Date string to validate
        format: Expected date format
        allow_empty: Whether to allow empty strings
    
    Returns:
        Validated date string or None
    """
    if not value or value == "":
        if allow_empty:
            return None
        raise ValidationError("Date is required")
    
    try:
        datetime.strptime(value, format)
        return value
    except ValueError:
        raise ValidationError(f"Invalid date format. Expected: {format}")


def validate_email(email: str, allow_empty: bool = False) -> Optional[str]:
    """Validate email address format."""
    if not email or email == "":
        if allow_empty:
            return None
        raise ValidationError("Email is required")
    
    email = email.strip().lower()
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValidationError("Invalid email format")
    
    if len(email) > 254:  # RFC 5321
        raise ValidationError("Email address too long")
    
    return email


def validate_username(username: str) -> str:
    """
    Validate username format.
    Must be alphanumeric with optional underscores, hyphens, and periods.
    """
    if not username:
        raise ValidationError("Username is required")
    
    username = username.strip()
    
    if len(username) < 3:
        raise ValidationError("Username must be at least 3 characters")
    
    if len(username) > 50:
        raise ValidationError("Username must be at most 50 characters")
    
    # Allow alphanumeric, underscore, hyphen, period
    if not re.match(r'^[a-zA-Z0-9._-]+$', username):
        raise ValidationError("Username can only contain letters, numbers, and ._-")
    
    # Don't allow leading/trailing special chars
    if username[0] in '._-' or username[-1] in '._-':
        raise ValidationError("Username cannot start or end with special characters")
    
    return username


def validate_password(password: str, min_length: int = 8) -> str:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        min_length: Minimum password length
    
    Returns:
        Validated password
    """
    if not password:
        raise ValidationError("Password is required")
    
    if len(password) < min_length:
        raise ValidationError(f"Password must be at least {min_length} characters")
    
    if len(password) > 128:
        raise ValidationError("Password is too long")
    
    # Check for basic complexity (at least one letter and one number)
    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)
    
    if not (has_letter and has_number):
        raise ValidationError("Password must contain both letters and numbers")
    
    return password


# ==================== Enum/Choice Validation ====================

def validate_choice(value: Any, choices: List[Any], allow_none: bool = False) -> Optional[Any]:
    """
    Validate that value is in allowed choices.
    
    Args:
        value: Value to validate
        choices: List of allowed values
        allow_none: Whether None is allowed
    
    Returns:
        Validated value
    """
    if value is None or value == "":
        if allow_none:
            return None
        raise ValidationError("Value is required")
    
    if value not in choices:
        raise ValidationError(f"Invalid choice. Must be one of: {', '.join(map(str, choices))}")
    
    return value


# ==================== File Validation ====================

def validate_filename(filename: str, allowed_extensions: Optional[List[str]] = None) -> str:
    """
    Validate uploaded filename.
    
    Args:
        filename: Original filename
        allowed_extensions: List of allowed extensions (e.g., ['pdf', 'jpg'])
    
    Returns:
        Validated filename
    """
    if not filename:
        raise ValidationError("Filename is required")
    
    # Remove directory paths
    filename = filename.split('/')[-1].split('\\')[-1]
    
    if len(filename) > 255:
        raise ValidationError("Filename too long")
    
    # Check for null bytes
    if '\x00' in filename:
        raise ValidationError("Invalid filename")
    
    if allowed_extensions:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in allowed_extensions:
            raise ValidationError(f"File type not allowed. Allowed: {', '.join(allowed_extensions)}")
    
    return filename


def validate_file_size(file_size: int, max_size_mb: int = 10) -> int:
    """Validate file size in bytes."""
    max_bytes = max_size_mb * 1024 * 1024
    
    if file_size <= 0:
        raise ValidationError("File is empty")
    
    if file_size > max_bytes:
        raise ValidationError(f"File size exceeds {max_size_mb}MB limit")
    
    return file_size


# ==================== Form Validation Decorators ====================

def validate_form_fields(**field_validators):
    """
    Decorator to validate form fields automatically.
    
    Usage:
        @validate_form_fields(
            username=lambda v: validate_username(v),
            email=lambda v: validate_email(v, allow_empty=True),
            age=lambda v: validate_integer(v, min_value=0, max_value=120)
        )
        def my_route():
            # Access validated data via g.validated_data
            username = g.validated_data['username']
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import g
            
            validated = {}
            errors = []
            
            for field_name, validator in field_validators.items():
                try:
                    value = request.form.get(field_name)
                    validated[field_name] = validator(value)
                except ValidationError as e:
                    errors.append(f"{field_name}: {str(e)}")
                    logger.warning(f"Validation error for {field_name}: {e}")
            
            if errors:
                for error in errors:
                    flash(error, "danger")
                return redirect(request.referrer or url_for('home'))
            
            g.validated_data = validated
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ==================== SQL Query Validation ====================

def validate_sql_identifier(identifier: str) -> str:
    """
    Validate SQL identifier (table/column name).
    Only allow alphanumeric and underscores.
    """
    if not identifier:
        raise ValidationError("Identifier cannot be empty")
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        raise ValidationError("Invalid SQL identifier")
    
    if len(identifier) > 64:
        raise ValidationError("Identifier too long")
    
    # Check for SQL keywords
    sql_keywords = {
        'select', 'insert', 'update', 'delete', 'drop', 'create',
        'alter', 'table', 'from', 'where', 'order', 'by', 'group'
    }
    if identifier.lower() in sql_keywords:
        raise ValidationError(f"'{identifier}' is a reserved SQL keyword")
    
    return identifier


def build_safe_like_query(field: str, value: str) -> tuple:
    """
    Build a safe LIKE query with parameterized values.
    
    Args:
        field: Column name (will be validated)
        value: Search value (will be sanitized)
    
    Returns:
        Tuple of (sql_fragment, parameter)
    
    Example:
        sql, param = build_safe_like_query("username", user_input)
        query = f"SELECT * FROM users WHERE {sql}"
        cursor.execute(query, (param,))
    """
    field = validate_sql_identifier(field)
    value = sanitize_sql_like(value)
    return f"{field} LIKE ?", f"%{value}%"


# ==================== Bulk Validation ====================

def validate_request_data(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate multiple form fields at once.
    
    Args:
        schema: Dictionary of {field_name: validator_function}
    
    Returns:
        Dictionary of validated data
    
    Raises:
        ValidationError: If any validation fails
    
    Example:
        validated = validate_request_data({
            'username': lambda v: validate_username(v),
            'age': lambda v: validate_integer(v, min_value=0),
            'email': lambda v: validate_email(v, allow_empty=True)
        })
    """
    validated = {}
    errors = []
    
    for field_name, validator in schema.items():
        try:
            value = request.form.get(field_name)
            validated[field_name] = validator(value)
        except ValidationError as e:
            errors.append(f"{field_name}: {str(e)}")
            logger.warning(f"Validation failed for {field_name}: {e}")
    
    if errors:
        raise ValidationError("; ".join(errors))
    
    return validated