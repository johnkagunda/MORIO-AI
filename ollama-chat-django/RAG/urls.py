# RAG/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Existing RAG endpoints
    path('chat/', views.rag_chat, name='rag_chat'),
    path('add-document/', views.add_document, name='add_document'),
    path('search/', views.search_documents, name='search_documents'),
    path('generate-embeddings/', views.generate_embeddings, name='generate_embeddings'),
    
    # New AI Configuration endpoints
    path('config/list/', views.list_ai_configs, name='list_ai_configs'),
    path('config/create/', views.create_ai_config, name='create_ai_config'),
    path('config/<int:config_id>/', views.get_ai_config, name='get_ai_config'),
    path('config/<int:config_id>/update/', views.update_ai_config, name='update_ai_config'),
    path('config/<int:config_id>/delete/', views.delete_ai_config, name='delete_ai_config'),
    path('config/<int:config_id>/generate-modelfile/', views.generate_modelfile, name='generate_modelfile'),
    path('config/manage/', views.ai_config_manager, name='ai_config_manager'),
    path('config/stats/', views.get_ai_config_stats, name='ai_config_stats'),
]