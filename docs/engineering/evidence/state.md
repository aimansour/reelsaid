# Shared state and work ownership

| Candidate | Fit for ReelSaid |
| --- | --- |
| Apify Request Queue and key-value store | Queue-head locks have exclusive ownership and renewal. The documented key-value record update cannot condition a write on the queue's lock token. Run-scoped storage is useful for customer outputs and storage permissions. [Queue head locks](https://docs.apify.com/api/v2/request-queue-head-lock-post) · [Store record writes](https://docs.apify.com/api/v2/key-value-store-record-put) |
| SQLite inside an Apify run | Executes the required transactions locally. Independent Actor runs have separate process and filesystem lifetimes, so the database is a verification backend. |
| Cloudflare Durable Objects | Suitable for serialized per-video coordination. Splitting an object's lease from account-wide cache and checkpoint indexes would add cross-object calls. [Durable Objects storage](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/) |
| Cloudflare D1 behind an authenticated Worker | Keeps the lease and account records in one database. An indexed conditional SQL statement can check a live fence and write a result atomically. Worker bindings avoid the management API for runtime traffic. [D1 Workers binding](https://developers.cloudflare.com/d1/worker-api/d1-database/) |

Select D1 with a dedicated Worker. The Free tier permits a bounded probe and charges no idle compute. Measure reads, writes, latency, and storage under the matched Actor workload before final resource and price decisions. [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)

Each canonical video has one active lease across runs. Each lease has a random fence and an expiry evaluated on the database clock. Renewal, release, staging, and result commit are conditional on the tenant, run, video, and current fence. A refresh can present the cache revision seen at the start of its attempt. Acquisition checks that revision in the same statement, so a completed overlapping refresh can be reused without admitting duplicate work.

The Actor binds tenant and run identity to its authenticated runtime environment. The database keys cache, watchlist, and checkpoint state by tenant. A cache key includes the language, caption preference, and word-timing option. Subtitle output is derived from the transcript. Watchlist writes preserve the first definitive answer's timestamp. Checkpoint chunks are written under a fresh generation and published only after all parts succeed, leaving the prior generation available through an interrupted write.

The state endpoint accepts only the checked-in operations with bound parameters. Its bearer credential grants access to the ReelSaid service. The private Apify Actor receives the credential at runtime. Verification logs omit credentials, payloads, and SQL. A fenced database write protects the state transition. The billing task implements reconciliation for the separate Apify charge request and its time-limited idempotency key. [Apify charge API](https://docs.apify.com/api/v2/post-charge-run)

The local suite executes the production SQL with independent SQLite connections. It verifies one winner across 12 simultaneous contenders, expiry fencing, tenant separation, refresh coalescing, the first watchlist answer, and checkpoint recovery. The cloud probe starts two Apify runs and verifies the same lease on the remote service.
