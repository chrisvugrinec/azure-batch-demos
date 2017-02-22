import redis
import ConfigParser

config = ConfigParser.ConfigParser()
config.readfp(open('/opt/scripts/config/config.txt'))
redis_url=config.get('AZURE_BLOB','redis_url')
redis_key=config.get('AZURE_BLOB','redis_key')
r = redis.StrictRedis(host=redis_url,port=6380, db=0, password=redis_key, ssl=True)

# clearing all keys
r.flushall()

file = open('anh-files', 'r')
counter=1
key = ''
value = ''
for line in file:
  if counter == 1:
    key = line
  if counter ==2:
    value = line
    print counter,'setting: ',key,' value: ',value
    counter = 0
    r.set(key,value)
  counter = counter + 1
file.close()
