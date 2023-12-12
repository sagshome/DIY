from django.contrib import admin

# Register your models here.

from .models import Equity, Portfolio, Transaction, EquityValue, EquityEvent, Inflation


class EquityAdmin(admin.ModelAdmin):
    list_display = ("symbol", "region", "name")
    fields = ["symbol", "name", "equity_type", "region", "currency", "last_updated", "searchable", "validated"]


class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", )


class TransactionAdmin(admin.ModelAdmin):
    model = Transaction
    list_display = ('equity', 'get_portfolio', 'value', 'date', 'price', 'quantity', 'xa_action')

    fieldsets = [
        (None, {'fields': ['equity', 'portfolio']}),
        ('Purchase', {'fields': ['date', 'price', 'quantity', 'xa_action', 'drip']}),
    ]

    def get_portfolio(self, obj):
        return obj.portfolio.name
    get_portfolio.admin_order_field = 'portfolio__name'
    get_portfolio.short_description = 'Portfolio'

    def get_equity(self, obj):
        return obj.equity

    get_equity.short_description = 'Equity'
    get_equity.admin_order_field = 'equity__key'


class EquityEventAdmin(admin.ModelAdmin):
    list_display = ("equity", "event_type", "date", "value", "event_source")


class EquityValueAdmin(admin.ModelAdmin):
    list_display = ("equity", "date", "price", "estimated")

class InflationAdmin(admin.ModelAdmin):
    list_display = ("date", "cost", "inflation", "estimated")


admin.site.register(EquityEvent, EquityEventAdmin)
admin.site.register(EquityValue, EquityValueAdmin)
admin.site.register(Equity, EquityAdmin)
admin.site.register(Portfolio, PortfolioAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Inflation, InflationAdmin)
