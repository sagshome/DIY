from django.contrib import admin

from .models import Category, SubCategory, Item, Template


class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    fields = ["name",]


class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "user")
    list_filter = ("category", "name", "user")
    fields = ["name", "category", "user"]

class TemplateAdmin(admin.ModelAdmin):
    list_display = ("type", "expression", "count", "category", "subcategory", "ignore")
    fields = ["type", "expression", "category", "subcategory", "ignore"]

class ItemAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "subcategory", "description", "details")
    fields = ["date", "category", "subcategory", "description", "details"]

admin.site.register(Category, CategoryAdmin)
admin.site.register(SubCategory, SubCategoryAdmin)
admin.site.register(Template, TemplateAdmin)
admin.site.register(Item, ItemAdmin)