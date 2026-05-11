# Rotating API keys

API keys are formatted `kx_<prefix8>_<secret43>`. The prefix is queryable; the
secret is argon2id-hashed. There is no recovery — issuing a new key is the
only path.

## Routine rotation

```sh
# 1) Mint the new key
NEW_KEY=$(kortex key create --name claude-code --scope project --scope-id 42)

# 2) Roll it out to the consuming agent (Claude Code config / env / Helm secret)

# 3) Revoke the old key once you confirm the new one is in use
kortex key revoke <old-public-id>
```

## Compromised key

```sh
kortex key revoke <public-id>
```

Revocation is immediate — the `api_keys.revoked_at` column flips and
`ApiKeyRepository.get_active_by_prefix` filters revoked rows. No cache
invalidation is needed because principal materialisation hits the row on
every request.

## Audit log

All key operations write to `audit_log`. Query recent rotations:

```sql
SELECT * FROM audit_log
WHERE action LIKE 'api_key%'
ORDER BY occurred_at DESC
LIMIT 50;
```
