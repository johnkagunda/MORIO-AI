from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import AIConfiguration
import os

@receiver(post_save, sender=AIConfiguration)
def auto_generate_modelfile_on_save(sender, instance, created, **kwargs):
    """
    Automatically generate Ollama modelfile when AIConfiguration is saved
    Only for active configurations
    """
    if instance.is_active:
        output_dir = getattr(settings, 'OLLAMA_CONFIG_DIR', 'documents/ollama_configs')
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate main file
        filename = f"{instance.ai_name.lower().replace(' ', '_')}_{instance.id}.txt"
        filepath = os.path.join(output_dir, filename)
        
        try:
            content = instance.generate_ollama_modelfile()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Generate latest version
            latest_file = os.path.join(output_dir, f"latest_{instance.ai_name.lower().replace(' ', '_')}.txt")
            with open(latest_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
        except Exception as e:
            print(f"Warning: Failed to auto-generate modelfile for {instance.ai_name}: {e}")