FROM ubuntu:20.04

ENV TZ=US/Eastern
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && \
    apt-get install -y python3 python3-pip libyaml-dev openssh-client && \
    pip3 install requests pyyaml && \
    apt-get remove -y make g++ && \
    apt-get remove -y cpp-9 gcc-9 manpages manpages-dev libpython3.8-dev libc6-dev systemd linux-libc-dev dpkg-dev python3-setuptools python3-distutils python3-pip python3.8-dev dpkg-dev libyaml-dev && \
    apt-get autoremove -y && \
    rm -rf /usr/share/doc && \
    rm -rf /root/.cache && \
    rm -rf /usr/share/man && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /var/cache/* && \
    rm -rf /tmp/*

ADD river.py /opt
ADD local /opt/local
ADD ssh /opt/ssh
ADD s3 /opt/s3
ADD start.sh /

ENTRYPOINT ["/start.sh"]