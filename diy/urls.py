"""
URL configuration for diy project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, re_path, path
from base.views import diy_main, sites_up, NewAccountConfirmView, NewAccountDoneView


urlpatterns = [
    path("", diy_main, name='home_page'),
    # path("help/<path:fakepath>", diy_help, name='diy_help'),
    path("accounts/login/", auth_views.LoginView.as_view(), name='login_view'),
    path("accounts/logout/", auth_views.LogoutView.as_view()),


    path("accounts/password_reset/done/", NewAccountDoneView.as_view(), name="new_account_done"),
    path("accounts/reset/<uidb64>/<token>/", NewAccountConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/", include("django.contrib.auth.urls")),
    re_path('admin/', admin.site.urls),
    re_path('stocks/', include('stocks.urls')),
    re_path('expenses/', include('expenses.urls')),
    re_path("base/", include('base.urls')),
    path("sites_up", sites_up, name="health_check")
]
