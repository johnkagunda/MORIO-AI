# RAG/views.py - Complete updated file
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404
from django.db.models import Count
import json
import requests
from .rag_service import rag_service
from .models import BusinessDocument, ConversationMemory, AIConfiguration
import os
from django.conf import settings

# ============================
# RAG CHAT ENDPOINT (UPDATED)
# ============================

@csrf_exempt
def rag_chat(request):
    """RAG chat endpoint with AI configuration support"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        query = data.get('query', '').strip()
        session_id = data.get('session_id', 'default')
        ai_config_id = data.get('ai_config_id')
        
        if not query:
            return JsonResponse({'error': 'Query is required'}, status=400)
        
        print(f"🔍 RAG Query: {query}")
        
        # Get AI configuration
        ai_config = None
        if ai_config_id:
            try:
                ai_config = AIConfiguration.objects.get(id=ai_config_id, is_active=True)
                print(f"🤖 Using AI config: {ai_config.ai_name} for {ai_config.company_name}")
            except AIConfiguration.DoesNotExist:
                print(f"⚠️ AI config {ai_config_id} not found or inactive, using default")
        
        # If no specific config, use the first active one
        if not ai_config:
            ai_config = AIConfiguration.objects.filter(is_active=True).first()
            if ai_config:
                print(f"🤖 Using active AI config: {ai_config.ai_name}")
        
        # Search for relevant documents (filtered by AI config if specified)
        relevant_docs = rag_service.search_documents(query)
        
        # Filter by AI config if specified
        if ai_config and ai_config.use_rag:
            # Get documents belonging to this AI config
            config_doc_ids = ai_config.documents.filter(is_active=True).values_list('id', flat=True)
            relevant_docs = [doc for doc in relevant_docs if doc.id in config_doc_ids]
            print(f"📄 Found {len(relevant_docs)} relevant documents for {ai_config.company_name}")
        else:
            print(f"📄 Found {len(relevant_docs)} relevant documents")
        
        # Build context
        if relevant_docs:
            context = "=== RELEVANT INFORMATION FROM DATABASE ===\n\n"
            for i, doc in enumerate(relevant_docs, 1):
                context += f"[{i}] {doc.title}:\n"
                content_preview = doc.content[:300] + "..." if len(doc.content) > 300 else doc.content
                context += f"{content_preview}\n\n"
        else:
            context = "No relevant information found in database.\n\n"
        
        # Build AI introduction based on config
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
        
        # Build prompt
        prompt = f"""{context}

{ai_role}
{ai_intro}

User Question: {query}

Instructions: Use the information above if relevant.
If the information isn't relevant or sufficient, use your general knowledge.
Always be helpful and professional.

