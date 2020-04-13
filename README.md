Requirements:
- pluggable storage, supporting only get, put and delete
- support for full and incremental backups, rolling by date (and probably size?)
- no large local temporary files
- backup configuration is stored remotely, together with backup data
- as modular as possible
- recovery as simple as fuck

Backup utility tool:
1. create or modify backup
- password
- backup base URL
- exclusions (Exclude those files)
- inclusions (include those files only)
- backup roll config
-- when to roll: max count of incremental backups
-- how many full backups to keep

2. run backup
- password
- backup base URL
- local dir(s) to back up

3. describe backup
- password
- backup base URL
Shows backup config

Lists all available backup versions (by date)

4. restore backup
- password
- backup base URL
- backup destination dir