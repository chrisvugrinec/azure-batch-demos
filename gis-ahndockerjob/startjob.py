from __future__ import print_function
try:
  import configparser
except ImportError:
  import ConfigParser as configparser

import datetime
import time
import os

import azure.storage.blob as azureblob
import azure.batch.batch_service_client as batch
import azure.batch.batch_auth as batchauth
import azure.batch.models as batchmodels

import common.helpers

# config.txt contains config for the docker image
# startjob.cfg contains config for this script to run

_CONTAINER_NAME = 'poolsandresourcefiles'
_POOL_NAME = common.helpers.generate_unique_resource_name('gis-ahn-pool')
#_POOL_NAME = 'gis-ahn-pool-20161204-215319'
_NODE_USERNAME = 'chris'
_JOB_PREFIX = 'ahnjob'
_TASK_NAME = 'ahntask'
_STARTTASK_RESOURCE_FILE = 'install-docker.sh'
_STARTTASK_SHELL_SCRIPT_PATH = os.path.join('resources', _STARTTASK_RESOURCE_FILE)


def do_dockerstuff(batch_client, block_blob_client, job_id, pool_id, docker_user, docker_password,docker_image):

  # upload scripts
  config_url = common.helpers.upload_blob_and_create_sas(block_blob_client,_CONTAINER_NAME,'config.txt',os.path.join('resources','config.txt'),datetime.datetime.utcnow() + datetime.timedelta(hours=1))

  task_commands = [
        'mkdir -p /opt/scripts/config',
        'cd /opt/scripts/config',
        'wget '+common.helpers._read_stream_as_string('\"'+config_url+'\" -O /opt/scripts/config/config.txt','utf-8'),
        'docker login chris-microsoft.azurecr.io -u '+docker_user+' -p '+docker_password,
        'docker run -i -v `pwd`:/opt/scripts/config '+docker_image+' /opt/scripts/getdata.sh',
  ]
  task_name=common.helpers.generate_unique_resource_name(_TASK_NAME)
  print('adding task: '+task_name)
  task = batchmodels.TaskAddParameter( id=task_name, command_line=common.helpers.wrap_commands_in_shell('linux', task_commands),run_elevated=True,) 
  batch_client.task.add(job_id=job_id, task=task)
  time.sleep( 5 )
  return task.id


def create_pool_and_wait_for_nodes( batch_client, block_blob_client, pool_id, vm_size, vm_count):

  sku_to_use, image_ref_to_use = common.helpers.select_latest_verified_vm_image_with_node_agent_sku( batch_client, 'Canonical', 'UbuntuServer', '14.04')
  block_blob_client.create_container(_CONTAINER_NAME, fail_on_exist=False)

  # upload start task script
  block_blob_client.create_container(_CONTAINER_NAME, fail_on_exist=False)
  sas_url = common.helpers.upload_blob_and_create_sas(block_blob_client,_CONTAINER_NAME,_STARTTASK_RESOURCE_FILE,_STARTTASK_SHELL_SCRIPT_PATH,datetime.datetime.utcnow() + datetime.timedelta(hours=1))

  # create pool and execute starttask
  pool = batchmodels.PoolAddParameter(
        id=pool_id,
        enable_inter_node_communication=True,
        virtual_machine_configuration=batchmodels.VirtualMachineConfiguration( image_reference=image_ref_to_use, node_agent_sku_id=sku_to_use),
        vm_size=vm_size,
        target_dedicated=vm_count,
        start_task=batchmodels.StartTask(command_line=_STARTTASK_RESOURCE_FILE,run_elevated=True,wait_for_success=True,resource_files=[batchmodels.ResourceFile(file_path=_STARTTASK_RESOURCE_FILE, blob_source=sas_url)]),)
  common.helpers.create_pool_if_not_exist(batch_client, pool)

  # because we want all nodes to be available before any tasks are assigned
  # to the pool, here we will wait for all compute nodes to reach idle
  nodes = common.helpers.wait_for_all_nodes_state( batch_client, pool, frozenset(
            (batchmodels.ComputeNodeState.starttaskfailed,
             batchmodels.ComputeNodeState.unusable,
             batchmodels.ComputeNodeState.idle)
      )
  )

  # ensure all node are idle
  if any(node.state != batchmodels.ComputeNodeState.idle for node in nodes):
    raise RuntimeError('node(s) of pool {} not in idle state'.format(pool.id))

  return nodes