Answer:"""
        
        # Determine which model to use
        model_name = "morio-phi:latest"  # Default
        if ai_config:
            # Check if we have a custom model for this config
            model_filename = f"{ai_config.ai_name.lower().replace(' ', '_')}_{ai_config.id}"
            model_path = os.path.join(
                getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs'),
                f"{model_filename}.txt"
            )
            
            # If modelfile exists, use custom model name
            if os.path.exists(model_path):
                custom_model_name = f"{ai_config.ai_name.lower().replace(' ', '-')}-{ai_config.id}"
                model_name = f"{custom_model_name}:latest"
                print(f"🤖 Using custom model: {model_name}")
        
        # Call Ollama
        ollama_data = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.5,
                "num_predict": 300,
            }
        }
        
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=ollama_data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result.get('response', '').strip()
            
            # Log conversation
            ConversationMemory.objects.create(
                session_id=session_id,
                query=query,
                response=ai_response,
                ai_config=ai_config,
                relevant_docs_ids=",".join(str(doc.id) for doc in relevant_docs)
            )
            
            # Prepare response with sources
            sources = []
            for doc in relevant_docs:
                sources.append({
                    'id': doc.id,
                    'title': doc.title,
                    'type': doc.get_document_type_display(),
                    'preview': doc.content[:150] + '...' if len(doc.content) > 150 else doc.content
                })
            
            response_data = {
                'success': True,
                'response': ai_response,
                'sources': sources,
                'source_count': len(sources),
                'ai_config': {
                    'id': ai_config.id if ai_config else None,
                    'name': ai_config.ai_name if ai_config else 'Default AI',
                    'company': ai_config.company_name if ai_config else None
                }
            }
            
            return JsonResponse(response_data)
        else:
            return JsonResponse({
                'success': False,
                'error': f'Ollama error: {response.status_code}',
                'ai_config': {
                    'id': ai_config.id if ai_config else None,
                    'name': ai_config.ai_name if ai_config else 'Default AI'
                }
            }, status=500)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

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
        
        # Get current user if authenticated
        user = request.user if request.user.is_authenticated else None
        
        # Get AI config if specified
        ai_config = None
        ai_config_id = data.get('ai_config_id')
        if ai_config_id:
            try:
                ai_config = AIConfiguration.objects.get(id=ai_config_id, is_active=True)
            except AIConfiguration.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'AI configuration {ai_config_id} not found or inactive'
                }, status=400)
        
        # Create document
        document = BusinessDocument.objects.create(
            title=data.get('title', 'Untitled'),
            content=data.get('content', ''),
            document_type=data.get('type', 'faq'),
            keywords=data.get('keywords', ''),
            ai_config=ai_config,
            is_active=data.get('is_active', True),
            created_by=user
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Document added successfully',
            'document_id': document.id,
            'title': document.title,
            'ai_config': {
                'id': ai_config.id if ai_config else None,
                'name': ai_config.ai_name if ai_config else None
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

def search_documents(request):
    """Search documents in database"""
    query = request.GET.get('q', '')
    ai_config_id = request.GET.get('ai_config_id')
    
    # Filter by AI config if specified
    documents = rag_service.search_documents(query, top_k=10)
    
    if ai_config_id:
        try:
            ai_config = AIConfiguration.objects.get(id=ai_config_id)
            documents = [doc for doc in documents if doc.ai_config == ai_config]
        except AIConfiguration.DoesNotExist:
            pass
    
    results = []
    for doc in documents:
        results.append({
            'id': doc.id,
            'title': doc.title,
            'type': doc.get_document_type_display(),
            'content': doc.content[:200] + '...' if len(doc.content) > 200 else doc.content,
            'keywords': doc.keywords,
            'created_at': doc.created_at.strftime('%Y-%m-%d'),
            'has_embeddings': bool(doc.embeddings_data),
            'ai_config': {
                'id': doc.ai_config.id if doc.ai_config else None,
                'name': doc.ai_config.ai_name if doc.ai_config else None
            }
        })
    
    return JsonResponse({
        'success': True,
        'query': query,
        'results': results,
        'count': len(results)
    })

@csrf_exempt
def generate_embeddings(request):
    """Generate embeddings for all documents"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        # Get documents without embeddings
        documents = BusinessDocument.objects.filter(embeddings_data__isnull=True) | \
                   BusinessDocument.objects.filter(embeddings_data__exact="")
        
        count = 0
        for doc in documents:
            doc.generate_embeddings()
            doc.save(update_fields=['embeddings_data'])
            count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Generated embeddings for {count} documents',
            'count': count,
            'total_documents': BusinessDocument.objects.count()
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# ============================
# AI CONFIGURATION MANAGEMENT
# ============================

