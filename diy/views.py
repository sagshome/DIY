from datetime import datetime, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import transaction

from base.forms import UserForm, ProfileForm


