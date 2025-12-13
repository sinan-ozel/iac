import os
import json

import boto3


REGION = os.environ.get('AWS_REGION', 'ca-central-1')
CLUSTER_NAME = os.environ.get('CLUSTER_NAME')
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID')


session = boto3.Session(region_name=REGION)
iam_client = session.client('iam')


# The Cluster Role
# Define the role name
role_name = f'{CLUSTER_NAME}-eks-role'

# Create the trust policy for the role
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": [
                    "eks.amazonaws.com",
                    "ec2.amazonaws.com"
                ]
            },
            "Action": "sts:AssumeRole"
        }
    ]
}

# Create the IAM role
try:
    response = iam_client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description='Role for EKS Node Group'
    )
    node_role_arn = response['Role']['Arn']
    print(f"Created role: {node_role_arn}")
except iam_client.exceptions.EntityAlreadyExistsException:
    response = iam_client.get_role(RoleName=role_name)
    node_role_arn = response['Role']['Arn']
    print(f"Role {role_name} already exists. Arn: {node_role_arn}.")
    # TODO: Check if trust_policy is correct.

# Attach necessary policies
policies = [
    # 'AmazonEKSWorkerNodePolicy',
    # 'AmazonEC2ContainerRegistryReadOnly',
    # 'AmazonEKS_CNI_Policy',
    'AmazonEKSClusterPolicy',
    # 'AmazonSSMManagedInstanceCore',
]
# Policy AmazonSSMManagedInstanceCore is not necessary, I used it for debugging, to connect to the node and run commands.

for policy in policies:
    try:
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=f'arn:aws:iam::aws:policy/{policy}'
        )
        print(f"Attached policy {policy} to role {role_name}.")
    except Exception as e:
        print(f"Error attaching policy {policy}: {e}")


# The Node Group Role
# Define the role name
role_name = f'{CLUSTER_NAME}-node-role'

# Create the trust policy for the role
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": [
                    "ec2.amazonaws.com"
                ]
            },
            "Action": "sts:AssumeRole"
        }
    ]
}

# Create the IAM role
try:
    response = iam_client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description='Role for EKS Node Group'
    )
    node_role_arn = response['Role']['Arn']
    print(f"Created role: {node_role_arn}")
except iam_client.exceptions.EntityAlreadyExistsException:
    response = iam_client.get_role(RoleName=role_name)
    node_role_arn = response['Role']['Arn']
    print(f"Role {role_name} already exists. Arn: {node_role_arn}.")
    # TODO: Check if trust_policy is correct.

# Attach necessary policies
policies = [
    'AmazonEKSWorkerNodePolicy',
    'AmazonEC2ContainerRegistryReadOnly',
    'AmazonEKS_CNI_Policy',
    # 'AmazonSSMManagedInstanceCore',
]
# Policy AmazonSSMManagedInstanceCore is not necessary, I used it for debugging, to connect to the node and run commands.

for policy in policies:
    try:
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=f'arn:aws:iam::aws:policy/{policy}'
        )
        print(f"Attached policy {policy} to role {role_name}.")
    except Exception as e:
        print(f"Error attaching policy {policy}: {e}")