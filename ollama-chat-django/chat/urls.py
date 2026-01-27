from django.urls import path
from . import views

urlpatterns = [
    # Web pages
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('chat/', views.chat_interface, name='chat_interface'),
    path('profile/', views.profile, name='profile'),
    
    # Health and status
    path('api/health/', views.health_check, name='health_check'),
    path('api/test/ollama/', views.test_ollama, name='test_ollama'),
    path('api/status/', views.server_status, name='server_status'),
    
    # Authentication API
    path('api/auth/register/', views.register_api, name='register_api'),
    path('api/auth/login/', views.login_api, name='login_api'),
    path('api/auth/logout/', views.logout_api, name='logout_api'),
    
    # Chat history management
    path('api/chat/sessions/', views.get_chat_sessions, name='get_chat_sessions'),
    path('api/chat/sessions/<uuid:session_id>/', views.get_chat_history, name='get_chat_history'),
    path('api/chat/sessions/<uuid:session_id>/delete/', views.delete_chat_session, name='delete_chat_session'),
    path('api/chat/sessions/<uuid:session_id>/title/', views.update_session_title, name='update_session_title'),
    
    # Chat API endpoints
    path('api/chat/send/', views.chat_api, name='chat_api'),
    path('api/chat/simple/', views.chat_api_simple, name='chat_api_simple'),
    
    # User profile API
    path('api/profile/', views.profile_api, name='profile_api'),
]