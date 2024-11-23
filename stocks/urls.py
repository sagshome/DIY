from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'', views.AccountView.as_view(), name='portfolio_home'),

    path(r'api/equity_list/', views.get_equity_list, name='equity_list'),
    path(r'api/cost_value/', views.cost_value_chart, name='cost_value_chart'),
    path(r'api/compare_chart/', views.compare_equity_chart, name='compare_equity_chart'),
    path('api/wealth', views.wealth_summary_chart, name='wealth_chart'),


    path(r'equity/add', views.add_equity, name='add_equity'),
    path(r'equity/<key>/update/', views.equity_update, name='equity_update'),

    path(r'account/', views.AccountView.as_view(), name='portfolio_list'),
    path(r'account/add/', views.AccountAdd.as_view(), name='account_add'),
    path(r'account/<pk>/', views.AccountDetailView.as_view(), name='account_details'),
    path(r'account/<pk>/close/', views.AccountCloseView.as_view(), name='account_close'),
    path(r'account/<pk>/edit/', views.AccountEdit.as_view(), name='account_edit'),
    # path(r'account/<pk>/copy/', views.AccountCopy.as_view(), name='account_copy'),
    path(r'account/<pk>/delete/', views.AccountDeleteView.as_view(), name='account_delete'),
    path(r'account/<pk>/table/', views.AccountTableView.as_view(), name='account_table'),
    path(r'account/<pk>/update/', views.account_update, name='account_update'),
    path(r'account/<container_type>/<pk>/<symbol>/details/', views.account_equity_details, name='account_equity_details'),
    path(r'account/<pk>/<symbol>/compare/', views.account_compare, name='portfolio_compare'),
    path(r'account/<p_pk>/<e_pk>/<date_str>/update', views.account_equity_date_update, name='update_by_date'),
    path(r'account/<pk>/<orig_id>/<compare_id>/compare/', views.account_equity_compare, name='portfolio_equity_compare'),

    path(r'portfolio/add/', views.PortfolioAdd.as_view(), name='portfolio_add'),
    path(r'portfolio/<pk>/', views.PortfolioDetailView.as_view(), name='portfolio_details'),
    path(r'portfolio/<pk>/edit/', views.PortfolioEdit.as_view(), name='portfolio_edit'),
    path(r'portfolio/<pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio_delete'),
    path(r'portfolio/<pk>/table/', views.PortfolioTableView.as_view(), name='portfolio_table'),

    path(r'transaction/add/', views.add_transaction,  name='transaction_add'),
    path(r'transaction/<pk>/edit/', views.TransactionEdit.as_view(),  name='transaction_edit'),
    path(r'transaction/<pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path(r'upload/', views.upload_file, name='portfolio_upload'),
    path(r'export/', views.export_stocks, name='stocks_export'),
    path(r'export/download/', views.export_stocks_download, name='stocks_download')

]
