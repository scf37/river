# Backuper
Simple command-line tool for space efficient incremental remote backups

## Defining features
- pluggable storage drivers on 3 shell scripts, supporting only get, put and delete
- support for full and incremental backups, rolling by date
- support for encryption
- no large local temporary files
- backup configuration is stored remotely, together with backup data
- recovery as simple as possible
- silent by default

## Quickstart
1. `./backuper.py create-config test.yaml`
2. edit test.yaml and enable encryption there
3. `backuper_key=hello ./backuper.py create ssh:bkp@host.com:/backups/test-backup test.yaml`
4. `backuper_key=hello ./backuper.py backup ssh:bkp@host.com:/backups/test-backup /data/my-files`
5. `backuper_key=hello ./backuper.py list ssh:bkp@host.com:/backups/test-backup`

## Documentation
### backuper.py invocation
Run `backuper.py` without parameters to get built-in help
### Backup configuration
Create backup configuration file via `create-config` command and see comments there
### Custom drivers
Create new folder, it will be driver name, with 3 executables inside. See existing drivers for details.
To work correcly, scripts should return non-zero exit code on error, stdout is only printed in verbose mode,
stderr is always printed on error
