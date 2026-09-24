from django.contrib import admin

from .models import Profile, API, Inflation

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "currency", "av_api_key")
    fields = ["user", "currency", "av_api_key"]

@admin.register(API)
class URLAdmin(admin.ModelAdmin):
    list_display = ("name", "_active")
    fields = ["name", "base", "_active", "_last_fail", "fail_reason", "fail_length"]

@admin.register(Inflation)
class InflationAdmin(admin.ModelAdmin):
    list_display = ("date", "cost", "inflation")
    fields = ["date", "cost", "inflation", "source"]

