from django.urls import path

from . import views, apis, charts

# Base is stocks/
urlpatterns = [
    path(r'', views.StocksMain.as_view(), name='portfolio_home'),

    path(r'api/search/', apis.search_equity, name='equity_search'),
    path(r'api/search_add/', apis.search_equity_add, name='equity_search_add'),

    path(r'api/equity_list/', apis.get_equity_list, name='equity_list'),
    path(r'api/action_list/', apis.get_action_list, name='action_list'),
    path(r'api/xa_values/', apis.get_equity_values, name='xa_values'),
    path(r'api/cash_value/', apis.get_cash_value, name='cash_value'),

    path(r'api/cost_value/', charts.cost_value_chart, name='cost_value_chart'),
    path(r'api/compare_chart/', charts.compare_equity_chart, name='compare_equity_chart'),
    path(r'api/wealth', charts.wealth_summary_chart, name='wealth_chart'),
    path(r'api/wealth_pie', charts.wealth_summary_pie, name='wealth_pie'),
    path(r'api/wealth_summary', charts.acc_summary, name='wealth_summary'),
    path(r'api/equity_summary', charts.equity_summary, name='equity_summary'),
    path(r'api/<pk>/<orig_id>/<compare_id>/compare/', charts.account_equity_compare, name='portfolio_equity_compare_chart'),

    path(r'equity/add', views.add_equity, name='add_equity'),
    path(r'equity/<id>/update/', views.equity_update, name='equity_update'),

    path(r'account/', views.StocksMain.as_view(), name='stocks_main'),
    path(r'account/add/', views.add_account, name='account_add'),
    path(r'account/<pk>/', views.AccountDetailView.as_view(), name='account_details'),
    path(r'account/<pk>/close/', views.AccountCloseView.as_view(), name='account_close'),
    path(r'account/<pk>/edit/', views.AccountEdit.as_view(), name='account_edit'),
    path(r'account/<pk>/delete/', views.AccountDeleteView.as_view(), name='account_delete'),
    path(r'account/<pk>/reconcile_value/', views.reconcile_value, name='value_account_reconcile'),
    path(r'account/<pk>/reconcile_cash/', views.reconcile_cash, name='cash_account_reconcile'),

    path(r'account/<pk>/table/', views.AccountTableView.as_view(), name='account_table'),
    path(r'account/<pk>/update/', views.account_update, name='account_update'),
    path(r'account/<container_type>/<pk>/<id>/details/', views.account_equity_details, name='account_equity_details'),

    path(r'account/<p_pk>/<e_pk>/<date_str>/update', views.account_equity_date_update, name='update_by_date'),
    path(r'account/<a_pk>/<date_str>/update', views.reconciliation, name='update_account_date'),

    path(r'portfolio/add/', views.PortfolioAdd.as_view(), name='portfolio_add'),
    path(r'portfolio/<pk>/', views.PortfolioDetailView.as_view(), name='portfolio_details'),
    path(r'portfolio/<pk>/edit/', views.PortfolioEdit.as_view(), name='portfolio_edit'),
    path(r'portfolio/<pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio_delete'),
    path(r'portfolio/<pk>/table/', views.PortfolioTableView.as_view(), name='portfolio_table'),
    path(r'portfolio/<pk>/update/', views.portfolio_update, name='portfolio_update'),

    path(r'transaction/<account_id>/add/', views.add_transaction, name='transaction_add'),
    path(r'transaction/<account_id>/fund/', views.set_transaction,  {'action': 'fund'}, name='set_fund'),
    path(r'transaction/<account_id>/withdraw/', views.set_transaction,  {'action': 'withdraw'}, name='set_withdraw'),
    path(r'transaction/<account_id>/balance/', views.set_transaction,  {'action': 'balance'}, name='set_balance'),
    path(r'transaction/<account_id>/value/', views.set_transaction,  {'action': 'value'}, name='set_value'),
    path(r'transaction/<account_id>/buy/', views.set_transaction,  {'action': 'buy'}, name='set_buy'),
    path(r'transaction/<account_id>/sell/', views.set_transaction,  {'action': 'sell'}, name='set_sell'),
    path(r'transaction/<pk>/edit/', views.TransactionEdit.as_view(),  name='transaction_edit'),
    path(r'transaction/<pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path(r'upload/', views.upload_file, name='portfolio_upload'),
    path(r'export/', views.export_stocks, name='stocks_export'),
    path(r'export/download/', views.export_stocks_download, name='stocks_download')
]
