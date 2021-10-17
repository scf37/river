#!/bin/bash

mkdir -p /data
cp -rn /opt/* /data
exec /data/river.py $@
