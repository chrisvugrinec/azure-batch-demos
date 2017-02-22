# Documentation Azure Batch - gis ahn docker job

See it in action: https://youtu.be/1th0ZSnuVFY

## What is it

A tool that gets geographical data from geodata.nationaalgeoregister.nl, unzips the tif files and put them on azure blob storage.
This way Data Scientists with a specialization on AHN data (something with the Heights in the Netherlands) can utilize and do queries on this data using for example notebooks.


## How to

* pre requisites:
  * azure account
  * azure batch account
  * azure storage account
  * azure redis cache (from azure markettplace)
  * a private docker registry (from azure marketplace)

* setup
  * setup a redis cache and config the ACCESS key in the config.txt file (in the resources folder)
  * setup a storage account and config the SHARED ACCESS URL in the config.txt file (in the resources folder)
  * Setup your azure batch account, and config the ACCESS key in the startjob.cfg file (in the resources folder)

* start
  * Run the init job to populate the Redis Cache
  * You can start the job by executing the start.sh script. This will call all the required azure batch API via the Python program (see startjob.py)

Hint, use the Azure Batch Explorer to see what is going on...for now, this is only available as a Windows Binary

## How does it work

this job does the following:
* initialization phase
  * with the init scripts (see in docker/dataloader) you do the following
  * collect data from 1 RSS feed: https://geodata.nationaalgeoregister.nl/ahn2/atom/ahn2_05m_int.xml
  * parse all the URL and keys from the XML (about 1370) and put them in a REDIS cache
* batch phase
  * creates a pool under your configured azure batch settings
  * in that pool it creates machines using the configured settings in startjob.cfg (please mind the limitation of the amount of cores you are able to order)
  * on all the machines it will install some pre-requisites (in this case a docker installation, see the resources/install-docker.sh file)
  * after all the machines have the state IDLE
  * it will run the following tasks on each machine:
    * copy the config file in the expected directory
    * login to the private docker registry
    * docker run -i -v `pwd`:/opt/scripts/config  chris-microsoft.azurecr.io/gis-azureshipyarjob:2.1 /opt/scripts/getdata.sh
      * this mounts the local config directory to the /opt/scripts/config directory
      * downloads and runs the chris-microsoft.azurecr.io/gis-azureshipyarjob:2.1 image
      * executes the getdata.sh script

The getdata.sh script, gets an URL from the redis cache, deletes this key. Downloads the file in the url, unzips it and pushes it to the configured blob storage.
 


