from django.core.management.base import BaseCommand
from django.conf import settings
import os
import sys

# Try to import the model
try:
    from RAG.models import AIConfiguration
    HAS_MODEL = True
except ImportError:
    HAS_MODEL = False

class Command(BaseCommand):
    help = 'Generate Ollama Modelfile from database configuration'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help='Specific AIConfiguration ID to export'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default='documents/ollama_configs',
            help='Output directory for modelfiles'
        )
        parser.add_argument(
            '--create-default',
            action='store_true',
            help='Create a default configuration if none exists'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all configurations without generating files'
        )
    
    def handle(self, *args, **options):
        if not HAS_MODEL:
            self.stdout.write(self.style.ERROR('AIConfiguration model not found. Make sure migrations are run.'))
            sys.exit(1)
        
        config_id = options['config_id']
        output_dir = options['output_dir']
        create_default = options['create_default']
        list_only = options['list']
        
        # List configurations if requested
        if list_only:
            self.list_configurations()
            return
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Get configurations
        if config_id:
            configs = AIConfiguration.objects.filter(id=config_id)
        else:
            configs = AIConfiguration.objects.filter(is_active=True)
        
        if not configs.exists():
            if create_default:
                self.stdout.write(self.style.WARNING('No configurations found. Creating default configuration...'))
                self.create_default_configuration()
                configs = AIConfiguration.objects.filter(is_active=True)
            else:
                self.stdout.write(self.style.WARNING('No AI configurations found in database!'))
                self.stdout.write('\nOptions:')
                self.stdout.write('1. Use Django admin: /admin/RAG/aiconfiguration/')
                self.stdout.write('2. Run with --create-default flag')
                self.stdout.write('3. Run with --list to see existing configs')
                self.stdout.write('\nExample: python manage.py generate_ollama_config --create-default')
                return
        
        generated_count = 0
        for config in configs:
            try:
                # Generate filename
                filename = f"{config.ai_name.lower().replace(' ', '_')}_{config.id}.txt"
                filepath = os.path.join(output_dir, filename)
                
                # Generate and save modelfile
                content = config.generate_ollama_modelfile()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # Also create a "latest" version
                latest_filename = f"latest_{config.ai_name.lower().replace(' ', '_')}.txt"
                latest_filepath = os.path.join(output_dir, latest_filename)
                with open(latest_filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Generated: {filepath}')
                )
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Latest copy: {latest_filepath}')
                )
                generated_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Failed to generate for {config.ai_name} (ID: {config.id}): {str(e)}')
                )
        
        if generated_count > 0:
            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(f'✅ Successfully generated {generated_count} modelfile(s)')
            )
            self.stdout.write(f'📁 Location: {os.path.abspath(output_dir)}')
            
            # Show usage instructions
            self.stdout.write('\n📋 Usage instructions:')
            self.stdout.write(f'1. Check file: type "{os.path.abspath(os.path.join(output_dir, "latest_*.txt"))}"')
            self.stdout.write('2. Create Ollama model: ollama create your-model -f path/to/file.txt')
            self.stdout.write('3. Run model: ollama run your-model')
    
    def list_configurations(self):
        """List all AI configurations"""
        configs = AIConfiguration.objects.all().order_by('id')
        
        if not configs.exists():
            self.stdout.write(self.style.WARNING('No configurations found in database'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {configs.count()} configuration(s):'))
        self.stdout.write('─' * 60)
        
        for config in configs:
            status = "🟢 ACTIVE" if config.is_active else "🔴 INACTIVE"
            self.stdout.write(f"ID: {config.id} {status}")
            self.stdout.write(f"  AI Name: {config.ai_name}")
            self.stdout.write(f"  Company: {config.company_name}")
            self.stdout.write(f"  Location: {config.location}")
            self.stdout.write(f"  Base Model: {config.base_model}")
            self.stdout.write(f"  Documents: {config.documents.count()}")
            self.stdout.write(f"  Created: {config.created_at.strftime('%Y-%m-%d %H:%M')}")
            self.stdout.write('─' * 60)
    
    def create_default_configuration(self):
        """Create a default configuration with placeholder values"""
        config = AIConfiguration.objects.create(
            ai_name="MORIO AI",
            company_name="Your Company Name",
            location="Your Location",
            role_description="customer assistant",
            greeting_message="Hello! I'm {ai_name} from {company_name}. How can I assist you today?"
        )
        self.stdout.write(self.style.SUCCESS(f'Created configuration ID: {config.id}'))
        self.stdout.write(self.style.WARNING('⚠️ Please update the configuration in Django admin with your actual company details!'))
        return config