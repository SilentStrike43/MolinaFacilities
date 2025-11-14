"""
Address Services
Address book management and validation
"""

from .book import AddressBookService
from .validator import AddressValidator

__all__ = ['AddressBookService', 'AddressValidator']