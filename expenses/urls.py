from django.urls import path

from . import views

# Base is stocks/
urlpatterns = [
    path(r'test/', views.expense_test, name='expense_test'),


    path(r'main/', views.expense_main, name='expense_main'),
    path(r'upload/', views.upload_expenses, name='expenses_upload'),
    path(r'assign/', views.assign_expenses, name='expenses_assign'),

    path(r'item_add/', views.ItemAdd.as_view(), name='expense_add'),
    path(r'<int:pk>/item_edit/', views.ItemEdit.as_view(), name='expense_edit'),
    path(r'<int:pk>/item_del/', views.ItemDelete.as_view(), name='expense_delete'),

    path(r'templates/', views.templates, name='expenses_templates'),
    path(r'<int:pk>/template_delete/', views.DeleteTemplateView.as_view(), name='template_delete'),
    path(r'<int:pk>/template_edit/', views.edit_template, name='template_edit'),

    path('ajax/load-subcategories/', views.load_subcategories, name='ajax-load-subcategories'),
    path('ajax/load-subcategories-search/', views.load_subcategories_search, name='ajax-load-subcategories-search'),
    path('ajax/load-categories-search/', views.load_categories_search, name='ajax-load-categories-search')

]

