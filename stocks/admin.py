from django.contrib import admin

# Register your models here.

from .models import Equity, Portfolio, Transaction, EquityValue, EquityEvent, Inflation, EquityAlias, ExchangeRate


class EquityAdmin(admin.ModelAdmin):
    list_display = ("symbol", "validated", "searchable", "region", "last_updated", "name")
    fields = ["symbol", "name", "equity_type", "region", "currency", "last_updated", "searchable", "validated"]


class EquityAliasAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'equity', 'name')


class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", )


class TransactionAdmin(admin.ModelAdmin):
    model = Transaction
    list_display = ('portfolio', 'equity', 'date', 'price', 'quantity', 'value', 'xa_action')

    fieldsets = [
        (None, {'fields': ['portfolio', 'equity']}),
        ('Purchase', {'fields': ['date', 'xa_action', 'value', 'price', 'quantity']}),
    ]


class EquityEventAdmin(admin.ModelAdmin):
    list_display = ("equity", "event_type", "date", "value", "event_source")


class EquityValueAdmin(admin.ModelAdmin):
    list_display = ("equity", "date", "price", "estimated")

class InflationAdmin(admin.ModelAdmin):
    list_display = ("date", "cost", "inflation", "estimated")

class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("date", "us_to_can", "can_to_us")

admin.site.register(EquityAlias, EquityAliasAdmin)
admin.site.register(EquityEvent, EquityEventAdmin)
admin.site.register(EquityValue, EquityValueAdmin)
admin.site.register(Equity, EquityAdmin)
admin.site.register(Portfolio, PortfolioAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Inflation, InflationAdmin)
admin.site.register(ExchangeRate, ExchangeRateAdmin)
