#!/usr/bin/env python3
"""
Chunk and index builder for 学练机产品知识库
Reads pages JSON, creates chunks, builds BM25 index.
"""

import json
import re
import pickle
import os
import sys
from datetime import datetime

INPUT_FILE = "/tmp/kb_pages.json"
OUTPUT_DIR = os.path.expanduser("~/release-platform/kb")
CHUNKS_FILE = os.path.join(OUTPUT_DIR, "chunks.json")
INDEX_FILE = os.path.join(OUTPUT_DIR, "bm25_index.pkl")
META_FILE = os.path.join(OUTPUT_DIR, "meta.json")

MAX_CHUNK_SIZE = 1500
MIN_CONTENT_SIZE = 100


def split_by_headings(content, title_path, page_id, title, url, parent_title, last_modified):
    """Split content by H2/H3 headings"""
    # Pattern to find heading-like structures in plain text
    # Since we stripped HTML, we look for lines that look like section titles
    # We'll split on double newlines that precede short lines (potential headings)
    
    # Try to find section breaks - lines followed by substantial content
    chunks = []
    
    # Split on patterns that look like section headers
    # These are typically short lines (< 80 chars) followed by content
    parts = re.split(r'(?<=[.!?])\s{2,}|\n{2,}', content)
    parts = [p.strip() for p in parts if p.strip()]
    
    current_chunk = []
    current_size = 0
    chunk_idx = 0
    
    for part in parts:
        part_size = len(part)
        
        if current_size + part_size > MAX_CHUNK_SIZE and current_chunk:
            # Save current chunk
            chunk_content = ' '.join(current_chunk)
            if len(chunk_content) >= MIN_CONTENT_SIZE:
                chunks.append({
                    "id": f"{page_id}_chunk_{chunk_idx}",
                    "page_id": page_id,
                    "title": title,
                    "url": url,
                    "parent_title": parent_title,
                    "title_path": title_path,
                    "content": chunk_content,
                    "word_count": len(chunk_content),
                    "last_modified": last_modified,
                    "chunk_index": chunk_idx
                })
                chunk_idx += 1
            current_chunk = [part]
            current_size = part_size
        else:
            current_chunk.append(part)
            current_size += part_size
    
    # Don't forget last chunk
    if current_chunk:
        chunk_content = ' '.join(current_chunk)
        if len(chunk_content) >= MIN_CONTENT_SIZE:
            chunks.append({
                "id": f"{page_id}_chunk_{chunk_idx}",
                "page_id": page_id,
                "title": title,
                "url": url,
                "parent_title": parent_title,
                "title_path": title_path,
                "content": chunk_content,
                "word_count": len(chunk_content),
                "last_modified": last_modified,
                "chunk_index": chunk_idx
            })
    
    return chunks


def create_chunks(pages):
    """Create chunks from pages"""
    chunks = []
    
    for page in pages:
        content = page.get('content', '')
        word_count = page.get('word_count', 0)
        page_id = page['id']
        title = page['title']
        url = page['url']
        parent_title = page.get('parent_title', '')
        title_path = page.get('title_path', title)
        last_modified = page.get('last_modified', '')
        
        # Skip pages with too little content
        if word_count < MIN_CONTENT_SIZE:
            continue
        
        if word_count <= MAX_CHUNK_SIZE:
            # Use entire page as one chunk
            chunks.append({
                "id": f"{page_id}_chunk_0",
                "page_id": page_id,
                "title": title,
                "url": url,
                "parent_title": parent_title,
                "title_path": title_path,
                "content": content,
                "word_count": word_count,
                "last_modified": last_modified,
                "chunk_index": 0
            })
        else:
            # Split into smaller chunks
            sub_chunks = split_by_headings(
                content, title_path, page_id, title, url, parent_title, last_modified
            )
            if sub_chunks:
                chunks.extend(sub_chunks)
            else:
                # Fallback: just use first 1500 chars
                chunks.append({
                    "id": f"{page_id}_chunk_0",
                    "page_id": page_id,
                    "title": title,
                    "url": url,
                    "parent_title": parent_title,
                    "title_path": title_path,
                    "content": content[:MAX_CHUNK_SIZE],
                    "word_count": min(word_count, MAX_CHUNK_SIZE),
                    "last_modified": last_modified,
                    "chunk_index": 0
                })
    
    return chunks


def build_bm25_index(chunks):
    """Build BM25 index using jieba tokenization"""
    import jieba
    from rank_bm25 import BM25Okapi
    
    print("Tokenizing with jieba...")
    tokenized_corpus = []
    
    for i, chunk in enumerate(chunks):
        if i % 100 == 0:
            print(f"  Tokenizing chunk {i}/{len(chunks)}...")
        
        # Combine title_path and content for better retrieval
        text = f"{chunk['title_path']} {chunk['title']} {chunk['content']}"
        tokens = list(jieba.cut(text))
        # Filter out single chars and spaces
        tokens = [t for t in tokens if len(t.strip()) > 1]
        tokenized_corpus.append(tokens)
    
    print("Building BM25 index...")
    bm25 = BM25Okapi(tokenized_corpus)
    
    return bm25, tokenized_corpus


def main():
    print("=== Chunk & Index Builder ===")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load pages
    print(f"Loading pages from {INPUT_FILE}...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        pages = json.load(f)
    
    print(f"Loaded {len(pages)} pages")
    
    # Create chunks
    print("Creating chunks...")
    chunks = create_chunks(pages)
    print(f"Created {len(chunks)} chunks")
    
    # Save chunks
    print(f"Saving chunks to {CHUNKS_FILE}...")
    with open(CHUNKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    
    # Build BM25 index
    print("Building BM25 index...")
    bm25, tokenized_corpus = build_bm25_index(chunks)
    
    # Save index
    print(f"Saving BM25 index to {INDEX_FILE}...")
    with open(INDEX_FILE, 'wb') as f:
        pickle.dump({
            'bm25': bm25,
            'tokenized_corpus': tokenized_corpus,
            'chunk_ids': [c['id'] for c in chunks]
        }, f)
    
    # Save metadata
    meta = {
        "total_pages": len(pages),
        "total_chunks": len(chunks),
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    with open(META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Index Build Complete ===")
    print(f"Chunks: {len(chunks)}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Files: {os.listdir(OUTPUT_DIR)}")
    
    return chunks


if __name__ == "__main__":
    main()
