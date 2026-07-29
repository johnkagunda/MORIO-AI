import logging
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AIConfiguration

logger = logging.getLogger(__name__)


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@receiver(post_save, sender=AIConfiguration)
def auto_generate_modelfile_on_save(sender, instance, **kwargs):
    """
    Automatically generate Ollama Modelfiles whenever an active
    AIConfiguration is created or updated.
    """
    if not instance.is_active:
        return

    try:
        output_dir = Path(
            getattr(
                settings,
                "OLLAMA_CONFIG_DIR",
                "documents/ollama_configs",
            )
        )

        safe_name = instance.ai_name.strip().lower().replace(" ", "_")
        content = instance.generate_ollama_modelfile()

        files = (
            output_dir / f"{safe_name}_{instance.id}.txt",
            output_dir / f"latest_{safe_name}.txt",
        )

        for file_path in files:
            _write_file(file_path, content)

        logger.info(
            "Successfully generated Modelfiles for '%s'.",
            instance.ai_name,
        )

    except Exception:
        logger.exception(
            "Failed to generate Modelfiles for '%s'.",
            instance.ai_name,
        )
