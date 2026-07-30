# RAG/views.py - Version 2: Logging & Error Handling
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.core.cache import cache
import json
import requests
from functools import lru_cache, wraps
from typing import List, Dict, Optional, Tuple
from .rag_service import rag_service
from .models import BusinessDocument, ConversationMemory, AIConfiguration
import os
from django.conf import settings
import traceback

# Setup logging
logger = logging.getLogger(__name__)

# Constants
OLLAMA_URL = "http://localhost:11434/api/generate"
CACHE_TIMEOUT = 300
DEFAULT_MODEL = "morio-phi:latest"
OLLAMA_TIMEOUT = 30
MAX_PREVIEW_LENGTH = 300
MAX_SNIPPET_LENGTH = 150

# ============================
# DECORATORS
# ============================

def log_api_call(view_func):
    """Decorator to log API calls"""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        logger.info(f"API Call: {request.path} from {request.META.get('REMOTE_ADDR')}")
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
                    logger.debug(f"Config {config_id} loaded from DB and cached")
            except AIConfiguration.DoesNotExist:
                logger.warning(f"Config {config_id} not found")
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
            logger.debug(f"Active config {config.id} loaded and cached")
    return config

def invalidate_config_cache(config_id: Optional[int] = None):
    """Invalidate AI config cache"""
    cache.delete('active_ai_config')
    if config_id:
        cache.delete(f'ai_config_{config_id}')
    logger.info(f"Cache invalidated for config {config_id}")

# ============================
# RAG CHAT ENDPOINT
# ============================

@csrf_exempt
@log_api_call
@handle_errors
def rag_chat(request):
    """Optimized RAG chat endpoint with AI configuration support"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    data = json.loads(request.body)
    query = data.get('query', '').strip()
    session_id = data.get('session_id', 'default')
    ai_config_id = data.get('ai_config_id')
    
    if not query:
        logger.warning(f"Empty query from session {session_id}")
        return JsonResponse({'error': 'Query is required'}, status=400)
    
    logger.info(f"Processing query: {query[:50]}... from session {session_id}")
    
    ai_config = get_cached_config(ai_config_id) if ai_config_id else get_active_config()
    relevant_docs = get_relevant_documents(query, ai_config)
    
    logger.info(f"Found {len(relevant_docs)} relevant documents")
    
    return process_chat_response(query, session_id, relevant_docs, ai_config)

def get_relevant_documents(query: str, ai_config: Optional[AIConfiguration]) -> List:
    """Get relevant documents with optimized filtering"""
    relevant_docs = rag_service.search_documents(query)
    
    if ai_config and ai_config.use_rag:
        config_doc_ids = set(ai_config.documents.filter(is_active=True).values_list('id', flat=True))
        relevant_docs = [doc for doc in relevant_docs if doc.id in config_doc_ids]
        logger.debug(f"Filtered to {len(relevant_docs)} documents for config {ai_config.id}")
    
    return relevant_docs

def process_chat_response(query: str, session_id: str, relevant_docs: List, 
                         ai_config: Optional[AIConfiguration]) -> JsonResponse:
    """Process and generate chat response"""
    context = build_context(relevant_docs)
    ai_intro, ai_role = build_ai_persona(ai_config)
    prompt = build_prompt(query, context, ai_role, ai_intro)
    model_name = get_model_name(ai_config)
    
    logger.info(f"Calling Ollama with model: {model_name}")
    response = call_ollama(model_name, prompt)
    
    if not response:
        logger.error(f"Ollama service unavailable for model {model_name}")
        return JsonResponse({
            'success': False,
            'error': 'Ollama service unavailable'
        }, status=503)
    
    ai_response = response.get('response', '').strip()
    
    try:
        save_conversation(session_id, query, ai_response, ai_config, relevant_docs)
        logger.info(f"Conversation saved for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to save conversation: {str(e)}")
    
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
        else:
            logger.error(f"Ollama returned status {response.status_code}: {response.text}")
    except requests.Timeout:
        logger.error(f"Ollama timeout after {OLLAMA_TIMEOUT}s for model {model}")
    except requests.ConnectionError:
        logger.error(f"Cannot connect to Ollama at {OLLAMA_URL}")
    return None

def save_conversation(session_id: str, query: str, response: str, 
                     ai_config: Optional[AIConfiguration], docs: List):
    """Save conversation to database"""
    try:
        doc_ids = ",".join(str(doc.id) for doc in docs)
        ConversationMemory.objects.create(
            session_id=session_id,
            query=query,
            response=response,
            ai_config=ai_config,
            relevant_docs_ids=doc_ids
        )
    except Exception as e:
        logger.error(f"Error saving conversation: {str(e)}")
        raise

def prepare_sources(docs: List) -> List[Dict]:
    """Prepare source documents for response"""
   
