from __future__ import print_function
import datetime
import io
import os
import time
import subprocess

import azure.storage.blob as azureblob
import azure.batch.models as batchmodels


_STANDARD_OUT_FILE_NAME = 'stdout.txt'
_STANDARD_ERROR_FILE_NAME = 'stderr.txt'
_SAMPLES_CONFIG_FILE_NAME = 'configuration.cfg'


class TimeoutError(Exception):
    """An error which can occur if a timeout has expired.
    """
    def __init__(self, message):
        self.message = message

def add_admin_user_to_compute_node(batch_client, pool_id, node, username, ssh_public_key):

    print('adding user {} to node {} in pool {}'.format( username, node.id, pool_id))
    batch_client.compute_node.add_user(
        pool_id,
        node.id,
        batchmodels.ComputeNodeUser(
            username,
            is_admin=True,
            password=None,
            ssh_public_key=decode_string( open(ssh_public_key, 'rb').read()))
    )
    print('user {} added to node {}.'.format(username, node.id))

def generate_ssh_keypair(key_fileprefix):
    pubkey = key_fileprefix + '.pub'
    try:
        os.remove(key_fileprefix)
    except OSError:
        pass
    try:
        os.remove(pubkey)
    except OSError:
        pass
    print('generating ssh key pair')
    subprocess.check_call(
        ['ssh-keygen', '-f', key_fileprefix, '-t', 'rsa', '-N', ''''''])
    return (key_fileprefix, pubkey)

def decode_string(string, encoding=None):
    if isinstance(string, str):
        return string
    if encoding is None:
        encoding = 'utf-8'
    if isinstance(string, bytes):
        return string.decode(encoding)
    raise ValueError('invalid string type: {}'.format(type(string)))


def select_latest_verified_vm_image_with_node_agent_sku(
        batch_client, publisher, offer, sku_starts_with):

    # get verified vm image list and node agent sku ids from service
    node_agent_skus = batch_client.account.list_node_agent_skus()
    # pick the latest supported sku
    skus_to_use = [
        (sku, image_ref) for sku in node_agent_skus for image_ref in sorted(
            sku.verified_image_references, key=lambda item: item.sku)
        if image_ref.publisher.lower() == publisher.lower() and
        image_ref.offer.lower() == offer.lower() and
        image_ref.sku.startswith(sku_starts_with)
    ]
    # skus are listed in reverse order, pick first for latest
    sku_to_use, image_ref_to_use = skus_to_use[0]
    return (sku_to_use.id, image_ref_to_use)


def wait_for_tasks_to_complete(batch_client, job_id, timeout):

    time_to_timeout_at = datetime.datetime.now() + timeout

    while datetime.datetime.now() < time_to_timeout_at:
        print("Checking if all tasks are complete...")
        tasks = batch_client.task.list(job_id)

        incomplete_tasks = [task for task in tasks if
                            task.state != batchmodels.TaskState.completed]
        if not incomplete_tasks:
            return
        time.sleep(5)

    raise TimeoutError("Timed out waiting for tasks to complete")


def print_task_output(batch_client, job_id, task_ids, encoding=None):

    for task_id in task_ids:
        file_text = read_task_file_as_string(
            batch_client,
            job_id,
            task_id,
            _STANDARD_OUT_FILE_NAME,
            encoding)
        print("{} content for task {}: ".format(
            _STANDARD_OUT_FILE_NAME,
            task_id))
        print(file_text)

        file_text = read_task_file_as_string(
            batch_client,
            job_id,
            task_id,
            _STANDARD_ERROR_FILE_NAME,
            encoding)
        print("{} content for task {}: ".format(
            _STANDARD_ERROR_FILE_NAME,
            task_id))
        print(file_text)


def print_configuration(config):

    configuration_dict = {s: dict(config.items(s)) for s in
                          config.sections() + ['DEFAULT']}

    print("Configuration is:")
    print(configuration_dict)


def _read_stream_as_string(stream, encoding):

    output = io.BytesIO()
    try:
        for data in stream:
            output.write(data)
        if encoding is None:
            encoding = 'utf-8'
        return output.getvalue().decode(encoding)
    finally:
        output.close()
    raise RuntimeError('could not write data to stream or decode bytes')


def read_task_file_as_string(batch_client, job_id, task_id, file_name, encoding=None):

    stream = batch_client.file.get_from_task(job_id, task_id, file_name)
    return _read_stream_as_string(stream, encoding)


def read_compute_node_file_as_string( batch_client, pool_id, node_id, file_name, encoding=None):

    stream = batch_client.file.get_from_compute_node(
        pool_id, node_id, file_name)
    return _read_stream_as_string(stream, encoding)


def create_pool_if_not_exist(batch_client, pool):

    try:
        print("Attempting to create pool:", pool.id)
        batch_client.pool.add(pool)
        print("Created pool:", pool.id)
    except batchmodels.BatchErrorException as e:
        if e.error.code != "PoolExists":
            raise
        else:
            print("Pool {!r} already exists".format(pool.id))


