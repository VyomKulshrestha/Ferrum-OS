use alloc::vec::Vec;
use alloc::string::String;
use libm::sqrtf;

/// A simple document entry in the vector store
pub struct Document {
    pub id: String,
    pub content: String,
    pub embedding: Vec<f32>,
}

/// A bare-metal in-memory vector store replacing ChromaDB
pub struct VectorStore {
    documents: Vec<Document>,
}

impl VectorStore {
    pub fn new() -> Self {
        Self {
            documents: Vec::new(),
        }
    }

    /// Adds a document with its pre-computed embedding
    pub fn add(&mut self, id: String, content: String, embedding: Vec<f32>) {
        self.documents.push(Document {
            id,
            content,
            embedding,
        });
    }

    /// Searches for the top_k most similar documents using cosine similarity
    pub fn search(&self, query_embedding: &[f32], top_k: usize) -> Vec<&Document> {
        let mut scored_docs: Vec<(f32, &Document)> = self.documents
            .iter()
            .map(|doc| {
                let score = Self::cosine_similarity(query_embedding, &doc.embedding);
                (score, doc)
            })
            .collect();

        // Sort descending by score
        // We use a simple bubble sort or selection sort since f32 doesn't implement Ord directly
        // and we might not have full sort_by without std, though alloc's slice::sort_by works if we wrap floats.
        scored_docs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(core::cmp::Ordering::Equal));

        scored_docs.into_iter()
            .take(top_k)
            .map(|(_, doc)| doc)
            .collect()
    }

    fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
        if a.len() != b.len() || a.is_empty() {
            return 0.0;
        }

        let mut dot_product = 0.0;
        let mut norm_a = 0.0;
        let mut norm_b = 0.0;

        for i in 0..a.len() {
            dot_product += a[i] * b[i];
            norm_a += a[i] * a[i];
            norm_b += b[i] * b[i];
        }

        if norm_a == 0.0 || norm_b == 0.0 {
            return 0.0;
        }

        dot_product / (sqrtf(norm_a) * sqrtf(norm_b))
    }
}
