import os
import json
from datetime import timezone
from collections import defaultdict

import boto3

# Expected logical volume names
VOLUME_NAMES = [
    'llm',
    'eberron-llm',
    'notebooks',
]

REGION = os.environ.get('REGION', 'ca-central-1')
AWS_VOLUME_FILTERS = [{'Name': f'tag:name', 'Values': VOLUME_NAMES}]

# AWS client
ec2 = boto3.client('ec2', region_name=REGION)
eks = boto3.client('eks', region_name=REGION)

# Fetch volumes
volumes = ec2.describe_volumes(Filters=AWS_VOLUME_FILTERS)['Volumes']

# Index by tag:Name
name_to_volume = {}
for v in volumes:
    tags = {t['Key']: t['Value'] for t in v.get('Tags', [])}
    name = tags.get('name')
    if name:
        name_to_volume[name] = v

# Fetch all relevant snapshots by tag
snapshots = ec2.describe_snapshots(
    Filters=AWS_VOLUME_FILTERS,
    OwnerIds=['self'],
)['Snapshots']

# Index latest snapshot per name
name_to_snapshots = defaultdict(list)
for snap in snapshots:
    tags = {t['Key']: t['Value'] for t in snap.get('Tags', [])}
    name = tags.get('name')
    if name:
        name_to_snapshots[name].append(snap)

# Get latest snapshot ID and its completion time per name
name_to_latest_snapshot_info = {}
for name, snaps in name_to_snapshots.items():
    latest = sorted(snaps, key=lambda s: s['StartTime'], reverse=True)[0]
    snapshot_id = latest['SnapshotId']
    snapshot_time = latest['StartTime'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    name_to_latest_snapshot_info[name] = (snapshot_id, snapshot_time)

# Markdown Table for Volumes
header =  "| Name | Provisioner | State   | Volume ID | Created | Mounted | Snapshot ID | Snapshot Time |\n"
divider = "|------|-------------|---------|-----------|---------|---------|-------------|---------------|\n"
rows = []

for name in VOLUME_NAMES:
    volume = name_to_volume.get(name)
    provisioner = 'AWS'
    snapshot_id, snapshot_time = name_to_latest_snapshot_info.get(name, ("—", "—"))

    if volume:
        state = volume['State']
        status_icon = "✅" if state == "available" else "❌"
        volume_id = volume['VolumeId']
        created = volume['CreateTime'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        mounted = "✅" if volume.get('Attachments') else "❌"
    else:
        state = "—"
        status_icon = "❌"
        volume_id = created = mounted = "—"

    rows.append(f"| {name} | {provisioner} | {status_icon} {state} | {volume_id} | {created} | {mounted} | {snapshot_id} | {snapshot_time} |")

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
    vpc_rows.append(f"| {name} | {vpc_id} | {REGION} | {state_icon} {state} |")

# Markdown Table for Clusters
cluster_header =  "| Cluster ID | Name | Region | Kubernetes Version |\n"
cluster_divider = "|------------|------|--------|--------------------|\n"
cluster_rows = []

cluster_names = eks.list_clusters()['clusters']
for cluster_name in cluster_names:
    cluster_details = eks.describe_cluster(name=cluster_name)['cluster']
    cluster_id = cluster_details.get('name', '—')  # EKS uses name as ID
    name = cluster_details.get('name', '—')
    region = REGION
    k8s_version = cluster_details.get('version', '—')
    cluster_rows.append(f"| {cluster_id} | {name} | {region} | {k8s_version} |")

# Write markdown
with open("STATUS.md", "w") as f:
    f.write("# Volumes\n\n")
    f.write(header)
    f.write(divider)
    f.write("\n".join(rows))
    f.write("\n")

    f.write("\n\n# VPCs\n\n")
    f.write(vpc_header)
    f.write(vpc_divider)
    f.write("\n".join(vpc_rows))
    f.write("\n")

    f.write("\n\n# Clusters\n\n")
    f.write(cluster_header)
    f.write(cluster_divider)
    f.write("\n".join(cluster_rows))
    f.write("\n")

