from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
import json
import requests
import sys
import platform
import time
from .models import User, ChatSession, ChatMessage

# ========== WEB VIEWS ==========

def index(request):
    """Home page"""
    return render(request, 'chat/index.html')

def register(request):
    """User registration page"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered')
            return render(request, 'chat/register.html')
        
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        login(request, user)
        messages.success(request, 'Registration successful!')
        return redirect('index')
    
    return render(request, 'chat/register.html')

@login_required
def chat_interface(request):
    """Chat interface"""
    return render(request, 'chat/chat.html')

@login_required
def profile(request):
    """User profile"""
    return render(request, 'chat/profile.html')

def health_check(request):
    """Health check endpoint"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            return JsonResponse({
                'status': 'healthy',
                'ollama': 'connected',
                'message': 'Server is running'
            })
        else:
            return JsonResponse({
                'status': 'warning',
                'ollama': f'error {response.status_code}',
                'message': 'Ollama API responded with error'
            })
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'status': 'degraded',
            'ollama': 'not connected',
            'message': 'Cannot connect to Ollama. Make sure it is running.'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        }, status=500)

def test_ollama(request):
    """Test Ollama connection"""
    try:
        test_data = {
            "model": "morio-phi:latest",
            "prompt": "Hello, how are you?",
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
                'error': f'Ollama API returned {response.status_code}',
                'details': response.text[:200]
            }, status=500)
            
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'success': False,
            'error': 'Cannot connect to Ollama. Make sure it is running on localhost:11434'
        }, status=503)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ========== API VIEWS ==========
