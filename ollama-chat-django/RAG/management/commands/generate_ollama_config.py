from django.core.management.base import BaseCommand
from RAG.models import AIConfiguration
import os


class Command(BaseCommand):
    help = "Generate Ollama Modelfiles"

    def add_arguments(self, parser):
        parser.add_argument("--config-id", type=int)
        parser.add_argument("--output-dir", default="documents/ollama_configs")
        parser.add_argument("--create-default", action="store_true")
        parser.add_argument("--list", action="store_true")

    def handle(self, *args, **opts):
        if opts["list"]:
            return self.list_configs()

        os.makedirs(opts["output_dir"], exist_ok=True)

        configs = (
            AIConfiguration.objects.filter(id=opts["config_id"])
            if opts["config_id"]
            else AIConfiguration.objects.filter(is_active=True)
        )

        if not configs.exists():
            if not opts["create_default"]:
                return self.stdout.write("No configurations found.")
            self.create_default()
            configs = AIConfiguration.objects.filter(is_active=True)

        count = 0
        for config in configs:
            try:
                name = config.ai_name.lower().replace(" ", "_")
                content = config.generate_ollama_modelfile()

                for file in (
                    f"{name}_{config.id}.txt",
                    f"latest_{name}.txt",
                ):
                    with open(os.path.join(opts["output_dir"], file), "w", encoding="utf-8") as f:
                        f.write(content)

                count += 1
            except Exception as e:
                self.stderr.write(f"{config.ai_name}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Generated {count} Modelfile(s)."))

    def list_configs(self):
        for c in AIConfiguration.objects.all():
            self.stdout.write(
                f"{c.id}: {c.ai_name} ({'Active' if c.is_active else 'Inactive'})"
            )

    def create_default(self):
        AIConfiguration.objects.create(
            ai_name="MORIO AI",
            company_name="Your Company",
            location="Your Location",
            role_description="customer assistant",
            greeting_message="Hello! I'm {ai_name}. How can I help?",
        )
