FROM scf37/base:latest

RUN apt-get update && \ 
    apt-get install -y python python-pip python3 python3-pip make g++ && \ 
    cd /tmp && \
    wget http://mattmahoney.net/dc/zpaq715.zip && \
    unzip zpaq715.zip && \
    make && \
    mkdir -p /opt/backuper && \
    cp zpaq /opt/backuper/zpaq && \
    apt-get remove -y make g++ && \
    apt-get remove -y cpp-4.8 gcc-4.8 manpages manpages-dev && \ 
    apt-get autoremove -y && \
#    curl https://bootstrap.pypa.io/get-pip.py | python && \
    pip install awscli && pip3 install requests && \
    rm -rf /usr/share/doc && \ 
    rm -rf /usr/share/man && \ 
    rm -rf /var/lib/apt/lists/* && \ 
    rm -rf /tmp/*

ADD ./local /opt/backuper/local
ADD ./s3 /opt/backuper/s3
ADD ./mailru /opt/backuper/mailru
ADD ./main.py /opt/backuper/main.py
ADD ./restore.py /opt/backuper/restore.py
ADD ./service.yml /service.yml

ENV START /opt/start
ENV LC_ALL=C.UTF-8
# Create log and conf dirs
RUN mkdir -p /data/logs && mkdir -p /data/conf

ADD ./start-app.py /opt/confyrm-app2/start-app
ENV PATH /opt/confyrm-app2:$PATH

ENV PATH /opt/backuper:$PATH
ENTRYPOINT ["start-app", "--script", "/opt/backuper/main.py"]
