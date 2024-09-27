def export_to_csv():
    # Your cleanup logic here
    if settings.ALPHAVANTAGEAPI_KEY:
        max_calls = 20
        total_calls = 0
        for equity in Equity.objects.all().order_by('last_updated'):
            if total_calls >= max_calls or not equity.searchable:  # We will get the others tomorrow
                logger.debug('Filling Equity Holes for %s' % equity)
                equity.fill_equity_value_holes()
            else:
                total_calls += 1
                equity.update(key=settings.ALPHAVANTAGEAPI_KEY)

    Inflation.update()
    ExchangeRate.update()

    for account in Account.objects.all():
        account.update_static_values()
