import os
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('parking.urls')),
]

# ---------------------------------------------------------------------------
# Static files (CSS / JS / fonts).
#
# With DEBUG=1, `runserver` serves them automatically. With DEBUG=0 it does
# NOT, which is what made the site load unstyled ("the CSS file doesn't work").
# This fallback keeps a local run working in either mode without needing
# collectstatic, WhiteNoise or nginx.
#
# For a real deployment set PARKWISE_SERVE_STATIC=0 and let nginx / WhiteNoise
# serve STATIC_ROOT instead — Django should not serve static in production.
# ---------------------------------------------------------------------------
serve_static = os.environ.get('PARKWISE_SERVE_STATIC', '1' if not settings.DEBUG else '0') == '1'

if serve_static:
    static_root = Path(settings.BASE_DIR) / 'static'
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', static_serve, {'document_root': static_root}),
    ]

admin.site.site_header = 'Parkwise administration'
admin.site.site_title = 'Parkwise'
