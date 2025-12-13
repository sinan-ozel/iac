import os

import pulumi
from pulumi import ResourceOptions, ResourceTransformArgs, ResourceTransformResult
import pulumi_aws as aws
import pulumi_eks as eks
import pulumi_awsx as awsx
# import pulumi_kubernetes as k8s

from helpers import get_ports, get_project_names, get_env_count


def transformation(args: ResourceTransformArgs):
    if args.type_ == "aws:ec2/vpc:Vpc" or args.type_ == "aws:ec2/subnet:Subnet":
        return ResourceTransformResult(
            props=args.props,
            opts=ResourceOptions.merge(args.opts, ResourceOptions(
                ignore_changes=["tags"],
            )))

PORTS = get_ports()  # e.g., [8888]
PROJECT_NAMES = get_project_names()  # e.g., ["my-project"]
CLUSTER_NAME = os.getenv("CLUSTER_NAME")
if not CLUSTER_NAME:
    raise ValueError("CLUSTER_NAME environment variable is not set.")
REGION = os.environ.get('AWS_REGION', 'ca-central-1')
DEFAULT_NODE_COUNT = get_env_count('DEFAULT_NODE_COUNT') or 1
GPU_NODE_COUNT = get_env_count('GPU_NODE_COUNT')
GPU_EPHEMERAL_VOLUME_SIZE = os.environ.get('GPU_EPHEMERAL_VOLUME_SIZE', '100')  # in GB, default 100GB
GPU_NODES_ARE_ISOLATED = os.environ.get('GPU_NODES_ARE_ISOLATED', 'false').lower() == 'true'
AWS_AVAILABILITY_ZONE_CHARS = ['a', 'b']

AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID")

ADMIN_REPOS = os.getenv("ADMIN_REPOS")
ADMIN_REPO_LIST = ADMIN_REPOS.split(",")

# Common tags for all resources
common_tags = {
    "project_names": ','.join(PROJECT_NAMES),
    "cluster_name": CLUSTER_NAME,
}


# VPC
vpc = awsx.ec2.Vpc(f"{CLUSTER_NAME}-vpc",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    availability_zone_names=[f"{REGION}{char}" for char in AWS_AVAILABILITY_ZONE_CHARS],
    nat_gateways={"strategy": "Single"},
    tags={
        **common_tags,
        "Name": f"{CLUSTER_NAME}-vpc",
    },
    subnet_specs=[
        {
            "type": awsx.ec2.SubnetType.PUBLIC,
            "name": f"public",
            "tags": {
                **common_tags,
                "SubnetType": "Public",
                "kubernetes.io/role/elb": "1",
            },
        },
        {
            "type": awsx.ec2.SubnetType.PRIVATE,
            "name": f"private",
            "tags": {
                **common_tags,
                "SubnetType": "Private",
                "kubernetes.io/role/internal-elb": "1",
            },
        },
    ],
    region=REGION,
    opts=ResourceOptions(transforms=[transformation]),
)

# Security group for EKS nodes
ingress_rules = []
ingress_rules.append({
    "protocol": "-1",
    "from_port": 0,
    "to_port": 0,
    "cidr_blocks": ["0.0.0.0/0"]
}) # Allow all for cluster comms
for open_port in PORTS:
    ingress_rules.append({
        "protocol": "tcp",
        "from_port": open_port,
        "to_port": open_port,
        "cidr_blocks": ["0.0.0.0/0"]
    })

node_role = aws.iam.Role.get(
    "node-role",
    "kubernetes-node-role"
)
node_instance_profile = aws.iam.get_instance_profile(name="kubernetes-node-role")
pulumi.export("node_instance_profile_arn", node_instance_profile.arn)
pulumi.export("node_instance_profile_name", node_instance_profile.name)

# EKS Cluster
cluster = eks.Cluster(f"{CLUSTER_NAME}",
    vpc_id=vpc.vpc_id,
    version="1.34",
    public_subnet_ids=vpc.public_subnet_ids,
    private_subnet_ids=vpc.private_subnet_ids,
    instance_roles=[node_role],
    cluster_tags={**common_tags, "Name": f"{CLUSTER_NAME}"},
    authentication_mode=eks.AuthenticationMode.API_AND_CONFIG_MAP,
    node_group_options=eks.ClusterNodeGroupOptionsArgs(
        ami_type="AL2023_x86_64_STANDARD",
        desired_capacity=DEFAULT_NODE_COUNT,
        min_size=DEFAULT_NODE_COUNT,
        max_size=DEFAULT_NODE_COUNT,
        instance_type="t3.medium",
        instance_profile_name=node_instance_profile.name,
        auto_scaling_group_tags={**common_tags, "Name": f"{CLUSTER_NAME}-nodegroup-default"},
    ),
    # skip_default_node_group=True,
    endpoint_private_access=True,
    endpoint_public_access=True,
)

