# Backup & restore

## What's backed up

The Helm chart ships a daily `CronJob` (`kortex-backup`) that runs `pg_dump`,
gzip-streams the dump, and uploads it to S3 under the `backup.s3Prefix`. By
default it runs at **02:15 UTC** and retains 14 days.

The S3 bucket itself holds attachments. For high-durability deployments,
enable cross-region replication on the bucket separately from the database
backup.

## Restoring

```sh
aws s3 cp s3://kortex-attachments/backups/kortex-20260511T021500Z.sql.gz - \
  | gunzip - \
  | psql "$KORTEX_DATABASE_URL"
```

After restore:

1. Run `alembic upgrade head` to apply any newer migrations.
2. Issue `kortex admin reindex-embeddings` to refresh embeddings if the
   embedder model has changed.
3. Bounce all worker pods so they pick up the rebuilt schema.

## Disaster recovery RPO/RTO

With daily backups, RPO ≤ 24h. To tighten:
- Add WAL archiving to S3 (Postgres 16's `archive_command`).
- Use a read replica for warm failover.
