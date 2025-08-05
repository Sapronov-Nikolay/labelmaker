from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_file, name='upload_file'),
    path('select-header/', views.select_header, name='select_header'),
    path('select-columns/', views.select_columns, name='select_columns'),
    path('label-settings/', views.label_settings, name='label_settings'),
    path('edit-data/', views.edit_data, name='edit_data'),
    path('generate-pdf/', views.generate_pdf, name='generate_pdf'),
]