root_access_entry = aws.eks.AccessEntry(
    "root-access-entry",
    cluster_name=cluster.core.cluster.name,
    principal_arn=f"arn:aws:iam::{AWS_ACCOUNT_ID}:root",
    type="STANDARD",
)

root_admin_assoc = aws.eks.AccessPolicyAssociation(
    "root-admin-assoc",
    cluster_name=cluster.core.cluster.name,
    principal_arn=f"arn:aws:iam::{AWS_ACCOUNT_ID}:root",
    policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
    access_scope=aws.eks.AccessPolicyAssociationAccessScopeArgs(
        type="cluster",
    ),
)

for admin_repo in ADMIN_REPO_LIST:
    admin_repo_org_name, admin_repo_name = admin_repo.split("/")
    role_arn = f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{CLUSTER_NAME}-{admin_repo_org_name}-{admin_repo_name}-admin-role"

    # EKS Access Entry
    aws.eks.AccessEntry(
        f"{admin_repo_name}-gha-access-entry",
        cluster_name=cluster.core.cluster.name,
        principal_arn=role_arn,
        type="STANDARD",
    )

    # EKS Access Policy Association
    aws.eks.AccessPolicyAssociation(
        f"{admin_repo_name}-gha-access-policy",
        cluster_name=cluster.core.cluster.name,
        principal_arn=role_arn,
        policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
        access_scope=aws.eks.AccessPolicyAssociationAccessScopeArgs(type="cluster"),
    )


# Node Group 2: GPU
if GPU_NODE_COUNT:

    nodegroup_gpu = aws.eks.NodeGroup(f"{CLUSTER_NAME}-nodegroup-gpu",
        cluster_name=cluster.core.cluster.name,
        node_role_arn=node_role.arn,
        subnet_ids=vpc.private_subnet_ids,
        scaling_config=aws.eks.NodeGroupScalingConfigArgs(
            desired_size=GPU_NODE_COUNT,
            min_size=GPU_NODE_COUNT,
            max_size=GPU_NODE_COUNT,
        ),
        instance_types=["g4dn.2xlarge"],
        ami_type="AL2023_x86_64_NVIDIA",
        tags={**common_tags, "Name": f"{CLUSTER_NAME}-nodegroup-gpu"},
        disk_size=int(GPU_EPHEMERAL_VOLUME_SIZE),
        taints=[aws.eks.NodeGroupTaintArgs(
            key="nvidia.com/gpu",
            value="true",
            effect="NO_SCHEDULE"
        )],
    )

    # Get security group IDs
    # The eks.Cluster creates a node security group for the default node group
    # The cluster also has a cluster security group that all nodes use
    cluster_sg_id = cluster.core.cluster.vpc_config.cluster_security_group_id
    node_sg_id = cluster.node_security_group_id

    if GPU_NODES_ARE_ISOLATED:
        # For isolated GPU nodes, we only allow minimal required traffic
        # kubectl port-forward works through the EKS API server, not direct network access

        # Allow kubelet API from control plane (required for kubectl port-forward and node management)
        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-gpu-kubelet-ingress",
            type="ingress",
            from_port=10250,
            to_port=10250,
            protocol="tcp",
            security_group_id=cluster_sg_id,
            self=True,
            description="Allow kubelet API from EKS control plane"
        )

        # Allow HTTPS to control plane (required for node to join cluster)
        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-gpu-https-egress",
            type="egress",
            from_port=443,
            to_port=443,
            protocol="tcp",
            security_group_id=cluster_sg_id,
            self=True,
            description="Allow HTTPS to EKS control plane"
        )

        # Allow DNS (required for cluster operations)
        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-gpu-dns-tcp-egress",
            type="egress",
            from_port=53,
            to_port=53,
            protocol="tcp",
            security_group_id=cluster_sg_id,
            cidr_blocks=["10.0.0.2/32"],  # VPC DNS resolver
            description="Allow DNS TCP to VPC resolver"
        )

        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-gpu-dns-udp-egress",
            type="egress",
            from_port=53,
            to_port=53,
            protocol="udp",
            security_group_id=cluster_sg_id,
            cidr_blocks=["10.0.0.2/32"],
            description="Allow DNS UDP to VPC resolver"
        )

        # Block all other traffic (no internet access, no downloads, no pod-to-pod communication)
        # This is implicit - by not adding additional rules, all other traffic is blocked

        pulumi.export("gpu_isolation_mode", "enabled")
        pulumi.export("cluster_managed_security_group_id", cluster_sg_id)
    else:        # Allow traffic between cluster security group (used by GPU nodes) and node security group (used by CPU nodes)
        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-cluster-to-node-ingress",
            type="ingress",
            from_port=0,
            to_port=65535,
            protocol="-1",
            security_group_id=node_sg_id,
            source_security_group_id=cluster_sg_id,
            description="Allow cluster SG (GPU nodes) to communicate with node SG (CPU nodes)"
        )

        aws.ec2.SecurityGroupRule(
            f"{CLUSTER_NAME}-node-to-cluster-ingress",
            type="ingress",
            from_port=0,
            to_port=65535,
            protocol="-1",
            security_group_id=cluster_sg_id,
            source_security_group_id=node_sg_id,
            description="Allow node SG (CPU nodes) to communicate with cluster SG (GPU nodes)"
        )


        # Export the security group IDs for reference
        pulumi.export("cluster_managed_security_group_id", cluster_sg_id)
        pulumi.export("node_security_group_id", node_sg_id)


