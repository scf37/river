# River
Simple command-line tool for space efficient incremental remote backups

## Defining features
- Pluggable storage drivers on 3 simple shell scripts: download file, upload file, delete remote file
- Full and incremental backups, rolling by date
- AES encryption
- No large local temporary files
- Backup configuration is stored remotely, together with backup data
- Recovery requires this tool and backup location only
- Silent by default

## Quickstart
1. `./river.py create-config test.yaml`
2. edit test.yaml and enable encryption there
3. `river_key=hello ./river.py create ssh:bkp@host.com:/backups/test-backup test.yaml`
4. `river_key=hello ./river.py backup ssh:bkp@host.com:/backups/test-backup /data/my-files`
5. `river_key=hello ./river.py list ssh:bkp@host.com:/backups/test-backup`

## Docker quickstart
1. `docker run scf37/river new-config - > test.yaml`
2. edit test.yaml and enable encryption there
3. `docker run -e river_key=hello -e SSH_OPTS='-o StrictHostKeyChecking=no -i /data/backup_rsa' -it --rm -v /data/river:/data -v /:/backup scf37/river create ssh:root@pazuzu.me:~/backups/mybackup - < test.yaml`
4. `docker run -e river_key=hello -e SSH_OPTS='-o StrictHostKeyChecking=no -i /data/backup_rsa' -it --rm -v /data/river:/data -v /:/backup scf37/river backup ssh:root@pazuzu.me:~/backups/mybackup /backup/home/me`
5. `docker run -e river_key=hello -e SSH_OPTS='-o StrictHostKeyChecking=no -i /data/backup_rsa' -it --rm -v /data/river:/data -v /:/backup scf37/river list ssh:root@pazuzu.me:~/backups/mybackup`

## Documentation
### river.py invocation
Run `river.py` or `docker run scf37/river` without parameters to get built-in help
### Backup configuration
Create backup configuration file via `new-config` command and see comments there
### Custom drivers
Create new folder, it will be driver name, with 3 executables inside. See existing drivers for details.
To work correctly, scripts should return non-zero exit code on error, stdout is only printed in verbose mode,
stderr is always printed on error
