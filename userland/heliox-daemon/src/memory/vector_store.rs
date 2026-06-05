use alloc::vec::Vec;
use alloc::string::String;
use libm::sqrtf;
use crate::{syscall4, SYS_READ_FILE, SYS_WRITE_FILE};
use crate::cognitive::json::{self, JsonValue};

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

    /// Returns the number of documents in the store.
    pub fn document_count(&self) -> usize {
        self.documents.len()
    }

    /// Saves the vector store to disk
    pub fn save(&self, path: &str) -> Result<(), String> {
        let mut json = String::from("[\n");
        for (i, doc) in self.documents.iter().enumerate() {
            json.push_str("  {\n");
            
            json.push_str(&alloc::format!("    \"id\": \"{}\",\n", doc.id.replace("\"", "\\\"")));
            
            let escaped_content = doc.content.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
            json.push_str(&alloc::format!("    \"content\": \"{}\",\n", escaped_content));
            
            json.push_str("    \"embedding\": [");
            for (j, val) in doc.embedding.iter().enumerate() {
                json.push_str(&alloc::format!("{}", val));
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
            Err(alloc::format!("Failed to write file, syscall returned {}", ret as i64))
        }
    }

    /// Loads the vector store from disk
    pub fn load(&mut self, path: &str) -> Result<(), String> {
        // Allocate a buffer for reading (1MB limit for now)
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
            return Err(alloc::format!("Failed to read file, syscall returned {}", bytes_read as i64));
        }

        let json_str = core::str::from_utf8(&buf[..bytes_read as usize])
            .map_err(|_| "Invalid UTF-8 in vector store file")?;

        let parsed = json::parse(json_str)
            .map_err(|e| alloc::format!("Failed to parse JSON: {}", e))?;

        if let Some(arr) = parsed.as_array() {
            self.documents.clear();
            for item in arr {
                if let Some(_obj) = item.as_object() {
                    let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").into();
                    let content = item.get("content").and_then(|v| v.as_str()).unwrap_or("").into();
                    
                    let mut embedding = Vec::new();
                    if let Some(emb_arr) = item.get("embedding").and_then(|v| v.as_array()) {
                        for num in emb_arr {
                            if let Some(f) = num.as_f64() {
                                embedding.push(f as f32);
                            }
                        }
                    }

                    self.documents.push(Document {
                        id,
                        content,
                        embedding,
                    });
                }
            }
        }

        Ok(())
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
