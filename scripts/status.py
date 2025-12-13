import os
import json
from datetime import timezone
from collections import defaultdict

import boto3
from exoscale.api.v2 import Client

# Expected logical volume names
VOLUME_NAMES = [
    'llm',
    'eberron-llm',
    'notebooks',
    'kubyterlab-llm-notebooks',
    'model-cache',
    'personal-cloud',
]

AWS_REGION = os.environ.get('AWS_REGION', 'ca-central-1')
EXOSCALE_ZONE = os.environ.get('EXOSCALE_ZONE', 'ch-gva-2')
AWS_VOLUME_FILTERS = [{'Name': f'tag:name', 'Values': VOLUME_NAMES}]

# AWS clients
ec2 = boto3.client('ec2', region_name=AWS_REGION)
eks = boto3.client('eks', region_name=AWS_REGION)

# Exoscale client
exo = Client(
    os.environ.get('EXOSCALE_API_KEY', ''),
    os.environ.get('EXOSCALE_API_SECRET', ''),
    zone=EXOSCALE_ZONE
)

# Fetch AWS volumes
aws_volumes = ec2.describe_volumes(Filters=AWS_VOLUME_FILTERS)['Volumes']

# Index AWS volumes by tag:name
aws_name_to_volume = {}
for v in aws_volumes:
    tags = {t['Key']: t['Value'] for t in v.get('Tags', [])}
    name = tags.get('name')
    if name:
        aws_name_to_volume[name] = v

# Fetch all relevant AWS snapshots by tag
aws_snapshots = ec2.describe_snapshots(
    Filters=AWS_VOLUME_FILTERS,
    OwnerIds=['self'],
)['Snapshots']

# Index latest AWS snapshot per name
aws_name_to_snapshots = defaultdict(list)
for snap in aws_snapshots:
    tags = {t['Key']: t['Value'] for t in snap.get('Tags', [])}
    name = tags.get('name')
    if name:
        aws_name_to_snapshots[name].append(snap)

