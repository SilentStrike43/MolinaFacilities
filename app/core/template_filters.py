# app/core/template_filters.py
"""
Custom Jinja2 template filters.
Extracted from app.py to keep the factory lean.
"""
from datetime import datetime


def register_template_filters(app):
    """Register all custom Jinja2 filters on the Flask app."""

    @app.template_filter('format_datetime')
    def format_datetime_filter(value, format='%Y-%m-%d %H:%M'):
        if value == 'now':
            return datetime.now().strftime(format)
        if not value:
            return ''
        try:
            if isinstance(value, str):
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = value
            return dt.strftime(format)
        except Exception:
            return value

    @app.template_filter('get_field_description')
    def get_field_description_filter(schema, migration_type, field_name):
        from app.modules.horizon.column_mapper import ColumnMapper
        return ColumnMapper.get_field_description(migration_type, field_name)
