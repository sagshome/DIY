from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import transaction

from base.forms import UserForm, ProfileForm


@login_required
def diy_main(request):
    return render(request, "base/diy_main.html")
