from django.contrib import admin

from .models import Profile, API

class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "currency", "av_api_key")
    fields = ["user", "currency", "av_api_key"]

class URLAdmin(admin.ModelAdmin):
    list_display = ("name", "_active")
    fields = ["name", "base", "_active", "_last_fail", "fail_reason", "fail_length"]

admin.site.register(Profile, ProfileAdmin)
admin.site.register(API, URLAdmin)
