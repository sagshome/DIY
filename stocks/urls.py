from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'', views.PortfolioView.as_view(), name='portfolio_home'),
    path(r'lookup', views.search, name="lookup"),
    path(r'equity/add', views.add_equity, name='add_equity'),
    path(r'equity/<key>/update/', views.equity_update, name='equity_update'),

    path(r'portfolio/', views.PortfolioView.as_view(), name='portfolio_list'),
    path(r'portfolio/add/', views.PortfolioAdd.as_view(), name='portfolio_add'),
    path(r'portfolio/<pk>/copy/', views.PortfolioCopy.as_view(), name='portfolio_copy'),
    path(r'portfolio/<pk>/compare/', views.portfolio_compare, name='portfolio_compare'),

    path(r'portfolio/<pk>/', views.PortfolioDetailView.as_view(), name='portfolio_details'),
    path(r'portfolio/<pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio_delete'),
    path(r'portfolio/<pk>/update/', views.portfolio_update, name='portfolio_update'),
    # path(r'portfolio/<pk>/buy/', views.PortfolioBuy.as_view(), name='portfolio_buy'),

    path(r'portfolio/<pk>/<key>/sell/', views.portfolio_equity_details, name='portfolio_equity_sell'),
    path(r'portfolio/<pk>/<key>/details/', views.portfolio_equity_details, name='portfolio_equity_details'),

    # path(r'portfolio/<pk>/eadd/', views.TransactionFormView.as_view()),
    path(r'portfolio/<pk>/buy/', views.portfolio_buy,  name='portfolio_buy'),

    path(r'test/', views.test),
    path(r'test2/', views.test2)


]