@csrf_exempt
def register_api(request):
    """API endpoint for user registration"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        
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
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
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

# ========== CHAT HISTORY MANAGEMENT ==========

@csrf_exempt
@login_required
def get_chat_sessions(request):
    """Get user's chat sessions"""
    try:
        sessions = ChatSession.objects.filter(
            user=request.user
        ).order_by('-updated_at')[:20]
        
        session_list = []
        for session in sessions:
            last_message = session.messages.order_by('created_at').last()
            preview = ""
            if last_message:
                preview = last_message.content[:100]
                if len(last_message.content) > 100:
                    preview += "..."
            
            session_list.append({
                'id': str(session.id),
                'title': session.title or 'New Chat',
                'created_at': session.created_at.isoformat(),
                'updated_at': session.updated_at.isoformat(),
                'message_count': session.messages.count(),
                'preview': preview
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


@csrf_exempt
@login_required
def get_chat_history(request, session_id):
    """Get messages from a specific chat session"""
    try:
        session = ChatSession.objects.get(
            id=session_id,
            user=request.user
        )
        
        messages = session.messages.order_by('created_at')
        
        message_list = []
        for msg in messages:
            message_list.append({
                'id': str(msg.id),
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at.isoformat(),
                'session_id': str(session.id)
            })
        
        return JsonResponse({
            'success': True,
            'session': {
                'id': str(session.id),
                'title': session.title,
                'created_at': session.created_at.isoformat()
            },
            'messages': message_list
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Chat session not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@csrf_exempt
@login_required
def delete_chat_session(request, session_id):
    """Delete a chat session"""
    try:
        session = ChatSession.objects.get(
            id=session_id,
            user=request.user
        )
        session_title = session.title
        session.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Deleted chat session: {session_title}'
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Chat session not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@csrf_exempt
@login_required
def update_session_title(request, session_id):
    """Update chat session title"""
    try:
        data = json.loads(request.body)
        title = data.get('title', '').strip()
        
        if not title:
            return JsonResponse({
                'success': False,
                'error': 'Title is required'
            }, status=400)
        
        session = ChatSession.objects.get(
            id=session_id,
            user=request.user
        )
        
        session.title = title
        session.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Title updated',
            'title': title
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Chat session not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

# ========== MAIN CHAT API ==========

@csrf_exempt
@login_required
def chat_api(request):
    """Chat API with streaming support - Let model handle identity naturally"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        prompt = data.get('prompt', '').strip()
        session_id = data.get('session_id')
        new_session = data.get('new_session', False)
        
        if not prompt:
            return JsonResponse({'error': 'No prompt'}, status=400)
        
        print(f"\n👤 USER: {prompt[:80]}")
        
        # ========== GET OR CREATE CHAT SESSION ==========
        chat_session = None
        
        if session_id and not new_session:
            try:
                chat_session = ChatSession.objects.get(
                    id=session_id,
                    user=request.user
                )
                print(f"📁 Using existing session: {chat_session.title}")
            except (ChatSession.DoesNotExist, ValueError):
                print("⚠️ Session not found or invalid ID, creating new one")
                chat_session = None
        
        # Create new session if needed
        if not chat_session or new_session:
            title = prompt[:50] + "..." if len(prompt) > 50 else prompt
            chat_session = ChatSession.objects.create(
                user=request.user,
                title=title
            )
            print(f"🆕 Created new session: {chat_session.id}")
        
        # ========== SAVE USER MESSAGE ==========
        user_message = ChatMessage.objects.create(
            session=chat_session,
            role='user',
            content=prompt
        )
        
        # ========== BUILD CONTEXT FROM HISTORY ==========
        # SIMPLIFIED: Let the model handle identity naturally from its SYSTEM prompt
        previous_messages = ChatMessage.objects.filter(
            session=chat_session
        ).exclude(id=user_message.id).order_by('created_at')[:10]
        
        context_prompt = ""
        for msg in previous_messages:
            if msg.role == 'user':
                context_prompt += f"Human: {msg.content}\n"
            elif msg.role == 'assistant':
                context_prompt += f"Assistant: {msg.content}\n"
        
        full_prompt = f"{context_prompt}Human: {prompt}\nAssistant: "
        print(f"📝 Context length: {len(context_prompt)} chars")
        
        # ========== STREAMING RESPONSE ==========
        stream_requested = data.get('stream', True)
        
        if not stream_requested:
            return chat_api_non_streaming_with_history(
                request, prompt, full_prompt, chat_session
            )
        
        # ========== FORCE MORIO-PHI MODEL ==========
        model_name = "morio-phi:latest"
        print(f"🎯 FORCING MODEL: {model_name}")
        print(f"📁 Session ID: {chat_session.id}")
        
        # Ollama request data
        ollama_data = {
            "model": model_name,
            "prompt": full_prompt,
            "stream": True,
            "options": {
                "num_predict": 100,
                "temperature": 0.3,
                "num_thread": 4,
                "num_ctx": 1024,
                "top_k": 20,
                "top_p": 0.8,
            }
        }
        
        # Streaming response generator
        def generate_stream():
            start_time = time.time()
            full_response = ""
            tokens_received = 0
            
            try:
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json=ollama_data,
                    stream=True,
                    timeout=100
                )
                
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            try:
                                chunk_data = json.loads(line.decode('utf-8'))
                                chunk = chunk_data.get('response', '')
                                
                                if chunk:
                                    full_response += chunk
                                    tokens_received = chunk_data.get('eval_count', tokens_received)
                                    
                                    chunk_json = json.dumps({
                                        'chunk': chunk, 
                                        'partial': True,
                                        'session_id': str(chat_session.id)
                                    })
                                    yield f"data: {chunk_json}\n\n"
                                
                                if chunk_data.get('done', False):
                                    response_time = time.time() - start_time
                                    actual_model = chunk_data.get('model', model_name)
                                    
                                    print(f"✅ {actual_model} ({response_time:.1f}s): {full_response[:100]}")
                                    
                                    # Save AI response
                                    ChatMessage.objects.create(
                                        session=chat_session,
                                        role='assistant',
                                        content=full_response
                                    )
                                    
                                    chat_session.save()
                                    
                                    completion_data = {
                                        'done': True,
                                        'full_response': full_response,
                                        'model': actual_model,
                                        'session_id': str(chat_session.id),
                                        'session_title': chat_session.title,
                                        'time': f"{response_time:.1f}s",
                                        'tokens': tokens_received,
                                        'success': True
                                    }
                                    completion_json = json.dumps(completion_data)
                                    yield f"data: {completion_json}\n\n"
                                    break
                                    
                            except json.JSONDecodeError as e:
                                print(f"JSON decode error: {e}")
                                continue
                else:
                    error_msg = f'Ollama API returned {response.status_code}'
                    print(f"❌ {error_msg}")
                    error_data = json.dumps({
                        'error': error_msg,
                        'success': False
                    })
                    yield f"data: {error_data}\n\n"
                    
            except requests.exceptions.ConnectionError:
                error_msg = "Cannot connect to Ollama. Make sure it's running."
                print(f"❌ {error_msg}")
                error_data = json.dumps({
                    'error': error_msg,
                    'success': False
                })
                yield f"data: {error_data}\n\n"
                
            except Exception as e:
                error_msg = str(e)[:200]
                print(f"❌ Error: {error_msg}")
                error_data = json.dumps({
                    'error': f'Streaming error: {error_msg}',
                    'success': False
                })
                yield f"data: {error_data}\n\n"
        
        response = StreamingHttpResponse(
            generate_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
        
    except Exception as e:
        print(f"❌ Setup error: {str(e)[:100]}")
        return JsonResponse({
            'error': f'Server error: {str(e)}',
            'success': False
        }, status=500)


def chat_api_non_streaming_with_history(request, prompt, full_prompt, chat_session):
    """Non-streaming fallback with history"""
    model_name = "morio-phi:latest"
    print(f"🎯 FORCING MODEL (non-streaming): {model_name}")
    
    ollama_data = {
        "model": model_name,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": 100,
            "temperature": 0.3,
            "num_thread": 4,
            "num_ctx": 1024,
            "top_k": 20,
            "top_p": 0.8,
        }
    }
    
    start_time = time.time()
    
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=ollama_data,
            timeout=100
        )
        
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result.get('response', '').strip()
            actual_model = result.get('model', model_name)
            
            print(f"✅ {actual_model} ({response_time:.1f}s): {ai_response[:100]}")
            
            ChatMessage.objects.create(
                session=chat_session,
                role='assistant',
                content=ai_response
            )
            
            chat_session.save()
            
            return JsonResponse({
                'success': True,
                'response': ai_response,
                'model': actual_model,
                'session_id': str(chat_session.id),
                'session_title': chat_session.title,
                'time': f"{response_time:.1f}s",
                'tokens': result.get('eval_count', 0)
            })
        else:
            print(f"❌ Error {response.status_code}")
            return JsonResponse({
                'success': False,
                'error': f'Model {model_name} failed',
                'session_id': str(chat_session.id)
            }, status=500)
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'session_id': str(chat_session.id)
        }, status=500)


def get_available_models():
    """Helper to get available models"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return [model.get('name', 'unknown') for model in models]
    except:
        pass
    return []

@csrf_exempt
def chat_api_simple(request):
    """Simplest working version"""
    try:
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                prompt = data.get('prompt', 'Hello')
            except:
                prompt = request.POST.get('prompt', 'Hello')
        else:
            prompt = 'Hello'
        
        print(f"Testing with prompt: {prompt}")
        
        ollama_data = {
            "model": "morio-phi:latest",
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=ollama_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            return JsonResponse({
                'success': True,
                'response': result.get('response', 'No response'),
                'model': 'morio-phi'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': f'Ollama error: {response.status_code}'
            }, status=500)
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@login_required
def chat_sessions_api(request):
    """Get user's chat sessions"""
    try:
        sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')[:10]
        
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

def server_status(request):
    """Server status information"""
    return JsonResponse({
        'success': True,
        'status': 'running',
        'server': {
            'name': 'Django Ollama Chat',
            'python_version': sys.version.split()[0],
            'platform': platform.platform(),
        },
        'endpoints': {
            'health': '/api/health/',
            'chat': '/api/chat/send/',
            'register': '/api/auth/register/',
            'login': '/api/auth/login/'
        }
    })