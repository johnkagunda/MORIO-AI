# RAG/views.py - Version 4: Async Processing & Performance
import logging
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.core.cache import cache
import json
import requests
from functools import lru_cache, wraps
from typing import List, Dict, Optional, Tuple, Generator
from .rag_service import rag_service
from .models import BusinessDocument, ConversationMemory, AIConfiguration
import os
from django.conf import settings
import traceback
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Setup logging
logger = logging.getLogger(__name__)

# Constants
OLLAMA_URL = "http://localhost:11434/api/generate"
CACHE_TIMEOUT = 300
DEFAULT_MODEL = "morio-phi:latest"
OLLAMA_TIMEOUT = 30
MAX_PREVIEW_LENGTH = 300
MAX_SNIPPET_LENGTH = 150
MAX_QUERY_LENGTH = 500
MAX_CONTENT_LENGTH = 100000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 60

# Thread pool for async tasks
executor = ThreadPoolExecutor(max_workers=4)
_embeddings_lock = threading.Lock()

# ============================
# DECORATORS
# ============================

def rate_limit(key_prefix: str, max_requests: int = RATE_LIMIT_REQUESTS, 
               timeout: int = RATE_LIMIT_WINDOW):
    """Rate limiting decorator"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            ip = request.META.get('REMOTE_ADDR', 'unknown')
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:50]
            client_id = hashlib.md5(f"{ip}_{user_agent}".encode()).hexdigest()
            
            cache_key = f'{key_prefix}_rate_{client_id}'
            count = cache.get(cache_key, 0)
            
            if count >= max_requests:
                logger.warning(f"Rate limit exceeded for {ip}")
                return JsonResponse({
                    'success': False,
                    'error': f'Rate limit exceeded. Maximum {max_requests} requests per {timeout} seconds.',
                    'retry_after': timeout
                }, status=429)
            
            cache.set(cache_key, count + 1, timeout)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator

def log_api_call(view_func):
    """Decorator to log API calls"""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user = request.user.username if request.user.is_authenticated else 'anonymous'
        logger.info(f"API Call: {request.path} - User: {user} - IP: {client_ip}")
        
        try:
            response = view_func(request, *args, **kwargs)
            logger.info(f"API Success: {request.path} - Status: {response.status_code}")
            return response
        except Exception as e:
            logger.error(f"API Error: {request.path} - {str(e)}\n{traceback.format_exc()}")
            raise
    return wrapped

def handle_errors(view_func):
    """Decorator for consistent error handling"""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Invalid JSON format'}, status=400)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error: {str(e)}")
            return JsonResponse({'success': False, 'error': f'Service unavailable: {str(e)}'}, status=503)
        except Exception as e:
            logger.error(f"Unexpected Error: {str(e)}\n{traceback.format_exc()}")
            return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)
    return wrapped

# ============================
# CACHE HELPERS
# ============================

def get_cached_config(config_id: Optional[int] = None) -> Optional[AIConfiguration]:
    """Get AI config from cache or database"""
    if config_id:
        cache_key = f'ai_config_{config_id}'
        config = cache.get(cache_key)
        if not config:
            try:
                config = AIConfiguration.objects.filter(id=config_id, is_active=True).first()
                if config:
                    cache.set(cache_key, config, CACHE_TIMEOUT)
            except AIConfiguration.DoesNotExist:
                return None
        return config
    return None

def get_active_config() -> Optional[AIConfiguration]:
    """Get active AI configuration with caching"""
    config = cache.get('active_ai_config')
    if not config:
        config = AIConfiguration.objects.filter(is_active=True).select_related().first()
        if config:
            cache.set('active_ai_config', config, CACHE_TIMEOUT)
    return config

def invalidate_config_cache(config_id: Optional[int] = None):
    """Invalidate AI config cache"""
    cache.delete('active_ai_config')
    if config_id:
        cache.delete(f'ai_config_{config_id}')

# ============================
# ASYNC TASKS
# ============================

def process_embeddings_async(doc_ids: List[int]):
    """Process embeddings for documents asynchronously"""
    def process_batch(batch_ids):
        for doc_id in batch_ids:
            try:
                doc = BusinessDocument.objects.get(id=doc_id)
                doc.generate_embeddings()
                doc.save(update_fields=['embeddings_data'])
                logger.debug(f"Embeddings generated for doc {doc_id}")
            except Exception as e:
                logger.error(f"Error processing doc {doc_id}: {str(e)}")
    
    # Process in batches
    batch_size = 10
    batches = [doc_ids[i:i+batch_size] for i in range(0, len(doc_ids), batch_size)]
    
    for batch in batches:
        executor.submit(process_batch, batch)

def generate_streaming_response(prompt: str, model: str) -> Generator:
    """Generate streaming response from Ollama"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.5,
                    "num_predict": 300,
                }
            },
            stream=True,
            timeout=OLLAMA_TIMEOUT
        )
        
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if 'response' in data:
                            yield json.dumps({'chunk': data['response']}) + '\n'
                        if data.get('done', False):
                            yield json.dumps({'done': True}) + '\n'
                    except json.JSONDecodeError:
                        continue
        else:
            yield json.dumps({'error': f'Ollama error: {response.status_code}'}) + '\n'
    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        yield json.dumps({'error': str(e)}) + '\n'

