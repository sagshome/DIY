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
