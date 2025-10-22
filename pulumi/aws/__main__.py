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
REGION = os.environ.get('REGION', 'ca-central-1')
DEFAULT_NODE_COUNT = get_env_count('DEFAULT_NODE_COUNT') or 1
GPU_NODE_COUNT = get_env_count('GPU_NODE_COUNT')
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
        # "kubernetes.io/role/elb": "1",
        # "kubernetes.io/role/internal-elb": "1",
        # f"kubernetes.io/cluster/{CLUSTER_NAME}": "owned"
    },
    subnet_specs=[
        {
            "type": awsx.ec2.SubnetType.PUBLIC,
            # "cidr_blocks": ["10.0.64.0/19"],
            "name": f"public",
            # "size": 0,
            "tags": {
                **common_tags,
                # "Name": f"{CLUSTER_NAME}-vpc-public-1",
                "SubnetType": "Public",
                "kubernetes.io/role/elb": "1",
                # f"kubernetes.io/cluster/{CLUSTER_NAME}": "owned"
            },
        },
        {
            "type": awsx.ec2.SubnetType.PRIVATE,
            # "cidr_blocks": ["10.0.0.0/18"],
            "name": f"private",
            # "size": 0,
            "tags": {
                **common_tags,
                # "Name": f"{CLUSTER_NAME}-vpc-private-1",
                "SubnetType": "Private",
                "kubernetes.io/role/internal-elb": "1",
                # f"kubernetes.io/cluster/{CLUSTER_NAME}": "owned"
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
    nodegroup_gpu = eks.NodeGroupV2(f"{CLUSTER_NAME}-nodegroup-gpu",
        cluster=cluster,
        instance_profile_name=node_instance_profile.name,
        node_subnet_ids=vpc.private_subnet_ids,
        desired_capacity=GPU_NODE_COUNT,
        min_size=GPU_NODE_COUNT,
        max_size=GPU_NODE_COUNT,
        instance_type="g4dn.xlarge",
        # ami_type="AL2_x86_64_GPU",
        gpu=True,
        auto_scaling_group_tags={**common_tags, "Name": f"{CLUSTER_NAME}-nodegroup-gpu"},
        taints={
            "nvidia.com/gpu": eks.TaintArgs(
                value="true",
                effect="NO_SCHEDULE"
            )
        }
    )

# Export kubeconfig and region
pulumi.export("kubeconfig", cluster.kubeconfig)
pulumi.export("region", REGION)
pulumi.export("cluster_name", cluster.core.cluster.name)
pulumi.export("public_subnet_ids", vpc.public_subnet_ids)

# # Tag public subnets for ELB
# def tag_subnet_with_cluster(subnet_ids: pulumi.Output[list[str]], cluster_name: str):
#     def create_tags(subnet_ids):
#         for idx, subnet_id in enumerate(subnet_ids):
#             aws.ec2.Tag(
#                 f"{cluster_name}-cluster-tag-public-subnet-{idx}",
#                 key=f"kubernetes.io/cluster/{cluster_name}",
#                 value="owned",
#                 resource_id=subnet_id
#             )
#     subnet_ids.apply(create_tags)

# tag_subnet_with_cluster(vpc.public_subnet_ids, cluster.core.cluster.name)

# for idx, subnet_id in enumerate(vpc.public_subnet_ids):
#     # aws.ec2.Tag(
#     #     f"{CLUSTER_NAME}-elb-public-subnet-{idx}",
#     #     key="kubernetes.io/role/elb",
#     #     value="1",
#     #     resource_id=subnet_id
#     # )
#     # aws.ec2.Tag(
#     #     f"{CLUSTER_NAME}-internal-elb-public-subnet-{idx}",
#     #     key="kubernetes.io/role/internal-elb",
#     #     value="1",
#     #     resource_id=subnet_id
#     # )
#     aws.ec2.Tag(
#         f"{CLUSTER_NAME}-cluster-tag-public-subnet-{idx}",
#         key=f"kubernetes.io/cluster/{CLUSTER_NAME}",
#         value="owned",
#         resource_id=subnet_id
#     )


# # Kubernetes provider
# k8s_provider = k8s.Provider("eks-k8s", kubeconfig=cluster.kubeconfig)

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

# # Install AWS Load Balancer Controller via Helm
# lb_controller = k8s.helm.v3.Chart(
#     "aws-load-balancer-controller",
#     k8s.helm.v3.ChartOpts(
#         chart="aws-load-balancer-controller",
#         version="1.7.1",
#         fetch_opts=k8s.helm.v3.FetchOpts(
#             repo="https://aws.github.io/eks-charts"
#         ),
#         namespace="kube-system",
#         values={
#             "clusterName": cluster.core.name,
#             "region": aws.config.region,
#             "vpcId": vpc.id,
#             "serviceAccount": {
#                 "create": True,
#                 "name": "aws-load-balancer-controller",
#             },
#         },
#     ),
#     opts=pulumi.ResourceOptions(provider=k8s_provider),
# )
#         },
#     ),
#     opts=pulumi.ResourceOptions(provider=k8s_provider),
# )
