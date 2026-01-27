# chat/api_views.py
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
import requests

@csrf_exempt
def register_api(request):
    """API endpoint for user registration"""
    try:
        data = json.loads(request.body)
        from .models import User
        
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        
        if not email or not password:
            return JsonResponse({
                'success': False,
                'error': 'Email and password are required'
            }, status=400)
        
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already registered'
            }, status=400)
        
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        login(request, user)
        
        return JsonResponse({
            'success': True,
            'message': 'Registration successful',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
def login_api(request):
    """API endpoint for user login"""
    try:
        data = json.loads(request.body)
        email = data.get('email')
        password = data.get('password')
        
        user = authenticate(request, email=email, password=password)
        
        if user is not None:
            if user.is_active:
                login(request, user)
                return JsonResponse({
                    'success': True,
                    'message': 'Login successful',
                    'user': {
                        'id': str(user.id),
                        'email': user.email,
                        'first_name': user.first_name,
                        'last_name': user.last_name
                    }
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Account is disabled'
                }, status=403)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid credentials'
            }, status=401)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
@login_required
def logout_api(request):
    """API endpoint for user logout"""
    try:
        logout(request)
        return JsonResponse({
            'success': True,
            'message': 'Logout successful'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
@login_required
def profile_api(request):
    """Get user profile data"""
    try:
        user = request.user
        return JsonResponse({
            'success': True,
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'date_joined': user.date_joined.isoformat()
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
@login_required
def chat_api(request):
    """Simple chat endpoint for now"""
    return JsonResponse({
        'success': True,
        'message': 'Chat endpoint is working',
        'note': 'Full chat functionality will be implemented soon'
    })

@csrf_exempt
@login_required
def chat_sessions_api(request):
    """Get user's chat sessions"""
    try:
        from .models import ChatSession
        sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
        
        session_list = []
        for session in sessions:
            session_list.append({
                'id': str(session.id),
                'title': session.title or 'Untitled Chat',
                'created_at': session.created_at.isoformat(),
                'message_count': session.messages.count()
            })
        
        return JsonResponse({
            'success': True,
            'sessions': session_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

def health_check_api(request):
    """Health check endpoint"""
    try:
        # Try to connect to Ollama
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            model_names = [model.get('name', '') for model in models]
            
            return JsonResponse({
                'status': 'healthy',
                'service': 'Django Ollama Chat',
                'ollama': {
                    'available': True,
                    'models': model_names
                },
                'database': 'connected'
            })
        else:
            return JsonResponse({
                'status': 'degraded',
                'service': 'Django Ollama Chat',
                'ollama': {
                    'available': False,
                    'error': f'HTTP {response.status_code}'
                },
                'database': 'connected'
            })
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'status': 'degraded',
            'service': 'Django Ollama Chat',
            'ollama': {
                'available': False,
                'error': 'Cannot connect to Ollama'
            },
            'database': 'connected'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'service': 'Django Ollama Chat',
            'error': str(e)
        }, status=500)

def test_ollama_simple(request):
    """Simple Ollama test"""
    try:
        test_data = {
            "model": "llama2",
            "prompt": "Hello",
            "stream": False
        }
        
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=test_data,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return JsonResponse({
                'success': True,
                'response': data.get('response', 'No response'),
                'model': data.get('model', 'unknown')
            })
        else:
            return JsonResponse({
                'success': False,
                'error': f'Ollama API returned {response.status_code}'
            }, status=500)
            
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'success': False,
            'error': 'Cannot connect to Ollama. Make sure it is running on localhost:11434'
        }, status=503)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

def server_status(request):
    """Server status information"""
    import sys
    import platform
    
    return JsonResponse({
        'success': True,
        'status': 'running',
        'server': {
            'name': 'Django Ollama Chat API',
            'python_version': sys.version,
            'platform': platform.platform(),
        },
        'endpoints': {
            'health': '/api/health/',
            'models': '/api/models/',
            'chat': '/api/chat/send/',
            'auth': {
                'register': '/api/auth/register/',
                'login': '/api/auth/login/'
            }
        }
    })

# Placeholder functions for now
def models_api(request):
    return JsonResponse({
        'success': True,
        'models': ['llama2', 'mistral', 'codellama'],
        'note': 'Using placeholder models for now'
    })

@login_required
def user_preferences_api(request):
    return JsonResponse({
        'success': True,
        'preferences': {
            'theme': 'auto',
            'default_model': 'llama2',
            'enable_streaming': True
        }
    })

@login_required
def token_usage_api(request):
    return JsonResponse({
        'success': True,
        'usage': {
            'tokens_used': 0,
            'token_limit': 1000000,
            'remaining': 1000000
        }
    })

@login_required
def notifications_api(request):
    return JsonResponse({
        'success': True,
        'notifications': [],
        'unread_count': 0
    })

@login_required
def chat_session_detail_api(request, session_id):
    return JsonResponse({
        'success': True,
        'session': {
            'id': session_id,
            'title': 'Chat Session'
        },
        'messages': []
    })

@login_required
def delete_session_api(request, session_id):
    return JsonResponse({
        'success': True,
        'message': 'Delete functionality will be implemented soon'
    })