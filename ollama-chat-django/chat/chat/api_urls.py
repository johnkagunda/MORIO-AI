# chat/api_urls.py
from django.urls import path
from . import api_views

urlpatterns = [
    # Authentication
    path('auth/register/', api_views.register_api, name='api_register'),
    path('auth/login/', api_views.login_api, name='api_login'),
    path('auth/logout/', api_views.logout_api, name='api_logout'),
    path('auth/profile/', api_views.profile_api, name='api_profile'),
    
    # Chat endpoints
    path('chat/send/', api_views.chat_api, name='api_chat'),
    path('chat/sessions/', api_views.chat_sessions_api, name='api_sessions'),
    path('chat/sessions/<uuid:session_id>/', api_views.chat_session_detail_api, name='api_session_detail'),
    path('chat/sessions/<uuid:session_id>/delete/', api_views.delete_session_api, name='api_session_delete'),
    
    # Models and configuration
    path('models/', api_views.models_api, name='api_models'),
    path('health/', api_views.health_check_api, name='api_health'),
    
    # User data
    path('user/preferences/', api_views.user_preferences_api, name='api_preferences'),
    path('user/token-usage/', api_views.token_usage_api, name='api_token_usage'),
    path('user/notifications/', api_views.notifications_api, name='api_notifications'),
    
    # Test endpoints
    path('test/', api_views.test_ollama_simple, name='api_test_simple'),
    path('status/', api_views.server_status, name='api_status'),
]