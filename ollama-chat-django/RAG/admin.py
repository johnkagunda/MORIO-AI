from django.contrib import admin
from .models import AIConfiguration, BusinessDocument, ConversationMemory


@admin.register(AIConfiguration)
class AIConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "ai_name", "company_name", "location",
        "is_active", "created_at"
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("ai_name", "company_name", "location")
    list_editable = ("is_active",)
    actions = ("activate", "deactivate")

    def activate(self, request, queryset):
        queryset.update(is_active=True)

    def deactivate(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(BusinessDocument)
class BusinessDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title", "document_type",
        "ai_config", "is_active", "created_at"
    )
    list_filter = ("document_type", "is_active")
    search_fields = ("title", "content", "keywords")
    list_editable = ("is_active",)


@admin.register(ConversationMemory)
class ConversationMemoryAdmin(admin.ModelAdmin):
    list_display = ("session_id", "query_preview", "ai_config", "timestamp")
    list_filter = ("ai_config", "timestamp")
    search_fields = ("session_id", "query", "response")
    readonly_fields = (
        "session_id", "query", "response",
        "ai_config", "relevant_docs_ids", "timestamp"
    )

    def query_preview(self, obj):
        return f"{obj.query[:50]}..." if len(obj.query) > 50 else obj.query
