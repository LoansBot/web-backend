#!/usr/bin/env bash
sudo yum -y install make glibc-devel gcc patch perl-core zlib-devel postgresql-devel
if [ ! -f /usr/local/src/openssl-1.1.1g.tar.gz ]; then
    # We need openssl >= 1.1 for scrypt, and we need to build python with it
    # available. We also update python here to latest since we're building
    # from source anyway
    sudo yum remove python3 -y

    cd /usr/local/src
    sudo wget https://www.openssl.org/source/openssl-1.1.1g.tar.gz
    sudo tar -xf openssl-1.1.1g.tar.gz
    cd openssl-1.1.1g
    sudo ./config --prefix=/usr/local/ssl --openssldir=/usr/local/ssl shared zlib
    sudo make
    sudo make install
    sudo bash -c 'echo "/usr/local/ssl/lib" > "/etc/ld.so.conf.d/openssl-1.1.1g.conf"'
    sudo ldconfig -v
    if [ -f /usr/bin/openssl ]; then
        sudo mv /usr/bin/openssl /usr/bin/openssl.BACKUP
    fi
    sudo cp -R /usr/local/ssl/bin /usr/

    cd /usr/local/src
    sudo wget https://www.python.org/ftp/python/3.8.3/Python-3.8.3.tgz
    sudo tar -xf Python-3.8.3.tgz
    cd Python-3.8.3
    sudo ./configure --prefix=/usr/local/python3.8 --enable-optimizations
    sudo make
    sudo make install
    sudo ln -s /usr/local/python3.8/bin/python3.8 /usr/bin/python3
fi
sudo python3 -m pip install --upgrade pip
sudo python3 -m pip install supervisor
sudo python3 -m pip install uvicorn
sudo /usr/local/bin/supervisorctl stop all || :
sudo pkill -F /webapps/lbapi/src/supervisord.pid || :
rm -rf /webapps/lbapi/src
rm -rf /webapps/lbapi/scripts
rm -rf /webapps/lbapi/cfg
rm -f /webapps/lbapi/requirements.txt
