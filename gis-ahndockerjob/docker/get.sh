#!/bin/bash
container=$(cat /opt/scripts/config/config.txt | grep container_name | sed 's/container_name=//')
export AZURE_STORAGE_CONNECTION_STRING=$(cat /opt/scripts/config/config.txt | grep azure_connection_string | sed 's/azure_connection_string=//')
filetoget="$1"
wget $filetoget -O /opt/scripts/temp.zip 2>/dev/null
xxx=$(unzip /opt/scripts/temp.zip)
unzippedfile=$(echo $xxx | awk '{print $4}')
echo "unzipped file: "$unzippedfile
azure storage blob upload /$unzippedfile $container 2>/dev/null
rm -f /opt/scripts/temp.zip 2>/dev/null
rm -f /$unzippedfile 2>/dev/null
