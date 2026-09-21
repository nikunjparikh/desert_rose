#!/bin/zsh
cd /Users/Nikunj/iot/desert_rose || exit 1
PY=/Users/Nikunj/opt/anaconda3/envs/balcony/bin/python
$PY puller.py || exit 1
$PY report.py || exit 1

rm -rf /tmp/balcony-pub && mkdir -p /tmp/balcony-pub
cp index.html /tmp/balcony-pub/
cd /tmp/balcony-pub || exit 1
git init -q && git add index.html && git commit -qm "balcony $(date)"
git push -qf https://github.com/nikunjparikh/desert_rose.git HEAD:balcony-page
