from django.core.management.base import BaseCommand
from RAG.models import BusinessDocument


class Command(BaseCommand):
    help = "Generate embeddings for BusinessDocuments"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **options):
        docs = (
            BusinessDocument.objects.all()
            if options["all"]
            else BusinessDocument.objects.filter(embeddings_data__isnull=True)
            | BusinessDocument.objects.filter(embeddings_data="")
        )

        self.stdout.write(f"Processing {docs.count()} documents...")

        count = 0
        for doc in docs:
            try:
                doc.generate_embeddings()
                doc.save(update_fields=["embeddings_data"])
                count += 1
            except Exception as e:
                self.stderr.write(f"{doc.title}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Done! {count} embeddings generated."))
