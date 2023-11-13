from django.contrib import admin

# Register your models here.

from .models import Equity, Portfolio, Transaction, EquityValue, EquityEvent


class EquityAdmin(admin.ModelAdmin):
    list_display = ("key", "name")
    fields = ["key", "name", "symbol", "equity_type", "region", "currency", "last_updated"]


class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", )


class TransactionAdmin(admin.ModelAdmin):
    model = Transaction
    list_display = ('equity_fk', 'get_portfolio', 'value', 'date', 'price', 'quantity', 'buy_action')

    fieldsets = [
        (None, {'fields': ['equity', 'portfolio']}),
        ('Purchase', {'fields': ['date', 'price', 'quantity', 'buy_action']}),
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
    list_display = ("equity", "event_type", "date", "value")


class EquityCloseAdmin(admin.ModelAdmin):
    list_display = ("equity", "date", "price")


admin.site.register(EquityEvent, EquityEventAdmin)
admin.site.register(EquityValue, EquityCloseAdmin)
admin.site.register(Equity, EquityAdmin)
admin.site.register(Portfolio, PortfolioAdmin)
admin.site.register(Transaction, TransactionAdmin)
