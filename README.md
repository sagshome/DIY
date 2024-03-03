The collection of things in DIY are utilities I wrote for myself.   The instruction below may help you (or 
even me in the future).

1. Get a https://www.alphavantage.co/ API key - The free key should work for less the 20 stocks
2. Install (or verify) docker is installed.
3. Install npm 
1. Github access (or how did you read this?)  - https://github.com/sagshome/DIY
   1. Pull or Download the source tree to <base>
   2. Copy <base>/build/example-diy.env <base>/diy/diy.env
   3. Make changes:
      4. Add a SECRET_KEY value,   go for 20ish characters
      5. Change ALPHAVANTAGEAPI_KEY
      6. You can change the DB values if you want.
1. Start it up

   docker run --name test_new --restart unless-stopped --network diy_network --env-file build/example-diy.env -d mysql
   docker run --name diy_db --restart unless-stopped --network diy_network --env-file build/example-diy.env -d mysql


## End stucture

    browser <-> NGINX <-> uwsgi <-> diy_app <-> MYSQL

I will build this backwards,  get the DB going,  get my app going and then get NGINX going.  It seems to 
be the easiest way for me to bring thinks up.   I played around with docker-compose, but it just seems 
like more work than I need for a DIY application.

This (docker-compose) is something I will look into but my next project is a raspberry-pi frontend for a NIS 
server and VPN access point for the house.

## Build and Testing
Assume you are running this with an activated virtual environment and from the project root

### Build a Docker Network
docker network create DIY_DB 

### Build DB container
Go get yourself a dockerized database.   You can use sqllite that comes with django, but you may as well 
get a full on DB.   I went with mysql,  and just set it up using the instructions provided.   I created my
DB user/credentials manually - https://hub.docker.com/_/mysql
- I set it up to restart unless explicitly stopped
- I just used internal docker storage, but I did expose the 3306 port so that I could also connect from shell_plus for doing one offs.
- See below for my docker inspect highlights
- Run this container in the diy_network

   docker run --name diy_db --restart unless-stopped --network diy_network --env-file build/example-diy.env -d mysql

### Build the app
I use the standard uwsgi,   at port 8001 which I expose so that I can connect directly.   You can choose
to not do this since in the end we will use NGINX to server up on port 80 (and 443 for https)

The command you will eventually be calling, so you may as well test this.

    docker build -t diy-app --file build/app-Dockerfile .
    docker run -d --name diy_app -p 8001:8001 --network diy_network diy-app

### Testing
    coverage run manage.py test stocks; coverage report
### Building
    ./diy/build/build.sh


## CSS

    npm install asyncdesign-webui


## Docker
We have three docker containers

1. Database - diy_db - exposing port for testing
2. nginx - diy_nginx - let it handle port 80
3. application/uwsgi


### Some useful docker commands.  

    docker update --restart unless-stopped <container>

    docker exec -it <container> sh

    docker build -f <docker_file> -t <image_tag> . 

    docker rm <container>

    docker rmi <image_tag>

    docker ps -a

    docker run -it --rm -v /etc -v logs:/var/log centos /bin/produce_some_logs

    docker network ls

### Docker hightlights
Just showing the hightlights.    I use things like the IP address to connect externally,  docker to docker
I use the dns names
#### docker inspect diy_db
    [
        {
            "Created": "2024-01-20T18:17:21.322401817Z",
            "Path": "docker-entrypoint.sh",
            "Args": [
                "mysqld"
            ],

            "Name": "/diy_db",
            "HostConfig": {

                "NetworkMode": "diy_network",
                "PortBindings": {
                    "3306/tcp": [
                        {
                            "HostIp": "",
                            "HostPort": "3306"
                        }
                    ]
                },
                "RestartPolicy": {
                    "Name": "unless-stopped",
                    "MaximumRetryCount": 0
                },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "61b98289a4259644617f442158a2a6428ccfd709e159c32a148828064c30d44d",
                    "Source": "/var/lib/docker/volumes/61b98289a4259644617f442158a2a6428ccfd709e159c32a148828064c30d44d/_data",
                    "Destination": "/var/lib/mysql",
                }
            ],
            "Config": {
                "Hostname": "mysql",
                "Env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "GOSU_VERSION=1.16",
                    "MYSQL_MAJOR=8.0",
                    "MYSQL_VERSION=8.0.36-1.el8",
                    "MYSQL_SHELL_VERSION=8.0.36-1.el8",
                    "MYSQL_ROOT_PASSWORD=root_pass",
                    "MYSQL_DATABASE=DIY",
                    "MYSQL_USER=diy_user",
                    "MYSQL_PASSWORD=diy_password"
                ],
                "Cmd": [
                    "mysqld"
                ],
                "Image": "database",
                "Volumes": {
                    "/var/lib/mysql": {}
                },
                "WorkingDir": "",
                "Entrypoint": [
                    "docker-entrypoint.sh"
                ],
                "OnBuild": null,
                "Labels": {}
            },
            "NetworkSettings": {
                "Bridge": "",
                "SandboxID": "0dc2ebb9875e75b26c87c90303ce2a178a7426f100ff0bdeadb4cb4ba29c8da5",
                "SandboxKey": "/var/run/docker/netns/0dc2ebb9875e",
                "Ports": {
                    "3306/tcp": [
                        {
                            "HostIp": "0.0.0.0",
                            "HostPort": "3306"
                        },
                        {
                            "HostIp": "::",
                            "HostPort": "3306"
                        }
                    ],
                    "33060/tcp": null
                },
                "Networks": {
                    "diy_network": {
                        "IPAMConfig": {
                            "IPv4Address": "172.20.0.10"
                        },
                        "Aliases": [
                            "b0dc5d4b9ea4",
                            "mysql"
                        ],
                        "DNSNames": [
                            "diy_db",
                            "b0dc5d4b9ea4",
                            "mysql"
                        ]
                    }
                }
            }
        }
    ]
