from django.contrib import admin
from django.contrib.admin import SimpleListFilter
# Register your models here.

from .models import Equity, Account, Transaction, EquityValue, EquityEvent, Inflation, EquityAlias, ExchangeRate, \
    DataSource, FundValue


@admin.display(description="Source")
def display_source(obj):
    return DataSource(obj.source).name


class FundValueAdmin(admin.ModelAdmin):
    list_display = ("equity", "real_date", "value", "source")
    list_filter = ("equity", "date", "source")
    fields = ["equity", "date", "real_date", "value", "source"]


class EquityAdmin(admin.ModelAdmin):
    list_display = ("symbol", "validated", "searchable", "region", "last_updated", "name")
    fields = ["symbol", "name", "equity_type", "region", "currency", "last_updated", "searchable", "validated", "deactived_date"]


class EquityAliasAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'equity', 'name')


class AccountAdmin(admin.ModelAdmin):
    list_display = ("name",)


class TransactionAdmin(admin.ModelAdmin):
    model = Transaction
    list_display = ('account__name', 'symbol', 'real_date', 'price', 'quantity', 'value', 'xa_action', 'estimated')
    list_filter = ('account__name', 'equity__symbol', 'xa_action')

    fieldsets = [
        (None, {'fields': ['account', 'equity']}),
        ('Purchase', {'fields': ['real_date', 'date', 'xa_action', 'value', 'currency_value', 'price', 'quantity', 'estimated']}),
    ]

    def account__name(self, obj):
        return obj.account.name

    def symbol(self, obj):
        if obj.equity:
            return obj.equity.symbol
        return None


class EquityEventAdmin(admin.ModelAdmin):
    list_display = ("equity", "event_type", "real_date", "value", "source", "api", "split_fixed")
    list_filter = ('date', 'equity__symbol', 'event_type', 'api')

    def source(self, obj: EquityValue):
        return DataSource(obj.source).name


class EquityValueAdmin(admin.ModelAdmin):
    list_display = ("equity", "real_date", "price", "source", "api", "split_fixed")
    list_filter = ("equity__symbol", 'date', 'api')

    def source(self, obj: EquityValue):
        return DataSource(obj.source).name


class InflationAdmin(admin.ModelAdmin):
    list_display = ("date", "cost", "inflation", "source")


class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("date", "us_to_can", "can_to_us", "source")


admin.site.register(EquityAlias, EquityAliasAdmin)
admin.site.register(EquityEvent, EquityEventAdmin)
admin.site.register(EquityValue, EquityValueAdmin)
admin.site.register(Equity, EquityAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Inflation, InflationAdmin)
admin.site.register(ExchangeRate, ExchangeRateAdmin)
admin.site.register(FundValue, FundValueAdmin)