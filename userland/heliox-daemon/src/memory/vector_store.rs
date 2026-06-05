// ============================================================================
// Heliox-Daemon - Vector Store with TF-IDF Embeddings
// ============================================================================
// Replaces the placeholder [0.0; 8] embeddings with real bag-of-words
// TF-IDF vectors. Each document is embedded into a 64-dimensional space
// based on a fixed vocabulary of common English + OS-specific terms.
//
// Also adds MemoryCategory for filtered RAG search.
// ============================================================================

use alloc::vec::Vec;
use alloc::string::String;
use alloc::format;
use libm::sqrtf;
use crate::{syscall4, SYS_READ_FILE, SYS_WRITE_FILE};
use crate::cognitive::json::{self, JsonValue};

/// Memory categories for filtered RAG retrieval.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MemoryCategory {
    /// LLM response text, conversation context
    Interaction,
    /// Output from a tool execution (success or failure)
    ToolResult,
    /// Consolidated insight from the reflector
    Lesson,
    /// User preference or configuration learned from usage
    Preference,
    /// Snapshot of system info (uptime, process list, etc.)
    SystemState,
}

impl MemoryCategory {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Interaction => "interaction",
            Self::ToolResult => "tool_result",
            Self::Lesson => "lesson",
            Self::Preference => "preference",
            Self::SystemState => "system_state",
        }
    }

    pub fn from_str(s: &str) -> Self {
        match s {
            "interaction" => Self::Interaction,
            "tool_result" => Self::ToolResult,
            "lesson" => Self::Lesson,
            "preference" => Self::Preference,
            "system_state" => Self::SystemState,
            _ => Self::Interaction,
        }
    }
}

// ============================================================================
// TF-IDF Vocabulary
// ============================================================================

/// Fixed vocabulary of 64 terms for bag-of-words TF-IDF embeddings.
/// Combines common English words with OS/agent-specific terminology.
const VOCAB_SIZE: usize = 64;

const VOCABULARY: [&str; VOCAB_SIZE] = [
    // Common English (0-15)
    "the", "is", "a", "to", "and", "of", "in", "that", "it", "for",
    "was", "on", "are", "with", "this", "not",
    // Action words (16-27)
    "read", "write", "create", "delete", "send", "receive", "connect",
    "start", "stop", "check", "search", "execute",
    // OS concepts (28-43)
    "file", "process", "memory", "disk", "network", "socket", "syscall",
    "tool", "error", "fail", "success", "result", "output", "input",
    "kernel", "system",
    // Agent concepts (44-55)
    "goal", "plan", "task", "action", "observe", "think", "verify",
    "lesson", "retry", "confirm", "approve", "deny",
    // Data types (56-63)
    "path", "name", "status", "config", "port", "host", "data", "log",
];

/// A simple document entry in the vector store
pub struct Document {
    pub id: String,
    pub content: String,
    pub category: MemoryCategory,
    pub embedding: Vec<f32>,
}

/// A bare-metal in-memory vector store with TF-IDF embeddings
pub struct VectorStore {
    documents: Vec<Document>,
    /// Cached IDF values (recomputed when doc count changes significantly)
    idf_cache: Vec<f32>,
    /// Doc count at which IDF was last computed
    idf_doc_count: usize,
}

impl VectorStore {
    pub fn new() -> Self {
        Self {
            documents: Vec::new(),
            idf_cache: alloc::vec![1.0f32; VOCAB_SIZE],
            idf_doc_count: 0,
        }
    }

    /// Adds a document with auto-computed TF-IDF embedding.
    pub fn add(&mut self, id: String, content: String, category: MemoryCategory) {
        let embedding = self.embed(&content);
        self.documents.push(Document {
            id,
            content,
            category,
            embedding,
        });
    }

    /// Adds a document with a pre-computed embedding (for backward compat).
    pub fn add_with_embedding(&mut self, id: String, content: String, category: MemoryCategory, embedding: Vec<f32>) {
        self.documents.push(Document {
            id,
            content,
            category,
            embedding,
        });
    }

