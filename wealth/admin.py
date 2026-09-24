from django.contrib import admin

from base.models import DataSource
from .models import Account, Portfolio, Investment, Value, Dividend, Position, Transaction, Funding, CashFlow, ValueBalance, DividendAmount


@admin.display(description="Source")
def display_source(obj):
    return DataSource(obj.source).name


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "portfolio", 'acct_type', "user", "managed", "portfolio", "closed")
    list_filter = ("user", "portfolio__name")


class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "user")


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ("symbol", "inv_type", "last_updated", "validated", "searchable")
    list_filter = ("inv_type",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(inv_type__in=['Trading'])


class ValueAdmin(admin.ModelAdmin):
    list_display = ("pk", "investment", "date", "value", "ex_dividend", "source", "split_fixed")
    list_filter = ("investment__symbol", "source")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(investment__inv_type__in=['Trading'])


class DividendAdmin(admin.ModelAdmin):
    list_display = ("id", "investment", "date", "day_scope", "source", "value")
    list_filter = ("day_scope", "investment__symbol")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("account", "investment", "quantity", "price", "date")
    list_filter = ("investment__symbol", "account__name")


class AmountAdmin(admin.ModelAdmin):
    list_display = ("div_date", "cash_date", "cash_account", "cash_record", "dividend", "cash_value", "altered")
    list_filter = ("dividend__investment", "cash_record__account__name")

    def div_date(self, obj):
        """Returns the ID of the related account."""
        return obj.dividend.date if obj.dividend else None

    def cash_date(self, obj):
        """Returns the ID of the related account."""
        return obj.cash_record.date if obj.cash_record else None

    def cash_account(self, obj):
        """Returns the ID of the related account."""
        return obj.cash_record.account if obj.cash_record else None

    def cash_value(self, obj):
        """Returns the ID of the related account."""
        return obj.cash_record.value if obj.cash_record else None


class TransactionAdmin(admin.ModelAdmin):
    list_display = ("account", "date", "investment", "quantity", "price", "source", "note")
    list_filter = ("source", "investment__symbol", "account__name")


class FundingAdmin(admin.ModelAdmin):
    list_display = ("account", "date", "investment", "value", "balance", "source", "note")
    list_filter = ("account__user", "account__name",  "source", "investment")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "investment":
            kwargs["queryset"] = Investment.objects.filter(name__endswith='~Funding')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ValueBalance)
class ValueBalanceAdmin(admin.ModelAdmin):
    list_display = ("account", "date", "value", "balance", "source", "note")
    list_filter = ("source", "account__user", "account__name",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "investment":
            kwargs["queryset"] = Investment.objects.filter(inv_type='Value')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(investment__inv_type='Value')


@admin.register(CashFlow)
class CashAdmin(admin.ModelAdmin):
    list_display = ("account", "get_account_id", "date", "value", "balance", "source", "note")
    list_filter = ("source", "account__user", "account__name",)

    #def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #    if db_field.name == "investment":
    #        kwargs["queryset"] = Investment.objects.filter(name__endswith='~Funding')
    #    return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_account_id(self, obj):
        """Returns the ID of the related account."""
        return obj.account.id if obj.account else None

# Register your models here.
admin.site.register(DividendAmount, AmountAdmin)
admin.site.register(Portfolio, PortfolioAdmin)
admin.site.register(Value, ValueAdmin)
admin.site.register(Dividend, DividendAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Funding, FundingAdmin)

