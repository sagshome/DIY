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