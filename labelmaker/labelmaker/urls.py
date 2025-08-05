#from django.contrib import admin
from django.urls import path, include
from generator import views  # Импорт из приложения generator

urlpatterns = [
    path('', include('generator.urls')),
]
