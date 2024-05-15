from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'new_user/', views.NewAccountView.as_view(), name='new_account'),
    path(r'main/', views.diy_main, name='diy_main'),
]