"""
Django settings for diy project.

- Customization including mandatory are taken from ENVIRONMENT variables (passed in a ENV file for docker)
  or they are read from local_settings.py file (easier for development) - see the diy/local.env file for required values
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# In production,  a production.env file is used to set variable via docker compose
load_dotenv(BASE_DIR / 'diy' / 'local.env')

try:
    DEBUG = os.environ['DIY_DEBUG']
    DEBUG = DEBUG == 'True'
except KeyError:
    DEBUG = False

try:
    NO_CACHE = os.environ['NO_CACHE']
    NO_CACHE = NO_CACHE == 'True'
except KeyError:
    NO_CACHE = False

try:
    DIY_LOCALDB = os.environ['DIY_LOCALDB']
    DIY_LOCALDB = DIY_LOCALDB == 'True'
except KeyError:
    DIY_LOCALDB = False

ALLOWED_HOSTS = ['*']   # I dont have a domain at home.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


if ('test' in sys.argv  # set with manage.py test
        or 'test' in sys.argv[0]  # set with pytest
        or ('PYTEST_RUN_CONFIG' in os.environ and os.environ['PYTEST_RUN_CONFIG'])
        or DIY_LOCALDB):  # set with local pycharm tests
    # print(f'Using a local DB - {DIY_LOCALDB}')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    # print('Using a remote DB')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ['MYSQL_DATABASE'],
            'USER': os.environ['MYSQL_USER'],
            'PASSWORD': os.environ['MYSQL_PASSWORD'],
            'HOST': os.environ['DATABASE_HOST'],  # 172.20.0.10 See comments in database/Dockerfile
            'PORT': 3306,
        }
    }

ALPHAVANTAGEAPI_KEY = os.environ['ALPHAVANTAGEAPI_KEY']
SECRET_KEY = os.environ['SECRET_KEY']

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10240

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_USE_TLS = True
EMAIL_PORT = 587
EMAIL_HOST_USER = os.environ['DIY_EMAIL_USER']
EMAIL_HOST_PASSWORD = os.environ['DIY_EMAIL_PASSWORD']

# Application definition
INSTALLED_APPS = [
    'base.apps.BaseConfig',
    'expenses.apps.ExpensesConfig',
    'stocks.apps.StocksConfig',

    'django_bootstrap5',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'django_celery_beat',
    'localflavor',
    'phonenumber_field',
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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module}:{lineno} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": "/tmp/DIY.log",
            "formatter": "verbose",
            "level": "DEBUG"
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            'level': 'DEBUG' if DEBUG else 'CRITICAL',
        },
    },
    "loggers": {
        "": {
            "handlers": ["console", "file"],
            'level': 'DEBUG' if DEBUG else 'WARNING',
        }
    }
}

ROOT_URLCONF = 'diy.urls'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'diy' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'diy.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'
USE_I18N = True

#Time Zone
USE_TZ = True  
TIME_ZONE = 'America/New_York'


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = "static_root/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
    BASE_DIR / "contrib"
]

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REDIS_HOST = '172.20.0.30'  # Use 'localhost' if running on the same machine
REDIS_PORT = 6379         # Default Redis port exposed by Docker
REDIS_DB = 0             # Redis database index
REDIS_PASSWORD = None    # Redis password (if you set one)

CELERY_BROKER_URL = 'redis://172.20.0.30:6379/0'  # Use Redis as the message broker
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULTS_BACKEND = CELERY_BROKER_URL

CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# 'BACKEND': 'django_redis.cache.RedisCache',
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}',
    }
}
