"""ASGI-Einstiegspunkt (für z. B. WebSockets, falls später gebraucht)."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "inventar.settings")

application = get_asgi_application()
