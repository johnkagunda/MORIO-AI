# RAG/rag_service.py - Optimized with caching and batch processing
import re
import json
from functools import lru_cache
from typing import List, Optional, Tuple, Set
from django.core.cache import cache

class RAGService:
    def __init__(self):
        # Try to load embedding model
        self.model = None
        self.np = None
        self.has_embeddings = False
        self.embedding_size = 384
        
        # Cache for search results
        self.search_cache = {}
        self.cache_timeout = 300  # 5 minutes
        
        try:
            # Import inside try block for better error handling
            from sentence_transformers import SentenceTransformer
            import numpy as np
            
            self.np = np
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.has_embeddings = True
            print("✅ RAG Service: Embedding model loaded")
            
        except ImportError as e:
            print(f"⚠️ RAG Service: Import error - {e}")
            print("   Make sure packages are installed: pip install numpy sentence-transformers")
        except Exception as e:
            print(f"⚠️ RAG Service: Error loading model: {e}")
    
    def search_documents(self, query: str, top_k: int = 10) -> List:
        """Search documents using embeddings or keywords with caching"""
        from .models import BusinessDocument
        
        # Check cache first
        cache_key = f'rag_search_{query}_{top_k}'
        cached_results = cache.get(cache_key)
        if cached_results is not None:
            print(f"📄 Returning {len(cached_results)} cached results")
            return cached_results
        
        # Clean query once
        query = query.strip().lower()
        if not query:
            results = list(BusinessDocument.objects.filter(is_active=True).order_by('-created_at')[:top_k])
            cache.set(cache_key, results, self.cache_timeout)
            return results
        
        # Get active documents efficiently with select_related
        all_docs = BusinessDocument.objects.filter(is_active=True).select_related('ai_config')
        
        if not all_docs.exists():
            print("⚠️ No documents in database")
            return []
        
        # Use a set for O(1) lookups and avoid duplicates
        results_set = set()
        results = []
        
        # First: Try embeddings search if available (most accurate)
        if self.has_embeddings and self.model:
            embedding_results = self._search_with_embeddings(query, all_docs, top_k)
            for doc in embedding_results:
                if doc.id not in results_set:
                    results_set.add(doc.id)
                    results.append(doc)
            
            if results:
                print(f"✅ Found {len(results)} documents using embeddings")
        
        # Second: Add keyword results for broader coverage
        keyword_results = self._search_with_keywords(query, all_docs, top_k * 2)
        for doc in keyword_results:
            if doc.id not in results_set:
                results_set.add(doc.id)
                results.append(doc)
                if len(results) >= top_k:
                    break
        
        # Third: If no results, try broader search with individual words
        if len(results) < 3:
            words = self._extract_keywords(query)
            for word in words:
                if len(word) > 3:  # Only meaningful words
                    word_results = self._search_with_keywords(word, all_docs, 2)
                    for doc in word_results:
                        if doc.id not in results_set:
                            results_set.add(doc.id)
                            results.append(doc)
                            if len(results) >= top_k:
                                break
                if len(results) >= top_k:
                    break
        
        # Cache results
        cache.set(cache_key, results[:top_k], self.cache_timeout)
        print(f"📄 Found {len(results)} documents total")
        return results[:top_k]
    
    def _search_with_embeddings(self, query: str, documents, top_k: int) -> List:
        """Search using embeddings similarity with optimized processing"""
        try:
            # Create query embedding once
            query_embedding = self.model.encode(query).tolist()
            
            # Batch process documents with embeddings
            scored_docs = []
            docs_with_embeddings = []
            
            for doc in documents:
                if doc.embeddings_data and doc.embeddings_data.strip():
                    docs_with_embeddings.append(doc)
            
            if not docs_with_embeddings:
                return []
            
            # Process in chunks for memory efficiency
            chunk_size = 50
            for i in range(0, len(docs_with_embeddings), chunk_size):
                chunk = docs_with_embeddings[i:i + chunk_size]
                for doc in chunk:
                    try:
                        doc_embedding = json.loads(doc.embeddings_data)
                        if doc_embedding and isinstance(doc_embedding, list) and len(doc_embedding) > 0:
                            similarity = self._cosine_similarity(query_embedding, doc_embedding)
                            if similarity > 0.2:  # Slightly increased threshold for quality
                                scored_docs.append((similarity, doc))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            
            # Sort once and return top k
            scored_docs.sort(key=lambda x: x[0], reverse=True)
            return [doc for score, doc in scored_docs[:top_k]]
            
        except Exception as e:
            print(f"⚠️ Embedding search error: {e}")
            return []
    
    def _search_with_keywords(self, query: str, documents, top_k: int) -> List:
        """Search using keywords - optimized with Q objects"""
        keywords = self._extract_keywords(query)
        
        if not keywords:
            return list(documents.order_by('-created_at')[:top_k])
        
        from django.db.models import Q
        
        # Build optimized search query
        search_query = Q()
        
        # Priority order for field matching
        field_weights = [
            ('title__icontains', 3),      # Highest priority
            ('keywords__icontains', 2),   # Medium priority
            ('content__icontains', 1),    # Standard priority
            ('document_type__icontains', 1)
        ]
        
        # Create weighted search
        for keyword in keywords:
            for field, weight in field_weights:
                search_query |= Q(**{field: keyword})
        
        # Execute search with distinct
        results = documents.filter(search_query).distinct().order_by('-created_at')[:top_k]
        return list(results)
    
    @lru_cache(maxsize=128)
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from query with caching"""
        # Common stop words as a set for O(1) lookup
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 
            'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been',
            'what', 'how', 'when', 'where', 'why', 'who', 'which', 'that', 'this',
            'have', 'has', 'had', 'do', 'does', 'did', 'can', 'could', 'will', 'would',
            'should', 'may', 'might', 'must', 'about', 'with', 'from', 'into', 'over',
            'under', 'above', 'below', 'between', 'through', 'during', 'before', 'after',
            'since', 'until', 'while', 'because', 'if', 'then', 'else', 'also', 'too',
            'very', 'just', 'only', 'not', 'no', 'yes', 'maybe', 'perhaps', 'please',
            'thank', 'thanks', 'hello', 'hi', 'hey', 'okay', 'ok', 'well', 'so', 'now'
        }
        
        # Clean and tokenize
        text = re.sub(r'[^\w\s]', '', text.lower())
        words = text.split()
        
        # Filter efficiently using set operations
        meaningful_words = []
        for word in words:
            if word not in stop_words and len(word) > 2:
                # Include years, counts, etc.
                if word.isdigit() and len(word) <= 4:
                    meaningful_words.append(word)
                elif not word.isdigit():
                    meaningful_words.append(word)
        
        # Return unique keywords, limit to 15
        return list(set(meaningful_words))[:15]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors - optimized"""
        if not vec1 or not vec2 or not self.np:
            return 0
        try:
            # Convert to numpy arrays once
            arr1 = self.np.array(vec1)
            arr2 = self.np.array(vec2)
            
            # Calculate using numpy's optimized operations
            dot_product = self.np.dot(arr1, arr2)
            
            # Calculate norms using numpy's optimized functions
            norm1 = self.np.linalg.norm(arr1)
            norm2 = self.np.linalg.norm(arr2)
            
            if norm1 == 0 or norm2 == 0:
                return 0
            
            similarity = dot_product / (norm1 * norm2)
            
            # Fast clamp
            if similarity > 1.0:
                return 1.0
            if similarity < -1.0:
                return -1.0
            return float(similarity)
            
        except Exception as e:
            print(f"⚠️ Cosine similarity calculation error: {e}")
            return 0
    
    def generate_rag_prompt(self, query: str, documents=None):
        """Generate a prompt with RAG context - optimized"""
        if documents is None:
            documents = self.search_documents(query, top_k=5)  # Reduced from 8 for efficiency
        
        if not documents:
            return "No relevant information found in the database.\n\n", []
        
        # Use list comprehension for faster string building
        context_parts = ["=== RELEVANT INFORMATION FROM COMPANY DATABASE ===\n"]
        
        for i, doc in enumerate(documents, 1):
            context_parts.extend([
                f"[DOCUMENT {i}]: {doc.title}\n",
                f"TYPE: {doc.get_document_type_display()}\n",
                f"CONTENT: {doc.content}\n"
            ])
            if doc.keywords:
                context_parts.append(f"KEYWORDS: {doc.keywords}\n")
            context_parts.append("-" * 60 + "\n")
        
        context_parts.extend([
            f"\n=== USER QUESTION ===\n{query}\n\n",
            "INSTRUCTIONS:\n",
            "1. Answer the question using ONLY the information from the database above.\n",
            "2. If the answer is in the database, provide specific details.\n",
            "3. If the information isn't in the database, say: 'The database doesn't have that specific information.'\n",
            "4. Do not make assumptions or use external knowledge.\n",
            "5. Reference document numbers when possible.\n\n",
            "ANSWER:"
        ])
        
        return "".join(context_parts), documents
    
    def clear_cache(self):
        """Clear the search cache"""
        cache.clear()
        self._extract_keywords.cache_clear()
        print("✅ RAG Service cache cleared")

# Create global instance
rag_service = RAGService()
