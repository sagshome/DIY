from django.urls import path

from . import views, apis, charts

# Base is wealth/
urlpatterns = [
    path(r"", views.WealthDetailMain.as_view(), name="wealth_home"),
    path("debug_import/", views.debug_import),
    path("debug/", views.debug),
    path(r"data/", views.WealthDataMain.as_view(), name="wealth_data"),
    # path(r'api/quick_delete', apis.delete_action, name="quick_delete"),
    # path(r'api/search/', apis.search_equity, name='equity_search'),
    # path(r'api/search_add/', apis.search_equity_add, name='equity_search_add'),
    path(r"api/equity_list/", apis.get_equity_list, name="equity_list"),
    # path(r'api/xa_action_list/', apis.get_xa_action_list, name='xa_action_list'),
    path(r"api/xa_values/", apis.get_equity_values, name="xa_values"),
    # path(r'api/cash_value/', apis.get_cash_value, name='cash_value'),
    # path(r'api/xa_list/', apis.get_transaction_list, name='xa_list'),
    path(r"api/wealth_summary", charts.acc_summary, name="wealth_summary"),
    path(
        r"api/zero_wealth_summary", charts.zero_acc_summary, name="zero_wealth_summary"
    ),
    path(
        r"api/generic_wealth", charts.generic_wealth_data, name="generic_wealth"
    ),
    # path(r'api/equity_summary', charts.equity_summary, name='equity_summary'),
    # path(r'equity/add', views.add_equity, name='add_equity'),
    # path(r'account/help', views.wealth_help, name='wealth_help'),
    path(r"account/add/", views.AccountAddView.as_view(), name="account_add"),
    path(
        r"account/<pk>/close/", views.AccountCloseView.as_view(), name="account_close"
    ),
    path(r"account/<pk>/edit/", views.AccountEdit.as_view(), name="account_edit"),
    path(
        r"account/<pk>/delete/",
        views.AccountDeleteView.as_view(),
        name="account_delete",
    ),
    # path(r'account/<pk>/reconcile_value/', views.reconcile_value, name='value_account_reconcile'),
    path(
        r"account/<pk>/table/",
        views.AccountReconcileView.as_view(),
        name="account_table",
    ),
    path(
        r"account/<pk>/equity/<symbol>/", views.EquityView.as_view(), name="equity_view"
    ),
    # path(r'account/<pk>/<date_str>/reconcile/', views.reconciliation, name='reconciliation'),
    path(
        r"account/<pk>/<date_str>/reconcile/",
        views.AccountDateReconcileView.as_view(),
        name="reconciliation",
    ),
    path(
        r"account/<pk>/reconcile/<date_str>/<scope_str>/",
        views.accountDateDetailReconcileView.as_view(),
        name="date_reconcile",
    ),
    path(r"account/<pk>/", views.AccountDetailView.as_view(), name="account_details"),
    path(r"portfolio/add/", views.PortfolioAdd.as_view(), name="portfolio_add"),
    path(r"portfolio/<pk>/edit/", views.PortfolioEdit.as_view(), name="portfolio_edit"),
    path(
        r"portfolio/<pk>/delete/",
        views.PortfolioDeleteView.as_view(),
        name="portfolio_delete",
    ),
    path(
        r"portfolio/<pk>/table/",
        views.PortfolioTableView.as_view(),
        name="portfolio_table",
    ),
    # path(r'portfolio/<pk>/update/', views.portfolio_update, name='portfolio_update'),
    path(
        r"portfolio/<pk>/",
        views.PortfolioDetailView.as_view(),
        name="portfolio_details",
    ),
    path(
        r"transaction/<account_id>/add/", views.add_transaction, name="transaction_add"
    ),
    path(
        r"transaction/<div_amount_id>/adjdiv/",
        views.update_dividend_amount,
        name="adjust_dividend",
    ),
    path(
        r"transaction/<account_id>/fund/",
        views.set_transaction,
        {"action": "FUND"},
        name="set_fund",
    ),
    path(
        r"transaction/<account_id>/withdraw/",
        views.set_transaction,
        {"action": "REDEEM"},
        name="set_withdraw",
    ),
    path(
        r"transaction/<account_id>/balance/",
        views.set_transaction,
        {"action": "BALANCE"},
        name="set_balance",
    ),
    path(
        r"transaction/<account_id>/value/",
        views.set_transaction,
        {"action": "VALUE"},
        name="set_value",
    ),
    # path(r'transaction/<account_id>/buy/', views.set_transaction,  {'action': 'BUY'}, name='set_buy'),
    # path(r'transaction/<account_id>/sell/', views.set_transaction,  {'action': 'SELL'}, name='set_sell'),
    path(
        r"transaction/<pk>/<rec_type>/edit/",
        views.edit_transaction2,
        name="transaction_edit",
    ),
    # path(r'transaction/<pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),
    # path(r'funding/<account_id>/add/', views.add_fund, name='fund_add'),
    path(r"upload/", views.upload_file, name="wealth_upload"),  # Used in base.html
    # path(r'export/', views.export_stocks, name='stocks_export'),
    # path(r'export/download/', views.export_stocks_download, name='stocks_download')
]
