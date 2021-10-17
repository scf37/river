FROM scf37/base:latest

ADD . /opt/backuper

ENTRYPOINT ["/opt/backuper/backuper.py"]