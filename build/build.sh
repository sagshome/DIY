#!/bin/sh

# Local script to rebuild / start everything

docker stop diy_app
docker stop diy_nginx
docker rm diy_app
docker rm diy_nginx

docker build -t diy-app --file build/app-Dockerfile .
docker build -t diy-nginx --file build/nginx-Dockerfile .

    docker network create --subnet=172.20.0.0/16 diy_network

    docker run --name diy_db     --restart unless-stopped --network diy_network --ip 172.20.0.10 --env-file diy/diy.env -d mysql

    docker run --name diy_app    --restart unless-stopped --network diy_network --ip 172.20.0.15 --env-file diy/diy.env -d diy-app

    docker run --name diy_nginx  --restart unless-stopped --network diy_network --ip 172.20.0.20 -p 80:80 -d diy-nginx