    /// Returns the number of documents in the store.
    pub fn document_count(&self) -> usize {
        self.documents.len()
    }

    /// Compute TF-IDF embedding for a text string.
    pub fn embed(&self, text: &str) -> Vec<f32> {
        let tf = Self::compute_tf(text);

        let mut embedding = alloc::vec![0.0f32; VOCAB_SIZE];
        for i in 0..VOCAB_SIZE {
            embedding[i] = tf[i] * self.idf_cache[i];
        }

        // L2 normalize
        Self::l2_normalize(&mut embedding);
        embedding
    }

    /// Compute term frequency for each vocab word in the text.
    fn compute_tf(text: &str) -> Vec<f32> {
        let mut counts = alloc::vec![0u32; VOCAB_SIZE];
        let lower = Self::to_lowercase(text);
        let words = Self::split_words(&lower);
        let total_words = words.len() as f32;

        if total_words == 0.0 {
            return alloc::vec![0.0f32; VOCAB_SIZE];
        }

        for word in &words {
            for (i, vocab_word) in VOCABULARY.iter().enumerate() {
                if word == vocab_word {
                    counts[i] += 1;
                    break;
                }
            }
        }

        counts.iter().map(|c| *c as f32 / total_words).collect()
    }

    /// Recompute IDF values based on current document collection.
    fn recompute_idf(&mut self) {
        let n = self.documents.len();
        if n == 0 {
            self.idf_cache = alloc::vec![1.0f32; VOCAB_SIZE];
            self.idf_doc_count = 0;
            return;
        }

        let mut doc_freq = alloc::vec![0u32; VOCAB_SIZE];

        for doc in &self.documents {
            let lower = Self::to_lowercase(&doc.content);
            let words = Self::split_words(&lower);
            // Track which vocab words appear in this document (set semantics)
            let mut seen = [false; VOCAB_SIZE];
            for word in &words {
                for (i, vocab_word) in VOCABULARY.iter().enumerate() {
                    if word == vocab_word && !seen[i] {
                        doc_freq[i] += 1;
                        seen[i] = true;
                        break;
                    }
                }
            }
        }

        self.idf_cache = doc_freq.iter().map(|df| {
            if *df == 0 {
                0.0
            } else {
                libm::logf(n as f32 / *df as f32) + 1.0
            }
        }).collect();

        self.idf_doc_count = n;
    }

    /// Searches for the top_k most similar documents using cosine similarity.
    /// Optionally filters by category.
    pub fn search(&mut self, query: &str, top_k: usize, category: Option<MemoryCategory>) -> Vec<&Document> {
        // Lazily recompute IDF if doc count changed significantly
        let current_count = self.documents.len();
        if current_count > 0 && (self.idf_doc_count == 0 || current_count > self.idf_doc_count * 2) {
            self.recompute_idf();
        }

        let query_embedding = self.embed(query);

        let mut scored_docs: Vec<(f32, usize)> = self.documents
            .iter()
            .enumerate()
            .filter(|(_, doc)| {
                match category {
                    Some(cat) => doc.category == cat,
                    None => true,
                }
            })
            .map(|(idx, doc)| {
                let score = Self::cosine_similarity(&query_embedding, &doc.embedding);
                (score, idx)
            })
            .collect();

        // Sort descending by score
        scored_docs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(core::cmp::Ordering::Equal));

