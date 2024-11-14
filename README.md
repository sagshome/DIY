Needed for Launch
1) ~~Support Income~~
   2) Income will come from bank statement (mostly) - Just like expenses
   3) 
2) Have domain mail
3) Rebrand
4) HTTPS
5) Main Page - revamp
6) Bulk Edit
7) export Investments
8) Fix CRON
9) Understand Stock Types
   a) Stocks/ETFs  <- I can look these up
   b) Mutual Funds  <- I can input and or import transactions/values
   10)   How do these differ from presentation - imports/exports 
      c) Values  <- I have no idea what I own,  I just know the value each month

The collection of things in DIY are utilities I wrote for myself.   The instruction below may help you (more likely just me) 
get things up and running.

## Prepare your environment
When done,  you will have something this running

    browser <-> NGINX <-> uwsgi <-> diy_app <-> MYSQL

### You need some API keys and other access
I currently use **alphavantage**,  It seems to work pretty well.  the free account gets me 25 calls a day
and this is enough for me.  If you need more you can buy a license
https://www.alphavantage.co/

You need to have github https://github.com/ access to pull or download this source tree

You need to have docker hub https://hub.docker.com/ access to pull down base images.    I may end up storing my
docker images in the future to make these instruction easier.


If not already done,  pull the software from https://github.com/sagshome/DIY   The folder where DIY lives will
be the <base> for these instructions.   You should see something like this when you pull your source tree

    DIY 
       base
       build
       diy
       expenses
       stocks


### Some base software and packages.
This is unix based.  I am sure you can figure it out.


#### Build your base docker images
    cd <base>
    docker build -t diy-app --file build/app-Dockerfile .
    docker build -t diy-cron --file build/cron-Dockerfile .
    docker build -t diy-nginx --file build/nginx-Dockerfile .

#### Edit your custom config
    cd <base>
    cp build/example-diy.env diy/diy.env
    edit diy/diy.env and change accordingly (you will need to add the alphavantage key for this)

    SECRET_KEY=make-a-secret-key
    ALPHAVANTAGEAPI_KEY=alpahvanateapi_key
    DIY_DEBUG=False
    DIY_LOCALDB=False
    DIY_EMAIL_USER=email_account
    DIY_EMAIL_PASSWORD=email_password

    MYSQL_ROOT_PASSWORD=my-secret-pw
    MYSQL_DATABASE=DIY
    MYSQL_USER=diy_user1
    MYSQL_PASSWORD=diy_password1
    DATABASE_HOST=diy_db


#### Start things up

    docker network create --subnet=172.20.0.0/16 diy_network

    docker run --name diy_db     --restart unless-stopped --network diy_network --ip 172.20.0.10 --env-file diy/diy.env -d mysql
    docker run --name diy_app    --restart unless-stopped --network diy_network --ip 172.20.0.15 --env-file diy/diy.env -d diy-app
    docker run --name diy_cron   --restart unless-stopped --network diy_network --ip 172.20.0.25 --env-file diy/diy.env -d diy-cron
    docker run --name diy_nginx  --restart unless-stopped --network diy_network --ip 172.20.0.20 -p 80:80 -d diy-nginx


### Your DONE !
Not too hard I hope.


## Things I need to improve
* External DB
* Backup DB
* Support No API Key


