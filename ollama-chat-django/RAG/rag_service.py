# RAG/rag_service.py
import re
import json

class RAGService:
    def __init__(self):
        # Try to load embedding model
        self.model = None
        self.np = None
        self.has_embeddings = False
        
        try:
            # Import inside try block
            from sentence_transformers import SentenceTransformer
            import numpy as np
            
            self.np = np
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            self.embedding_size = 384
            self.has_embeddings = True
            print("✅ RAG Service: Embedding model loaded")
            
        except ImportError as e:
            print(f"⚠️ RAG Service: Import error - {e}")
            print("   Make sure packages are installed: pip install numpy sentence-transformers")
        except Exception as e:
            print(f"⚠️ RAG Service: Error loading model: {e}")
    
    def search_documents(self, query, top_k=10):
        """Search documents using embeddings or keywords - IMPROVED"""
        from .models import BusinessDocument
        
        # Get ALL active documents first
        all_docs = BusinessDocument.objects.filter(is_active=True)
        
        if not all_docs.exists():
            print("⚠️ No documents in database")
            return []
        
        # Clean query
        query = query.strip().lower()
        if not query:
            return list(all_docs.order_by('-created_at')[:top_k])
        
        # First: Try embeddings search if available
        results = []
        if self.has_embeddings and self.model:
            results = self._search_with_embeddings(query, all_docs, top_k)
            if results:
                print(f"✅ Found {len(results)} documents using embeddings")
                # Also add some keyword results for broader coverage
                keyword_results = self._search_with_keywords(query, all_docs, top_k // 2)
                for doc in keyword_results:
                    if doc not in results:
                        results.append(doc)
                return results
        
        # Second: Try keyword search (fallback or primary)
        results = self._search_with_keywords(query, all_docs, top_k)
        
        # Third: If few results, try broader search
        if len(results) < 3:
            # Extract individual words and search for each
            words = self._extract_keywords(query)
            for word in words:
                if len(word) > 3:  # Only meaningful words
                    word_results = self._search_with_keywords(word, all_docs, 2)
                    for doc in word_results:
                        if doc not in results:
                            results.append(doc)
                            if len(results) >= top_k:
                                break
                if len(results) >= top_k:
                    break
        
        print(f"📄 Found {len(results)} documents total")
        return results[:top_k]  # Ensure we don't exceed top_k
    
    def _search_with_embeddings(self, query, documents, top_k):
        """Search using embeddings similarity"""
        try:
            # Create query embedding
            query_embedding = self.model.encode(query).tolist()
            
            # Calculate similarities for documents with embeddings
            scored_docs = []
            for doc in documents:
                if doc.embeddings_data and doc.embeddings_data.strip():
                    try:
                        # Parse embeddings from JSON string
                        doc_embedding = json.loads(doc.embeddings_data)
                        if doc_embedding and isinstance(doc_embedding, list) and len(doc_embedding) > 0:
                            similarity = self._cosine_similarity(query_embedding, doc_embedding)
                            # Lower threshold to catch more documents
                            if similarity > 0.15:  # Reduced from 0.2
                                scored_docs.append((similarity, doc))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            
            # Sort by similarity (highest first)
            scored_docs.sort(reverse=True, key=lambda x: x[0])
            
            # Return top k
            return [doc for score, doc in scored_docs[:top_k]]
            
        except Exception as e:
            print(f"⚠️ Embedding search error: {e}")
            return []
    
    def _search_with_keywords(self, query, documents, top_k):
        """Search using keywords - IMPROVED"""
        keywords = self._extract_keywords(query)
        
        if not keywords:
            # If no keywords, return recent documents
            return list(documents.order_by('-created_at')[:top_k])
        
        # Build search query
        from django.db.models import Q
        search_query = Q()
        
        # Search in multiple fields with different weights
        for keyword in keywords:
            # Title matches are most important
            search_query |= Q(title__icontains=keyword)
            # Content matches are important
            search_query |= Q(content__icontains=keyword)
            # Keyword field matches
            search_query |= Q(keywords__icontains=keyword)
            # Also search in document type
            search_query |= Q(document_type__icontains=keyword)
        
        # Execute search and order by relevance
        results = documents.filter(search_query).distinct().order_by('-created_at')[:top_k]
        return list(results)
    
    def _extract_keywords(self, text):
        """Extract keywords from query - IMPROVED"""
        # Common stop words to ignore
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
        
        # Filter and return meaningful keywords
        keywords = []
        for word in words:
            # Skip stop words and very short words
            if word not in stop_words and len(word) > 2:
                # Also check for numbers
                if word.isdigit() and len(word) <= 4:  # Include years, counts, etc.
                    keywords.append(word)
                elif not word.isdigit():  # Regular words
                    keywords.append(word)
        
        # Return unique keywords, limit to 15
        return list(set(keywords))[:15]
    
    def _cosine_similarity(self, vec1, vec2):
        """Calculate cosine similarity between two vectors"""
        if not vec1 or not vec2 or not self.np:
            return 0
        try:
            # Convert to numpy arrays if they aren't already
            if not isinstance(vec1, self.np.ndarray):
                vec1 = self.np.array(vec1)
            if not isinstance(vec2, self.np.ndarray):
                vec2 = self.np.array(vec2)
            
            # Calculate dot product
            dot_product = self.np.dot(vec1, vec2)
            
            # Calculate norms
            norm1 = self.np.linalg.norm(vec1)
            norm2 = self.np.linalg.norm(vec2)
            
            # Avoid division by zero
            if norm1 == 0 or norm2 == 0:
                return 0
            
            # Calculate cosine similarity
            similarity = dot_product / (norm1 * norm2)
            
            # Ensure result is within valid range
            return float(max(-1.0, min(1.0, similarity)))
            
        except Exception as e:
            print(f"⚠️ Cosine similarity calculation error: {e}")
            return 0
    
    def generate_rag_prompt(self, query, documents=None):
        """Generate a prompt with RAG context - for direct use if needed"""
        if documents is None:
            documents = self.search_documents(query, top_k=8)
        
        if not documents:
            return "No relevant information found in the database.\n\n", []
        
        # Build comprehensive context
        context = "=== RELEVANT INFORMATION FROM COMPANY DATABASE ===\n\n"
        
        for i, doc in enumerate(documents, 1):
            context += f"[DOCUMENT {i}]: {doc.title}\n"
            context += f"TYPE: {doc.get_document_type_display()}\n"
            context += f"CONTENT: {doc.content}\n"
            if doc.keywords:
                context += f"KEYWORDS: {doc.keywords}\n"
            context += "-" * 60 + "\n\n"
        
        context += f"=== USER QUESTION ===\n{query}\n\n"
        
        prompt = f"""{context}
INSTRUCTIONS:
1. Answer the question using ONLY the information from the database above.
2. If the answer is in the database, provide specific details.
3. If the information isn't in the database, say: "The database doesn't have that specific information."
4. Do not make assumptions or use external knowledge.
5. Reference document numbers when possible.

ANSWER:"""
        
        return prompt, documents

# Create global instance
rag_service = RAGService()