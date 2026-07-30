# RAG/views.py - Version 1: Base Optimized
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.core.cache import cache
import json
import requests
from functools import lru_cache
from typing import List, Dict, Optional, Tuple
from .rag_service import rag_service
from .models import BusinessDocument, ConversationMemory, AIConfiguration
import os
from django.conf import settings

# Constants
OLLAMA_URL = "http://localhost:11434/api/generate"
CACHE_TIMEOUT = 300  # 5 minutes
DEFAULT_MODEL = "morio-phi:latest"
OLLAMA_TIMEOUT = 30
MAX_PREVIEW_LENGTH = 300
MAX_SNIPPET_LENGTH = 150

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
# RAG CHAT ENDPOINT
# ============================

@csrf_exempt
def rag_chat(request):
    """Optimized RAG chat endpoint with AI configuration support"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        query = data.get('query', '').strip()
        session_id = data.get('session_id', 'default')
        ai_config_id = data.get('ai_config_id')
        
        if not query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        # Get AI configuration (with caching)
        ai_config = get_cached_config(ai_config_id) if ai_config_id else get_active_config()
        
        # Search for relevant documents (filtered by AI config)
        relevant_docs = get_relevant_documents(query, ai_config)
        
        # Build response
        return process_chat_response(query, session_id, relevant_docs, ai_config)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except requests.exceptions.RequestException as e:
        return JsonResponse({'success': False, 'error': f'Ollama connection error: {str(e)}'}, status=503)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

def get_relevant_documents(query: str, ai_config: Optional[AIConfiguration]) -> List:
    """Get relevant documents with optimized filtering"""
    relevant_docs = rag_service.search_documents(query)
    
    if ai_config and ai_config.use_rag:
        config_doc_ids = set(ai_config.documents.filter(is_active=True).values_list('id', flat=True))
        relevant_docs = [doc for doc in relevant_docs if doc.id in config_doc_ids]
    
    return relevant_docs

def process_chat_response(query: str, session_id: str, relevant_docs: List, 
                         ai_config: Optional[AIConfiguration]) -> JsonResponse:
    """Process and generate chat response"""
    context = build_context(relevant_docs)
    ai_intro, ai_role = build_ai_persona(ai_config)
    prompt = build_prompt(query, context, ai_role, ai_intro)
    model_name = get_model_name(ai_config)
    response = call_ollama(model_name, prompt)
    
    if not response:
        return JsonResponse({
            'success': False,
            'error': 'Ollama service unavailable'
        }, status=503)
    
    ai_response = response.get('response', '').strip()
    save_conversation(session_id, query, ai_response, ai_config, relevant_docs)
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
    except (requests.Timeout, requests.ConnectionError):
        pass
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
        print(f"Error saving conversation: {e}")

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
# DOCUMENT MANAGEMENT
# ============================

@csrf_exempt
def add_document(request):
    """Add document to RAG database"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        if not data.get('content'):
            return JsonResponse({'error': 'Content is required'}, status=400)
        
        ai_config = None
        ai_config_id = data.get('ai_config_id')
        if ai_config_id:
            ai_config = get_cached_config(ai_config_id)
            if not ai_config:
                return JsonResponse({
                    'success': False,
                    'error': 'AI configuration not found or inactive'
                }, status=400)
        
        document = BusinessDocument.objects.create(
            title=data.get('title', 'Untitled')[:255],
            content=data.get('content'),
            document_type=data.get('type', 'faq'),
            keywords=data.get('keywords', '')[:500],
            ai_config=ai_config,
            is_active=data.get('is_active', True),
            created_by=request.user if request.user.is_authenticated else None
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Document added successfully',
            'document_id': document.id,
            'title': document.title
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

def search_documents(request):
    """Search documents with optimized query"""
    query = request.GET.get('q', '').strip()
    ai_config_id = request.GET.get('ai_config_id')
    
    cache_key = f'doc_search_{query}_{ai_config_id}'
    cached_results = cache.get(cache_key)
    if cached_results:
        return JsonResponse(cached_results)
    
    documents = rag_service.search_documents(query, top_k=10) if query else []
    
    if ai_config_id:
        ai_config = get_cached_config(ai_config_id)
        if ai_config:
            documents = [doc for doc in documents if doc.ai_config_id == ai_config.id]
    
    results = []
    for doc in documents[:20]:
        results.append({
            'id': doc.id,
            'title': doc.title,
            'type': doc.get_document_type_display(),
            'content': doc.content[:200] + '...' if len(doc.content) > 200 else doc.content,
            'keywords': doc.keywords,
            'created_at': doc.created_at.strftime('%Y-%m-%d'),
            'has_embeddings': bool(doc.embeddings_data)
        })
    
    response_data = {
        'success': True,
        'query': query,
        'results': results,
        'count': len(results)
    }
    
    cache.set(cache_key, response_data, CACHE_TIMEOUT)
    return JsonResponse(response_data)

@csrf_exempt
def generate_embeddings(request):
    """Generate embeddings for all documents (with progress tracking)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        total_docs = BusinessDocument.objects.count()
        docs_to_process = BusinessDocument.objects.filter(
            Q(embeddings_data__isnull=True) | Q(embeddings_data__exact="")
        )
        
        count = 0
        for doc in docs_to_process.iterator(chunk_size=100):
            doc.generate_embeddings()
            doc.save(update_fields=['embeddings_data'])
            count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Generated embeddings for {count} documents',
            'count': count,
            'total_documents': total_docs
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ============================
# AI CONFIGURATION MANAGEMENT
# ============================

@staff_member_required
@require_http_methods(["GET"])
def list_ai_configs(request):
    """List all AI configurations with aggregated counts"""
    configs = AIConfiguration.objects.annotate(
        documents_count=Count('documents'),
        conversations_count=Count('conversations')
    ).order_by('-is_active', 'ai_name')
    
    data = [{
        'id': config.id,
        'ai_name': config.ai_name,
        'company_name': config.company_name,
        'location': config.location,
        'is_active': config.is_active,
        'base_model': config.base_model,
        'role_description': config.role_description,
        'greeting_message': config.greeting_message,
        'documents_count': config.documents_count,
        'conversations_count': config.conversations_count,
        'created_at': config.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': config.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
    } for config in configs]
    
    return JsonResponse({
        'success': True,
        'count': len(data),
        'configurations': data
    })

@staff_member_required
@require_http_methods(["GET"])
def get_ai_config(request, config_id):
    """Get specific AI configuration with caching"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    modelfile_exists = False
    modelfile_path = None
    output_dir = getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs')
    filename = f"{config.ai_name.lower().replace(' ', '_')}_{config.id}.txt"
    modelfile_path = os.path.join(output_dir, filename)
    modelfile_exists = os.path.exists(modelfile_path)
    
    data = {
        'id': config.id,
        'ai_name': config.ai_name,
        'company_name': config.company_name,
        'location': config.location,
        'is_active': config.is_active,
        'base_model': config.base_model,
        'role_description': config.role_description,
        'greeting_message': config.greeting_message,
        'system_prompt': config.get_system_prompt(),
        'use_rag': config.use_rag,
        'rag_threshold': config.rag_threshold,
        'max_context_length': config.max_context_length,
        'modelfile_exists': modelfile_exists,
        'modelfile_path': modelfile_path if modelfile_exists else None,
        'documents_count': config.documents.count(),
        'conversations_count': config.conversations.count(),
        'created_at': config.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': config.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    return JsonResponse({'success': True, 'configuration': data})

@staff_member_required
@require_http_methods(["POST"])
def create_ai_config(request):
    """Create a new AI configuration"""
    try:
        data = json.loads(request.body)
        
        required_fields = ['ai_name', 'company_name', 'location']
        missing_fields = [f for f in required_fields if not str(data.get(f, '')).strip()]
        if missing_fields:
            return JsonResponse({
                'success': False,
                'error': f'Required fields missing: {", ".join(missing_fields)}'
            }, status=400)
        
        config = AIConfiguration.objects.create(
            ai_name=data['ai_name'].strip(),
            company_name=data['company_name'].strip(),
            location=data['location'].strip(),
            role_description=data.get('role_description', 'customer assistant').strip(),
            base_model=data.get('base_model', 'phi').strip(),
            greeting_message=data.get('greeting_message', 
                "Hi there! I'm {ai_name}, your assistant for {company_name} in {location}! How can I help you today?").strip(),
            is_active=data.get('is_active', True)
        )
        
        modelfile_generated = False
        modelfile_path = None
        if data.get('generate_modelfile', False):
            try:
                modelfile_path = config.save_ollama_modelfile()
                modelfile_generated = True
            except Exception as e:
                print(f"Error generating modelfile: {e}")
        
        response_data = {
            'success': True,
            'message': 'AI configuration created successfully',
            'config_id': config.id,
            'ai_name': config.ai_name,
            'modelfile_generated': modelfile_generated
        }
        
        if modelfile_generated:
            response_data['modelfile_path'] = modelfile_path
        
        invalidate_config_cache()
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@staff_member_required
@require_http_methods(["PUT", "PATCH"])
def update_ai_config(request, config_id):
    """Update an existing AI configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        data = json.loads(request.body)
        
        updatable_fields = [
            'ai_name', 'company_name', 'location', 
            'role_description', 'base_model', 'greeting_message',
            'is_active', 'use_rag', 'rag_threshold', 'max_context_length'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(config, field, data[field])
        
        config.save()
        
        modelfile_generated = False
        modelfile_path = None
        if data.get('regenerate_modelfile', False):
            try:
                modelfile_path = config.save_ollama_modelfile()
                modelfile_generated = True
            except Exception as e:
                print(f"Error regenerating modelfile: {e}")
        
        invalidate_config_cache(config.id)
        
        return JsonResponse({
            'success': True,
            'message': 'AI configuration updated successfully',
            'config_id': config.id,
            'ai_name': config.ai_name,
            'modelfile_regenerated': modelfile_generated,
            'modelfile_path': modelfile_path if modelfile_generated else None
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@staff_member_required
@require_http_methods(["DELETE"])
def delete_ai_config(request, config_id):
    """Delete an AI configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        ai_name = config.ai_name
        config.delete()
        invalidate_config_cache(config_id)
        
        return JsonResponse({
            'success': True,
            'message': f'AI configuration "{ai_name}" deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@staff_member_required
@require_http_methods(["POST"])
def generate_modelfile(request, config_id):
    """Generate modelfile for specific configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        filepath = config.save_ollama_modelfile()
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return JsonResponse({
            'success': True,
            'message': f'Modelfile generated for {config.ai_name}',
            'filepath': filepath,
            'filename': os.path.basename(filepath),
            'content': content
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Failed to generate modelfile: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["GET"])
def ai_config_manager(request):
    """Web interface for managing AI configurations"""
    stats = cache.get('ai_config_stats')
    if not stats:
        stats = {
            'total_configs': AIConfiguration.objects.count(),
            'active_configs': AIConfiguration.objects.filter(is_active=True).count(),
            'total_documents': BusinessDocument.objects.count(),
            'total_conversations': ConversationMemory.objects.count(),
        }
        cache.set('ai_config_stats', stats, CACHE_TIMEOUT)
    
    recent_configs = AIConfiguration.objects.select_related().order_by('-created_at')[:5]
    
    context = {
        **stats,
        'recent_configs': recent_configs,
    }
    
    return render(request, 'RAG/ai_config.html', context)

# ============================
# HELPER FUNCTIONS
# ============================

@lru_cache(maxsize=1)
def get_active_ai_config():
    """Helper function to get the active AI configuration with LRU cache"""
    try:
        return AIConfiguration.objects.filter(is_active=True).first()
    except AIConfiguration.DoesNotExist:
        return None

@staff_member_required
@require_http_methods(["GET"])
def get_ai_config_stats(request):
    """Get statistics about AI configurations with caching"""
    stats = cache.get('ai_config_full_stats')
    if stats:
        return JsonResponse({'success': True, 'stats': stats})
    
    configs = AIConfiguration.objects.annotate(
        doc_count=Count('documents'),
        conv_count=Count('conversations')
    )
    
    docs_with_embeddings = BusinessDocument.objects.exclude(
        embeddings_data__isnull=True
    ).exclude(embeddings_data__exact="").count()
    
    docs_per_company = [{
        'company': config.company_name,
        'ai_name': config.ai_name,
        'documents': config.doc_count,
        'conversations': config.conv_count
    } for config in configs]
    
    stats = {
        'total_configs': configs.count(),
        'active_configs': configs.filter(is_active=True).count(),
        'total_documents': BusinessDocument.objects.count(),
        'documents_with_embeddings': docs_with_embeddings,
        'total_conversations': ConversationMemory.objects.count(),
        'companies': list(configs.values_list('company_name', flat=True).distinct()),
        'docs_per_company': docs_per_company,
    }
    
    cache.set('ai_config_full_stats', stats, CACHE_TIMEOUT)
    
    return JsonResponse({'success': True, 'stats': stats})