# Get latest AWS snapshot ID and its completion time per name
aws_name_to_latest_snapshot_info = {}
for name, snaps in aws_name_to_snapshots.items():
    latest = sorted(snaps, key=lambda s: s['StartTime'], reverse=True)[0]
    snapshot_id = latest['SnapshotId']
    snapshot_time = latest['StartTime'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    aws_name_to_latest_snapshot_info[name] = (snapshot_id, snapshot_time)

# Fetch Exoscale volumes
exoscale_name_to_volume = {}
exoscale_name_to_latest_snapshot_info = {}

exo_volumes_response = exo.list_block_storage_volumes()
exo_volumes = exo_volumes_response.get('block-storage-volumes', [])
for v in exo_volumes:
    name = v.get('labels', {}).get('name') if v.get('labels') else None
    if name in VOLUME_NAMES:
        exoscale_name_to_volume[name] = v

# Fetch Exoscale snapshots
exo_snapshots_response = exo.list_block_storage_snapshots()
exo_snapshots = exo_snapshots_response.get('block-storage-snapshots', [])
exo_name_to_snapshots = defaultdict(list)
for snap in exo_snapshots:
    name = snap.get('labels', {}).get('name') if snap.get('labels') else None
    if name in VOLUME_NAMES:
        exo_name_to_snapshots[name].append(snap)

# Get latest Exoscale snapshot
for name, snaps in exo_name_to_snapshots.items():
    latest = sorted(snaps, key=lambda s: s.get('created-at', ''), reverse=True)[0]
    snapshot_id = latest['id']
    snapshot_time = latest.get('created-at', '')
    exoscale_name_to_latest_snapshot_info[name] = (snapshot_id, snapshot_time)

# Markdown Table for AWS Volumes
aws_header =  "| Name | State   | Volume ID | Created | Mounted | Snapshot ID | Snapshot Time |\n"
aws_divider = "|------|---------|-----------|---------|---------|-------------|---------------|\n"
aws_rows = []

for name in VOLUME_NAMES:
    aws_volume = aws_name_to_volume.get(name)
    if aws_volume:
        snapshot_id, snapshot_time = aws_name_to_latest_snapshot_info.get(name, ("—", "—"))
        state = aws_volume['State']
        status_icon = "✅" if state == "available" else "❌"
        volume_id = aws_volume['VolumeId']
        created = aws_volume['CreateTime'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        mounted = "✅" if aws_volume.get('Attachments') else "❌"
    else:
        state = "—"
        status_icon = "❌"
        volume_id = created = mounted = "—"
        snapshot_id, snapshot_time = ("—", "—")

    aws_rows.append(f"| {name} | {status_icon} {state} | {volume_id} | {created} | {mounted} | {snapshot_id} | {snapshot_time} |")

# Markdown Table for Exoscale Volumes
exo_header =  "| Name | State   | Volume ID | Created | Mounted | Snapshot ID | Snapshot Time |\n"
exo_divider = "|------|---------|-----------|---------|---------|-------------|---------------|\n"
exo_rows = []

for name in VOLUME_NAMES:
    exo_volume = exoscale_name_to_volume.get(name)
    if exo_volume:
        snapshot_id, snapshot_time = exoscale_name_to_latest_snapshot_info.get(name, ("—", "—"))
        state = exo_volume.get('state', 'unknown')
        status_icon = "✅" if state.lower() in ["attached", "detached"] else "❌"
        volume_id = exo_volume['id']
        created = exo_volume.get('created-at', '—')
        mounted = "✅" if state.lower() == "attached" else "❌"
    else:
        state = "—"
        status_icon = "❌"
        volume_id = created = mounted = "—"
        snapshot_id, snapshot_time = ("—", "—")

    exo_rows.append(f"| {name} | {status_icon} {state} | {volume_id} | {created} | {mounted} | {snapshot_id} | {snapshot_time} |")

# Markdown Table for VPCs
vpc_header =  "| VPC Name | VPC ID | Region | VPC State |\n"
vpc_divider = "|----------|--------|--------|-----------|\n"
vpc_rows = []

vpcs = ec2.describe_vpcs()['Vpcs']
for vpc in vpcs:
    tags = {t['Key']: t['Value'] for t in vpc.get('Tags', [])}
    name = tags.get('Name', tags.get('name', '—'))  # Capital 'N' is standard in AWS for VPC 'Name' tag
    vpc_id = vpc.get('VpcId', "—")
    state = vpc.get('State', "—")
    state_icon = "✅" if state == "available" else "❌"
    vpc_rows.append(f"| {name} | {vpc_id} | {AWS_REGION} | {state_icon} {state} |")

# Markdown Table for AWS Clusters
aws_cluster_header =  "| Cluster ID | Name | Region | Kubernetes Version |\n"
aws_cluster_divider = "|------------|------|--------|--------------------|\n"
aws_cluster_rows = []

cluster_names = eks.list_clusters()['clusters']
for cluster_name in cluster_names:
    cluster_details = eks.describe_cluster(name=cluster_name)['cluster']
    cluster_id = cluster_details.get('name', '—')  # EKS uses name as ID
    name = cluster_details.get('name', '—')
    region = AWS_REGION
    k8s_version = cluster_details.get('version', '—')
    aws_cluster_rows.append(f"| {cluster_id} | {name} | {region} | {k8s_version} |")

# Markdown Table for Exoscale Clusters
exo_cluster_header =  "| Cluster ID | Name | Zone | Kubernetes Version |\n"
exo_cluster_divider = "|------------|------|------|--------------------|\n"
exo_cluster_rows = []

exo_clusters_response = exo.list_sks_clusters()
exo_clusters = exo_clusters_response.get('sks-clusters', [])
for cluster in exo_clusters:
    cluster_id = cluster.get('id', '—')
    name = cluster.get('name', '—')
    zone = cluster.get('zone', '—')
    k8s_version = cluster.get('version', '—')
    exo_cluster_rows.append(f"| {cluster_id} | {name} | {zone} | {k8s_version} |")

# Write markdown
with open("STATUS.md", "w") as f:
    f.write("# AWS Volumes\n\n")
    f.write(aws_header)
    f.write(aws_divider)
    f.write("\n".join(aws_rows))
    f.write("\n")

    f.write("\n\n# Exoscale Volumes\n\n")
    f.write(exo_header)
    f.write(exo_divider)
    f.write("\n".join(exo_rows))
    f.write("\n")

    f.write("\n\n# VPCs\n\n")
    f.write(vpc_header)
    f.write(vpc_divider)
    f.write("\n".join(vpc_rows))
    f.write("\n")

    f.write("\n\n# AWS Clusters\n\n")
    f.write(aws_cluster_header)
    f.write(aws_cluster_divider)
    f.write("\n".join(aws_cluster_rows))
    f.write("\n")

    f.write("\n\n# Exoscale Clusters\n\n")
    f.write(exo_cluster_header)
    f.write(exo_cluster_divider)
    f.write("\n".join(exo_cluster_rows))
    f.write("\n")

