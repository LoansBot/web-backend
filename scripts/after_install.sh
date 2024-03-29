#!/usr/bin/env bash
sudo python3 -m pip install -r /webapps/lbapi/logging-requirements.txt
sudo python3 -m pip install -r /webapps/lbapi/shared-requirements.txt
sudo python3 -m pip install -r /webapps/lbapi/requirements.txt
echo "Starting up supervisor"
source /home/ec2-user/secrets.sh
cd /webapps/lbapi/src
sudo -E /usr/local/bin/supervisord -c ../cfg/supervisor.conf || :
