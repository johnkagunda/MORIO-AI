# RAG/management/commands/generate_embeddings.py
from django.core.management.base import BaseCommand
from RAG.models import BusinessDocument
import json

class Command(BaseCommand):
    help = 'Generate embeddings for all BusinessDocuments'
    
    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Regenerate all embeddings')
    
    def handle(self, *args, **options):
        self.stdout.write("🔧 Generating embeddings for Business Documents...")
        
        # Get documents
        if options['all']:
            documents = BusinessDocument.objects.all()
            self.stdout.write(f"Regenerating ALL embeddings for {documents.count()} documents")
        else:
            documents = BusinessDocument.objects.filter(embeddings_data__isnull=True) | \
                       BusinessDocument.objects.filter(embeddings_data__exact="")
            self.stdout.write(f"Generating embeddings for {documents.count()} documents without embeddings")
        
        # Process each document
        count = 0
        for doc in documents:
            try:
                # This will auto-generate embeddings
                doc.generate_embeddings()
                doc.save(update_fields=['embeddings_data'])
                
                count += 1
                if count % 10 == 0:
                    self.stdout.write(f"  Processed {count} documents...")
                    
            except Exception as e:
                self.stderr.write(f"❌ Error processing '{doc.title}': {e}")
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ COMPLETE: Generated embeddings for {count} documents"))
        self.stdout.write(f"   Total documents: {BusinessDocument.objects.count()}")
        self.stdout.write(f"   With embeddings: {BusinessDocument.objects.exclude(embeddings_data__isnull=True).exclude(embeddings_data__exact='').count()}")