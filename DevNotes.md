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