# ============================
# RAG CHAT ENDPOINT (STREAMING)
# ============================

@csrf_exempt
@rate_limit('rag_chat')
@log_api_call
@handle_errors
def rag_chat(request):
    """Optimized RAG chat endpoint with streaming support"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    data = json.loads(request.body)
    query = data.get('query', '').strip()
    session_id = data.get('session_id', 'default')
    ai_config_id = data.get('ai_config_id')
    stream = data.get('stream', False)
    
    if not query:
        return JsonResponse({'error': 'Query is required'}, status=400)
    
    ai_config = get_cached_config(ai_config_id) if ai_config_id else get_active_config()
    relevant_docs = get_relevant_documents(query, ai_config)
    
    context = build_context(relevant_docs)
    ai_intro, ai_role = build_ai_persona(ai_config)
    prompt = build_prompt(query, context, ai_role, ai_intro)
    model_name = get_model_name(ai_config)
    
    # If streaming is requested
    if stream:
        response_stream = generate_streaming_response(prompt, model_name)
        return StreamingHttpResponse(
            response_stream,
            content_type='application/x-ndjson'
        )
    
    # Non-streaming response
    response = call_ollama(model_name, prompt)
    
    if not response:
        return JsonResponse({
            'success': False,
            'error': 'Ollama service unavailable'
        }, status=503)
    
    ai_response = response.get('response', '').strip()
    
    # Save conversation asynchronously
    executor.submit(
        save_conversation_async,
        session_id, query, ai_response, ai_config, relevant_docs
    )
    
    sources = prepare_sources(relevant_docs)
    
    return JsonResponse({
        'success': True,
        'response': ai_response,
        'sources': sources,
        'source_count': len(sources),
        'ai_config': {
            'id': ai_config.id if ai_config else None,
            'name': ai_config.ai_name if ai_config else 'Default AI',
            'company': ai_config.company_name if ai_config else None
        }
    })

def get_relevant_documents(query: str, ai_config: Optional[AIConfiguration]) -> List:
    """Get relevant documents with optimized filtering"""
    relevant_docs = rag_service.search_documents(query)
    
    if ai_config and ai_config.use_rag:
        config_doc_ids = set(ai_config.documents.filter(is_active=True).values_list('id', flat=True))
        relevant_docs = [doc for doc in relevant_docs if doc.id in config_doc_ids]
    
    return relevant_docs

def build_context(docs: List) -> str:
    """Build context from documents efficiently"""
    if not docs:
        return "No relevant information found in database.\n\n"
    
    context_parts = ["=== RELEVANT INFORMATION FROM DATABASE ===\n"]
    for i, doc in enumerate(docs, 1):
        context_parts.append(f"[{i}] {doc.title}:")
        content = doc.content[:MAX_PREVIEW_LENGTH]
        if len(doc.content) > MAX_PREVIEW_LENGTH:
            content += "..."
        context_parts.append(f"{content}\n")
    
    return "\n".join(context_parts)

def build_ai_persona(ai_config: Optional[AIConfiguration]) -> Tuple[str, str]:
    """Build AI persona messages"""
    if ai_config:
        ai_intro = ai_config.greeting_message.format(
            ai_name=ai_config.ai_name,
            company_name=ai_config.company_name,
            location=ai_config.location
        )
        ai_role = f"You are {ai_config.ai_name}, an {ai_config.role_description} for {ai_config.company_name} in {ai_config.location}."
    else:
        ai_intro = "Hello! I'm your AI assistant."
        ai_role = "You are an AI assistant."
    return ai_intro, ai_role

def build_prompt(query: str, context: str, ai_role: str, ai_intro: str) -> str:
    """Build the complete prompt"""
    return f"""{context}