def create_job(batch_service_client, job_id, pool_id):

    print('Creating job [{}]...'.format(job_id))

    job = batchmodels.JobAddParameter(
        job_id,
        batchmodels.PoolInformation(pool_id=pool_id))

    try:
        batch_service_client.job.add(job)
    except batchmodels.batch_error.BatchErrorException as err:
        print_batch_exception(err)
        if err.error.code != "JobExists":
            raise
        else:
            print("Job {!r} already exists".format(job_id))


def wait_for_all_nodes_state(batch_client, pool, node_state):

    print('waiting for all nodes in pool {} to reach one of: {!r}'.format( pool.id, node_state))
    i = 0
    while True:
        # refresh pool to ensure that there is no resize error
        pool = batch_client.pool.get(pool.id)
        if pool.resize_error is not None:
            raise RuntimeError(
                'resize error encountered for pool {}: {!r}'.format(
                    pool.id, pool.resize_error))
        nodes = list(batch_client.compute_node.list(pool.id))
        if (len(nodes) >= pool.target_dedicated and
                all(node.state in node_state for node in nodes)):
            return nodes
        i += 1
        if i % 3 == 0:
            print('waiting for {} nodes to reach desired state...'.format(
                pool.target_dedicated))
        time.sleep(10)


def create_container_and_create_sas( block_blob_client, container_name, permission, expiry=None, timeout=None):

    if expiry is None:
        if timeout is None:
            timeout = 30
        expiry = datetime.datetime.utcnow() + datetime.timedelta(
            minutes=timeout)

    block_blob_client.create_container(
        container_name,
        fail_on_exist=False)

    return block_blob_client.generate_container_shared_access_signature(
        container_name=container_name, permission=permission, expiry=expiry)


def create_sas_token( block_blob_client, container_name, blob_name, permission, expiry=None, timeout=None):

    if expiry is None:
        if timeout is None:
            timeout = 30
        expiry = datetime.datetime.utcnow() + datetime.timedelta(
            minutes=timeout)
    return block_blob_client.generate_blob_shared_access_signature(
        container_name, blob_name, permission=permission, expiry=expiry)


def upload_blob_and_create_sas( block_blob_client, container_name, blob_name, file_name, expiry, timeout=None):

    block_blob_client.create_container(
        container_name,
        fail_on_exist=False)

    block_blob_client.create_blob_from_path(
        container_name,
        blob_name,
        file_name)

    sas_token = create_sas_token(
        block_blob_client,
        container_name,
        blob_name,
        permission=azureblob.BlobPermissions.READ,
        expiry=expiry,
        timeout=timeout)

    sas_url = block_blob_client.make_blob_url(
        container_name,
        blob_name,
        sas_token=sas_token)

    return sas_url


def upload_file_to_container( block_blob_client, container_name, file_path, timeout):

    blob_name = os.path.basename(file_path)
    print('Uploading file {} to container [{}]...'.format(
        file_path, container_name))
    sas_url = upload_blob_and_create_sas(
        block_blob_client, container_name, blob_name, file_path, expiry=None,
        timeout=timeout)
    return batchmodels.ResourceFile(
        file_path=blob_name, blob_source=sas_url)


def download_blob_from_container( block_blob_client, container_name, blob_name, directory_path):

    print('Downloading result file from container [{}]...'.format( container_name))

    destination_file_path = os.path.join(directory_path, blob_name)

    block_blob_client.get_blob_to_path( container_name, blob_name, destination_file_path)

    print('  Downloaded blob [{}] from container [{}] to {}'.format( blob_name, container_name, destination_file_path))

    print('  Download complete!')


def generate_unique_resource_name(resource_prefix):

    return resource_prefix + "-" + \
        datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def query_yes_no(question, default="yes"):

    valid = {'y': 'yes', 'n': 'no'}
    if default is None:
        prompt = ' [y/n] '
    elif default == 'yes':
        prompt = ' [Y/n] '
    elif default == 'no':
        prompt = ' [y/N] '
    else:
        raise ValueError("Invalid default answer: '{}'".format(default))

    while 1:
        choice = input(question + prompt).lower()
        if default and not choice:
            return default
        try:
            return valid[choice[0]]
        except (KeyError, IndexError):
            print("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")


def print_batch_exception(batch_exception):

    print('-------------------------------------------')
    print('Exception encountered:')
    if (batch_exception.error and batch_exception.error.message and
            batch_exception.error.message.value):
        print(batch_exception.error.message.value)
        if batch_exception.error.values:
            print()
            for mesg in batch_exception.error.values:
                print('{}:\t{}'.format(mesg.key, mesg.value))
    print('-------------------------------------------')


def wrap_commands_in_shell(ostype, commands):

    if ostype.lower() == 'linux':
        return '/bin/bash -c \'set -e; set -o pipefail; {}; wait\''.format(
            ';'.join(commands))
    elif ostype.lower() == 'windows':
        return 'cmd.exe /c "{}"'.format('&'.join(commands))
    else:
        raise ValueError('unknown ostype: {}'.format(ostype))
