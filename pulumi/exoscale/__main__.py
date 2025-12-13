# This script defines the SKS cluster resource for Pulumi.
# To destroy the cluster, run: pulumi destroy -s <stack>
import os

import pulumi
import pulumiverse_exoscale as exoscale

from helpers import get_project_names, get_env_count

CLUSTER_NAME = os.environ['CLUSTER_NAME']
REGION = os.environ.get('EXOSCALE_ZONE', 'ch-gva-2')
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

print(dir(exoscale))

print(dir(cluster))

sks_kubeconfig = exoscale.SksKubeconfig("kubeconfig",
    cluster_id=cluster.id,
    groups=["system:masters"],
    user="admin",
    zone=REGION,
    early_renewal_seconds=0,
    ttl_seconds=0)

print(dir(sks_kubeconfig))

pulumi.export("kubeconfig", sks_kubeconfig.kubeconfig)
pulumi.export("region", REGION)
pulumi.export("cluster_name", cluster.name)
# pulumi.export("public_subnet_ids", vpc.public_subnet_ids)

# Create PersistentVolume if VOLUME_NAME is set
VOLUME_NAME = os.environ.get('VOLUME_NAME')
if VOLUME_NAME:
    from exoscale.api.v2 import Client

    # Find the volume by label
    exo_client = Client(
        os.environ.get('EXOSCALE_API_KEY', ''),
        os.environ.get('EXOSCALE_API_SECRET', ''),
        zone=REGION
    )

    exo_volumes_response = exo_client.list_block_storage_volumes()
    exo_volumes = exo_volumes_response.get('block-storage-volumes', [])

    matching_volumes = [
        v for v in exo_volumes
        if v.get('labels', {}).get('name') == VOLUME_NAME
    ]

    if not matching_volumes:
        raise RuntimeError(
            f"VOLUME_NAME '{VOLUME_NAME}' is set but no volume found with label name={VOLUME_NAME}. "
            f"Please provision the volume first using the volume workflow."
        )

    # Sort by creation time, most recent first
    matching_volumes.sort(key=lambda v: v.get('created-at', ''), reverse=True)
    volume = matching_volumes[0]
    volume_id = volume['id']
    volume_size_gb = volume['size']

    print(f"Found Exoscale volume {volume_id} ({volume_size_gb}GB) in {REGION}")

    # Note: Exoscale CSI driver must be enabled on the SKS cluster
    # This can be done via: exo compute sks update --enable-csi-addon <cluster-name>
    # Or enabled when creating the cluster via Pulumi/Terraform

    import pulumi_kubernetes as k8s

    # Create Kubernetes provider
    k8s_provider = k8s.Provider(
        "k8s-provider",
        kubeconfig=sks_kubeconfig.kubeconfig,
    )

    # Create PersistentVolume using Exoscale CSI driver
    pv = k8s.core.v1.PersistentVolume(
        f"{VOLUME_NAME}-pv",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=f"{VOLUME_NAME}-pv",
            labels={"volume-name": VOLUME_NAME},
        ),
        spec=k8s.core.v1.PersistentVolumeSpecArgs(
            capacity={"storage": f"{volume_size_gb}Gi"},
            access_modes=["ReadWriteOnce"],
            persistent_volume_reclaim_policy="Retain",
            storage_class_name="exoscale-sbs",  # Exoscale CSI storage class
            csi=k8s.core.v1.CSIPersistentVolumeSourceArgs(
                driver="csi.exoscale.com",
                volume_handle=volume_id,
                fs_type="ext4",
            ),
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider),
    )

    # Create PersistentVolumeClaim
    pvc = k8s.core.v1.PersistentVolumeClaim(
        f"{VOLUME_NAME}-pvc",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=f"{VOLUME_NAME}-pvc",
            labels={"volume-name": VOLUME_NAME},
        ),
        spec=k8s.core.v1.PersistentVolumeClaimSpecArgs(
            access_modes=["ReadWriteOnce"],
            resources=k8s.core.v1.VolumeResourceRequirementsArgs(
                requests={"storage": f"{volume_size_gb}Gi"},
            ),
            storage_class_name="exoscale-sbs",
            volume_name=f"{VOLUME_NAME}-pv",
        ),
        opts=pulumi.ResourceOptions(provider=k8s_provider, depends_on=[pv]),
    )

    pulumi.export("persistent_volume_id", volume_id)
    pulumi.export("persistent_volume_name", pv.metadata.name)
    pulumi.export("persistent_volume_claim_name", pvc.metadata.name)
