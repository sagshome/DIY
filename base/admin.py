from django.contrib import admin

from .models import Profile, URL

class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "currency", "av_api_key")
    fields = ["user", "currency", "av_api_key"]

class URLAdmin(admin.ModelAdmin):
    list_display = ("name", "_active")
    fields = ["name", "base", "_active", "_last_fail"]

admin.site.register(Profile, ProfileAdmin)
admin.site.register(URL, URLAdmin)
