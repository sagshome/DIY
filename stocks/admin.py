from django.contrib import admin

# Register your models here.

from .models import Equity, Account, Transaction, EquityValue, EquityEvent, Inflation, EquityAlias, ExchangeRate, \
    DataSource


@admin.display(description="Source")
def display_source(obj):
    return DataSource(obj.source).name


class EquityAdmin(admin.ModelAdmin):
    list_display = ("symbol", "validated", "searchable", "region", "last_updated", "name")
    fields = ["symbol", "name", "equity_type", "region", "currency", "last_updated", "searchable", "validated", "deactived_date"]


class EquityAliasAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'equity', 'name')


class AccountAdmin(admin.ModelAdmin):
    list_display = ("name",)


class TransactionAdmin(admin.ModelAdmin):
    model = Transaction
    list_display = ('account', 'equity', 'real_date', 'price', 'quantity', 'value', 'xa_action', 'estimated')

    fieldsets = [
        (None, {'fields': ['account', 'equity']}),
        ('Purchase', {'fields': ['real_date', 'date', 'xa_action', 'value', 'price', 'quantity', 'estimated']}),
    ]


class EquityEventAdmin(admin.ModelAdmin):
    list_display = ("equity", "event_type", "date", "value", "source")


class EquityValueAdmin(admin.ModelAdmin):
    list_display = ("equity", "date", "price", "source")

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
