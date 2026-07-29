"""
WSGI configuration for the core project.

This module exposes the WSGI application as a module-level variable named
`application`.

For more information, see:
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application


def get_application():
    """Create and return the WSGI application."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    return get_wsgi_application()


application = get_application()