if __name__ == '__main__':

  public_key = None
  private_key = None

  app_config = configparser.ConfigParser()
  # read [this filename].cfg as configfile
  app_config.read('resources/'+os.path.splitext(os.path.basename(__file__))[0] + '.cfg')

  # Set up the configuration
  batch_account_key = app_config.get('AZ_BATCH', 'batchaccountkey')
  batch_account_name = app_config.get('AZ_BATCH', 'batchaccountname')
  batch_service_url = app_config.get('AZ_BATCH', 'batchserviceurl')

  storage_account_key = app_config.get('AZ_STORAGE', 'storageaccountkey')
  storage_account_name = app_config.get('AZ_STORAGE', 'storageaccountname')
  storage_account_suffix = app_config.get('AZ_STORAGE','storageaccountsuffix')

  should_delete_container = app_config.getboolean( 'JOB', 'shoulddeletecontainer')
  should_delete_job = app_config.getboolean( 'JOB', 'shoulddeletejob')
  should_delete_pool = app_config.getboolean( 'JOB', 'shoulddeletepool')
  pool_vm_size = app_config.get( 'JOB', 'poolvmsize')
  pool_vm_count = app_config.getint( 'JOB', 'poolvmcount') 

  docker_user = app_config.get( 'DOCKER', 'dockerreguser')
  docker_password = app_config.get( 'DOCKER', 'dockerregpassword')
  docker_image = app_config.get( 'DOCKER', 'dockerimage')

  credentials = batchauth.SharedKeyCredentials(batch_account_name, batch_account_key)
  batch_client = batch.BatchServiceClient(credentials, base_url=batch_service_url)
  block_blob_client = azureblob.BlockBlobService( account_name=storage_account_name, account_key=storage_account_key, endpoint_suffix=storage_account_suffix)



  job_id = common.helpers.generate_unique_resource_name(_JOB_PREFIX)
  print('creating job with id: '+job_id)
  pool_id = _POOL_NAME

  # create pool and wait for node idle
  nodes = create_pool_and_wait_for_nodes( batch_client, block_blob_client, pool_id, pool_vm_size, pool_vm_count)

  # generate ssh key pair
  #private_key, public_key = common.helpers.generate_ssh_keypair('batch_id_rsa')

  # add compute node user to nodes with ssh key
  #for node in nodes:
    #common.helpers.add_admin_user_to_compute_node(batch_client, pool_id, node, _NODE_USERNAME, public_key)

  try:
    # create job
    job = batchmodels.JobAddParameter(id=job_id,pool_info=batchmodels.PoolInformation(pool_id=pool_id))
    batch_client.job.add(job)

    # submit job and add a task
    for node in nodes:
      #print('docker user: '+docker_user)
      task_id = do_dockerstuff(batch_client, block_blob_client, job_id, pool_id, docker_user, docker_password, docker_image)

    # wait for tasks to complete
    common.helpers.wait_for_tasks_to_complete( batch_client, job_id, datetime.timedelta(minutes=15))
  finally:
    if should_delete_container:
      print('Deleting container: {}'.format(_CONTAINER_NAME))
      block_blob_client.delete_container(_CONTAINER_NAME, fail_not_exist=False)
    if should_delete_job:
      print('Deleting job: {}'.format(job_id))
      batch_client.job.delete(job_id)
    if should_delete_pool:
      print('Deleting pool: {}'.format(pool_id))
      batch_client.pool.delete(pool_id)
