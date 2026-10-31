"""Settings for the Parkwise place-search parking network."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = os.environ.get('VERCEL') == '1'
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
DEMO_MODE = os.environ.get('PARKWISE_DEMO_MODE', '1' if DEBUG else '0') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'parkwise-local-prototype-only-change-before-deployment')
if not DEBUG and SECRET_KEY.startswith('parkwise-local-'):
    raise RuntimeError('Set DJANGO_SECRET_KEY before running with DJANGO_DEBUG=0.')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*' if DEBUG else 'localhost,127.0.0.1').split(',')
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get('DJANGO_CSRF_ORIGINS', '').split(',') if x]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += ['https://*.e2b.app']
if os.environ.get('PREVIEW_MODE') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'None'
    CSRF_COOKIE_SAMESITE = 'None'

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'parking',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'parking_project.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'parking_project.wsgi.application'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': os.environ.get('PARKWISE_DB_PATH', '/tmp/parkwise.sqlite3' if IS_VERCEL else str(BASE_DIR / 'db.sqlite3')),
    'OPTIONS': {'timeout': 20},
    'TEST': {'NAME': BASE_DIR / 'test_db.sqlite3'},
}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('PARKWISE_TIME_ZONE', 'Asia/Kolkata')
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Bump this whenever CSS/JS changes so browsers never run a stale cached copy.
STATIC_VERSION = os.environ.get('PARKWISE_STATIC_VERSION', '2.1')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 12
LOGIN_URL = '/?signin=1'
