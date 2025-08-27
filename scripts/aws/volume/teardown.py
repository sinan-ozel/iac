import os
import boto3

from helpers import wait_until

# Load environment variables
NAME = os.environ['VOLUME_NAME']
EBS_VOLUME_SIZE = int(os.environ['VOLUME_SIZE'])

# Hardcoded constants
REGION = os.environ.get('REGION', 'ca-central-1')
TAGS = {'name': NAME}
FILTERS = [{'Name': f'tag:{k}', 'Values': [v]} for k, v in TAGS.items()]

# Boto3 session
session = boto3.Session(region_name=REGION)
ec2_client = session.client('ec2')
sts_client = session.client('sts')
aws_account_id = sts_client.get_caller_identity().get('Account')

response = ec2_client.describe_volumes(Filters=FILTERS)
volumes = response.get('Volumes', [])
if not volumes:
    raise RuntimeError(f'No volumes found matching the filter: {FILTERS}')
volume_ids = [volume['VolumeId'] for volume in volumes]

for volume_id in volume_ids:
    response = ec2_client.create_snapshot(
        VolumeId=volume_id,
        Description=f"Snapshot For: {volume_id}. Tags: {TAGS}",
        TagSpecifications=[
            {
                'ResourceType': 'snapshot',
                'Tags': [{'Key': k, 'Value': TAGS[k]} for k in TAGS]
            }
        ]
    )

snapshot_id = response['SnapshotId']

for volume_id in volume_ids:
    ec2_client.delete_volume(VolumeId=volume_id)

wait_until(ec2_client.describe_volumes, {'Filters': FILTERS}, lambda x: len(x['Volumes']) == 0)