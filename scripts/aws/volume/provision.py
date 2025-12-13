import os
import boto3
import json
from operator import itemgetter

from helpers import wait_until


# Load environment variables
NAME = os.environ['VOLUME_NAME']
EBS_VOLUME_SIZE = int(os.environ['VOLUME_SIZE'])

# Hardcoded constants
REGION = os.environ.get('AWS_REGION', 'ca-central-1')
TAGS = {'name': NAME}
FILTERS = [{'Name': f'tag:{k}', 'Values': [v]} for k, v in TAGS.items()]

# Boto3 session
session = boto3.Session(region_name=REGION)
ec2_client = session.client('ec2')
sts_client = session.client('sts')
aws_account_id = sts_client.get_caller_identity().get('Account')

# Main logic
volume_id = None
availability_zone = None

response = ec2_client.describe_volumes(Filters=FILTERS)
volumes = sorted(response.get('Volumes', []), key=itemgetter('CreateTime'), reverse=True)

if volumes:
    volume_id = volumes[0]['VolumeId']
    availability_zone = volumes[0]['AvailabilityZone']
    if volumes[0]['State'].lower() == 'deleting':
        raise RuntimeError('Volume is being deleted. Please wait and try again.')
else:
    # Try to find the most recent snapshot
    snapshots = []
    response = ec2_client.describe_snapshots(Filters=FILTERS)
    snapshots = sorted(response.get('Snapshots', []), key=itemgetter('StartTime'), reverse=True)

    response = ec2_client.describe_availability_zones()
    availability_zones = response['AvailabilityZones']
    availability_zone = availability_zones[0]['ZoneName']

    if snapshots:
        snapshot = snapshots[0]
        snapshot_id = snapshot['SnapshotId']
        snapshot_size = snapshot['VolumeSize']  # in GiB

        if EBS_VOLUME_SIZE < snapshot_size:
            raise ValueError(
                f"EBS_VOLUME_SIZE ({EBS_VOLUME_SIZE} GiB) is smaller than the snapshot volume size "
                f"({snapshot_size} GiB). Cannot create volume."
            )

        print(f"Creating volume from snapshot: {snapshot_id}")
        response = ec2_client.create_volume(
            SnapshotId=snapshot_id,
            Size=EBS_VOLUME_SIZE,
            AvailabilityZone=availability_zone,
            VolumeType='gp3',
            TagSpecifications=[{
                'ResourceType': 'volume',
                'Tags': [{'Key': k, 'Value': v} for k, v in TAGS.items()]
                        + [{'Key': 'Name', 'Value': NAME}]
            }]
        )
    else:
        print("Creating new empty volume")
        response = ec2_client.create_volume(
            Size=EBS_VOLUME_SIZE,
            AvailabilityZone=availability_zone,
            VolumeType='gp3',
            TagSpecifications=[{
                'ResourceType': 'volume',
                'Tags': [{'Key': k, 'Value': v} for k, v in TAGS.items()]
                        + [{'Key': 'Name', 'Value': NAME}]
            }]
        )
    volume_id = response['VolumeId']

    wait_until(
        check=ec2_client.describe_volumes,
        kwargs={'VolumeIds': [volume_id]},
        cond=lambda x: x['Volumes'][0]['State'].lower() == 'available'
    )

print(f"Provisioned Volume ID: {volume_id}")
print(f"Availability Zone: {availability_zone}")

with open(f'volume-aws-{NAME}.json', 'w') as f:
    json.dump({
        'volume_id': volume_id,
    }, f)