        scored_docs.into_iter()
            .take(top_k)
            .map(|(_, idx)| &self.documents[idx])
            .collect()
    }

    /// Search with a pre-computed embedding vector (backward compat).
    pub fn search_by_embedding(&self, query_embedding: &[f32], top_k: usize) -> Vec<&Document> {
        let mut scored_docs: Vec<(f32, &Document)> = self.documents
            .iter()
            .map(|doc| {
                let score = Self::cosine_similarity(query_embedding, &doc.embedding);
                (score, doc)
            })
            .collect();

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

    fn l2_normalize(v: &mut Vec<f32>) {
        let magnitude: f32 = v.iter().map(|x| x * x).sum();
        if magnitude > 0.0 {
            let mag = sqrtf(magnitude);
            for x in v.iter_mut() {
                *x /= mag;
            }
        }
    }

    /// Simple lowercase conversion (ASCII only, no_std).
    fn to_lowercase(s: &str) -> String {
        let mut result = String::with_capacity(s.len());
        for c in s.chars() {
            if c >= 'A' && c <= 'Z' {
                result.push((c as u8 + 32) as char);
            } else {
                result.push(c);
            }
        }
        result
    }

    /// Split text into words on whitespace and punctuation.
    fn split_words(s: &str) -> Vec<&str> {
        s.split(|c: char| !c.is_alphanumeric() && c != '_')
            .filter(|w| !w.is_empty())
            .collect()
    }

    // ========================================================================
    // Persistence (save/load to Ext2 via syscalls)
    // ========================================================================

    /// Saves the vector store to disk.
    pub fn save(&self, path: &str) -> Result<(), String> {
        let mut json = String::from("[\n");
        for (i, doc) in self.documents.iter().enumerate() {
            json.push_str("  {\n");

            json.push_str(&format!("    \"id\": \"{}\",\n", doc.id.replace("\"", "\\\"")));

            let escaped_content = doc.content.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
            json.push_str(&format!("    \"content\": \"{}\",\n", escaped_content));

            json.push_str(&format!("    \"category\": \"{}\",\n", doc.category.as_str()));

            json.push_str("    \"embedding\": [");
            for (j, val) in doc.embedding.iter().enumerate() {
                json.push_str(&format!("{}", val));
                if j < doc.embedding.len() - 1 {
                    json.push_str(", ");
                }
            }
            json.push_str("]\n");

            json.push_str("  }");
            if i < self.documents.len() - 1 {
                json.push_str(",");
            }
            json.push_str("\n");
        }
        json.push_str("]\n");

        let ret = unsafe {
            syscall4(
                SYS_WRITE_FILE,
                path.as_ptr() as u64,
                path.len() as u64,
                json.as_ptr() as u64,
                json.len() as u64,
            )
        };

        if ret == 0 {
            Ok(())
        } else {
            Err(format!("Failed to write file, syscall returned {}", ret as i64))
        }
    }

    /// Loads the vector store from disk.
    pub fn load(&mut self, path: &str) -> Result<(), String> {
        let mut buf = alloc::vec![0u8; 1024 * 1024];

        let bytes_read = unsafe {
            syscall4(
                SYS_READ_FILE,
                path.as_ptr() as u64,
                path.len() as u64,
                buf.as_mut_ptr() as u64,
                buf.len() as u64,
            )
        };

        if (bytes_read as i64) < 0 {
            return Err(format!("Failed to read file, syscall returned {}", bytes_read as i64));
        }

        let json_str = core::str::from_utf8(&buf[..bytes_read as usize])
            .map_err(|_| "Invalid UTF-8 in vector store file")?;

        let parsed = json::parse(json_str)
            .map_err(|e| format!("Failed to parse JSON: {}", e))?;

        if let Some(arr) = parsed.as_array() {
            self.documents.clear();
            for item in arr {
                if let Some(_obj) = item.as_object() {
                    let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").into();
                    let content: String = item.get("content").and_then(|v| v.as_str()).unwrap_or("").into();
                    let category = item.get("category")
                        .and_then(|v| v.as_str())
                        .map(MemoryCategory::from_str)
                        .unwrap_or(MemoryCategory::Interaction);

                    let mut embedding = Vec::new();
                    if let Some(emb_arr) = item.get("embedding").and_then(|v| v.as_array()) {
                        for num in emb_arr {
                            if let Some(f) = num.as_f64() {
                                embedding.push(f as f32);
                            }
                        }
                    }

                    // If embedding is missing or wrong size, recompute
                    if embedding.len() != VOCAB_SIZE {
                        embedding = self.embed(&content);
                    }

                    self.documents.push(Document {
                        id,
                        content,
                        category,
                        embedding,
                    });
                }
            }
        }

        // Recompute IDF after loading
        self.recompute_idf();

        Ok(())
    }
}
