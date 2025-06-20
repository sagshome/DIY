from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'new_user/', views.profile_create, name='new_account'),
    path(r'profile/', views.profile_edit, name='profile'),
    path(r'main/', views.diy_main, name='diy_main'),
    path(r'main/mobile/', views.diy_main_mobile, name='diy_main_mobile'),
    path(r'get_states/', views.get_state, name='get_states'),
]