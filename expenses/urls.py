from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'main/', views.expense_main, name='expense_main'),
    path(r'upload/', views.upload_expenses, name='expense_upload'),
    path(r'assign/', views.assign_expenses, name='expenses_assign'),
    path(r'search/', views.generic_search, name='expense_search'),
    path(r'templates/', views.templates, name='expenses_templates'),
    path(r'list/', views.expense_list, name='expenses_list'),

    path(r'<int:pk>/category/', views.expense_category, name='expense_category'),
    path(r'<int:pk>/catlist/', views.expense_list_category, name='expense_list'),
    path(r'<int:pk>/assign/', views.AssignCategory.as_view(), name='expense_assign'),
    path(r'<int:pk>/template_delete/', views.DeleteTemplateView.as_view(), name='template_delete'),
    path(r'<int:pk>/template_update/', views.EditTemplateView.as_view(), name='template_update'),
    path(r'<int:pk>/template_reapply/', views.reapply_template, name='template_reapply'),
    path('ajax/load-subcategories/', views.load_subcategories, name='ajax-load-subcategories')

]

