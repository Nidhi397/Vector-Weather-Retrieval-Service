-- Setup script for weather_embeddings table
-- Run this manually in your Lakebase Postgres database
-- Embedding model: sentence-transformers/all-MiniLM-L6-v2
-- Dimension: 384

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;


-- Create the embeddings table
CREATE TABLE IF NOT EXISTS weather_embeddings (
    id TEXT PRIMARY KEY,

    -- Links this chunk back to the original weather document
    document_id TEXT NOT NULL,

    -- Identifies the location/type of weather information
    location TEXT NOT NULL,

    source_type TEXT NOT NULL,

    -- Which chunk of the original document this is
    chunk_index INTEGER NOT NULL,

    -- Actual text that was embedded
    chunk_text TEXT NOT NULL,

    -- 384-dimensional embedding
    embedding VECTOR(384) NOT NULL,

    -- Keep track of which model generated the vector
    model_name TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Create HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_weather_embeddings_embedding
ON weather_embeddings
USING hnsw (embedding vector_cosine_ops);


-- Verify the table was created
SELECT
    table_name,
    column_name,
    data_type,
    udt_name
FROM information_schema.columns
WHERE table_name = 'weather_embeddings'
ORDER BY ordinal_position;