@staff_member_required
@require_http_methods(["GET"])
def list_ai_configs(request):
    """List all AI configurations (API endpoint)"""
    configs = AIConfiguration.objects.all().order_by('-is_active', 'ai_name')
    
    data = []
    for config in configs:
        data.append({
            'id': config.id,
            'ai_name': config.ai_name,
            'company_name': config.company_name,
            'location': config.location,
            'is_active': config.is_active,
            'base_model': config.base_model,
            'role_description': config.role_description,
            'greeting_message': config.greeting_message,
            'documents_count': config.documents.count(),
            'conversations_count': config.conversations.count(),
            'created_at': config.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': config.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        })
    
    return JsonResponse({
        'success': True,
        'count': len(data),
        'configurations': data
    })

@staff_member_required
@require_http_methods(["GET"])
def get_ai_config(request, config_id):
    """Get specific AI configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    # Check if modelfile exists
    modelfile_exists = False
    modelfile_path = None
    try:
        output_dir = getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs')
        filename = f"{config.ai_name.lower().replace(' ', '_')}_{config.id}.txt"
        modelfile_path = os.path.join(output_dir, filename)
        modelfile_exists = os.path.exists(modelfile_path)
    except:
        pass
    
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
        'ollama_modelfile': config.generate_ollama_modelfile(),
        'use_rag': config.use_rag,
        'rag_threshold': config.rag_threshold,
        'max_context_length': config.max_context_length,
        'modelfile_exists': modelfile_exists,
        'modelfile_path': modelfile_path,
        'documents_count': config.documents.count(),
        'conversations_count': config.conversations.count(),
        'created_at': config.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': config.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    return JsonResponse({
        'success': True,
        'configuration': data
    })

@staff_member_required
@require_http_methods(["POST"])
def create_ai_config(request):
    """Create a new AI configuration (API endpoint)"""
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['ai_name', 'company_name', 'location']
        for field in required_fields:
            if field not in data or not str(data[field]).strip():
                return JsonResponse({
                    'success': False,
                    'error': f'{field} is required'
                }, status=400)
        
        # Create configuration
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
        
        # Generate modelfile if requested
        if data.get('generate_modelfile', False):
            try:
                filepath = config.save_ollama_modelfile()
                modelfile_generated = True
                modelfile_path = filepath
            except Exception as e:
                modelfile_generated = False
                modelfile_error = str(e)
        else:
            modelfile_generated = False
        
        response_data = {
            'success': True,
            'message': 'AI configuration created successfully',
            'config_id': config.id,
            'ai_name': config.ai_name,
            'modelfile_generated': modelfile_generated
        }
        
        if modelfile_generated:
            response_data['modelfile_path'] = modelfile_path
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@staff_member_required
@require_http_methods(["PUT", "PATCH"])
def update_ai_config(request, config_id):
    """Update an existing AI configuration (API endpoint)"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        data = json.loads(request.body)
        
        # Update fields
        updatable_fields = [
            'ai_name', 'company_name', 'location', 
            'role_description', 'base_model', 'greeting_message',
            'is_active', 'use_rag', 'rag_threshold', 'max_context_length'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(config, field, data[field])
        
        config.save()
        
        # Regenerate modelfile if requested
        modelfile_generated = False
        modelfile_path = None
        if data.get('regenerate_modelfile', False):
            try:
                filepath = config.save_ollama_modelfile()
                modelfile_generated = True
                modelfile_path = filepath
            except Exception as e:
                modelfile_generated = False
                modelfile_error = str(e)
        
        response_data = {
            'success': True,
            'message': 'AI configuration updated successfully',
            'config_id': config.id,
            'ai_name': config.ai_name,
            'modelfile_regenerated': modelfile_generated
        }
        
        if modelfile_generated:
            response_data['modelfile_path'] = modelfile_path
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@staff_member_required
@require_http_methods(["DELETE"])
def delete_ai_config(request, config_id):
    """Delete an AI configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        ai_name = config.ai_name
        config.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'AI configuration "{ai_name}" deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@staff_member_required
@require_http_methods(["POST"])
def generate_modelfile(request, config_id):
    """Generate modelfile for specific configuration"""
    config = get_object_or_404(AIConfiguration, id=config_id)
    
    try:
        filepath = config.save_ollama_modelfile()
        
        # Read the file content to return
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return JsonResponse({
            'success': True,
            'message': f'Modelfile generated for {config.ai_name}',
            'filepath': filepath,
            'filename': os.path.basename(filepath),
            'content': content,
            'ai_config': {
                'id': config.id,
                'name': config.ai_name,
                'company': config.company_name
            }
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
    # Get stats for the dashboard
    total_configs = AIConfiguration.objects.count()
    active_configs = AIConfiguration.objects.filter(is_active=True).count()
    total_documents = BusinessDocument.objects.count()
    total_conversations = ConversationMemory.objects.count()
    
    # Get recent configurations
    recent_configs = AIConfiguration.objects.order_by('-created_at')[:5]
    
    context = {
        'total_configs': total_configs,
        'active_configs': active_configs,
        'total_documents': total_documents,
        'total_conversations': total_conversations,
        'recent_configs': recent_configs,
    }
    
    return render(request, 'RAG/ai_config.html', context)

# ============================
# HELPER FUNCTIONS
# ============================

def get_active_ai_config():
    """Helper function to get the active AI configuration"""
    try:
        return AIConfiguration.objects.filter(is_active=True).first()
    except AIConfiguration.DoesNotExist:
        return None

def get_ai_config_stats(request):
    """Get statistics about AI configurations"""
    stats = {
        'total_configs': AIConfiguration.objects.count(),
        'active_configs': AIConfiguration.objects.filter(is_active=True).count(),
        'total_documents': BusinessDocument.objects.count(),
        'documents_with_embeddings': BusinessDocument.objects.exclude(embeddings_data__isnull=True)
                                                          .exclude(embeddings_data__exact="").count(),
        'total_conversations': ConversationMemory.objects.count(),
        'companies': list(AIConfiguration.objects.values_list('company_name', flat=True).distinct()),
    }
    
    # Documents per company
    docs_per_company = []
    for config in AIConfiguration.objects.all():
        docs_per_company.append({
            'company': config.company_name,
            'ai_name': config.ai_name,
            'documents': config.documents.count(),
            'conversations': config.conversations.count()
        })
    
    stats['docs_per_company'] = docs_per_company
    
    return JsonResponse({
        'success': True,
        'stats': stats
    })
