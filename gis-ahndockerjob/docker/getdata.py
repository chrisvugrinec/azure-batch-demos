import redis
import ConfigParser
from subprocess import call

config = ConfigParser.ConfigParser()
config.readfp(open('/opt/scripts/config/config.txt'))
redis_url=config.get('AZURE_BLOB','redis_url')
redis_key=config.get('AZURE_BLOB','redis_key')
r = redis.StrictRedis(host=redis_url,port=6380, db=0, password=redis_key, ssl=True)

keys = r.keys()

for key in keys:
  value = r.get(key)
  print 'value: ',value
  print 'removing key from cache: ',key
  r.delete(key)
  if value:
    call(["/opt/scripts/get.sh", value])

