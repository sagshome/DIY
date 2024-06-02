#!/bin/sh


# Local script to rebuild / start everything
echo 'Stopping Services'
docker stop diy_app
docker stop diy_nginx
docker stop diy_db
docker rm diy_app
docker rm diy_nginx
docker rmi diy-app
docker rmi diy-nginx

echo 'Building containers'
docker build -t diy-app --file build/app-Dockerfile .
docker build -t diy-nginx --file build/nginx-Dockerfile .

echo 'Starting Services'
docker network create --subnet=172.20.0.0/16 diy_network 2> /dev/null
docker start diy_db
sleep 5
# docker run --name diy_db  --restart unless-stopped --network diy_network --ip 172.20.0.10 --env-file diy/diy.env -d mysql
docker run --name diy_app    --restart unless-stopped --network diy_network --ip 172.20.0.15 --env-file diy/diy.env -d diy-app
docker run --name diy_nginx  --restart unless-stopped --network diy_network --ip 172.20.0.20 -p 80:80 -d diy-nginx



