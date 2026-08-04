# chat/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
import uuid
from django.utils import timezone


class CustomUserManager(BaseUserManager):
    """Custom user manager where email is the unique identifier"""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and save a User with the given email and password"""
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        
        # Ensure required fields are set
        extra_fields.setdefault('is_active', True)
        
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a SuperUser with the given email and password"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        
        return self.create_user(email, password, **extra_fields)
    
    def get_by_natural_key(self, email):
        """Allow authentication by email"""
        return self.get(email=email)


class User(AbstractUser):
    """Custom User model with UUID primary key and email authentication"""
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        db_index=True
    )
    email = models.EmailField(
        _('email address'), 
        unique=True,
        db_index=True,
        error_messages={
            'unique': _("A user with that email already exists."),
        }
    )
    
    # Remove username field
    username = None
    
    # Set email as the USERNAME_FIELD
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    # Use custom manager
    objects = CustomUserManager()
    
    class Meta:
        db_table = 'users'  # Custom table name for clarity
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['date_joined']),
        ]
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        """Return the full name or email if not set"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email
    
    def get_short_name(self):
        """Return first name or email if not set"""
        return self.first_name or self.email.split('@')[0]


class ChatSession(models.Model):
    """Chat conversation session with optimization for querying"""
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        db_index=True
    )
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='chat_sessions',
        db_index=True
    )
    title = models.CharField(
        max_length=200, 
        blank=True,
        default=''
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chat_sessions'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'updated_at']),
            models.Index(fields=['is_active', 'updated_at']),
        ]
    
    def __str__(self):
        return f"{self.title or 'Untitled'} - {self.user.email}"
    
    def update_timestamp(self):
        """Update the updated_at timestamp"""
        self.updated_at = timezone.now()
        self.save(update_fields=['updated_at'])
    
    @classmethod
    def get_active_sessions(cls, user):
        """Get all active sessions for a user"""
        return cls.objects.filter(user=user, is_active=True)


class ChatMessage(models.Model):
    """Individual chat message with optimized indexing"""
    
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System')
    ]
    
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        db_index=True
    )
    session = models.ForeignKey(
        ChatSession, 
        on_delete=models.CASCADE, 
        related_name='messages',
        db_index=True
    )
    role = models.CharField(
        max_length=10,  # Reduced from 20 to optimize storage
        choices=ROLE_CHOICES,
        db_index=True
    )
    content = models.TextField()
    token_count = models.PositiveIntegerField(null=True, blank=True, help_text="Number of tokens in the message")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['role', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
    
    def get_preview(self, length=50):
        """Get a preview of the message content"""
        return self.content[:length] + '...' if len(self.content) > length else self.content
    
    @classmethod
    def get_session_messages(cls, session_id, limit=None):
        """Get messages for a session with optional limit"""
        queryset = cls.objects.filter(session_id=session_id).select_related('session')
        if limit:
            queryset = queryset[:limit]
        return queryset
    
    @classmethod
    def create_message(cls, session, role, content, token_count=None):
        """Create a new message with validation"""
        if role not in dict(cls.ROLE_CHOICES):
            raise ValueError(f"Invalid role: {role}")
        return cls.objects.create(
            session=session,
            role=role,
            content=content,
            token_count=token_count
        )


# Optional: Add a model for tracking user activity
class UserActivity(models.Model):
    """Track user activity for analytics"""
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='activities',
        db_index=True
    )
    session = models.ForeignKey(
        ChatSession, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        related_name='activities'
    )
    activity_type = models.CharField(
        max_length=50,
        choices=[
            ('login', 'Login'),
            ('logout', 'Logout'),
            ('message_sent', 'Message Sent'),
            ('session_created', 'Session Created'),
            ('session_ended', 'Session Ended'),
        ],
        db_index=True
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'user_activities'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['activity_type', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.email} - {self.activity_type} at {self.created_at}"
