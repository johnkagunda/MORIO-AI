# Add this to rag_service.py - Error handling improvements
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# Setup logging
logger = logging.getLogger(__name__)

class RAGServiceError(Exception):
    """Custom exception for RAG service errors"""
    pass

class RAGService:
    # ... existing code ...
    
    def search_documents(self, query: str, top_k: int = 10) -> List:
        """Search documents with improved error handling"""
        try:
            return self._search_documents_impl(query, top_k)
        except Exception as e:
            logger.error(f"Error searching documents: {e}", exc_info=True)
            # Return empty list instead of failing
            return []
    
    def _search_documents_impl(self, query: str, top_k: int) -> List:
        """Internal implementation with error handling"""
        from .models import BusinessDocument
        
        try:
            # Check cache
            cache_key = f'rag_search_{query}_{top_k}'
            cached_results = cache.get(cache_key)
            if cached_results is not None:
                logger.debug(f"Returning {len(cached_results)} cached results for: {query[:50]}...")
                return cached_results
            
            # Validate inputs
            if not query or not isinstance(query, str):
                query = ""
            
            query = query.strip().lower()
            
            # Handle empty query
            if not query:
                results = list(BusinessDocument.objects.filter(is_active=True).order_by('-created_at')[:top_k])
                cache.set(cache_key, results, self.cache_timeout)
                return results
            
            # Get active documents
            all_docs = BusinessDocument.objects.filter(is_active=True).select_related('ai_config')
            
            if not all_docs.exists():
                logger.warning("No active documents found in database")
                return []
            
            # Start search with performance tracking
            start_time = datetime.now()
            results = self._perform_search(query, all_docs, top_k)
            elapsed = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"Search completed in {elapsed:.2f}s, found {len(results)} results")
            
            # Cache results
            cache.set(cache_key, results[:top_k], self.cache_timeout)
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Error in _search_documents_impl: {e}", exc_info=True)
            raise
    
    def _perform_search(self, query: str, all_docs, top_k: int) -> List:
        """Perform the actual search with fallback strategies"""
        results_set = set()
        results = []
        
        # Try embeddings first
        if self.has_embeddings and self.model:
            try:
                embedding_results = self._search_with_embeddings(query, all_docs, top_k)
                for doc in embedding_results:
                    if doc.id not in results_set:
                        results_set.add(doc.id)
                        results.append(doc)
                logger.debug(f"Embeddings found {len(results)} results")
            except Exception as e:
                logger.warning(f"Embedding search failed: {e}")
        
        # Add keyword results
        try:
            keyword_results = self._search_with_keywords(query, all_docs, top_k * 2)
            for doc in keyword_results:
                if doc.id not in results_set:
                    results_set.add(doc.id)
                    results.append(doc)
                    if len(results) >= top_k:
                        break
            logger.debug(f"Keyword search found {len(results)} total results")
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
        
        # Try broader search if needed
        if len(results) < 3:
            try:
                words = self._extract_keywords(query)
                for word in words:
                    if len(word) > 3:
                        word_results = self._search_with_keywords(word, all_docs, 2)
                        for doc in word_results:
                            if doc.id not in results_set:
                                results_set.add(doc.id)
                                results.append(doc)
                                if len(results) >= top_k:
                                    break
                    if len(results) >= top_k:
                        break
                logger.debug(f"Broader search found {len(results)} total results")
            except Exception as e:
                logger.warning(f"Broader search failed: {e}")
        
        return results
    
    def generate_rag_prompt(self, query: str, documents=None):
        """Generate prompt with validation"""
        try:
            if not query:
                raise ValueError("Query cannot be empty")
            
            if documents is None:
                documents = self.search_documents(query, top_k=5)
            
            if not documents:
                return "No relevant information found in the database.\n\n", []
            
            # Validate documents
            valid_docs = [doc for doc in documents if doc and hasattr(doc, 'content')]
            if not valid_docs:
                return "Invalid documents found.\n\n", []
            
            return self._build_prompt(query, valid_docs)
            
        except Exception as e:
            logger.error(f"Error generating RAG prompt: {e}", exc_info=True)
            return f"Error generating prompt: {str(e)}\n\n", []
    
    def _build_prompt(self, query: str, documents: List) -> Tuple[str, List]:
        """Build prompt string efficiently"""
        context_parts = [
            "=== RELEVANT INFORMATION FROM COMPANY DATABASE ===\n"
        ]
        
        for i, doc in enumerate(documents, 1):
            context_parts.extend([
                f"[DOCUMENT {i}]: {doc.title[:100]}\n",
                f"TYPE: {doc.get_document_type_display()}\n",
                f"CONTENT: {doc.content[:500]}\n"  # Truncate for performance
            ])
            if doc.keywords:
                context_parts.append(f"KEYWORDS: {doc.keywords}\n")
            context_parts.append("-" * 60 + "\n")
        
        context_parts.extend([
            f"\n=== USER QUESTION ===\n{query[:500]}\n\n",
            "INSTRUCTIONS:\n",
            "1. Answer using ONLY the information from the database above.\n",
            "2. If the answer is in the database, provide specific details.\n",
            "3. If not found, say: 'The database doesn't have that specific information.'\n",
            "4. Don't make assumptions or use external knowledge.\n",
            "5. Reference document numbers when possible.\n\n",
            "ANSWER:"
        ])
        
        return "".join(context_parts), documents

# Create global instance
rag_service = RAGService()