# Export kubeconfig and region
pulumi.export("kubeconfig", cluster.kubeconfig)
pulumi.export("region", REGION)
pulumi.export("cluster_name", cluster.core.cluster.name)
pulumi.export("public_subnet_ids", vpc.public_subnet_ids)

# # Install AWS EBS CSI Driver via Helm
# ebs_csi = k8s.helm.v3.Chart(
#     "aws-ebs-csi-driver",
#     k8s.helm.v3.ChartOpts(
#         chart="aws-ebs-csi-driver",
#         version="2.30.0",
#         fetch_opts=k8s.helm.v3.FetchOpts(
#             repo="https://kubernetes-sigs.github.io/aws-ebs-csi-driver"
#         ),
#         namespace="kube-system",
#     ),
#     opts=pulumi.ResourceOptions(provider=k8s_provider),
# )

# # Create PersistentVolume if VOLUME_NAME is set
# VOLUME_NAME = os.environ.get('VOLUME_NAME')
# if VOLUME_NAME:
#     import boto3
#     from operator import itemgetter

#     # Find the volume by tag
#     ec2_client = boto3.client('ec2', region_name=REGION)
#     TAGS = {'name': VOLUME_NAME}
#     FILTERS = [{'Name': f'tag:{k}', 'Values': [v]} for k, v in TAGS.items()]

#     response = ec2_client.describe_volumes(Filters=FILTERS)
#     volumes = sorted(response.get('Volumes', []), key=itemgetter('CreateTime'), reverse=True)

#     if not volumes:
#         raise RuntimeError(
#             f"VOLUME_NAME '{VOLUME_NAME}' is set but no volume found with tag name={VOLUME_NAME}. "
#             f"Please provision the volume first using the volume workflow."
#         )

#     volume = volumes[0]
#     volume_id = volume['VolumeId']
#     volume_size_gb = volume['Size']
#     availability_zone = volume['AvailabilityZone']

#     print(f"Found volume {volume_id} ({volume_size_gb}GB) in {availability_zone}")

#     # Create PersistentVolume
#     pv = k8s.core.v1.PersistentVolume(
#         f"{VOLUME_NAME}-pv",
#         metadata=k8s.meta.v1.ObjectMetaArgs(
#             name=f"{VOLUME_NAME}-pv",
#             labels={"volume-name": VOLUME_NAME},
#         ),
#         spec=k8s.core.v1.PersistentVolumeSpecArgs(
#             capacity={"storage": f"{volume_size_gb}Gi"},
#             access_modes=["ReadWriteOnce"],
#             persistent_volume_reclaim_policy="Retain",
#             storage_class_name="gp3",
#             aws_elastic_block_store=k8s.core.v1.AWSElasticBlockStoreVolumeSourceArgs(
#                 volume_id=volume_id,
#                 fs_type="ext4",
#             ),
#             node_affinity=k8s.core.v1.VolumeNodeAffinityArgs(
#                 required=k8s.core.v1.NodeSelectorArgs(
#                     node_selector_terms=[k8s.core.v1.NodeSelectorTermArgs(
#                         match_expressions=[k8s.core.v1.NodeSelectorRequirementArgs(
#                             key="topology.kubernetes.io/zone",
#                             operator="In",
#                             values=[availability_zone],
#                         )],
#                     )],
#                 ),
#             ),
#         ),
#         opts=pulumi.ResourceOptions(provider=k8s_provider),
#     )

#     # Create PersistentVolumeClaim
#     pvc = k8s.core.v1.PersistentVolumeClaim(
#         f"{VOLUME_NAME}-pvc",
#         metadata=k8s.meta.v1.ObjectMetaArgs(
#             name=f"{VOLUME_NAME}-pvc",
#             labels={"volume-name": VOLUME_NAME},
#         ),
#         spec=k8s.core.v1.PersistentVolumeClaimSpecArgs(
#             access_modes=["ReadWriteOnce"],
#             resources=k8s.core.v1.VolumeResourceRequirementsArgs(
#                 requests={"storage": f"{volume_size_gb}Gi"},
#             ),
#             storage_class_name="gp3",
#             volume_name=f"{VOLUME_NAME}-pv",
#         ),
#         opts=pulumi.ResourceOptions(provider=k8s_provider, depends_on=[pv]),
#     )

#     pulumi.export("persistent_volume_id", volume_id)
#     pulumi.export("persistent_volume_name", pv.metadata.name)
#     pulumi.export("persistent_volume_claim_name", pvc.metadata.name)
