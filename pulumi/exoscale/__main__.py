# This script defines the SKS cluster resource for Pulumi.
# To destroy the cluster, run: pulumi destroy -s <stack>
import os

import pulumi
import pulumiverse_exoscale as exoscale

from helpers import get_project_names, get_env_count

CLUSTER_NAME = os.environ['CLUSTER_NAME']
REGION = os.environ.get('REGION', 'ch-gva-2')
PROJECT_NAMES = get_project_names()
DEFAULT_NODE_COUNT = get_env_count('DEFAULT_NODE_COUNT') or 1
GPU_NODE_COUNT = get_env_count('GPU_NODE_COUNT')

cluster = exoscale.SksCluster(
    f'{CLUSTER_NAME}-cluster',
    zone=REGION,
    name=f'{CLUSTER_NAME}-cluster',
    labels={
        "project_names": ','.join(PROJECT_NAMES)
    }
)

default_nodepool = exoscale.SksNodepool(
    f'{CLUSTER_NAME}-default',
    cluster_id=cluster.id,
    zone=cluster.zone,
    instance_type="standard.medium",
    size=DEFAULT_NODE_COUNT,
    labels={
        "project_names": ','.join(PROJECT_NAMES)
    }
)

if GPU_NODE_COUNT:
    gpu_nodepool = exoscale.SksNodepool(
        f'{CLUSTER_NAME}-gpu',
        cluster_id=cluster.id,
        zone=cluster.zone,
        instance_type="gpua30.small",
        size=GPU_NODE_COUNT,
        labels={
            "project_names": ','.join(PROJECT_NAMES)
        },
        taints=[{
            "key": "nvidia.com/gpu",
            "value": "true",
            "effect": "NO_SCHEDULE"
        }]
    )

sks_kubeconfig = exoscale.SksKubeconfig("kubeconfig",
    cluster_id=cluster.id,
    groups=["system:masters"],
    user="admin",
    zone=REGION,
    early_renewal_seconds=0,
    ttl_seconds=0)

pulumi.export("kubeconfig", sks_kubeconfig.kubeconfig)
pulumi.export("region", REGION)
pulumi.export("cluster_name", cluster.name)