{ai_role}
{ai_intro}

User Question: {query}

Instructions: Use the information above if relevant.
If the information isn't relevant or sufficient, use your general knowledge.
Always be helpful and professional.

Answer:"""

def get_model_name(ai_config: Optional[AIConfiguration]) -> str:
    """Get model name with caching"""
    if not ai_config:
        return DEFAULT_MODEL
    
    cache_key = f'model_name_{ai_config.id}'
    model_name = cache.get(cache_key)
    
    if model_name:
        return model_name
    
    model_filename = f"{ai_config.ai_name.lower().replace(' ', '_')}_{ai_config.id}"
    model_path = os.path.join(
        getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs'),
        f"{model_filename}.txt"
    )
    
    if os.path.exists(model_path):
        model_name = f"{ai_config.ai_name.lower().replace(' ', '-')}-{ai_config.id}:latest"
        cache.set(cache_key, model_name, CACHE_TIMEOUT)
        return model_name
    
    return DEFAULT_MODEL

def call_ollama(model: str, prompt: str) -> Optional[Dict]:
    """Call Ollama API with timeout and error handling"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "num_predict": 300,
                }
            },
            timeout=OLLAMA_TIMEOUT
        )
        if response.status_code == 200:
            return response.json()
    except (requests.Timeout, requests.ConnectionError):
        pass
    return None

def save_conversation_async(session_id: str, query: str, response: str, 
                           ai_config: Optional[AIConfiguration], docs: List):
    """Save conversation asynchronously"""
    try:
        doc_ids = ",".join(str(doc.id) for doc in docs)
        ConversationMemory.objects.create(
            session_id=session_id,
            query=query,
            response=response,
            ai_config=ai_config,
            relevant_docs_ids=doc_ids
        )
        logger.debug(f"Conversation saved async for session {session_id}")
    except Exception as e:
        logger.error(f"Error saving conversation async: {str(e)}")

def prepare_sources(docs: List) -> List[Dict]:
    """Prepare source documents for response"""
    sources = []
    for doc in docs:
        content = doc.content[:MAX_SNIPPET_LENGTH]
        if len(doc.content) > MAX_SNIPPET_LENGTH:
            content += "..."
        sources.append({
            'id': doc.id,
            'title': doc.title,
            'type': doc.get_document_type_display(),
            'preview': content
        })
    return sources

# ============================
# ASYNC EMBEDDINGS GENERATION
# ============================

@csrf_exempt
@staff_member_required
@log_api_call
@handle_errors
def generate_embeddings_async(request):
    """Generate embeddings asynchronously for all documents"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    with _embeddings_lock:
        docs_to_process = BusinessDocument.objects.filter(
            Q(embeddings_data__isnull=True) | Q(embeddings_data__exact="")
        )
        doc_ids = list(docs_to_process.values_list('id', flat=True))
        
        if not doc_ids:
            return JsonResponse({
                'success': True,
                'message': 'All documents already have embeddings',
                'documents_queued': 0
            })
    
    # Process asynchronously
    executor.submit(process_embeddings_async, doc_ids)
    
    return JsonResponse({
        'success': True,
        'message': f'Started processing {len(doc_ids)} documents',
        'documents_queued': len(doc_ids),
        'estimated_time': f'{len(doc_ids) * 2} seconds'
    })

@csrf_exempt
@staff_member_required
@log_api_call
@handle_errors
def get_embedding_status(request):
    """Get status of embedding generation"""
    total = BusinessDocument.objects.count()
    with_embeddings = BusinessDocument.objects.exclude(
        embeddings_data__isnull=True
    ).exclude(embeddings_data__exact="").count()
    
    return JsonResponse({
        'success': True,
        'total_documents': total,
        'documents_with_embeddings': with_embeddings,
        'documents_pending': total - with_embeddings,
        'percentage_complete': (with_embeddings / total * 100) if total > 0 else 0
    })

# [Continue with other functions...]
