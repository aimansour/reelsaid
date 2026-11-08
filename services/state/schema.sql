CREATE TABLE IF NOT EXISTS leases (
    video_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    fence TEXT NOT NULL,
    expires_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS staged (
    tenant_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    fence TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (tenant_id, video_id, fingerprint, fence)
);

CREATE TABLE IF NOT EXISTS results (
    tenant_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (tenant_id, video_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS answers (
    tenant_id TEXT NOT NULL,
    watchlist_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    first_seen_ms INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, watchlist_id, video_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    previous_generation TEXT,
    chunk_count INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_parts (
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    part INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (tenant_id, dataset_id, generation, part)
);
