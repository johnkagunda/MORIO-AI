# chat/serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import (
    APILog, User, ChatSession, ChatMessage, UserPreference,
    ModelConfiguration, Notification, UserTokenUsage
)
from django.utils import timezone

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'avatar', 'bio',
                 'is_premium', 'tokens_used', 'token_limit',
                 'default_model', 'default_temperature', 'default_max_tokens',
                 'created_at', 'last_login')
        read_only_fields = ('id', 'tokens_used', 'created_at', 'last_login')

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    
    class Meta:
        model = User
        fields = ('email', 'password', 'confirm_password', 'first_name', 'last_name')
    
    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords don't match")
        return data
    
    def create(self, validated_data):
        validated_data.pop('confirm_password')
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    
    def validate(self, data):
        user = authenticate(email=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid credentials')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled')
        return user

class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ('id', 'role', 'content', 'model_used', 'temperature', 
                 'tokens_used', 'processing_time', 'prompt_tokens',
                 'completion_tokens', 'error', 'error_message', 'created_at')
        read_only_fields = ('id', 'created_at')

class ChatSessionSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    user = UserSerializer(read_only=True)
    message_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = ('id', 'title', 'user', 'model_used', 'temperature', 'max_tokens',
                 'total_messages', 'total_tokens', 'messages', 'message_count',
                 'created_at', 'updated_at', 'last_active')
        read_only_fields = ('id', 'user', 'total_messages', 'total_tokens',
                           'created_at', 'updated_at', 'last_active')
    
    def get_message_count(self, obj):
        return obj.messages.count()

class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'updated_at')

class ModelConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelConfiguration
        fields = '__all__'

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at')

class TokenUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserTokenUsage
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')

class APILogSerializer(serializers.ModelSerializer):
    class Meta:
        model = APILog
        fields = '__all__'
        read_only_fields = ('id', 'created_at')