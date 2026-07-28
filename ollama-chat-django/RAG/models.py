# RAG/models.py - Complete updated file
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
import json

class AIConfiguration(models.Model):
    """Configuration for the AI assistant - Database-driven"""
    ai_name = models.CharField(
        max_length=100, 
        default="",
        help_text="Name of your AI assistant"
    )
    company_name = models.CharField(
        max_length=200, 
        default="",
        help_text="Company this AI represents"
    )
    location = models.CharField(
        max_length=200, 
        default="",
        help_text="Location/office of the company"
    )
    base_model = models.CharField(
        max_length=100, 
        default="phi", 
        help_text="Ollama base model name"
    )
    
    # AI Personality Settings
    role_description = models.TextField(
        default="customer assistant",
        help_text="Brief description of the AI's role"
    )
    greeting_message = models.TextField(
        default="Hi there! I'm {ai_name}, your assistant for {company_name} in {location}! How can I help you today?",
        help_text="Use {ai_name}, {company_name}, {location} as placeholders"
    )
    
    # RAG Integration Settings
    use_rag = models.BooleanField(default=True, help_text="Enable RAG for document-based responses")
    rag_threshold = models.FloatField(default=0.7, help_text="Similarity threshold for RAG retrieval")
    max_context_length = models.IntegerField(default=2000, help_text="Max context length for responses")
    
    # System Prompt Template
    system_prompt_template = models.TextField(
        default="""ROLE: You are {ai_name}, an {role_description} for {company_name} in {location}

PERSONALITY: You are helpful, friendly, and professional. You provide accurate information and excellent customer service.

RULES:
1. Your name is ALWAYS {ai_name}
2. You work for {company_name} in {location}
3. ALWAYS introduce yourself as: "{greeting_message}"
4. If you don't know something, say so and offer to help find the answer
5. Always be polite and professional
6. Use relevant information from provided context when available
7. Keep responses concise and helpful""",
        help_text="System prompt template for Ollama"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "AI Configuration"
        verbose_name_plural = "AI Configurations"
        ordering = ['-is_active', '-created_at']
    
    def __str__(self):
        return f"{self.ai_name} - {self.company_name}"
    
    def clean(self):
        """Validate that required fields are set"""
        if not self.ai_name:
            raise ValidationError({'ai_name': 'AI Name is required'})
        if not self.company_name:
            raise ValidationError({'company_name': 'Company Name is required'})
        if not self.location:
            raise ValidationError({'location': 'Location is required'})
    
    def save(self, *args, **kwargs):
        self.full_clean()  # Run validation before saving
        super().save(*args, **kwargs)
    
    def get_system_prompt(self):
        """Generate the full system prompt with placeholders filled"""
        formatted_greeting = self.greeting_message.format(
            ai_name=self.ai_name,
            company_name=self.company_name,
            location=self.location
        )
        
        return self.system_prompt_template.format(
            ai_name=self.ai_name,
            company_name=self.company_name,
            location=self.location,
            role_description=self.role_description,
            greeting_message=formatted_greeting
        )
    
    def generate_ollama_modelfile(self):
        """Generate the Ollama Modelfile content"""
        return f"""FROM {self.base_model}
SYSTEM \"\"\"{self.get_system_prompt()}\"\"\""""
    
    def save_ollama_modelfile(self, filepath=None):
        """Save the Ollama Modelfile to disk"""
        if not filepath:
            import os
            from django.conf import settings
            output_dir = getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs')
            os.makedirs(output_dir, exist_ok=True)
            filename = f"{self.ai_name.lower().replace(' ', '_')}_{self.id}.txt"
            filepath = os.path.join(output_dir, filename)
        
        content = self.generate_ollama_modelfile()
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath


class BusinessDocument(models.Model):
    DOCUMENT_TYPES = [
        ('faq', 'FAQ'),
        ('policy', 'Company Policy'),
        ('product', 'Product Info'),
        ('service', 'Service Info'),
        ('employee', 'Employee Info'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=255)
    content = models.TextField()
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='faq')
    keywords = models.CharField(max_length=500, blank=True)
    # Reference to which AI configuration this document belongs
    ai_config = models.ForeignKey(AIConfiguration, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    # Store embeddings as TextField
    embeddings_data = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_embeddings(self, embeddings):
        """Store embeddings as JSON string"""
        self.embeddings_data = json.dumps(embeddings)
    
    def get_embeddings(self):
        """Get embeddings from JSON string"""
        if self.embeddings_data:
            return json.loads(self.embeddings_data)
        return []

    def __str__(self):
        return f"{self.title} - {self.get_document_type_display()}"


class ConversationMemory(models.Model):
    session_id = models.CharField(max_length=100)
    query = models.TextField()
    response = models.TextField()
    # Reference to which AI configuration was used
    ai_config = models.ForeignKey(AIConfiguration, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    # Store as comma-separated string
    relevant_docs_ids = models.CharField(max_length=500, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['session_id', 'timestamp']),
            models.Index(fields=['ai_config']),
        ]

    def set_relevant_docs(self, doc_ids):
        """Store list of document IDs"""
        self.relevant_docs_ids = ",".join(str(doc_id) for doc_id in doc_ids)
    
    def get_relevant_docs(self):
        """Get list of document IDs"""
        if self.relevant_docs_ids:
            return [int(id_str.strip()) for id_str in self.relevant_docs_ids.split(",") if id_str.strip()]
        return []

    def __str__(self):
        return f"{self.session_id}: {self.query[:50]}..."

    @classmethod
    def get_conversation_history(cls, session_id, limit=10):
        """Get conversation history for a session"""
        return cls.objects.filter(session_id=session_id).order_by('timestamp')[:limit]
