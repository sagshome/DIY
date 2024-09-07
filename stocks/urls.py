from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'', views.PortfolioView.as_view(), name='portfolio_home'),

    path(r'api/equity_list/', views.get_equity_list, name='equity_list'),
    path(r'api/cost_value/', views.cost_value_chart, name='cost_value_chart'),
    path(r'api/compare_chart/', views.compare_equity_chart, name='compare_equity_chart'),

    path(r'equity/add', views.add_equity, name='add_equity'),
    path(r'equity/<key>/update/', views.equity_update, name='equity_update'),

    path(r'portfolio/', views.PortfolioView.as_view(), name='portfolio_list'),
    path(r'portfolio/add/', views.PortfolioAdd.as_view(), name='portfolio_add'),
    path(r'portfolio/<pk>/', views.PortfolioDetailView.as_view(), name='portfolio_details'),
    path(r'portfolio/<pk>/edit/', views.PortfolioEdit.as_view(), name='portfolio_edit'),
    path(r'portfolio/<pk>/copy/', views.PortfolioCopy.as_view(), name='portfolio_copy'),
    path(r'portfolio/<pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio_delete'),
    path(r'portfolio/<pk>/table/', views.PortfolioTableView.as_view(), name='portfolio_table'),
    path(r'portfolio/<pk>/update/', views.portfolio_update, name='portfolio_update'),
    path(r'portfolio/<pk>/<symbol>/details/', views.portfolio_equity_details, name='portfolio_equity_details'),
    path(r'portfolio/<pk>/<symbol>/compare/', views.portfolio_compare, name='portfolio_compare'),
    path(r'portfolio/<pk>/<orig_id>/<compare_id>/compare/', views.portfolio_equity_compare, name='portfolio_equity_compare'),

    path(r'portfolio/transaction/add/', views.add_transaction,  name='transaction_add'),
    path(r'portfolio/transaction/<pk>/edit/', views.TransactionEdit.as_view(),  name='transaction_edit'),
    path(r'portfolio/transaction/<pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path(r'upload/', views.upload_file, name='portfolio_upload'),

]
