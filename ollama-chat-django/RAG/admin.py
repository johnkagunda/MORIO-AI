from django.contrib import admin
from django.utils.html import format_html
from .models import AIConfiguration, BusinessDocument, ConversationMemory

@admin.register(AIConfiguration)
class AIConfigurationAdmin(admin.ModelAdmin):
    list_display = ['id', 'ai_name', 'company_name', 'location', 'is_active', 'created_at', 'generate_modelfile_link']
    list_filter = ['is_active', 'created_at']
    list_editable = ['is_active']
    search_fields = ['ai_name', 'company_name', 'location']
    fieldsets = (
        ('Basic Information', {
            'fields': ('ai_name', 'company_name', 'location', 'is_active')
        }),
        ('AI Settings', {
            'fields': ('base_model', 'role_description', 'greeting_message')
        }),
        ('RAG Settings', {
            'fields': ('use_rag', 'rag_threshold', 'max_context_length')
        }),
        ('Advanced', {
            'fields': ('system_prompt_template',),
            'classes': ('collapse',)
        }),
    )
    actions = ['export_modelfiles', 'activate_configs', 'deactivate_configs']
    
    def generate_modelfile_link(self, obj):
        return format_html(
            '<a href="/admin/RAG/aiconfiguration/{}/generate-modelfile/" target="_blank">📄 Generate</a>',
            obj.id
        )
    generate_modelfile_link.short_description = 'Modelfile'
    
    def export_modelfiles(self, request, queryset):
        for config in queryset:
            try:
                filepath = config.save_ollama_modelfile()
                self.message_user(request, f"Generated modelfile for {config.ai_name}: {filepath}")
            except Exception as e:
                self.message_user(request, f"Error generating for {config.ai_name}: {str(e)}", level='error')
    export_modelfiles.short_description = "📄 Export selected to Modelfile"
    
    def activate_configs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Activated {updated} configuration(s)")
    activate_configs.short_description = "🟢 Activate selected"
    
    def deactivate_configs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated} configuration(s)")
    deactivate_configs.short_description = "🔴 Deactivate selected"

@admin.register(BusinessDocument)
class BusinessDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'document_type', 'ai_config', 'is_active', 'created_at']
    list_filter = ['document_type', 'is_active', 'ai_config']
    search_fields = ['title', 'content', 'keywords']
    list_editable = ['is_active']

@admin.register(ConversationMemory)
class ConversationMemoryAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'query_preview', 'ai_config', 'timestamp']
    list_filter = ['ai_config', 'timestamp']
    search_fields = ['session_id', 'query', 'response']
    readonly_fields = ['session_id', 'query', 'response', 'ai_config', 'relevant_docs_ids', 'timestamp']
    
    def query_preview(self, obj):
        return obj.query[:50] + "..." if len(obj.query) > 50 else obj.query
    query_preview.short_description = 'Query'