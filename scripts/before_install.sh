#!/usr/bin/env bash
sudo yum -y install python3 make glibc-devel gcc patch python3-devel postgresql-devel
sudo python3 -m pip install --upgrade pip
sudo python3 -m pip install supervisor
sudo python3 -m pip install uvicorn
sudo /usr/local/bin/supervisorctl stop all || :
sudo pkill -F /webapps/lbapi/src/supervisord.pid || :
rm -rf /webapps/lbapi/src
rm -rf /webapps/lbapi/scripts
rm -rf /webapps/lbapi/cfg
rm -f /webapps/lbapi/requirements.txt
