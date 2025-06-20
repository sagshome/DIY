Can I just use a morningstar get request and parse out values ?

attributes on Model Equity
update_url
update_source  (which I already have)

https://www.morningstar.ca/ca/report/fund/performance.aspx?t=0P00011J9I&FundServCode=MMF1492@7&lang=en-CA



coverage run --source=expenses manage.py test expenses
coverage report -m

# Tracking Wealth #
* Contributions are used to calculate Growth
* Contributions + TransIn (Funding) is used to calculate rates of returns
 
* Withdraw requests always remove Contributions first
  * If Contributions is 0
 
* Transfer requests generate Redeem until Funding is Depleted
* If the transfer cases Redeem then make a Funding request
* If the transfer causes TransOut then make a TransIn request 

* Transfer of actual shares,  cause a SELL,  BUY, based on AvgPrice
  * Redeem/Fund or TransOut/TransIn

## Portfolios ##
Cost is based on funds that are directly contributed into accounts
that make up the portfolio.   When money moves from account to account,  growth that
funded the new account should not be counted as new funds.

## Accounts ##
Cost is based on funds that were contributed or transferred
into the account.

Funding = Contributions + TransIn (TransIn can be positive or negative)

## Equities ##
Cost and Effective cost are based on actual purchase and sale of equities


# Use Cases #
Tracking wealth

Funds - are comprised of 
* Contributions (1:1 mapping of direct payments)
* Transfers In (Gains or Losses from a previous account)
* Interest/Dividends (From equities or savings held in this account)
* Dividends (from)

New money comes into an account via.
1) Stock Transfer
2) Money Transfer
3) Interest
4) 

## Use Case 1 - Transfer Account - Net Gain - Same Portfolio ##
Account 1 (acc1) - is closed out and moved to Account 2 (acc2).   acc1 Present Funding is 
tf1 (10K) and value when closed cv1 (15K).   

I expect acct to have tf2 of 10k,  and a transferred value tv2 of 5K.   

If I look at a portfolio view,  I would see seamless funding to the 10K mark.
If I look at the acc1 view I would see it closed off with an obvious 5K in gain
If I look at the acc2 view,  I would see a funding of 10K and a starting value of 15K,  but 
on the datatable side,  I should only calculate the gains/losses based on the 15K starting
value.

### Notes ###
* When I close an account,  I would need to reedem the PV funded and transfer
out/in the differance between the funding and value it could be negative
  * xa1 - Redeem acc1 - tf1
  * xa2 - Fund acc2 - tf1
  * xa2 - TransIn acc2 (cv1 - tf1)
* when producting an account chart,  the 'funding' value would be based on transfer-in and funding
  * account.p_pd['ActualFunding] = account.p_pd['Funds] + account.p_pd['TransIn]
* when producing a portfolio chart,  only on the funding value
* I need to change the account dataframe to reflect the differance
  * New column TransIn (calculated on demand) ?
* or do I do it in the actual chart view.
* How do I prevent squacking when building a dataframe and the redeem is more then I have
  * Add a column TransOut to compare to  Reedemed <= (TransOut + Funding)  9000 <= (-1000 + 10000)

## Use Case 2 - Transfer Account - Net Gain - Differant Portfolio ##
Account 1 (acc1) - is closed out and moved to Account 2 (acc2).   acc1 total funding is
tf1 (10K) and value when closed cv1 (15K).

I expect acct to have tf2 of 10k,  and a transferred value tv2 of 5K.

* If I look at a portfolio view,  I would see seamless funding drop by 10k on close date.
* If I look at the acc1 view I would see it closed off with an obvious 5K in gain
* If I look at the acc2 view,  I would see a funding of 10K and a starting value of 15K,  but
on the datatable side,  I should only calculate the gains/losses based on the 15K starting
value.

### Notes ###
Same as UseCase 1

## Use Case 3 - Transfer some stock - Different Portfolio ##
Account 1 (acc1) - moves X shares of Y Account 2.  
* The value of the trade is removed from funding
* The value of the trade is added to funding


* If I look at a portfolio view,  I would see seamless funding drop by 10k on close date.
* If I look at the acc1 view I would see it closed off with an obvious 5K in gain
* If I look at the acc2 view,  I would see a funding of 10K and a starting value of 15K,  but
  on the datatable side,  I should only calculate the gains/losses based on the 15K starting
  value.

### Notes ###
Same as UseCase 1

# Notes and such #
docker run --name redis-container -p 6379:6379 -d redis
docker exec -it redis-container redis-cli
PING  
  -> PONG


## Profiles ##
* Extend the User model

### Actions Needed ###
* Login  - Using stock view with customized template
* Logout - Using stock view with customized template
* Lost Password - Using stock view with customized template 
  * Just use the email for the username ?
* Register
  * email_address is the only required field
  * User statis is active = False
  * On successful submit - redirect to info page telling them to check their email,  and send an email
  * Confirm / set password
    * User status is active = True
* Change Password
* Change Profile

Set up Celery: For executing tasks asynchronously.
Configure Redis as the Broker: You’re already using Redis for caching, so we’ll use it as Celery’s broker.
Add Celery Beat: For scheduling periodic tasks.

Write and Run Tasks: Implement on-demand and scheduled tasks.
Integrate with Docker Compose: Ensure the setup works seamlessly in your deployment environment.



## How do deal with stock splits

Using the API from **alphavantage**,   I get records that look like a Dividend but they are adjusted stock splits.   
This means I need to Double my shares (value was in this record) and I need to update all the prior dividends to match 
the split.   Things to consider

Do it automatically once I see the record.
* How do I double on the import ?   I will have 'UPLOAD' dividends not real dividends.
  * I could do the API call as soon as I get the

## Personal Notes
I don't use this tech very often anymore,  notes for me really


### Some useful docker commands.  

    docker update --restart unless-stopped <container>

    docker exec -it <container> sh

    docker build -f <docker_file> -t <image_tag> . 

    docker rm <container>

    docker rmi <image_tag>

    docker ps -a

    docker run -it --rm -v /etc -v logs:/var/log centos /bin/produce_some_logs

    docker network ls

DataFrames
EPD 393 rows
 Date Equity  Shares    Dividend       Price    Value  TotalDividends  EffectiveCost  InflatedCost

PPD 63 Rows
 Date  EffectiveCost      Value  TotalDividends   InflatedCost           Cash


Funding vs Growth vs Value vs Gain

Funding is money from my bank to buy funds
when I close out an account.   How can I tell what was Funded vs Gain,  when I transfer into a new account,  how do I 
track what was funded vs what was gain.

Transfer OUT / Transfer IN are special functions - they do not require a sale,  (although one is reported) but Funding should be transfer in

So if I transfer out 100K,  but I funded 75K,   Should I need to tell it where I am transfering in to and move the funding records over and a CASH record?

docker run -it --rm \
  -v ./nginx/letsencrypt:/etc/letsencrypt \
  -v ./nginx/lib:/var/lib/letsencrypt \
  -v ./nginx/var/www/html:/var/www/html \
  certbot/certbot certonly \
  --webroot \
  --webroot-path=/var/www/html \
  --email scott.sargent61@gmail.com \
  --agree-tos \
  --no-eff-email \
  -d itsonlyourmoney.com -d www.itsonlyourmoney.com
